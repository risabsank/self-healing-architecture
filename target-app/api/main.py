import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, UTC
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel


APP_NAME = os.getenv("APP_NAME", "breakable-target-api")
DATABASE_URL = os.getenv("DATABASE_URL", "")
REQUIRED_ENV_NAME = os.getenv("REQUIRED_ENV_NAME", "TARGET_REQUIRED_SECRET")
FEATURE_CHECKOUT_ENABLED = os.getenv("FEATURE_CHECKOUT_ENABLED", "true").lower() == "true"

ACTIVE_SCENARIOS: set[str] = set()
STRUCTURED_EVENTS: list[dict[str, Any]] = []

SCENARIOS: dict[str, dict[str, Any]] = {
    "bad_database_url": {
        "description": "Simulates an unreachable database host.",
        "symptoms": ["healthcheck database check fails", "database-backed endpoints return 500"],
        "expected_status": "unhealthy",
    },
    "missing_required_env": {
        "description": "Simulates a missing required environment variable.",
        "symptoms": ["healthcheck required_env check fails"],
        "expected_status": "unhealthy",
    },
    "bad_feature_flag": {
        "description": "Simulates a broken feature path behind the checkout flag.",
        "symptoms": ["checkout endpoint returns 500", "core health remains healthy"],
        "expected_status": "degraded",
    },
    "dependency_unavailable": {
        "description": "Simulates an unavailable downstream dependency.",
        "symptoms": ["checkout endpoint returns 503", "core health remains healthy"],
        "expected_status": "degraded",
    },
    "schema_mismatch": {
        "description": "Simulates application code expecting a missing database column.",
        "symptoms": ["items endpoint returns 500", "healthcheck schema check fails"],
        "expected_status": "unhealthy",
    },
    "port_conflict": {
        "description": "Simulates a startup/runtime port binding problem as an observable health failure.",
        "symptoms": ["healthcheck process check fails"],
        "expected_status": "unhealthy",
    },
    "rate_limit": {
        "description": "Simulates a dependency rate-limit response.",
        "symptoms": ["checkout endpoint returns 429"],
        "expected_status": "degraded",
    },
}

app = FastAPI(
    title="Breakable Target API",
    description="Small API used by Self-Healing Runtime to exercise live failure detection.",
    version="0.1.0",
)


class ItemCreate(BaseModel):
    name: str


class RestoreConfigRequest(BaseModel):
    key: str
    scenario: str


class RollbackConfigRequest(BaseModel):
    target: str


class RestartRequest(BaseModel):
    service: str


def record_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "type": event_type,
        "service": APP_NAME,
        "active_scenarios": sorted(ACTIVE_SCENARIOS),
        "payload": payload,
    }
    STRUCTURED_EVENTS.append(event)
    del STRUCTURED_EVENTS[:-200]
    print(json.dumps(event), flush=True)
    return event


@contextmanager
def db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    if "bad_database_url" in ACTIVE_SCENARIOS:
        raise RuntimeError("simulated database connection failure: unreachable host wrong-db")

    with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
        yield conn


def check_database() -> dict[str, Any]:
    if "schema_mismatch" in ACTIVE_SCENARIOS:
        raise RuntimeError("simulated schema mismatch: column items.description does not exist")

    start = time.perf_counter()
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM items")
            item_count = cur.fetchone()[0]

    latency_ms = int((time.perf_counter() - start) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "item_count": item_count}


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "message": "Target app is running.",
        "docs": "/docs",
    }


@app.get("/metadata")
def metadata():
    return {
        "service": APP_NAME,
        "dependencies": ["postgres"],
        "features": {
            "checkout": FEATURE_CHECKOUT_ENABLED,
        },
        "active_scenarios": sorted(ACTIVE_SCENARIOS),
        "available_scenarios": SCENARIOS,
        "required_env": {
            "name": REQUIRED_ENV_NAME,
            "present": bool(os.getenv(REQUIRED_ENV_NAME)),
        },
    }


@app.get("/health")
def health():
    checks: dict[str, Any] = {
        "required_env": {
            "ok": bool(os.getenv(REQUIRED_ENV_NAME)) and "missing_required_env" not in ACTIVE_SCENARIOS,
            "name": REQUIRED_ENV_NAME,
        }
    }

    try:
        checks["database"] = check_database()
    except Exception as exc:
        checks["database"] = {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    checks["process"] = {
        "ok": "port_conflict" not in ACTIVE_SCENARIOS,
        "message": "simulated port binding conflict" if "port_conflict" in ACTIVE_SCENARIOS else "process accepting traffic",
    }

    healthy = all(check.get("ok", False) for check in checks.values())
    return {
        "service": APP_NAME,
        "status": "healthy" if healthy else "unhealthy",
        "active_scenarios": sorted(ACTIVE_SCENARIOS),
        "checks": checks,
    }


@app.get("/items")
def list_items():
    if "schema_mismatch" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=500, detail="simulated schema mismatch: column items.description does not exist")

    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT id, name, created_at FROM items ORDER BY id")
                return {"items": list(cur.fetchall())}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/items", status_code=201)
