from typing import Any

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.memory import write_incident_memory
from app.observability import record_incident_event, record_runtime_event
from app.sandbox.allowed_actions import ActionPolicyError, validate_action_policy
from app.sandbox.verification import verify_recovery


class ActionExecutionError(RuntimeError):
    pass


class ActionBlockedError(ActionExecutionError):
    pass


EXECUTABLE_STATUSES = {"selected", "approved", "awaiting_approval", "failed"}


async def execute_remediation_action(
    conn: Connection,
    action_id: str,
    actor: str = "guarded-runtime-executor",
) -> dict[str, Any]:
    action = load_action(conn, action_id)
    incident = load_incident(conn, str(action["incident_id"]))
    params = dict(action["params"] or {})

    try:
        policy = validate_action_policy(
            action["action_type"],
            params,
            float(action["risk_score"]),
            bool(action["requires_approval"]),
        )
        ensure_executable(action)
    except (ActionPolicyError, ActionBlockedError) as exc:
        status = blocked_status(exc)
        write_state(conn, action, incident, status, f"mitigation.{status}", actor, {"reason": str(exc)}, status)
        conn.commit()
        raise ActionBlockedError(str(exc)) from exc

    service = load_service(conn, incident["sandbox_id"], params["service"])
    write_state(
        conn,
        action,
        incident,
        "executing",
        "mitigation.executing",
        actor,
        {"params": params, "policy": policy.description},
        "remediating",
    )
    conn.commit()

    try:
        # The executor only calls typed target runtime endpoints. It never
        # receives or runs raw shell commands.
        target_result = await apply_runtime_action(action["action_type"], params, service["base_url"])
        record_incident_event(
            conn,
            incident_id=str(incident["id"]),
            sandbox_id=incident["sandbox_id"],
            event_type="verification.started",
            actor=actor,
            payload={"action_id": str(action["id"]), "action_type": action["action_type"]},
        )
        verification = await verify_recovery(conn, str(incident["id"]), action, service)
        result = {
            "status": "executed",
            "policy": policy.description,
            "target_result": target_result,
            "verification": verification,
        }
        finish_execution(conn, action, incident, actor, result)
        conn.commit()
        return result
    except Exception as exc:
        result = {"status": "failed", "error": type(exc).__name__, "message": str(exc)}
        write_state(conn, action, incident, "failed", "mitigation.failed", actor, {"result": result}, "mitigation_failed")
        conn.commit()
        raise ActionExecutionError(str(exc)) from exc


def ensure_executable(action: dict[str, Any]) -> None:
    if action["status"] not in EXECUTABLE_STATUSES:
        raise ActionBlockedError(f"Action status does not allow execution: {action['status']}")
    if action["requires_approval"] and action["status"] != "approved":
        raise ActionBlockedError("Action requires approval before execution")


def blocked_status(exc: Exception) -> str:
    return "awaiting_approval" if str(exc) == "Action requires approval before execution" else "blocked"


def load_action(conn: Connection, action_id: str) -> dict[str, Any]:
    action = fetch_one(
        conn,
        """
        SELECT id, incident_id, action_type, params, risk_score, requires_approval, status, result
        FROM remediation_actions
        WHERE id = %s
        """,
        (action_id,),
    )
    if not action:
        raise ActionExecutionError(f"Remediation action not found: {action_id}")
    return action


def load_incident(conn: Connection, incident_id: str) -> dict[str, Any]:
    incident = fetch_one(
        conn,
        "SELECT id, sandbox_id, status, title FROM incidents WHERE id = %s",
        (incident_id,),
    )
    if not incident:
        raise ActionExecutionError(f"Incident not found: {incident_id}")
    return incident


def load_service(conn: Connection, sandbox_id: str, service_name: str) -> dict[str, Any]:
    service = fetch_one(
        conn,
        """
        SELECT sandbox_id, service_name, service_type, base_url, health_url, metadata
        FROM sandbox_services
        WHERE sandbox_id = %s AND service_name = %s
        """,
        (sandbox_id, service_name),
    )
    if not service or not service["base_url"] or not service["health_url"]:
        raise ActionExecutionError(f"Sandbox service is not executable: {sandbox_id}/{service_name}")
    return service


