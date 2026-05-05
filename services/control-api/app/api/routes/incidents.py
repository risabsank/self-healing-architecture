from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.graph import analyze_incident
from app.core.db import get_connection
from app.models.schemas import IncidentCreate

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
def list_incidents(conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, status, title, detected_at, resolved_at, root_cause, final_summary
            FROM incidents
            ORDER BY detected_at DESC
            LIMIT 100
            """
        )
        return {"incidents": cur.fetchall()}


@router.post("", status_code=201)
def create_incident(payload: IncidentCreate, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidents (sandbox_id, status, title)
            VALUES (%s, %s, %s)
            RETURNING id, sandbox_id, status, title, detected_at, resolved_at, root_cause, final_summary
            """,
            (payload.sandbox_id, payload.status, payload.title),
        )
        incident = cur.fetchone()
        cur.execute(
            """
            INSERT INTO incident_events (incident_id, sandbox_id, type, actor, payload)
            VALUES (%s, %s, 'incident.created', 'control-api', %s)
            """,
            (
                incident["id"],
                payload.sandbox_id,
                Jsonb({"title": payload.title, "status": payload.status}),
            ),
        )
    conn.commit()
    return incident


@router.get("/{incident_id}")
def get_incident(incident_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, status, title, detected_at, resolved_at, root_cause, final_summary
            FROM incidents
            WHERE id = %s
            """,
            (incident_id,),
        )
        incident = cur.fetchone()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return incident


@router.get("/{incident_id}/timeline")
def get_incident_timeline(incident_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, incident_id, sandbox_id, ts, type, actor, payload
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY ts ASC
            """,
            (incident_id,),
        )
        return {"events": cur.fetchall()}


@router.post("/{incident_id}/analyze")
def run_incident_analysis(incident_id: str, conn: Connection = Depends(get_connection)):
    try:
        analysis = analyze_incident(conn, incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return analysis.model_dump()


@router.get("/{incident_id}/evidence")
def get_incident_evidence(incident_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source, kind, content, confidence
            FROM evidence_items
            WHERE incident_id = %s
            ORDER BY id
            """,
            (incident_id,),
        )
        return {"evidence": cur.fetchall()}


@router.get("/{incident_id}/hypotheses")
def get_incident_hypotheses(incident_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, cause, evidence_ids, confidence, rationale_summary
            FROM hypotheses
            WHERE incident_id = %s
            ORDER BY confidence DESC
            """,
            (incident_id,),
        )
        return {"hypotheses": cur.fetchall()}


@router.get("/{incident_id}/actions")
def get_incident_actions(incident_id: str, conn: Connection = Depends(get_connection)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, action_type, params, risk_score, requires_approval, status, result
            FROM remediation_actions
            WHERE incident_id = %s
            ORDER BY
              CASE status WHEN 'selected' THEN 0 ELSE 1 END,
              risk_score ASC
            """,
            (incident_id,),
        )
        return {"actions": cur.fetchall()}
