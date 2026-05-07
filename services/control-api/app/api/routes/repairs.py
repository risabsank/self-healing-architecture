from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.core.db import get_connection
from app.repair import (
    apply_repair,
    approve_repair,
    create_repair_plan,
    get_repair,
    list_repairs,
    reject_repair,
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


@router.post("/repairs/{repair_id}/apply")
def apply_repair_change(repair_id: str, conn: Connection = Depends(get_connection)):
    return repair_or_error(apply_repair, conn, repair_id)


def repair_or_error(operation, conn: Connection, identifier: str, status_code: int = 404):
    try:
        return operation(conn, identifier)
    except ValueError as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