def fetch_one(conn: Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


async def apply_runtime_action(action_type: str, params: dict[str, Any], base_url: str) -> dict[str, Any]:
    if action_type == "SET_ENV_VAR":
        return await target_request(
            "POST",
            f"{base_url}/runtime/config/restore",
            {"key": params["key"], "scenario": config_scenario(params["key"])},
        )
    if action_type == "RESTART_SERVICE":
        return await target_request("POST", f"{base_url}/runtime/restart", {"service": params["service"]})
    if action_type == "DISABLE_FEATURE_FLAG":
        result = await target_request("POST", f"{base_url}/runtime/feature-flags/{params['flag']}/disable", {})
        if "rate_limit" in result.get("active", []):
            result["rate_limit_dependency_fallback"] = await switch_dependency_to_mock(base_url, "checkout-provider")
        return result
    if action_type == "SWITCH_DEPENDENCY_TO_MOCK":
        return await switch_dependency_to_mock(base_url, params["dependency"])
    if action_type == "ROLLBACK_CONFIG":
        return await target_request("POST", f"{base_url}/runtime/config/rollback", {"target": params["target"]})
    raise ActionExecutionError(f"Action type has no runtime adapter: {action_type}")


def config_scenario(key: str) -> str:
    scenarios = {"DATABASE_URL": "bad_database_url", "TARGET_REQUIRED_SECRET": "missing_required_env"}
    return scenarios[key]


async def switch_dependency_to_mock(base_url: str, dependency: str) -> dict[str, Any]:
    return await target_request("POST", f"{base_url}/runtime/dependencies/{dependency}/switch-to-mock", {})


async def target_request(method: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(method, url, json=payload)
            body = response.json()
    except httpx.HTTPError as exc:
        raise ActionExecutionError(f"Target runtime action failed: {exc}") from exc
    except ValueError as exc:
        raise ActionExecutionError("Target runtime action returned non-JSON response") from exc

    if response.status_code >= 400:
        raise ActionExecutionError(f"Target runtime action rejected request: {body}")
    return body


def write_state(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    action_status: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    incident_status: str,
) -> None:
    result = {**(action["result"] or {}), "execution": {"status": action_status, **payload}}
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE remediation_actions SET status = %s, result = %s WHERE id = %s",
            (action_status, Jsonb(result), action["id"]),
        )
        cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (incident_status, incident["id"]))

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type=event_type,
        actor=actor,
        payload={"action_id": str(action["id"]), "action_type": action["action_type"], **payload},
    )


def finish_execution(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    actor: str,
    result: dict[str, Any],
) -> None:
    verification_passed = result["verification"]["status"] == "passed"
    event_type = "verification.completed" if verification_passed else "verification.failed"
    incident_status = "resolved" if verification_passed else "verifying"

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE remediation_actions SET status = 'executed', result = %s WHERE id = %s",
            (Jsonb({**(action["result"] or {}), "execution": result}), action["id"]),
        )
        if verification_passed:
            cur.execute(
                """
                UPDATE incidents
                SET status = 'resolved',
                    resolved_at = coalesce(resolved_at, now()),
                    final_summary = 'Service health recovered after guarded runtime mitigation.'
                WHERE id = %s
                """,
                (incident["id"],),
            )
        else:
            cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (incident_status, incident["id"]))

    for timeline_type, payload in (
        (event_type, {"verification": result["verification"]}),
        ("mitigation.executed", {"result": result}),
    ):
        record_incident_event(
            conn,
            incident_id=str(incident["id"]),
            sandbox_id=incident["sandbox_id"],
            event_type=timeline_type,
            actor=actor,
            payload={"action_id": str(action["id"]), "action_type": action["action_type"], **payload},
        )

    record_runtime_event(
        conn,
        event_type="mitigation.executed",
        actor=actor,
        sandbox_id=incident["sandbox_id"],
        service_name=(action["params"] or {}).get("service"),
        payload={
            "incident_id": str(incident["id"]),
            "action_id": str(action["id"]),
            "action_type": action["action_type"],
            "result": result,
        },
    )
    if verification_passed:
        write_incident_memory(conn, str(incident["id"]))
