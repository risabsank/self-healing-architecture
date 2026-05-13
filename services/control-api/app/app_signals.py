from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.models.schemas import ApplicationManifest, MetricObservationCreate, OperatorNoteCreate
from app.observability import record_incident_event


NOTE_TRIGGER_WORDS = ("degraded", "down", "error", "errors", "failing", "failure", "outage", "slow", "latency")
OPEN_INCIDENT_STATUSES = (
    "detected",
    "investigating",
    "hypothesizing",
    "mitigation_selected",
    "awaiting_approval",
    "remediating",
    "verifying",
    "blocked",
)


def record_metric(conn: Connection, app: dict[str, Any], payload: MetricObservationCreate) -> dict[str, Any]:
    manifest = ApplicationManifest.model_validate(app["manifest"])
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_metric_observations (app_id, metric_name, value, unit, source, labels)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, app_id, metric_name, value, unit, source, labels, observed_at
            """,
            (app["app_id"], payload.metric_name, payload.value, payload.unit, payload.source, Jsonb(payload.labels)),
        )
        observation = cur.fetchone()

    evaluations = [evaluate_slo(conn, app, observation, slo.model_dump()) for slo in manifest.slo_targets if slo.metric == payload.metric_name]
    conn.commit()
    return {"observation": serialize_time(observation, "observed_at"), "slo_evaluations": evaluations}


def evaluate_slo(
    conn: Connection,
    app: dict[str, Any],
    observation: dict[str, Any],
    slo: dict[str, Any],
) -> dict[str, Any]:
    passed = compare(float(observation["value"]), float(slo["target"]), slo["comparator"])
    incident = None
    if not passed:
        incident = create_signal_incident(
            conn,
            app,
            f"SLO breach: {slo['name']}",
            "slo_breach",
            {
                "slo": slo,
                "metric": observation["metric_name"],
                "observed_value": observation["value"],
                "target": slo["target"],
                "comparator": slo["comparator"],
                "severity": slo.get("severity", "high"),
            },
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_slo_evaluations (
              app_id, slo_name, metric_name, status, target, observed_value,
              comparator, slo_window, observation_id, incident_id, detail
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, app_id, slo_name, metric_name, status, target, observed_value,
                      comparator, slo_window AS window, observation_id, incident_id, detail, evaluated_at
            """,
            (
                app["app_id"],
                slo["name"],
                observation["metric_name"],
                "healthy" if passed else "breached",
                slo["target"],
                observation["value"],
                slo["comparator"],
                slo["window"],
                observation["id"],
                incident["id"] if incident else None,
                Jsonb({"severity": slo.get("severity"), "description": slo.get("description")}),
            ),
        )
        evaluation = cur.fetchone()
    return serialize_time(evaluation, "evaluated_at")


def record_note(conn: Connection, app: dict[str, Any], payload: OperatorNoteCreate) -> dict[str, Any]:
    incident = None
    if note_should_trigger_incident(payload):
        incident = create_signal_incident(
            conn,
            app,
            f"Operator note: {payload.note[:80]}",
            "operator_note",
            {
                "note": payload.note,
                "severity": payload.severity,
                "service_name": payload.service_name,
                "tags": payload.tags,
                "metric_refs": payload.metric_refs,
            },
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_operator_notes (
              app_id, sandbox_id, service_name, severity, note, tags, metric_refs, incident_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, app_id, sandbox_id, service_name, severity, note, tags, metric_refs, incident_id, created_at
            """,
            (
                app["app_id"],
                app["sandbox_id"],
                payload.service_name,
                payload.severity,
                payload.note,
                Jsonb(payload.tags),
                Jsonb(payload.metric_refs),
                incident["id"] if incident else None,
            ),
        )
        note = cur.fetchone()
    conn.commit()
    return {"note": serialize_time(note, "created_at"), "incident": serialize_time(incident, "detected_at") if incident else None}


def latest_metrics(conn: Connection, app_id: str, limit: int = 50) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, app_id, metric_name, value, unit, source, labels, observed_at
            FROM app_metric_observations
            WHERE app_id = %s
            ORDER BY observed_at DESC
            LIMIT %s
            """,
            (app_id, limit),
        )
        observations = [serialize_time(row, "observed_at") for row in cur.fetchall()]
        cur.execute(
            """
            SELECT id, app_id, slo_name, metric_name, status, target, observed_value,
                   comparator, slo_window AS window, observation_id, incident_id, detail, evaluated_at
            FROM app_slo_evaluations
            WHERE app_id = %s
            ORDER BY evaluated_at DESC
            LIMIT %s
            """,
            (app_id, limit),
        )
        evaluations = [serialize_time(row, "evaluated_at") for row in cur.fetchall()]
    return {"observations": observations, "slo_evaluations": evaluations}


def latest_notes(conn: Connection, app_id: str, limit: int = 25) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, app_id, sandbox_id, service_name, severity, note, tags, metric_refs, incident_id, created_at
            FROM app_operator_notes
            WHERE app_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (app_id, limit),
        )
        return [serialize_time(row, "created_at") for row in cur.fetchall()]


