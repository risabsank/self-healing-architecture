from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.db import get_connection
from app.models.schemas import SandboxCreate, SnapshotRequest
from app.monitoring import check_service_health
from app.sandbox.registry import list_runtimes, runtime_for

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


@router.get("/runtimes")
def get_runtimes():
    return {"runtimes": list_runtimes()}


@router.get("/{sandbox_id}")
def get_sandbox(sandbox_id: str, conn: Connection = Depends(get_connection)):
    sandbox = load_sandbox(conn, sandbox_id)
    with conn.cursor() as cur:
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
        "runtime": runtime_for(sandbox["runtime"]).describe(sandbox_id),
        "services": services,
        "latest_health": latest_health,
    }


@router.post("/{sandbox_id}/snapshots", status_code=202)
def create_snapshot(sandbox_id: str, payload: SnapshotRequest, conn: Connection = Depends(get_connection)):
    sandbox = load_sandbox(conn, sandbox_id)
    result = runtime_for(sandbox["runtime"]).create_snapshot(sandbox_id, payload.name)
    return record_snapshot(conn, sandbox_id, payload.name, "create", result)


@router.post("/{sandbox_id}/snapshots/{snapshot_name}/restore", status_code=202)
def restore_snapshot(sandbox_id: str, snapshot_name: str, conn: Connection = Depends(get_connection)):
    sandbox = load_sandbox(conn, sandbox_id)
    result = runtime_for(sandbox["runtime"]).restore_snapshot(sandbox_id, snapshot_name)
    return record_snapshot(conn, sandbox_id, snapshot_name, "restore", result)


@router.get("/{sandbox_id}/snapshots")
def list_snapshots(sandbox_id: str, conn: Connection = Depends(get_connection)):
    load_sandbox(conn, sandbox_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, snapshot_name, operation, status, detail, created_at
            FROM sandbox_snapshots
            WHERE sandbox_id = %s
            ORDER BY created_at DESC
            """,
            (sandbox_id,),
        )
        return {"snapshots": cur.fetchall()}


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


def load_sandbox(conn: Connection, sandbox_id: str) -> dict:
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
    return sandbox


def record_snapshot(conn: Connection, sandbox_id: str, name: str, operation: str, result) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sandbox_snapshots (sandbox_id, snapshot_name, operation, status, detail)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, sandbox_id, snapshot_name, operation, status, detail, created_at
            """,
            (sandbox_id, name, operation, result.status, Jsonb(result.payload())),
        )
        snapshot = cur.fetchone()
    conn.commit()
    return snapshot
