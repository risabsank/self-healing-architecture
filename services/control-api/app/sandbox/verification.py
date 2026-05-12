from collections.abc import Callable
from typing import Any

import httpx
from psycopg import Connection

from app.apps import app_probes, get_application_for_sandbox, manifest_from_app, safe_action, service_manifest
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
    app = get_application_for_sandbox(conn, service["sandbox_id"])
    manifest = manifest_from_app(app)
    svc_manifest = service_manifest(manifest, service["service_name"])
    manifest_action = safe_action(manifest, action["action_type"], (action["params"] or {}).get("service", service["service_name"]))
    health = await check_service_health(
        conn,
        service["sandbox_id"],
        service["service_name"],
        service["health_url"],
        manage_incidents=False,
    )
    probe_results = await run_manifest_probes(base_url, app_probes(manifest, "critical"))
    scenarios = await get_json(f"{base_url}/scenarios")

    expected_cleared = expected_scenarios(action["action_type"], action["params"] or {}, manifest_action)
    checks = [
        check("health_check", health["status"] == "healthy", "target health status is healthy", health),
        check(
            "scenario_clearance",
            not expected_cleared or (scenarios["ok"] and not set(expected_cleared) & set(scenarios["body"].get("active", []))),
            f"cleared scenarios are inactive: {expected_cleared}",
            {"active_scenarios": scenarios["body"].get("active", []), "expected_cleared": expected_cleared},
        ),
    ]
    checks.extend(probe_results)
    checks.extend(specific_checks(action["action_type"], action["params"] or {}, health, probe_results, svc_manifest))

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
    probe_results: list[dict[str, Any]],
    svc_manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    health_checks = health.get("detail", {}).get("checks", {})
    probe_by_name = {probe["name"]: probe for probe in probe_results}
    checkout = probe_by_name.get("probe_checkout", {})
    items = probe_by_name.get("probe_items", {})
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
            lambda: bool(items.get("passed", True)),
            items,
        ),
        ("DISABLE_FEATURE_FLAG", "FEATURE_CHECKOUT_ENABLED"): (
            "checkout_dependency_recovered",
            "checkout path no longer returns dependency or feature failures",
            lambda: bool(checkout.get("passed", True)),
            checkout,
        ),
        ("SWITCH_DEPENDENCY_TO_MOCK", "checkout-provider"): (
            "checkout_dependency_recovered",
            "checkout dependency behavior is healthy",
            lambda: bool(checkout.get("passed", True)),
            checkout,
        ),
    }
    rule = rules.get((action_type, action_key(action_type, params))) or rules.get((action_type, "default"))
    if not rule:
        return []
    name, expected, predicate, observed = rule
    return [check(name, predicate(), expected, observed)]


def expected_scenarios(action_type: str, params: dict[str, Any], manifest_action: dict[str, Any] | None = None) -> list[str]:
    if manifest_action and manifest_action.get("clears_scenarios"):
        return manifest_action["clears_scenarios"]
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
    return tuple([await get_json(url) for url in urls])


async def run_manifest_probes(base_url: str, probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for probe in probes:
        response = await request_probe(base_url, probe)
        body = response.get("body") or {}
        healthy_status = probe.get("healthy_status")
        status_ok = response["ok"] and response.get("status_code", 999) < probe.get("expected_status_lt", 500)
        body_ok = not healthy_status or body.get("status") == healthy_status
        results.append(
            check(
                f"probe_{probe['name']}",
                status_ok and body_ok,
                f"{probe.get('method', 'GET')} {probe['path']} passes manifest probe",
                response,
            )
        )
    return results


async def request_probe(base_url: str, probe: dict[str, Any]) -> dict[str, Any]:
    method = probe.get("method", "GET")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(method, f"{base_url}{probe['path']}")
            return {"ok": response.status_code < 500, "status_code": response.status_code, "body": response.json()}
    except Exception as exc:
        return {"ok": False, "status_code": None, "body": {}, "error": type(exc).__name__, "message": str(exc)}


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
