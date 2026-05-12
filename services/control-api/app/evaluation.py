import asyncio
import time
from dataclasses import dataclass
from statistics import mean
from typing import Any

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.agents.graph import analyze_incident
from app.monitoring import check_service_health
from app.observability import record_incident_event
from app.sandbox.action_executor import execute_remediation_action


SANDBOX_ID = "local-docker"
SERVICE_NAME = "target-api"
EVALUATION_ACTOR = "evaluation-harness"
DETECTION_POLL_SECONDS = 0.2


class EvaluationRequest(BaseModel):
    scenarios: list[str] | None = None
    repeats: int = Field(default=1, ge=1, le=10)
    detection_timeout_seconds: float = Field(default=8.0, ge=1.0, le=60.0)
    auto_approve_actions: bool = True


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    expected_root_cause: str
    expected_action: str
    degraded_only: bool = False


SCENARIOS: dict[str, ScenarioSpec] = {
    "bad_database_url": ScenarioSpec("bad_database_url", "Broken database connection string", "SET_ENV_VAR"),
    "missing_required_env": ScenarioSpec("missing_required_env", "Missing required environment variable", "SET_ENV_VAR"),
    "schema_mismatch": ScenarioSpec("schema_mismatch", "Application/schema mismatch after change", "ROLLBACK_CONFIG"),
    "port_conflict": ScenarioSpec("port_conflict", "Service process or port binding conflict", "RESTART_SERVICE"),
    "bad_feature_flag": ScenarioSpec("bad_feature_flag", "Bad feature flag enabled a broken code path", "DISABLE_FEATURE_FLAG", True),
    "dependency_unavailable": ScenarioSpec(
        "dependency_unavailable",
        "Downstream API dependency unavailable",
        "SWITCH_DEPENDENCY_TO_MOCK",
        True,
    ),
    "rate_limit": ScenarioSpec("rate_limit", "Dependency rate limiting", "DISABLE_FEATURE_FLAG", True),
}


