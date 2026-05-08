import json
from typing import Any

from psycopg import Connection

from app.agents.llm import ClaudeClient, repair_system_prompt
from app.agents.state import LLMRepairDecision


def plan_repair_with_claude(
    conn: Connection,
    incident: dict[str, Any],
    approved_paths: list[str],
) -> LLMRepairDecision:
    prompt = json.dumps(repair_prompt_payload(conn, incident, approved_paths), default=str)
    return ClaudeClient().complete_json(repair_system_prompt(), prompt, LLMRepairDecision)


def repair_prompt_payload(conn: Connection, incident: dict[str, Any], approved_paths: list[str]) -> dict[str, Any]:
    incident_id = str(incident["id"])
    return {
        "task": "Plan a bounded durable repair for this incident.",
        "output_schema": LLMRepairDecision.model_json_schema(),
        "approved_paths": approved_paths,
        "incident": {
            "id": incident_id,
            "title": incident.get("title"),
            "root_cause": incident.get("root_cause"),
            "final_summary": incident.get("final_summary"),
        },
        "evidence": load_evidence(conn, incident_id),
        "actions": load_actions(conn, incident_id),
    }


def load_evidence(conn: Connection, incident_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source, kind, content, confidence
            FROM evidence_items
            WHERE incident_id = %s
            ORDER BY id
            LIMIT 20
            """,
            (incident_id,),
        )
        return cur.fetchall()


def load_actions(conn: Connection, incident_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT action_type, params, risk_score, requires_approval, status, result
            FROM remediation_actions
            WHERE incident_id = %s
            ORDER BY risk_score ASC
            LIMIT 10
            """,
            (incident_id,),
        )
        return cur.fetchall()
