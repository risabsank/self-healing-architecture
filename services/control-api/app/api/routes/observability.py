import asyncio
import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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


@router.get("/events/stream")
async def stream_runtime_events(
    limit: int = Query(default=100, ge=1, le=500),
    conn: Connection = Depends(get_connection),
):
    # Fetch before returning the StreamingResponse so FastAPI can close the
    # request-scoped database connection without breaking the body iterator.
    events = list_runtime_events(limit, conn)["events"]
    return StreamingResponse(event_stream(events), media_type="text/event-stream")


async def event_stream(events: list[dict]):
    # Lightweight SSE snapshot stream: enough for dashboards and scripts without
    # introducing a broker. Clients reconnect to receive the latest timeline.
    for event in reversed(events):
        yield f"data: {json.dumps(json_safe(event))}\n\n"
        await asyncio.sleep(0)


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value
