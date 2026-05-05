from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from app.core.db import get_connection

router = APIRouter(tags=["observability"])


@router.get("/sandboxes/{sandbox_id}/health-history")
def get_health_history(
    sandbox_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    conn: Connection = Depends(get_connection),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, service_name, status, latency_ms, detail, checked_at
            FROM health_checks
            WHERE sandbox_id = %s
            ORDER BY checked_at DESC
            LIMIT %s
            """,
            (sandbox_id, limit),
        )
        checks = cur.fetchall()

    return {"sandbox_id": sandbox_id, "health_checks": checks}


@router.get("/sandboxes/{sandbox_id}/timeline")
def get_sandbox_timeline(
    sandbox_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    conn: Connection = Depends(get_connection),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, service_name, ts, type, actor, payload
            FROM runtime_events
            WHERE sandbox_id = %s
            ORDER BY ts DESC
            LIMIT %s
            """,
            (sandbox_id, limit),
        )
        events = cur.fetchall()

    return {"sandbox_id": sandbox_id, "events": events}


@router.get("/events")
def list_runtime_events(
    limit: int = Query(default=100, ge=1, le=500),
    conn: Connection = Depends(get_connection),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, service_name, ts, type, actor, payload
            FROM runtime_events
            ORDER BY ts DESC
            LIMIT %s
            """,
            (limit,),
        )
        events = cur.fetchall()

    return {"events": events}
