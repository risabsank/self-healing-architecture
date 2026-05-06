from typing import Any

import httpx
from psycopg import Connection

from app.monitoring import check_service_health


class VerificationError(RuntimeError):
    pass


ACTION_SCENARIO_EXPECTATIONS = {
    "SET_ENV_VAR": {
        "DATABASE_URL": ["bad_database_url"],
        "TARGET_REQUIRED_SECRET": ["missing_required_env"],
    },
    "RESTART_SERVICE": {
        "default": ["port_conflict"],
    },
    "DISABLE_FEATURE_FLAG": {
        "FEATURE_CHECKOUT_ENABLED": ["bad_feature_flag", "rate_limit"],
    },
    "SWITCH_DEPENDENCY_TO_MOCK": {
        "checkout-provider": ["dependency_unavailable", "rate_limit"],
    },
    "ROLLBACK_CONFIG": {
        "previous_known_good_app_version": ["schema_mismatch"],
    },
}


async def verify_recovery(
    conn: Connection,
    incident_id: str,
    action: dict[str, Any],
    service: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    params = dict(action["params"] or {})
    base_url = service["base_url"]

    health_result = await check_service_health(
        conn=conn,
        sandbox_id=service["sandbox_id"],
        service_name=service["service_name"],
        health_url=service["health_url"],
        manage_incidents=False,
    )
    checks.append(
        build_check(
            name="health_check",
            passed=health_result["status"] == "healthy",
            expected="target health status is healthy",
            observed=health_result,
        )
    )

    metadata = await get_json(f"{base_url}/metadata")
    checks.append(
        build_check(
            name="metadata_check",
            passed=metadata["ok"],
            expected="target metadata endpoint returns JSON",
            observed=metadata,
        )
    )

    scenario_result = await get_json(f"{base_url}/scenarios")
    active_scenarios = scenario_result["body"].get("active", []) if scenario_result["ok"] else []
    expected_cleared = expected_cleared_scenarios(action["action_type"], params)
    checks.append(
        build_check(
            name="scenario_clearance",
            passed=scenario_result["ok"] and not any(scenario in active_scenarios for scenario in expected_cleared),
            expected=f"cleared scenarios are inactive: {expected_cleared}",
            observed={"active_scenarios": active_scenarios, "expected_cleared": expected_cleared},
        )
    )

    items_result = await get_json(f"{base_url}/items")
    checks.append(
        build_check(
            name="database_backed_endpoint",
            passed=items_result["ok"] and isinstance(items_result["body"].get("items"), list),
            expected="GET /items returns a JSON item list",
            observed=items_result,
        )
    )

    checkout_result = await get_json(f"{base_url}/checkout")
    checkout_status = checkout_result["body"].get("status") if checkout_result["ok"] else None
    checks.append(
        build_check(
            name="dependency_probe",
            passed=checkout_result["ok"] and checkout_status in {"ready", "disabled"},
            expected="GET /checkout returns ready or intentionally disabled",
            observed=checkout_result,
        )
    )

    checks.extend(action_specific_checks(action["action_type"], params, health_result, items_result, checkout_result))
    passed = all(check["passed"] for check in checks)

    return {
        "status": "passed" if passed else "failed",
        "incident_id": incident_id,
        "action_id": str(action["id"]),
        "service": service["service_name"],
        "checks": checks,
        "summary": "All recovery verification checks passed."
        if passed
        else "One or more recovery verification checks failed.",
    }


def action_specific_checks(
    action_type: str,
    params: dict[str, Any],
    health_result: dict[str, Any],
    items_result: dict[str, Any],
    checkout_result: dict[str, Any],
) -> list[dict[str, Any]]:
    health_checks = health_result.get("detail", {}).get("checks", {})
    checks: list[dict[str, Any]] = []

    if action_type == "SET_ENV_VAR" and params.get("key") == "DATABASE_URL":
        checks.append(
            build_check(
                name="database_dependency",
                passed=bool(health_checks.get("database", {}).get("ok")),
                expected="database dependency is healthy after restoring DATABASE_URL",
                observed=health_checks.get("database", {}),
            )
        )

    if action_type == "SET_ENV_VAR" and params.get("key") == "TARGET_REQUIRED_SECRET":
        checks.append(
            build_check(
                name="required_env_present",
                passed=bool(health_checks.get("required_env", {}).get("ok")),
                expected="required environment check is healthy",
                observed=health_checks.get("required_env", {}),
            )
        )

    if action_type == "RESTART_SERVICE":
        checks.append(
            build_check(
                name="process_accepting_traffic",
                passed=bool(health_checks.get("process", {}).get("ok")),
                expected="process check is healthy after restart",
                observed=health_checks.get("process", {}),
            )
        )

    if action_type == "ROLLBACK_CONFIG":
        checks.append(
            build_check(
                name="schema_compatible_endpoint",
                passed=items_result["ok"] and isinstance(items_result["body"].get("items"), list),
                expected="database-backed item listing works after rollback",
                observed=items_result,
            )
        )

    if action_type in {"DISABLE_FEATURE_FLAG", "SWITCH_DEPENDENCY_TO_MOCK"}:
        checks.append(
            build_check(
                name="checkout_dependency_recovered",
                passed=checkout_result["ok"] and checkout_result["body"].get("status") in {"ready", "disabled"},
                expected="checkout path no longer returns dependency or feature failures",
                observed=checkout_result,
            )
        )

    return checks


def expected_cleared_scenarios(action_type: str, params: dict[str, Any]) -> list[str]:
    expectations = ACTION_SCENARIO_EXPECTATIONS.get(action_type, {})

    if action_type == "SET_ENV_VAR":
        return expectations.get(params.get("key"), [])

    if action_type == "DISABLE_FEATURE_FLAG":
        return expectations.get(params.get("flag"), [])

    if action_type == "SWITCH_DEPENDENCY_TO_MOCK":
        return expectations.get(params.get("dependency"), [])

    if action_type == "ROLLBACK_CONFIG":
        return expectations.get(params.get("target"), [])

    return expectations.get("default", [])


async def get_json(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(url)
            body = response.json()
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "body": {},
            "error": type(exc).__name__,
            "message": str(exc),
        }

    return {
        "ok": response.status_code < 400,
        "status_code": response.status_code,
        "body": body,
    }


def build_check(name: str, passed: bool, expected: str, observed: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "expected": expected,
        "observed": observed,
    }
