import os
import time
from contextlib import contextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel


APP_NAME = os.getenv("APP_NAME", "breakable-target-api")
DATABASE_URL = os.getenv("DATABASE_URL", "")
REQUIRED_ENV_NAME = os.getenv("REQUIRED_ENV_NAME", "TARGET_REQUIRED_SECRET")
FEATURE_CHECKOUT_ENABLED = os.getenv("FEATURE_CHECKOUT_ENABLED", "true").lower() == "true"

app = FastAPI(
    title="Breakable Target API",
    description="Small API used by Self-Healing Runtime to exercise live failure detection.",
    version="0.1.0",
)


class ItemCreate(BaseModel):
    name: str


@contextmanager
def db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
        yield conn


def check_database() -> dict[str, Any]:
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
        "required_env": {
            "name": REQUIRED_ENV_NAME,
            "present": bool(os.getenv(REQUIRED_ENV_NAME)),
        },
    }


@app.get("/health")
def health():
    checks: dict[str, Any] = {
        "required_env": {
            "ok": bool(os.getenv(REQUIRED_ENV_NAME)),
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

    healthy = all(check.get("ok", False) for check in checks.values())
    return {
        "service": APP_NAME,
        "status": "healthy" if healthy else "unhealthy",
        "checks": checks,
    }


@app.get("/items")
def list_items():
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

    try:
        db = check_database()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"checkout dependency failed: {exc}") from exc

    return {
        "status": "ready",
        "dependency": db,
    }
