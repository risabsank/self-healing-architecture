from collections.abc import Callable
from typing import Any

import httpx
from psycopg import Connection

from app.monitoring import check_service_health


CLEARED_SCENARIOS = {
    ("SET_ENV_VAR", "DATABASE_URL"): ["bad_database_url"],
    ("SET_ENV_VAR", "TARGET_REQUIRED_SECRET"): ["missing_required_env"],
    ("RESTART_SERVICE", "default"): ["port_conflict"],
    ("DISABLE_FEATURE_FLAG", "FEATURE_CHECKOUT_ENABLED"): ["bad_feature_flag", "rate_limit"],
    ("SWITCH_DEPENDENCY_TO_MOCK", "checkout-provider"): ["dependency_unavailable", "rate_limit"],
    ("ROLLBACK_CONFIG", "previous_known_good_app_version"): ["schema_mismatch"],
}


async def verify_recovery(
    conn: Connection,
    incident_id: str,
    action: dict[str, Any],
    service: dict[str, Any],
) -> dict[str, Any]:
    base_url = service["base_url"]
    health = await check_service_health(
        conn,
        service["sandbox_id"],
        service["service_name"],
        service["health_url"],
        manage_incidents=False,
    )
    metadata, scenarios, items, checkout = await fetch_many(
        f"{base_url}/metadata",
        f"{base_url}/scenarios",
        f"{base_url}/items",
        f"{base_url}/checkout",
    )

    expected_cleared = expected_scenarios(action["action_type"], action["params"] or {})
    checks = [
        check("health_check", health["status"] == "healthy", "target health status is healthy", health),
        check("metadata_check", metadata["ok"], "target metadata endpoint returns JSON", metadata),
        check(
            "scenario_clearance",
            scenarios["ok"] and not set(expected_cleared) & set(scenarios["body"].get("active", [])),
            f"cleared scenarios are inactive: {expected_cleared}",
            {"active_scenarios": scenarios["body"].get("active", []), "expected_cleared": expected_cleared},
        ),
        check("database_backed_endpoint", has_items(items), "GET /items returns a JSON item list", items),
        check("dependency_probe", checkout_ok(checkout), "GET /checkout returns ready or intentionally disabled", checkout),
    ]
    checks.extend(specific_checks(action["action_type"], action["params"] or {}, health, items, checkout))

    passed = all(item["passed"] for item in checks)
    return {
        "status": "passed" if passed else "failed",
        "incident_id": incident_id,
        "action_id": str(action["id"]),
        "service": service["service_name"],
        "checks": checks,
        "summary": "All recovery verification checks passed." if passed else "One or more recovery verification checks failed.",
    }


def specific_checks(
    action_type: str,
    params: dict[str, Any],
    health: dict[str, Any],
    items: dict[str, Any],
    checkout: dict[str, Any],
) -> list[dict[str, Any]]:
    health_checks = health.get("detail", {}).get("checks", {})
    rules: dict[tuple[str, str], tuple[str, str, Callable[[], bool], dict[str, Any]]] = {
        ("SET_ENV_VAR", "DATABASE_URL"): (
            "database_dependency",
            "database dependency is healthy after restoring DATABASE_URL",
            lambda: bool(health_checks.get("database", {}).get("ok")),
            health_checks.get("database", {}),
        ),
        ("SET_ENV_VAR", "TARGET_REQUIRED_SECRET"): (
            "required_env_present",
            "required environment check is healthy",
            lambda: bool(health_checks.get("required_env", {}).get("ok")),
            health_checks.get("required_env", {}),
        ),
        ("RESTART_SERVICE", "default"): (
            "process_accepting_traffic",
            "process check is healthy after restart",
            lambda: bool(health_checks.get("process", {}).get("ok")),
            health_checks.get("process", {}),
        ),
        ("ROLLBACK_CONFIG", "previous_known_good_app_version"): (
            "schema_compatible_endpoint",
            "database-backed item listing works after rollback",
            lambda: has_items(items),
            items,
        ),
        ("DISABLE_FEATURE_FLAG", "FEATURE_CHECKOUT_ENABLED"): (
            "checkout_dependency_recovered",
            "checkout path no longer returns dependency or feature failures",
            lambda: checkout_ok(checkout),
            checkout,
        ),
        ("SWITCH_DEPENDENCY_TO_MOCK", "checkout-provider"): (
            "checkout_dependency_recovered",
            "checkout dependency behavior is healthy",
            lambda: checkout_ok(checkout),
            checkout,
        ),
    }
    rule = rules.get((action_type, action_key(action_type, params))) or rules.get((action_type, "default"))
    if not rule:
        return []
    name, expected, predicate, observed = rule
    return [check(name, predicate(), expected, observed)]


def expected_scenarios(action_type: str, params: dict[str, Any]) -> list[str]:
    return CLEARED_SCENARIOS.get((action_type, action_key(action_type, params)), CLEARED_SCENARIOS.get((action_type, "default"), []))


def action_key(action_type: str, params: dict[str, Any]) -> str:
    key = {
        "SET_ENV_VAR": params.get("key"),
        "DISABLE_FEATURE_FLAG": params.get("flag"),
        "SWITCH_DEPENDENCY_TO_MOCK": params.get("dependency"),
        "ROLLBACK_CONFIG": params.get("target"),
    }.get(action_type, "default")
    return key or "default"


async def fetch_many(*urls: str) -> tuple[dict[str, Any], ...]:
    return tuple(await get_json(url) for url in urls)


async def get_json(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(url)
            return {"ok": response.status_code < 400, "status_code": response.status_code, "body": response.json()}
    except Exception as exc:
        return {"ok": False, "status_code": None, "body": {}, "error": type(exc).__name__, "message": str(exc)}


def has_items(response: dict[str, Any]) -> bool:
    return response["ok"] and isinstance(response["body"].get("items"), list)


def checkout_ok(response: dict[str, Any]) -> bool:
    return response["ok"] and response["body"].get("status") in {"ready", "disabled"}


def check(name: str, passed: bool, expected: str, observed: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": passed, "expected": expected, "observed": observed}
