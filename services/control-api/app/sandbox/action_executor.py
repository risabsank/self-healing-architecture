from typing import Any

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.monitoring import check_service_health
from app.observability import record_incident_event, record_runtime_event
from app.sandbox.allowed_actions import ActionPolicyError, validate_action_policy


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
            action_type=action["action_type"],
            params=params,
            risk_score=float(action["risk_score"]),
            requires_approval=bool(action["requires_approval"]),
        )
    except ActionPolicyError as exc:
        result = mark_action_blocked(conn, action, incident, actor, str(exc))
        conn.commit()
        raise ActionBlockedError(str(exc)) from exc

    if action["status"] not in EXECUTABLE_STATUSES:
        message = f"Action status does not allow execution: {action['status']}"
        result = mark_action_blocked(conn, action, incident, actor, message)
        conn.commit()
        raise ActionBlockedError(message)

    if action["requires_approval"] and action["status"] != "approved":
        message = "Action requires approval before execution"
        result = mark_action_awaiting_approval(conn, action, incident, actor, message)
        conn.commit()
        raise ActionBlockedError(message)

    service = load_service(conn, incident["sandbox_id"], params["service"])
    mark_action_executing(conn, action, incident, actor, policy.description)
    conn.commit()

    try:
        target_result = await apply_runtime_action(
            action_type=action["action_type"],
            params=params,
            base_url=service["base_url"],
        )
        verification = await check_service_health(
            conn=conn,
            sandbox_id=incident["sandbox_id"],
            service_name=service["service_name"],
            health_url=service["health_url"],
        )
        result = {
            "status": "executed",
            "policy": policy.description,
            "target_result": target_result,
            "verification": verification,
        }
        mark_action_executed(conn, action, incident, actor, result)
        conn.commit()
        return result
    except Exception as exc:
        result = {
            "status": "failed",
            "error": type(exc).__name__,
            "message": str(exc),
        }
        mark_action_failed(conn, action, incident, actor, result)
        conn.commit()
        raise ActionExecutionError(str(exc)) from exc


def load_action(conn: Connection, action_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, incident_id, action_type, params, risk_score, requires_approval, status, result
            FROM remediation_actions
            WHERE id = %s
            """,
            (action_id,),
        )
        action = cur.fetchone()

    if not action:
        raise ActionExecutionError(f"Remediation action not found: {action_id}")
    return action


def load_incident(conn: Connection, incident_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, status, title
            FROM incidents
            WHERE id = %s
            """,
            (incident_id,),
        )
        incident = cur.fetchone()

    if not incident:
        raise ActionExecutionError(f"Incident not found: {incident_id}")
    return incident


def load_service(conn: Connection, sandbox_id: str, service_name: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sandbox_id, service_name, service_type, base_url, health_url, metadata
            FROM sandbox_services
            WHERE sandbox_id = %s AND service_name = %s
            """,
            (sandbox_id, service_name),
        )
        service = cur.fetchone()

    if not service or not service["base_url"] or not service["health_url"]:
        raise ActionExecutionError(f"Sandbox service is not executable: {sandbox_id}/{service_name}")
    return service


async def apply_runtime_action(action_type: str, params: dict[str, Any], base_url: str) -> dict[str, Any]:
    if action_type == "SET_ENV_VAR":
        return await restore_config_value(base_url, params["key"])

    if action_type == "RESTART_SERVICE":
        return await target_request("POST", f"{base_url}/runtime/restart", {"service": params["service"]})

    if action_type == "DISABLE_FEATURE_FLAG":
        return await disable_feature_flag(base_url, params["flag"])

    if action_type == "SWITCH_DEPENDENCY_TO_MOCK":
        return await switch_dependency_to_mock(base_url, params["dependency"])

    if action_type == "ROLLBACK_CONFIG":
        return await rollback_config(base_url, params["target"])

    raise ActionExecutionError(f"Action type has no runtime adapter: {action_type}")


async def restore_config_value(base_url: str, key: str) -> dict[str, Any]:
    scenario_by_key = {
        "DATABASE_URL": "bad_database_url",
        "TARGET_REQUIRED_SECRET": "missing_required_env",
    }
    return await target_request(
        "POST",
        f"{base_url}/runtime/config/restore",
        {"key": key, "scenario": scenario_by_key[key]},
    )


async def disable_feature_flag(base_url: str, flag: str) -> dict[str, Any]:
    result = await target_request("POST", f"{base_url}/runtime/feature-flags/{flag}/disable", {})
    if "rate_limit" in result.get("active", []):
        rate_limit_result = await target_request(
            "POST",
            f"{base_url}/runtime/dependencies/checkout-provider/switch-to-mock",
            {},
        )
        result["rate_limit_dependency_fallback"] = rate_limit_result
    return result


async def switch_dependency_to_mock(base_url: str, dependency: str) -> dict[str, Any]:
    return await target_request(
        "POST",
        f"{base_url}/runtime/dependencies/{dependency}/switch-to-mock",
        {},
    )


async def rollback_config(base_url: str, target: str) -> dict[str, Any]:
    return await target_request("POST", f"{base_url}/runtime/config/rollback", {"target": target})


async def target_request(method: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(method, url, json=payload)
    except httpx.HTTPError as exc:
        raise ActionExecutionError(f"Target runtime action failed: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise ActionExecutionError("Target runtime action returned non-JSON response") from exc

    if response.status_code >= 400:
        raise ActionExecutionError(f"Target runtime action rejected request: {body}")

    return body


def mark_action_executing(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    actor: str,
    policy_description: str,
) -> None:
    result = {
        **(action["result"] or {}),
        "execution": {
            "status": "executing",
            "policy": policy_description,
        },
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = 'executing', result = %s
            WHERE id = %s
            """,
            (Jsonb(result), action["id"]),
        )
        cur.execute("UPDATE incidents SET status = 'remediating' WHERE id = %s", (incident["id"],))

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type="mitigation.executing",
        actor=actor,
        payload={
            "action_id": str(action["id"]),
            "action_type": action["action_type"],
            "params": action["params"],
            "policy": policy_description,
        },
    )


