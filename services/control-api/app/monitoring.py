import asyncio
import time
from typing import Any

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb


async def check_service_health(
    conn: Connection,
    sandbox_id: str,
    service_name: str,
    health_url: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    status = "unknown"
    detail: dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(health_url)
            latency_ms = int((time.perf_counter() - start) * 1000)
            detail = response.json()
            status = detail.get("status", "unknown")
            if response.status_code >= 500:
                status = "unhealthy"
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        status = "unhealthy"
        detail = {
            "error": type(exc).__name__,
            "message": str(exc),
        }

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO health_checks (sandbox_id, service_name, status, latency_ms, detail)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, checked_at
            """,
            (sandbox_id, service_name, status, latency_ms, Jsonb(detail)),
        )
        inserted = cur.fetchone()
    conn.commit()

    return {
        "id": inserted["id"],
        "checked_at": inserted["checked_at"],
        "sandbox_id": sandbox_id,
        "service_name": service_name,
        "status": status,
        "latency_ms": latency_ms,
        "detail": detail,
    }


async def run_all_health_checks(conn: Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sandbox_id, service_name, health_url
            FROM sandbox_services
            WHERE health_url IS NOT NULL
            ORDER BY sandbox_id, service_name
            """
        )
        services = cur.fetchall()

    results = []
    for service in services:
        results.append(
            await check_service_health(
                conn=conn,
                sandbox_id=service["sandbox_id"],
                service_name=service["service_name"],
                health_url=service["health_url"],
            )
        )
    return results


async def monitor_loop(connection_factory, interval_seconds: int) -> None:
    while True:
        try:
            with connection_factory() as conn:
                await run_all_health_checks(conn)
        except Exception:
            pass

        await asyncio.sleep(interval_seconds)
