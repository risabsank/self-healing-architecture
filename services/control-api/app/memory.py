from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.observability import record_incident_event

MEMORY_SELECT = """
SELECT id, incident_id, summary, symptoms, root_cause,
       successful_action, failed_actions, verification_result, repair_change, rollout_result, created_at
FROM incident_memories
"""


def ensure_memory_schema(conn: Connection) -> None:
    # Keeps local Docker volumes compatible as the lightweight schema evolves.
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE incident_memories ADD COLUMN IF NOT EXISTS symptoms JSONB NOT NULL DEFAULT '[]'::jsonb")
        cur.execute("ALTER TABLE incident_memories ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '[]'::jsonb")
        cur.execute("ALTER TABLE incident_memories ADD COLUMN IF NOT EXISTS verification_result JSONB")
        cur.execute("ALTER TABLE incident_memories ADD COLUMN IF NOT EXISTS repair_change JSONB")
        cur.execute("ALTER TABLE incident_memories ADD COLUMN IF NOT EXISTS rollout_result JSONB")
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_memories_incident_id
            ON incident_memories (incident_id)
            WHERE incident_id IS NOT NULL
            """
        )
    conn.commit()


def write_incident_memory(conn: Connection, incident_id: str) -> dict[str, Any] | None:
    incident = fetch_one(
        conn,
        """
        SELECT id, sandbox_id, title, root_cause, final_summary
        FROM incidents
        WHERE id = %s
        """,
        (incident_id,),
    )
    if not incident:
        return None

    evidence = fetch_all(
        conn,
        """
        SELECT source, kind, content, confidence
        FROM evidence_items
        WHERE incident_id = %s
        ORDER BY id
        """,
        (incident_id,),
    )
    actions = fetch_all(
        conn,
        """
        SELECT action_type, params, risk_score, requires_approval, status, result
        FROM remediation_actions
        WHERE incident_id = %s
        ORDER BY
          CASE status WHEN 'executed' THEN 0 ELSE 1 END,
          risk_score ASC
        """,
        (incident_id,),
    )
    failed_events = fetch_all(
        conn,
        """
        SELECT type, actor, payload, ts
        FROM incident_events
        WHERE incident_id = %s AND type IN ('mitigation.failed', 'mitigation.blocked', 'mitigation.rejected')
        ORDER BY ts
        """,
        (incident_id,),
    )

    successful_action = next((action for action in actions if action["status"] == "executed"), None)
    repair_change = fetch_one(
        conn,
        """
        SELECT id, status, change_type, affected_paths, patch_summary,
               risk_score, requires_approval, verification_plan, rollback_plan, result, created_at
        FROM repair_changes
        WHERE incident_id = %s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (incident_id,),
    )
    rollout_result = fetch_one(
        conn,
        """
        SELECT id, repair_change_id, status, target_environment, traffic_percentage,
               health_signals, started_at, completed_at, decision
        FROM canary_rollouts
        WHERE repair_change_id = %s
        ORDER BY completed_at DESC NULLS LAST, started_at DESC
        LIMIT 1
        """,
        (repair_change["id"],) if repair_change else (None,),
    )
    failed_actions = failed_action_records(actions, failed_events)
    verification = (successful_action or {}).get("result", {}).get("execution", {}).get("verification")
    symptoms = extract_symptoms(evidence)
    summary = incident["final_summary"] or summarize_memory(incident, symptoms, successful_action)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_memories (
              incident_id, summary, symptoms, evidence, root_cause,
              successful_action, failed_actions, verification_result, repair_change, rollout_result
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (incident_id) WHERE incident_id IS NOT NULL
            DO UPDATE SET
              summary = EXCLUDED.summary,
              symptoms = EXCLUDED.symptoms,
              evidence = EXCLUDED.evidence,
              root_cause = EXCLUDED.root_cause,
              successful_action = EXCLUDED.successful_action,
              failed_actions = EXCLUDED.failed_actions,
              verification_result = EXCLUDED.verification_result,
              repair_change = EXCLUDED.repair_change,
              rollout_result = EXCLUDED.rollout_result
            RETURNING id, incident_id, summary, symptoms, root_cause, successful_action, failed_actions, verification_result, repair_change, rollout_result, created_at
            """,
            (
                incident_id,
                summary,
                Jsonb(symptoms),
                Jsonb(evidence),
                incident["root_cause"],
                Jsonb(successful_action),
                Jsonb(failed_actions),
                Jsonb(verification),
                Jsonb(serialize_repair_change(repair_change) if repair_change else None),
                Jsonb(serialize_rollout_result(rollout_result) if rollout_result else None),
            ),
        )
        memory = cur.fetchone()

    record_incident_event(
        conn,
        incident_id=incident_id,
        sandbox_id=incident["sandbox_id"],
        event_type="memory.stored",
        actor="memory-writer",
        payload={"memory_id": str(memory["id"]), "summary": memory["summary"], "root_cause": memory["root_cause"]},
    )
    return memory


def retrieve_similar_memories(conn: Connection, evidence: list[Any], limit: int = 3) -> list[dict[str, Any]]:
    return search_memories(conn, " ".join(evidence_text(item) for item in evidence), limit)


def list_memories(conn: Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = fetch_all(
        conn,
        f"{MEMORY_SELECT} ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    return [serialize_memory(row) for row in rows]


def search_memories(conn: Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    query_terms = tokenize(query)
    if not query_terms:
        return []

    scored = [(memory_score(query_terms, memory), memory) for memory in list_memories(conn, 100)]
    return [
        {**memory, "similarity_score": score}
        for score, memory in sorted(scored, key=lambda item: item[0], reverse=True)
        if score > 0
    ][:limit]


def serialize_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        **memory,
        "id": str(memory["id"]),
        "incident_id": str(memory["incident_id"]) if memory.get("incident_id") else None,
        "created_at": memory["created_at"].isoformat() if memory.get("created_at") else None,
    }


def serialize_repair_change(repair: dict[str, Any]) -> dict[str, Any]:
    return {
        **repair,
        "id": str(repair["id"]),
        "created_at": repair["created_at"].isoformat() if repair.get("created_at") else None,
    }


def serialize_rollout_result(rollout: dict[str, Any]) -> dict[str, Any]:
    return {
        **rollout,
        "id": str(rollout["id"]),
        "repair_change_id": str(rollout["repair_change_id"]),
        "started_at": rollout["started_at"].isoformat() if rollout.get("started_at") else None,
        "completed_at": rollout["completed_at"].isoformat() if rollout.get("completed_at") else None,
    }


def failed_action_records(actions: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed_actions = [action for action in actions if action["status"] in {"failed", "blocked", "rejected"}]
    failed_events = [
        {
            "event_type": event["type"],
            "actor": event["actor"],
            "payload": event["payload"],
            "ts": event["ts"].isoformat(),
        }
        for event in events
    ]
    return failed_actions + failed_events


def extract_symptoms(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    symptoms = []
    for item in evidence:
        if item["source"] == "scenario" or str(item["kind"]).startswith("failed_check"):
            content = item["content"]
            symptoms.append(
                {
                    "kind": item["kind"],
                    "summary": content.get("summary") or item_summary(content),
                    "content": content.get("content", content),
                    "confidence": item["confidence"],
                }
            )
    return symptoms


def item_summary(content: dict[str, Any]) -> str:
    return content.get("summary") or content.get("kind") or "incident symptom"


def summarize_memory(incident: dict[str, Any], symptoms: list[dict[str, Any]], action: dict[str, Any] | None) -> str:
    action_type = action["action_type"] if action else "no successful action"
    return f"{incident['root_cause'] or incident['title']} recovered with {action_type}; symptoms: {len(symptoms)}."


def evidence_text(item: Any) -> str:
    return " ".join([getattr(item, "summary", ""), str(getattr(item, "content", "")), getattr(item, "kind", "")])


def memory_score(query_terms: set[str], memory: dict[str, Any]) -> float:
    memory_terms = tokenize(
        " ".join(
            [
                memory.get("summary") or "",
                memory.get("root_cause") or "",
                str(memory.get("symptoms") or ""),
            ]
        )
    )
    if not memory_terms:
        return 0
    overlap = query_terms & memory_terms
    return round(len(overlap) / max(len(query_terms), 1), 3)


def tokenize(text: str) -> set[str]:
    stop = {"the", "and", "or", "a", "an", "to", "of", "is", "in", "for", "with", "after", "before"}
    return {
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(token) > 2 and token not in stop
    }


def fetch_one(conn: Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(conn: Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()
