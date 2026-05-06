import httpx
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.core.db import get_connection
from app.observability import record_runtime_event

router = APIRouter(prefix="/sandboxes/{sandbox_id}/scenarios", tags=["scenarios"])


def get_target_base_url(conn: Connection, sandbox_id: str, service_name: str = "target-api") -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT base_url
            FROM sandbox_services
            WHERE sandbox_id = %s AND service_name = %s
            """,
            (sandbox_id, service_name),
        )
        service = cur.fetchone()

    if not service or not service["base_url"]:
        raise HTTPException(status_code=404, detail="Target service not found")

    return service["base_url"]


async def proxy_target_request(method: str, url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(method, url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Target service request failed: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Target service returned non-JSON response") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=body)

    return body


@router.get("")
async def list_scenarios(sandbox_id: str, conn: Connection = Depends(get_connection)):
    base_url = get_target_base_url(conn, sandbox_id)
    return await proxy_target_request("GET", f"{base_url}/scenarios")


@router.post("/{scenario_name}/activate")
async def activate_scenario(
    sandbox_id: str,
    scenario_name: str,
    conn: Connection = Depends(get_connection),
):
    return await change_scenario(conn, sandbox_id, f"/scenarios/{scenario_name}/activate", "scenario.activated", scenario_name)


@router.post("/{scenario_name}/deactivate")
async def deactivate_scenario(
    sandbox_id: str,
    scenario_name: str,
    conn: Connection = Depends(get_connection),
):
    return await change_scenario(conn, sandbox_id, f"/scenarios/{scenario_name}/deactivate", "scenario.deactivated", scenario_name)


@router.post("/reset")
async def reset_scenarios(sandbox_id: str, conn: Connection = Depends(get_connection)):
    return await change_scenario(conn, sandbox_id, "/scenarios/reset", "scenario.reset")


async def change_scenario(
    conn: Connection,
    sandbox_id: str,
    path: str,
    event_type: str,
    scenario_name: str | None = None,
) -> dict:
    base_url = get_target_base_url(conn, sandbox_id)
    result = await proxy_target_request("POST", f"{base_url}{path}")
    payload = {"target_result": result}
    if scenario_name:
        payload["scenario"] = scenario_name
    record_runtime_event(
        conn,
        event_type=event_type,
        actor="control-api",
        sandbox_id=sandbox_id,
        service_name="target-api",
        payload=payload,
    )
    conn.commit()
    return result