def ensure_evaluation_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_runs (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              status TEXT NOT NULL,
              scenario_filter JSONB NOT NULL DEFAULT '[]'::jsonb,
              repeats INTEGER NOT NULL,
              aggregate_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
              result JSONB NOT NULL DEFAULT '{}'::jsonb,
              started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              completed_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_cases (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              run_id UUID REFERENCES evaluation_runs(id) ON DELETE CASCADE,
              scenario_name TEXT NOT NULL,
              iteration INTEGER NOT NULL,
              status TEXT NOT NULL,
              incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
              expected_root_cause TEXT NOT NULL,
              diagnosed_root_cause TEXT,
              selected_action TEXT,
              metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
              result JSONB NOT NULL DEFAULT '{}'::jsonb,
              started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              completed_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_evaluation_cases_run_iteration
            ON evaluation_cases (run_id, iteration, scenario_name)
            """
        )
    conn.commit()


async def run_evaluation(conn: Connection, request: EvaluationRequest) -> dict[str, Any]:
    ensure_evaluation_schema(conn)
    scenario_names = requested_scenarios(request.scenarios)
    run = create_run(conn, scenario_names, request.repeats)

    cases = []
    for iteration in range(1, request.repeats + 1):
        for scenario_name in scenario_names:
            case = await run_case(conn, str(run["id"]), SCENARIOS[scenario_name], iteration, request)
            cases.append(case)

    aggregate = aggregate_metrics(cases)
    status = "passed" if all(case["status"] == "passed" for case in cases) else "failed"
    completed = finish_run(conn, str(run["id"]), status, aggregate, {"case_count": len(cases)})
    completed["cases"] = cases
    return completed


def requested_scenarios(names: list[str] | None) -> list[str]:
    if not names:
        return list(SCENARIOS)
    unknown = sorted(set(names) - set(SCENARIOS))
    if unknown:
        raise ValueError(f"Unknown evaluation scenario(s): {', '.join(unknown)}")
    return names


async def run_case(
    conn: Connection,
    run_id: str,
    spec: ScenarioSpec,
    iteration: int,
    request: EvaluationRequest,
) -> dict[str, Any]:
    case = create_case(conn, run_id, spec, iteration)
    base_url, health_url = load_target_urls(conn)
    started = time.perf_counter()

    try:
        await prepare_target(conn, base_url, health_url)
        memory_before = memory_count(conn)

        detection = await activate_and_detect(conn, base_url, health_url, spec, request.detection_timeout_seconds)
        detection_ms = elapsed_ms(started)

        incident = create_incident(conn, spec, detection)
        analysis, diagnosis_ms = diagnose(conn, str(incident["id"]))

        action = prepare_action(conn, str(incident["id"]), request.auto_approve_actions)
        execution, recovery_ms = await execute_action(conn, action)
        final_health = await check_service_health(conn, SANDBOX_ID, SERVICE_NAME, health_url, manage_incidents=False)

        analysis_body = analysis.model_dump()
        metrics = case_metrics(
            spec=spec,
            detection_ms=detection_ms,
            diagnosis_ms=diagnosis_ms,
            recovery_ms=recovery_ms,
            analysis=analysis_body,
            action=action,
            execution=execution,
            memory_before=memory_before,
        )
        result = {
            "detection": detection,
            "analysis": analysis_body,
            "action": serialize_action(action),
            "execution": execution,
            "final_health": final_health,
        }
        status = "passed" if metrics["diagnosis_accurate"] and metrics["first_action_success"] else "failed"
        return finish_case(conn, str(case["id"]), status, str(incident["id"]), metrics, result)
    except Exception as exc:
        metrics = {"detection_time_ms": elapsed_ms(started), "error": type(exc).__name__}
        result = {"message": str(exc)}
        return finish_case(conn, str(case["id"]), "failed", None, metrics, result)
    finally:
        await reset_scenarios(base_url)


async def prepare_target(conn: Connection, base_url: str, health_url: str) -> None:
    await reset_scenarios(base_url)
    await check_service_health(conn, SANDBOX_ID, SERVICE_NAME, health_url, manage_incidents=False)


async def activate_and_detect(
    conn: Connection,
    base_url: str,
    health_url: str,
    spec: ScenarioSpec,
    timeout_seconds: float,
) -> dict[str, Any]:
    await target_post(base_url, f"/scenarios/{spec.name}/activate")
    return await detect_failure(conn, base_url, health_url, spec, timeout_seconds)


def diagnose(conn: Connection, incident_id: str) -> tuple[Any, int]:
    started = time.perf_counter()
    return analyze_incident(conn, incident_id), elapsed_ms(started)


def prepare_action(conn: Connection, incident_id: str, auto_approve: bool) -> dict[str, Any] | None:
    action = selected_action(conn, incident_id)
    if action and action["requires_approval"] and auto_approve:
        approve_action(conn, action)
        action["status"] = "approved"
    return action


async def execute_action(conn: Connection, action: dict[str, Any] | None) -> tuple[dict[str, Any] | None, int | None]:
    if not action:
        return None, None
    started = time.perf_counter()
    result = await execute_remediation_action(conn, str(action["id"]))
    return result, elapsed_ms(started)


async def detect_failure(
    conn: Connection,
    base_url: str,
    health_url: str,
    spec: ScenarioSpec,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_seconds

    while time.perf_counter() < deadline:
        health = await check_service_health(conn, SANDBOX_ID, SERVICE_NAME, health_url, manage_incidents=False)
        degraded = await checkout_degraded(base_url) if spec.degraded_only else None
        observation = {"health": health, "degraded_probe": degraded}

        if health["status"] == "unhealthy" or (degraded and degraded["degraded"]):
            return observation

        await asyncio.sleep(DETECTION_POLL_SECONDS)

    raise TimeoutError(f"Scenario was not detected before timeout: {spec.name}")


async def checkout_degraded(base_url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{base_url}/checkout")
            body = response.json()
        return {
            "degraded": response.status_code >= 400,
            "status_code": response.status_code,
            "body": body,
        }
    except Exception as exc:
        return {"degraded": True, "error": type(exc).__name__, "message": str(exc)}


def create_run(conn: Connection, scenarios: list[str], repeats: int) -> dict[str, Any]:
    return fetch_one(
        conn,
        """
        INSERT INTO evaluation_runs (status, scenario_filter, repeats)
        VALUES ('running', %s, %s)
        RETURNING *
        """,
        (Jsonb(scenarios), repeats),
    )


def create_case(conn: Connection, run_id: str, spec: ScenarioSpec, iteration: int) -> dict[str, Any]:
    return fetch_one(
        conn,
        """
        INSERT INTO evaluation_cases (
          run_id, scenario_name, iteration, status, expected_root_cause
        )
        VALUES (%s, %s, %s, 'running', %s)
        RETURNING *
        """,
        (run_id, spec.name, iteration, spec.expected_root_cause),
    )


def finish_run(
    conn: Connection,
    run_id: str,
    status: str,
    aggregate: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return fetch_one(
        conn,
        """
        UPDATE evaluation_runs
        SET status = %s, aggregate_metrics = %s, result = %s, completed_at = now()
        WHERE id = %s
        RETURNING *
        """,
        (status, Jsonb(aggregate), Jsonb(result), run_id),
    )


def finish_case(
    conn: Connection,
    case_id: str,
    status: str,
    incident_id: str | None,
    metrics: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    analysis = result.get("analysis") or {}
    action = result.get("action") or {}
    return fetch_one(
        conn,
        """
        UPDATE evaluation_cases
        SET status = %s,
            incident_id = %s,
            diagnosed_root_cause = %s,
            selected_action = %s,
            metrics = %s,
            result = %s,
            completed_at = now()
        WHERE id = %s
        RETURNING *
        """,
        (
            status,
            incident_id,
            top_hypothesis(analysis),
            action.get("action_type"),
            Jsonb(metrics),
            Jsonb(result),
            case_id,
        ),
    )


def create_incident(conn: Connection, spec: ScenarioSpec, detection: dict[str, Any]) -> dict[str, Any]:
    incident = fetch_one(
        conn,
        """
        INSERT INTO incidents (sandbox_id, status, title)
        VALUES (%s, 'detected', %s)
        RETURNING *
        """,
        (SANDBOX_ID, f"Evaluation scenario detected: {spec.name}"),
        commit=False,
    )

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=SANDBOX_ID,
        event_type="incident.detected",
        actor=EVALUATION_ACTOR,
        payload={"scenario": spec.name, "detection": detection},
    )
    conn.commit()
    return incident


def approve_action(conn: Connection, action: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = 'approved',
                result = coalesce(result, '{}'::jsonb) || %s
            WHERE id = %s
            """,
            (Jsonb({"approval": {"status": "approved", "actor": EVALUATION_ACTOR}}), action["id"]),
        )
    record_incident_event(
        conn,
        incident_id=str(action["incident_id"]),
        sandbox_id=SANDBOX_ID,
        event_type="mitigation.approved",
        actor=EVALUATION_ACTOR,
        payload={"action_id": str(action["id"]), "action_type": action["action_type"]},
    )
    conn.commit()


def case_metrics(
    *,
    spec: ScenarioSpec,
    detection_ms: int,
    diagnosis_ms: int,
    recovery_ms: int | None,
    analysis: dict[str, Any],
    action: dict[str, Any] | None,
    execution: dict[str, Any] | None,
    memory_before: int,
) -> dict[str, Any]:
    top_cause = top_hypothesis(analysis)
    memory_matches = [item for item in analysis.get("evidence", []) if item.get("source") == "memory"]
    first_action_success = bool(execution and execution.get("verification", {}).get("status") == "passed")
    selected_type = action["action_type"] if action else None
    return {
        "detection_time_ms": detection_ms,
        "diagnosis_time_ms": diagnosis_ms,
        "recovery_time_ms": recovery_ms,
        "diagnosis_accurate": root_cause_matches(spec.expected_root_cause, top_cause),
        "expected_root_cause": spec.expected_root_cause,
        "diagnosed_root_cause": top_cause,
        "expected_action": spec.expected_action,
        "selected_action": selected_type,
        "first_action_success": first_action_success,
        "rollback_used": selected_type == "ROLLBACK_CONFIG",
        "memory_matches": len(memory_matches),
        "memory_available_before_case": memory_before > 0,
        "memory_useful": bool(memory_matches and first_action_success),
    }


def aggregate_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [case["metrics"] for case in cases]
    return {
        "case_count": len(metrics),
        "passed": sum(1 for case in cases if case["status"] == "passed"),
        "failed": sum(1 for case in cases if case["status"] != "passed"),
        "avg_detection_time_ms": avg(item.get("detection_time_ms") for item in metrics),
        "avg_recovery_time_ms": avg(item.get("recovery_time_ms") for item in metrics),
        "diagnosis_accuracy": rate(item.get("diagnosis_accurate") for item in metrics),
        "first_action_success_rate": rate(item.get("first_action_success") for item in metrics),
        "rollback_rate": rate(item.get("rollback_used") for item in metrics),
        "memory_usefulness_rate": rate(item.get("memory_useful") for item in metrics if item.get("memory_available_before_case")),
    }


def avg(values: Any) -> int | None:
    numbers = [value for value in values if isinstance(value, (int, float))]
    return int(mean(numbers)) if numbers else None


def rate(values: Any) -> float | None:
    items = [value for value in values if value is not None]
    return round(sum(1 for value in items if value) / len(items), 3) if items else None


def load_target_urls(conn: Connection) -> tuple[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT base_url, health_url
            FROM sandbox_services
            WHERE sandbox_id = %s AND service_name = %s
            """,
            (SANDBOX_ID, SERVICE_NAME),
        )
        service = cur.fetchone()
    if not service:
        raise ValueError("Evaluation target service is not registered")
    return service["base_url"], service["health_url"]


def selected_action(conn: Connection, incident_id: str) -> dict[str, Any] | None:
    return fetch_one(
        conn,
        """
        SELECT id, incident_id, action_type, params, risk_score, requires_approval, status, result
        FROM remediation_actions
        WHERE incident_id = %s AND status IN ('selected', 'awaiting_approval', 'approved')
        ORDER BY
          CASE status WHEN 'selected' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
          risk_score ASC
        LIMIT 1
        """,
        (incident_id,),
        commit=False,
    )


def memory_count(conn: Connection) -> int:
    return fetch_one(conn, "SELECT count(*) AS count FROM incident_memories", commit=False)["count"]


def fetch_one(
    conn: Connection,
    sql: str,
    params: tuple[Any, ...] = (),
    commit: bool = True,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if commit:
        conn.commit()
    return row


async def reset_scenarios(base_url: str) -> None:
    await target_post(base_url, "/scenarios/reset")


async def target_post(base_url: str, path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(f"{base_url}{path}")
        response.raise_for_status()
        return response.json()


def serialize_action(action: dict[str, Any] | None) -> dict[str, Any] | None:
    if not action:
        return None
    return {**action, "id": str(action["id"]), "incident_id": str(action["incident_id"])}


def top_hypothesis(analysis: dict[str, Any]) -> str | None:
    hypotheses = analysis.get("hypotheses") or []
    return hypotheses[0].get("cause") if hypotheses else None


def root_cause_matches(expected: str, diagnosed: str | None) -> bool:
    if not diagnosed:
        return False
    expected_terms = important_terms(expected)
    diagnosed_terms = important_terms(diagnosed)
    return bool(expected_terms) and len(expected_terms & diagnosed_terms) / len(expected_terms) >= 0.6


def important_terms(text: str) -> set[str]:
    stop = {"the", "and", "or", "a", "an", "to", "of", "is", "in", "for", "with", "after", "before", "enabled"}
    return {
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(token) > 2 and token not in stop
    }


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
