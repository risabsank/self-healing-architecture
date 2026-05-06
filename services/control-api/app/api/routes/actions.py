from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.db import get_connection
from app.observability import record_incident_event
from app.sandbox.action_executor import (
    ActionBlockedError,
    ActionExecutionError,
    execute_remediation_action,
)
from app.sandbox.allowed_actions import list_allowed_actions

router = APIRouter(tags=["guarded-actions"])


@router.get("/actions/allowed")
def get_allowed_actions():
    return {"actions": list_allowed_actions()}


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, conn: Connection = Depends(get_connection)):
    action = load_action_for_update(conn, action_id)
    if not action["requires_approval"]:
        raise HTTPException(status_code=409, detail="Action does not require approval")
    return set_approval(conn, action, "approved", "mitigation_selected")


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: str, conn: Connection = Depends(get_connection)):
    action = load_action_for_update(conn, action_id)
    return set_approval(conn, action, "rejected", "blocked")


@router.post("/actions/{action_id}/execute")
async def execute_action(action_id: str, conn: Connection = Depends(get_connection)):
    return await execute_or_raise(conn, action_id)


@router.post("/incidents/{incident_id}/actions/execute-selected")
async def execute_selected_action(incident_id: str, conn: Connection = Depends(get_connection)):
    action = find_selected_action(conn, incident_id)
    if not action:
        raise HTTPException(status_code=404, detail="Selected remediation action not found")

    return await execute_or_raise(conn, str(action["id"]))


async def execute_or_raise(conn: Connection, action_id: str):
    try:
        return await execute_remediation_action(conn, action_id)
    except ActionBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActionExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def set_approval(conn: Connection, action: dict, status: str, incident_status: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_actions
            SET status = %s,
                result = coalesce(result, '{}'::jsonb) || %s
            WHERE id = %s
            RETURNING id, incident_id, action_type, params, risk_score, requires_approval, status, result
            """,
            (
                status,
                Jsonb({"approval": {"status": status, "actor": "operator"}}),
                action["id"],
            ),
        )
        updated = cur.fetchone()
        cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (incident_status, action["incident_id"]))

    record_incident_event(
        conn,
        incident_id=str(action["incident_id"]),
        sandbox_id=action["sandbox_id"],
        event_type=f"mitigation.{status}",
        actor="operator",
        payload={"action_id": str(action["id"]), "action_type": action["action_type"]},
    )
    conn.commit()
    return updated


def load_action_for_update(conn: Connection, action_id: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              remediation_actions.id,
              remediation_actions.incident_id,
              remediation_actions.action_type,
              remediation_actions.params,
              remediation_actions.risk_score,
              remediation_actions.requires_approval,
              remediation_actions.status,
              remediation_actions.result,
              incidents.sandbox_id
            FROM remediation_actions
            JOIN incidents ON incidents.id = remediation_actions.incident_id
            WHERE remediation_actions.id = %s
            """,
            (action_id,),
        )
        action = cur.fetchone()

    if not action:
        raise HTTPException(status_code=404, detail="Remediation action not found")
    return action


def find_selected_action(conn: Connection, incident_id: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM remediation_actions
            WHERE incident_id = %s AND status IN ('selected', 'approved', 'awaiting_approval', 'failed')
            ORDER BY
              CASE status WHEN 'approved' THEN 0 WHEN 'selected' THEN 1 WHEN 'awaiting_approval' THEN 2 ELSE 3 END,
              risk_score ASC
            LIMIT 1
            """,
            (incident_id,),
        )
        return cur.fetchone()