def mark_action_executed(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    actor: str,
    result: dict[str, Any],
) -> None:
    verification = result.get("verification") or {}
    incident_status = "resolved" if verification.get("status") == "healthy" else "verifying"
    final_summary = (
        "Service health recovered after guarded runtime mitigation."
        if incident_status == "resolved"
        else None
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = 'executed', result = %s
            WHERE id = %s
            """,
            (Jsonb({**(action["result"] or {}), "execution": result}), action["id"]),
        )
        if final_summary:
            cur.execute(
                """
                UPDATE incidents
                SET status = %s,
                    resolved_at = coalesce(resolved_at, now()),
                    final_summary = %s
                WHERE id = %s
                """,
                (incident_status, final_summary, incident["id"]),
            )
        else:
            cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (incident_status, incident["id"]))

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type="mitigation.executed",
        actor=actor,
        payload={
            "action_id": str(action["id"]),
            "action_type": action["action_type"],
            "result": result,
        },
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


def mark_action_failed(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    actor: str,
    result: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = 'failed', result = %s
            WHERE id = %s
            """,
            (Jsonb({**(action["result"] or {}), "execution": result}), action["id"]),
        )
        cur.execute("UPDATE incidents SET status = 'mitigation_failed' WHERE id = %s", (incident["id"],))

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type="mitigation.failed",
        actor=actor,
        payload={"action_id": str(action["id"]), "action_type": action["action_type"], "result": result},
    )


def mark_action_blocked(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    actor: str,
    reason: str,
) -> dict[str, Any]:
    result = {
        **(action["result"] or {}),
        "execution": {
            "status": "blocked",
            "reason": reason,
        },
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = 'blocked', result = %s
            WHERE id = %s
            """,
            (Jsonb(result), action["id"]),
        )
        cur.execute("UPDATE incidents SET status = 'blocked' WHERE id = %s", (incident["id"],))

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type="mitigation.blocked",
        actor=actor,
        payload={
            "action_id": str(action["id"]),
            "action_type": action["action_type"],
            "reason": reason,
        },
    )
    return result


def mark_action_awaiting_approval(
    conn: Connection,
    action: dict[str, Any],
    incident: dict[str, Any],
    actor: str,
    reason: str,
) -> dict[str, Any]:
    result = {
        **(action["result"] or {}),
        "execution": {
            "status": "awaiting_approval",
            "reason": reason,
        },
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = 'awaiting_approval', result = %s
            WHERE id = %s
            """,
            (Jsonb(result), action["id"]),
        )
        cur.execute("UPDATE incidents SET status = 'awaiting_approval' WHERE id = %s", (incident["id"],))

    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type="mitigation.awaiting_approval",
        actor=actor,
        payload={
            "action_id": str(action["id"]),
            "action_type": action["action_type"],
            "reason": reason,
        },
    )
    return result