def create_item(item: ItemCreate):
    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "INSERT INTO items (name) VALUES (%s) RETURNING id, name, created_at",
                    (item.name,),
                )
                created = cur.fetchone()
                conn.commit()
                return created
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/checkout")
def checkout_probe():
    if not FEATURE_CHECKOUT_ENABLED:
        return {"status": "disabled"}

    if "bad_feature_flag" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=500, detail="simulated feature flag failure in checkout path")

    if "dependency_unavailable" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=503, detail="simulated downstream dependency unavailable")

    if "rate_limit" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=429, detail="simulated dependency rate limit")

    try:
        db = check_database()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"checkout dependency failed: {exc}") from exc

    return {
        "status": "ready",
        "dependency": db,
    }


@app.get("/scenarios")
def list_scenarios():
    return {
        "active": sorted(ACTIVE_SCENARIOS),
        "available": SCENARIOS,
    }


@app.post("/scenarios/{scenario_name}/activate")
def activate_scenario(scenario_name: str):
    if scenario_name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown failure scenario")

    ACTIVE_SCENARIOS.add(scenario_name)
    event = record_event(
        "scenario.activated",
        {
            "scenario": scenario_name,
            "metadata": SCENARIOS[scenario_name],
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.post("/scenarios/{scenario_name}/deactivate")
def deactivate_scenario(scenario_name: str):
    if scenario_name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown failure scenario")

    ACTIVE_SCENARIOS.discard(scenario_name)
    event = record_event(
        "scenario.deactivated",
        {
            "scenario": scenario_name,
            "metadata": SCENARIOS[scenario_name],
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.post("/scenarios/reset")
def reset_scenarios():
    previous = sorted(ACTIVE_SCENARIOS)
    ACTIVE_SCENARIOS.clear()
    event = record_event("scenario.reset", {"previous": previous})
    return {"active": [], "event": event}


@app.post("/runtime/restart")
def restart_service(request: RestartRequest):
    if request.service != "target-api":
        raise HTTPException(status_code=404, detail="Runtime service is not managed by this target")

    ACTIVE_SCENARIOS.discard("port_conflict")
    event = record_event(
        "runtime.restart_requested",
        {
            "service": request.service,
            "cleared_scenarios": ["port_conflict"],
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.post("/runtime/config/restore")
def restore_config(request: RestoreConfigRequest):
    scenario_by_key = {
        "DATABASE_URL": "bad_database_url",
        "TARGET_REQUIRED_SECRET": "missing_required_env",
    }
    expected_scenario = scenario_by_key.get(request.key)
    if not expected_scenario or request.scenario != expected_scenario:
        raise HTTPException(status_code=400, detail="Config key is not restorable through this runtime action")

    ACTIVE_SCENARIOS.discard(expected_scenario)
    event = record_event(
        "runtime.config_restored",
        {
            "key": request.key,
            "cleared_scenarios": [expected_scenario],
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.post("/runtime/feature-flags/{flag}/disable")
def disable_feature_flag(flag: str):
    if flag != "FEATURE_CHECKOUT_ENABLED":
        raise HTTPException(status_code=404, detail="Feature flag is not managed by this target")

    cleared = []
    for scenario in ("bad_feature_flag", "rate_limit"):
        if scenario in ACTIVE_SCENARIOS:
            ACTIVE_SCENARIOS.discard(scenario)
            cleared.append(scenario)

    event = record_event(
        "runtime.feature_flag_disabled",
        {
            "flag": flag,
            "cleared_scenarios": cleared,
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.post("/runtime/dependencies/{dependency}/switch-to-mock")
def switch_dependency_to_mock(dependency: str):
    if dependency != "checkout-provider":
        raise HTTPException(status_code=404, detail="Dependency is not managed by this target")

    cleared = []
    for scenario in ("dependency_unavailable", "rate_limit"):
        if scenario in ACTIVE_SCENARIOS:
            ACTIVE_SCENARIOS.discard(scenario)
            cleared.append(scenario)

    event = record_event(
        "runtime.dependency_switched_to_mock",
        {
            "dependency": dependency,
            "cleared_scenarios": cleared,
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.post("/runtime/config/rollback")
def rollback_config(request: RollbackConfigRequest):
    if request.target != "previous_known_good_app_version":
        raise HTTPException(status_code=404, detail="Rollback target is not managed by this target")

    ACTIVE_SCENARIOS.discard("schema_mismatch")
    event = record_event(
        "runtime.config_rolled_back",
        {
            "target": request.target,
            "cleared_scenarios": ["schema_mismatch"],
        },
    )
    return {"active": sorted(ACTIVE_SCENARIOS), "event": event}


@app.get("/events")
def list_events(limit: int = 100):
    bounded_limit = min(max(limit, 1), 200)
    return {"events": STRUCTURED_EVENTS[-bounded_limit:]}
