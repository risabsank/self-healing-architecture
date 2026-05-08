from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.core.db import get_connection
from app.evaluation import EvaluationRequest, ensure_evaluation_schema, run_evaluation


router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("/run", status_code=201)
async def start_evaluation(payload: EvaluationRequest, conn: Connection = Depends(get_connection)):
    try:
        return await run_evaluation(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_evaluations(conn: Connection = Depends(get_connection)):
    ensure_evaluation_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, scenario_filter, repeats, aggregate_metrics, result, started_at, completed_at
            FROM evaluation_runs
            ORDER BY started_at DESC
            LIMIT 50
            """
        )
        return {"runs": cur.fetchall()}


@router.get("/{run_id}")
def get_evaluation(run_id: str, conn: Connection = Depends(get_connection)):
    ensure_evaluation_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, scenario_filter, repeats, aggregate_metrics, result, started_at, completed_at
            FROM evaluation_runs
            WHERE id = %s
            """,
            (run_id,),
        )
        run = cur.fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return run


@router.get("/{run_id}/cases")
def list_evaluation_cases(run_id: str, conn: Connection = Depends(get_connection)):
    ensure_evaluation_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              id, run_id, scenario_name, iteration, status, incident_id,
              expected_root_cause, diagnosed_root_cause, selected_action,
              metrics, result, started_at, completed_at
            FROM evaluation_cases
            WHERE run_id = %s
            ORDER BY iteration ASC, scenario_name ASC
            """,
            (run_id,),
        )
        return {"cases": cur.fetchall()}
