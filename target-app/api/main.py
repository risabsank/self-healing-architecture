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


@app.get("/events")
def list_events(limit: int = 100):
    bounded_limit = min(max(limit, 1), 200)
    return {"events": STRUCTURED_EVENTS[-bounded_limit:]}
