import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from psycopg import Connection

from app.app_signals import latest_metrics, latest_notes, record_metric, record_note, slo_status
from app.apps import (
    deactivate_application,
    get_application,
    list_applications,
    manifest_from_app,
    register_application,
    validate_manifest_readiness,
)
from app.core.db import get_connection
from app.customizations import (
    approve_customization_proposal,
    create_customization_proposal,
    get_customization_proposal,
    list_customization_proposals,
    reject_customization_proposal,
)
from app.models.schemas import ApplicationManifest, CustomizationPlanCreate, MetricObservationCreate, OperatorNoteCreate
from app.monitoring import check_service_health

router = APIRouter(prefix="/apps", tags=["applications"])


@router.get("")
def list_registered_apps(conn: Connection = Depends(get_connection)):
    return {"apps": list_applications(conn)}


@router.post("/register", status_code=201)
def register_app(manifest: ApplicationManifest, conn: Connection = Depends(get_connection)):
    return register_application(conn, manifest)


@router.post("/register-yaml", status_code=201)
async def register_app_yaml(request: Request, conn: Connection = Depends(get_connection)):
    return register_application(conn, await manifest_from_yaml_request(request))


@router.post("/validate")
def validate_app_manifest(manifest: ApplicationManifest):
    return validate_manifest_readiness(manifest)


@router.post("/validate-yaml")
async def validate_app_manifest_yaml(request: Request):
    return validate_manifest_readiness(await manifest_from_yaml_request(request))


@router.get("/{app_id}")
def read_app(app_id: str, conn: Connection = Depends(get_connection)):
    app = get_application(conn, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.delete("/{app_id}")
def unregister_app(app_id: str, conn: Connection = Depends(get_connection)):
    app = deactivate_application(conn, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"app": app, "removed_from_monitoring": True}


@router.get("/{app_id}/validation")
def read_app_validation(app_id: str, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)
    return validate_manifest_readiness(manifest_from_app(app))


@router.post("/{app_id}/customizations/plan", status_code=201)
def plan_customization(app_id: str, payload: CustomizationPlanCreate, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)
    return create_customization_proposal(conn, app, payload)


@router.get("/{app_id}/customizations")
def read_customizations(app_id: str, conn: Connection = Depends(get_connection)):
    require_app(conn, app_id)
    return {"proposals": list_customization_proposals(conn, app_id)}


@router.get("/{app_id}/customizations/{proposal_id}")
def read_customization(app_id: str, proposal_id: str, conn: Connection = Depends(get_connection)):
    require_app(conn, app_id)
    proposal = get_customization_proposal(conn, app_id, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Customization proposal not found")
    return proposal


@router.post("/{app_id}/customizations/{proposal_id}/approve")
def approve_customization(app_id: str, proposal_id: str, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)
    try:
        proposal = approve_customization_proposal(conn, app, proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not proposal:
        raise HTTPException(status_code=404, detail="Customization proposal not found")
    return proposal


@router.post("/{app_id}/customizations/{proposal_id}/reject")
def reject_customization(app_id: str, proposal_id: str, conn: Connection = Depends(get_connection)):
    require_app(conn, app_id)
    proposal = reject_customization_proposal(conn, app_id, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Customization proposal not found")
    return proposal


@router.post("/{app_id}/metrics", status_code=201)
def ingest_metric(app_id: str, payload: MetricObservationCreate, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)
    return record_metric(conn, app, payload)


@router.get("/{app_id}/metrics")
def read_metrics(app_id: str, conn: Connection = Depends(get_connection)):
    require_app(conn, app_id)
    return latest_metrics(conn, app_id)


@router.get("/{app_id}/slo-status")
def read_slo_status(app_id: str, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)
    return slo_status(conn, app)


@router.post("/{app_id}/notes", status_code=201)
def create_operator_note(app_id: str, payload: OperatorNoteCreate, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)
    return record_note(conn, app, payload)


@router.get("/{app_id}/notes")
def read_operator_notes(app_id: str, conn: Connection = Depends(get_connection)):
    require_app(conn, app_id)
    return {"notes": latest_notes(conn, app_id)}


@router.post("/{app_id}/health-check")
async def run_app_health_check(app_id: str, conn: Connection = Depends(get_connection)):
    app = require_app(conn, app_id)

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


def require_app(conn: Connection, app_id: str):
    app = get_application(conn, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


async def manifest_from_yaml_request(request: Request) -> ApplicationManifest:
    body = (await request.body()).decode("utf-8")
    try:
        parsed = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="Manifest YAML must define an object at the top level.")
    try:
        return ApplicationManifest.model_validate(parsed)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
