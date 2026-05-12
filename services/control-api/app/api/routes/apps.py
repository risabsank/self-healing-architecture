from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.apps import get_application, list_applications, register_application
from app.core.db import get_connection
from app.models.schemas import ApplicationManifest
from app.monitoring import check_service_health

router = APIRouter(prefix="/apps", tags=["applications"])


@router.get("")
def list_registered_apps(conn: Connection = Depends(get_connection)):
    return {"apps": list_applications(conn)}


@router.post("/register", status_code=201)
def register_app(manifest: ApplicationManifest, conn: Connection = Depends(get_connection)):
    return register_application(conn, manifest)


@router.get("/{app_id}")
def read_app(app_id: str, conn: Connection = Depends(get_connection)):
    app = get_application(conn, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.post("/{app_id}/health-check")
async def run_app_health_check(app_id: str, conn: Connection = Depends(get_connection)):
    app = get_application(conn, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    results = []
    for service in app["manifest"].get("services", []):
        if service.get("health_url"):
            results.append(
                await check_service_health(
                    conn=conn,
                    sandbox_id=app["sandbox_id"],
                    service_name=service["name"],
                    health_url=service["health_url"],
                )
            )
    return {"app_id": app_id, "results": results}
