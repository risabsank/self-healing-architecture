from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.cicd import list_verification_runs, run_verification_pipeline
from app.core.db import get_connection
from app.repair import (
    apply_repair,
    approve_repair,
    create_repair_plan,
    get_repair,
    list_repairs,
    repair_diff,
    reject_repair,
    rollback_repair,
)
from app.rollout import (
    list_rollouts,
    promote_rollout,
    quarantine_rollout,
    rollback_rollout,
    start_canary_rollout,
)

router = APIRouter(tags=["durable-repairs"])


@router.get("/incidents/{incident_id}/repairs")
def get_incident_repairs(incident_id: str, conn: Connection = Depends(get_connection)):
    return {"repairs": list_repairs(conn, incident_id)}


@router.post("/incidents/{incident_id}/repairs/plan", status_code=201)
def plan_incident_repair(incident_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(create_repair_plan, conn, incident_id, 422)


@router.get("/repairs/{repair_id}")
def read_repair(repair_id: str, conn: Connection = Depends(get_connection)):
    repair = get_repair(conn, repair_id)
    if not repair:
        raise HTTPException(status_code=404, detail="Repair not found")
    return repair


@router.post("/repairs/{repair_id}/approve")
def approve_repair_change(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(approve_repair, conn, repair_id)


@router.post("/repairs/{repair_id}/reject")
def reject_repair_change(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(reject_repair, conn, repair_id)


@router.get("/repairs/{repair_id}/diff")
def get_repair_diff(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(repair_diff, conn, repair_id)


@router.post("/repairs/{repair_id}/apply")
def apply_repair_change(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(apply_repair, conn, repair_id)


@router.post("/repairs/{repair_id}/rollback")
def rollback_repair_change(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(rollback_repair, conn, repair_id, 422)


@router.get("/repairs/{repair_id}/verification-runs")
def get_repair_verification_runs(repair_id: str, conn: Connection = Depends(get_connection)):
    return {"verification_runs": list_verification_runs(conn, repair_id)}


@router.post("/repairs/{repair_id}/verify")
def verify_repair_change(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(run_verification_pipeline, conn, repair_id, 422)


@router.get("/repairs/{repair_id}/canary-rollouts")
def get_repair_canary_rollouts(repair_id: str, conn: Connection = Depends(get_connection)):
    return {"canary_rollouts": list_rollouts(conn, repair_id)}


@router.post("/repairs/{repair_id}/canary-rollouts/start")
def start_repair_canary_rollout(
    repair_id: str,
    traffic_percentage: float = 10.0,
    conn: Connection = Depends(get_connection),
):
    return rollout_or_error(conn, repair_id, traffic_percentage)


@router.post("/canary-rollouts/{rollout_id}/promote")
def promote_canary(rollout_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(promote_rollout, conn, rollout_id)


@router.post("/canary-rollouts/{rollout_id}/rollback")
def rollback_canary(rollout_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(rollback_rollout, conn, rollout_id)


@router.post("/canary-rollouts/{rollout_id}/quarantine")
def quarantine_canary(rollout_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(quarantine_rollout, conn, rollout_id)


def repair_or_error(operation, conn: Connection, identifier: str, status_code: int = 404):
    try:
        return operation(conn, identifier)
    except ValueError as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def rollout_or_error(conn: Connection, repair_id: str, traffic_percentage: float):
    try:
        return start_canary_rollout(conn, repair_id, traffic_percentage)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
