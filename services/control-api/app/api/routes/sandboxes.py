from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.db import get_connection
from app.models.schemas import SandboxCreate
from app.monitoring import check_service_health
from app.sandbox.docker_runtime import DockerRuntime

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


@router.get("")
def list_sandboxes(conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, runtime, status, metadata, created_at, updated_at
            FROM sandboxes
            ORDER BY created_at DESC
            """
        )
        return {"sandboxes": cur.fetchall()}


@router.post("", status_code=201)
def create_sandbox(payload: SandboxCreate, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sandboxes (id, name, runtime, status, metadata)
            VALUES (%s, %s, %s, 'active', %s)
            RETURNING id, name, runtime, status, metadata, created_at, updated_at
            """,
            (payload.id, payload.name, payload.runtime, Jsonb(payload.metadata)),
        )
        sandbox = cur.fetchone()
    conn.commit()
    return sandbox


@router.get("/{sandbox_id}")
def get_sandbox(sandbox_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, runtime, status, metadata, created_at, updated_at
            FROM sandboxes
            WHERE id = %s
            """,
            (sandbox_id,),
        )
        sandbox = cur.fetchone()

        if not sandbox:
            raise HTTPException(status_code=404, detail="Sandbox not found")

        cur.execute(
            """
            SELECT service_name, service_type, base_url, health_url, metadata
            FROM sandbox_services
            WHERE sandbox_id = %s
            ORDER BY service_name
            """,
            (sandbox_id,),
        )
        services = cur.fetchall()

        cur.execute(
            """
            SELECT DISTINCT ON (service_name)
              service_name, status, latency_ms, detail, checked_at
            FROM health_checks
            WHERE sandbox_id = %s
            ORDER BY service_name, checked_at DESC
            """,
            (sandbox_id,),
        )
        latest_health = cur.fetchall()

    return {
        "sandbox": sandbox,
        "runtime": DockerRuntime(sandbox_id=sandbox_id).describe(),
        "services": services,
        "latest_health": latest_health,
    }


@router.post("/{sandbox_id}/health-check")
async def run_sandbox_health_check(sandbox_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT service_name, health_url
            FROM sandbox_services
            WHERE sandbox_id = %s AND health_url IS NOT NULL
            ORDER BY service_name
            """,
            (sandbox_id,),
        )
        services = cur.fetchall()

    if not services:
        raise HTTPException(status_code=404, detail="Sandbox or health-checkable services not found")

    results = []
    for service in services:
        results.append(
            await check_service_health(
                conn=conn,
                sandbox_id=sandbox_id,
                service_name=service["service_name"],
                health_url=service["health_url"],
            )
        )

    return {"sandbox_id": sandbox_id, "results": results}
