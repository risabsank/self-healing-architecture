import json
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


def record_runtime_event(
    conn: Connection,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    sandbox_id: str | None = None,
    service_name: str | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runtime_events (sandbox_id, service_name, type, actor, payload)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, sandbox_id, service_name, ts, type, actor, payload
            """,
            (sandbox_id, service_name, event_type, actor, Jsonb(payload)),
        )
        event = cur.fetchone()
        print(json.dumps({"type": event_type, "actor": actor, "payload": payload}, default=str), flush=True)
        return event


def record_incident_event(
    conn: Connection,
    incident_id: str,
    sandbox_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_events (incident_id, sandbox_id, type, actor, payload)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, incident_id, sandbox_id, ts, type, actor, payload
            """,
            (incident_id, sandbox_id, event_type, actor, Jsonb(payload)),
        )
        return cur.fetchone()
