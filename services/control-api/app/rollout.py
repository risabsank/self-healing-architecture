import time
from typing import Any, Literal

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.observability import record_incident_event
from app.repair import get_repair, load_incident


TARGET_BASE_URL = "http://target-api:8001"
CANARY_ENVIRONMENT = "local-docker-canary"
CANARY_PROBES = (
    ("health", "GET", "/health"),
    ("metadata", "GET", "/metadata"),
    ("items", "GET", "/items"),
    ("checkout", "GET", "/checkout"),
)
DECISION_STATUS = {
    "promote": "promoted",
    "rollback": "rolled_back",
    "quarantine": "quarantined",
}
RolloutDecision = Literal["promote", "rollback", "quarantine"]


def ensure_rollout_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS canary_rollouts (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              repair_change_id UUID REFERENCES repair_changes(id) ON DELETE CASCADE,
              status TEXT NOT NULL,
              target_environment TEXT NOT NULL,
              traffic_percentage FLOAT NOT NULL,
              health_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
              started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              completed_at TIMESTAMPTZ,
              decision TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_canary_rollouts_repair_status
            ON canary_rollouts (repair_change_id, status)
            """
        )
    conn.commit()


def list_rollouts(conn: Connection, repair_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM canary_rollouts
            WHERE repair_change_id = %s
            ORDER BY started_at DESC
            """,
            (repair_id,),
        )
        return cur.fetchall()


def get_rollout(conn: Connection, rollout_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM canary_rollouts WHERE id = %s", (rollout_id,))
        return cur.fetchone()


def start_canary_rollout(conn: Connection, repair_id: str, traffic_percentage: float = 10.0) -> dict[str, Any]:
    repair = require_verified_repair(conn, repair_id)
    rollout = create_rollout(conn, repair_id, bounded_traffic(traffic_percentage))
    signals = collect_canary_signals()
    completed = finish_rollout(conn, rollout, repair, decide_rollout(signals), signals)
    conn.commit()
    return completed


def promote_rollout(conn: Connection, rollout_id: str) -> dict[str, Any]:
    return force_decision(conn, rollout_id, "promote")


def rollback_rollout(conn: Connection, rollout_id: str) -> dict[str, Any]:
    return force_decision(conn, rollout_id, "rollback")


def quarantine_rollout(conn: Connection, rollout_id: str) -> dict[str, Any]:
    return force_decision(conn, rollout_id, "quarantine")


def require_verified_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = get_repair(conn, repair_id)
    if not repair:
        raise ValueError(f"Repair not found: {repair_id}")
    if repair["status"] != "verified":
        raise ValueError(f"Repair must be verified before canary rollout: {repair['status']}")
    return repair


def create_rollout(conn: Connection, repair_id: str, traffic_percentage: float) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO canary_rollouts (
              repair_change_id, status, target_environment, traffic_percentage, health_signals
            )
            VALUES (%s, 'running', %s, %s, '{}'::jsonb)
            RETURNING *
            """,
            (repair_id, CANARY_ENVIRONMENT, traffic_percentage),
        )
        rollout = cur.fetchone()
    conn.commit()
    return rollout


def collect_canary_signals() -> dict[str, Any]:
    probes = [probe(*definition) for definition in CANARY_PROBES]
    passed = sum(1 for item in probes if item["passed"])
    return {
        "strategy": "synthetic_probe_canary",
        "sample_size": len(probes),
        "passed": passed,
        "failed": len(probes) - passed,
        "probes": probes,
        "error_rate": round((len(probes) - passed) / max(len(probes), 1), 3),
    }


def probe(name: str, method: str, path: str) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=8) as client:
            response = client.request(method, f"{TARGET_BASE_URL}{path}")
        body = response.json()
        passed = response.status_code < 500 and not (name == "health" and body.get("status") != "healthy")
        detail = {"status_code": response.status_code, "body": body}
    except Exception as exc:
        passed = False
        detail = {"error": type(exc).__name__, "message": str(exc)}

    return {
        "name": name,
        "method": method,
        "path": path,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "duration_ms": int((time.perf_counter() - start) * 1000),
        "detail": detail,
    }


def decide_rollout(signals: dict[str, Any]) -> RolloutDecision:
    if signals["failed"] == 0:
        return "promote"
    if signals["error_rate"] >= 0.5:
        return "rollback"
    return "quarantine"


def finish_rollout(
    conn: Connection,
    rollout: dict[str, Any],
    repair: dict[str, Any],
    decision: RolloutDecision,
    signals: dict[str, Any],
) -> dict[str, Any]:
    status = DECISION_STATUS[decision]
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE canary_rollouts
            SET status = %s,
                health_signals = %s,
                decision = %s,
                completed_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, Jsonb(signals), decision, rollout["id"]),
        )
        completed = cur.fetchone()
        cur.execute(
            """
            UPDATE repair_changes
            SET status = %s,
                result = coalesce(result, '{}'::jsonb) || %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                "released" if decision == "promote" else status,
                Jsonb({"canary": serialize_rollout(completed)}),
                repair["id"],
            ),
        )

    incident = load_incident(conn, str(repair["incident_id"]))
    record_rollout_event(conn, incident, completed)
    update_incident_memory(conn, str(incident["id"]))
    return completed


def force_decision(conn: Connection, rollout_id: str, decision: RolloutDecision) -> dict[str, Any]:
    rollout = require_rollout(conn, rollout_id)
    repair = require_repair_for_rollout(conn, rollout)
    # Manual decisions reuse the same persistence path as automated decisions,
    # but preserve the previous canary status in the health signals.
    signals = {
        **(rollout["health_signals"] or {}),
        "manual_decision": decision,
        "previous_status": rollout["status"],
    }
    completed = finish_rollout(conn, rollout, repair, decision, signals)
    conn.commit()
    return completed


def require_rollout(conn: Connection, rollout_id: str) -> dict[str, Any]:
    rollout = get_rollout(conn, rollout_id)
    if not rollout:
        raise ValueError(f"Canary rollout not found: {rollout_id}")
    return rollout


def require_repair_for_rollout(conn: Connection, rollout: dict[str, Any]) -> dict[str, Any]:
    repair = get_repair(conn, str(rollout["repair_change_id"]))
    if not repair:
        raise ValueError(f"Repair not found for rollout: {rollout['repair_change_id']}")
    return repair


def record_rollout_event(conn: Connection, incident: dict[str, Any], rollout: dict[str, Any]) -> None:
    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type=f"canary.{rollout['status']}",
        actor="canary-rollout",
        payload=serialize_rollout(rollout),
    )


def update_incident_memory(conn: Connection, incident_id: str) -> None:
    from app.memory import write_incident_memory

    write_incident_memory(conn, incident_id)


def bounded_traffic(value: float) -> float:
    return min(max(float(value), 0.1), 25.0)


def serialize_rollout(rollout: dict[str, Any]) -> dict[str, Any]:
    return {
        **rollout,
        "id": str(rollout["id"]),
        "repair_change_id": str(rollout["repair_change_id"]),
        "started_at": rollout["started_at"].isoformat() if rollout.get("started_at") else None,
        "completed_at": rollout["completed_at"].isoformat() if rollout.get("completed_at") else None,
    }
