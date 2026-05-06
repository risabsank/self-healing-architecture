import asyncio
import time
from typing import Any

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.graph import analyze_incident
from app.observability import record_incident_event, record_runtime_event

OPEN_INCIDENT_STATUSES = (
    "detected",
    "investigating",
    "hypothesizing",
    "mitigation_selected",
    "awaiting_approval",
    "remediating",
    "verifying",
    "blocked",
)


def ensure_incident_for_unhealthy_check(
    conn: Connection,
    health_result: dict[str, Any],
) -> dict[str, Any] | None:
    if health_result["status"] != "unhealthy":
        return None

    sandbox_id = health_result["sandbox_id"]
    service_name = health_result["service_name"]
    existing = find_open_incident(conn, sandbox_id)

    if existing:
        record_incident_event(
            conn,
            incident_id=str(existing["id"]),
            sandbox_id=sandbox_id,
            event_type="healthcheck.unhealthy",
            actor="monitor",
            payload=health_result,
        )
        return existing

    with conn.cursor() as cur:
        title = f"{service_name} is unhealthy"
        cur.execute(
            """
            INSERT INTO incidents (sandbox_id, status, title)
            VALUES (%s, 'detected', %s)
            RETURNING id, sandbox_id, status, title, detected_at
            """,
            (sandbox_id, title),
        )
        incident = cur.fetchone()

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=sandbox_id,
        event_type="incident.detected",
        actor="monitor",
        payload={
            "title": title,
            "trigger": "healthcheck.unhealthy",
            "health_check": health_result,
        },
    )
    try:
        analyze_incident(conn, str(incident["id"]))
    except Exception as exc:
        record_incident_event(
            conn,
            incident_id=str(incident["id"]),
            sandbox_id=sandbox_id,
            event_type="agent.failed",
            actor="incident-agent",
            payload={"error": type(exc).__name__, "message": str(exc)},
        )
    return incident


def record_recovery_observation(conn: Connection, health_result: dict[str, Any]) -> None:
    if health_result["status"] != "healthy":
        return

    sandbox_id = health_result["sandbox_id"]
    incident = find_open_incident(conn, sandbox_id)
    if incident:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE incidents
                SET status = 'resolved',
                    resolved_at = now(),
                    final_summary = 'Service health recovered after observation.'
                WHERE id = %s
                """,
                (incident["id"],),
            )
        record_incident_event(
            conn,
            incident_id=str(incident["id"]),
            sandbox_id=sandbox_id,
            event_type="incident.resolved",
            actor="monitor",
            payload=health_result,
        )


def find_open_incident(conn: Connection, sandbox_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, title
            FROM incidents
            WHERE sandbox_id = %s AND status = ANY(%s)
            ORDER BY detected_at DESC
            LIMIT 1
            """,
            (sandbox_id, list(OPEN_INCIDENT_STATUSES)),
        )
        return cur.fetchone()


async def check_service_health(
    conn: Connection,
    sandbox_id: str,
    service_name: str,
    health_url: str,
    manage_incidents: bool = True,
) -> dict[str, Any]:
    start = time.perf_counter()
    status = "unknown"
    detail: dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(health_url)
            latency_ms = int((time.perf_counter() - start) * 1000)
            detail = response.json()
            status = detail.get("status", "unknown")
            if response.status_code >= 500:
                status = "unhealthy"
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        status = "unhealthy"
        detail = {
            "error": type(exc).__name__,
            "message": str(exc),
        }

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO health_checks (sandbox_id, service_name, status, latency_ms, detail)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, checked_at
            """,
            (sandbox_id, service_name, status, latency_ms, Jsonb(detail)),
        )
        inserted = cur.fetchone()

    result = {
        "id": str(inserted["id"]),
        "checked_at": inserted["checked_at"].isoformat(),
        "sandbox_id": sandbox_id,
        "service_name": service_name,
        "status": status,
        "latency_ms": latency_ms,
        "detail": detail,
    }
    record_runtime_event(
        conn,
        event_type="healthcheck.recorded",
        actor="monitor",
        sandbox_id=sandbox_id,
        service_name=service_name,
        payload=result,
    )
    if manage_incidents:
        ensure_incident_for_unhealthy_check(conn, result)
        record_recovery_observation(conn, result)
    conn.commit()

    return result


async def run_all_health_checks(conn: Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sandbox_id, service_name, health_url
            FROM sandbox_services
            WHERE health_url IS NOT NULL
            ORDER BY sandbox_id, service_name
            """
        )
        services = cur.fetchall()

    results = []
    for service in services:
        results.append(
            await check_service_health(
                conn=conn,
                sandbox_id=service["sandbox_id"],
                service_name=service["service_name"],
                health_url=service["health_url"],
            )
        )
    return results


async def monitor_loop(connection_factory, interval_seconds: int) -> None:
    while True:
        try:
            with connection_factory() as conn:
                await run_all_health_checks(conn)
        except Exception:
            pass

        await asyncio.sleep(interval_seconds)