def slo_status(conn: Connection, app: dict[str, Any]) -> dict[str, Any]:
    manifest = ApplicationManifest.model_validate(app["manifest"])
    latest = {}
    for row in latest_metrics(conn, app["app_id"], 100)["slo_evaluations"]:
        latest.setdefault(row["slo_name"], row)
    targets = []
    for slo in manifest.slo_targets:
        evaluation = latest.get(slo.name)
        targets.append({**slo.model_dump(), "latest": evaluation, "status": evaluation["status"] if evaluation else "unknown"})
    return {"app_id": app["app_id"], "slo_targets": targets}


def create_signal_incident(conn: Connection, app: dict[str, Any], title: str, trigger_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    service_name = payload.get("service_name") or primary_service_name(app)
    severity = payload.get("severity") or "high"
    existing = find_open_signal_incident(conn, app["app_id"], service_name)
    if existing:
        record_incident_event(
            conn,
            incident_id=str(existing["id"]),
            sandbox_id=app["sandbox_id"],
            event_type=f"incident.correlated.{trigger_type}",
            actor="app-signal-ingestor",
            payload={"app_id": app["app_id"], "service_name": service_name, **payload},
        )
        return existing

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidents (sandbox_id, app_id, service_name, severity, trigger_source, status, title)
            VALUES (%s, %s, %s, %s, %s, 'detected', %s)
            RETURNING id, sandbox_id, app_id, service_name, severity, trigger_source,
                      status, title, detected_at, resolved_at, root_cause, final_summary
            """,
            (app["sandbox_id"], app["app_id"], service_name, severity, trigger_type, title),
        )
        incident = cur.fetchone()
    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=app["sandbox_id"],
        event_type=f"incident.triggered.{trigger_type}",
        actor="app-signal-ingestor",
        payload={"app_id": app["app_id"], "service_name": service_name, **payload},
    )
    return incident


def find_open_signal_incident(conn: Connection, app_id: str, service_name: str | None) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, app_id, service_name, severity, trigger_source,
                   status, title, detected_at, resolved_at, root_cause, final_summary
            FROM incidents
            WHERE app_id = %s
              AND COALESCE(service_name, '') = COALESCE(%s, '')
              AND status = ANY(%s)
            ORDER BY detected_at DESC
            LIMIT 1
            """,
            (app_id, service_name, list(OPEN_INCIDENT_STATUSES)),
        )
        return cur.fetchone()


def primary_service_name(app: dict[str, Any]) -> str | None:
    services = (app.get("manifest") or {}).get("services") or []
    return services[0].get("name") if services else None


def note_should_trigger_incident(note: OperatorNoteCreate) -> bool:
    if note.severity in {"high", "critical"}:
        return True
    lowered = note.note.lower()
    return any(word in lowered for word in NOTE_TRIGGER_WORDS)


def compare(value: float, target: float, comparator: str) -> bool:
    if comparator == "<=":
        return value <= target
    if comparator == ">=":
        return value >= target
    if comparator == "<":
        return value < target
    if comparator == ">":
        return value > target
    if comparator == "==":
        return value == target
    raise ValueError(f"Unsupported comparator: {comparator}")


def serialize_time(row: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not row:
        return None
    return {**row, key: row[key].isoformat() if row.get(key) else None}
