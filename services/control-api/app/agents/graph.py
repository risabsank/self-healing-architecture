from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.state import Evidence, Hypothesis, IncidentAnalysis, MitigationCandidate
from app.observability import record_incident_event


SAFE_AUTONOMOUS_RISK_THRESHOLD = 0.35


SCENARIO_ROOT_CAUSES: dict[str, dict[str, Any]] = {
    "bad_database_url": {
        "cause": "Broken database connection string",
        "confidence": 0.92,
        "rationale": "The database health check failed while the process and required environment checks remained healthy.",
        "mitigations": [
            {
                "action_type": "SET_ENV_VAR",
                "params": {
                    "service": "target-api",
                    "key": "DATABASE_URL",
                    "value_from": "known_good_config",
                },
                "expected_effect": "Restore database connectivity for the target API.",
                "risk_score": 0.2,
                "requires_approval": False,
            },
            {
                "action_type": "RESTART_SERVICE",
                "params": {"service": "target-api"},
                "expected_effect": "Reload service configuration after restoring DATABASE_URL.",
                "risk_score": 0.18,
                "requires_approval": False,
            },
        ],
    },
    "missing_required_env": {
        "cause": "Missing required environment variable",
        "confidence": 0.9,
        "rationale": "The required environment check failed before deeper service dependencies were needed.",
        "mitigations": [
            {
                "action_type": "SET_ENV_VAR",
                "params": {
                    "service": "target-api",
                    "key": "TARGET_REQUIRED_SECRET",
                    "value_from": "known_good_config",
                },
                "expected_effect": "Restore the required runtime configuration value.",
                "risk_score": 0.2,
                "requires_approval": False,
            },
            {
                "action_type": "RESTART_SERVICE",
                "params": {"service": "target-api"},
                "expected_effect": "Reload environment after restoring the missing variable.",
                "risk_score": 0.18,
                "requires_approval": False,
            },
        ],
    },
    "schema_mismatch": {
        "cause": "Application/schema mismatch after change",
        "confidence": 0.86,
        "rationale": "The health payload reports a schema mismatch consistent with app code expecting a missing database shape.",
        "mitigations": [
            {
                "action_type": "ROLLBACK_CONFIG",
                "params": {"service": "target-api", "target": "previous_known_good_app_version"},
                "expected_effect": "Return the app to a version compatible with the current schema.",
                "risk_score": 0.42,
                "requires_approval": True,
            }
        ],
    },
    "port_conflict": {
        "cause": "Service process or port binding conflict",
        "confidence": 0.82,
        "rationale": "The process check reports a simulated port binding conflict.",
        "mitigations": [
            {
                "action_type": "RESTART_SERVICE",
                "params": {"service": "target-api"},
                "expected_effect": "Restart the service to clear the runtime conflict.",
                "risk_score": 0.22,
                "requires_approval": False,
            }
        ],
    },
    "bad_feature_flag": {
        "cause": "Bad feature flag enabled a broken code path",
        "confidence": 0.8,
        "rationale": "The active scenario indicates a feature-specific failure that can be isolated by disabling the flag.",
        "mitigations": [
            {
                "action_type": "DISABLE_FEATURE_FLAG",
                "params": {"service": "target-api", "flag": "FEATURE_CHECKOUT_ENABLED"},
                "expected_effect": "Disable the broken checkout path while preserving core service health.",
                "risk_score": 0.16,
                "requires_approval": False,
            }
        ],
    },
    "dependency_unavailable": {
        "cause": "Downstream API dependency unavailable",
        "confidence": 0.78,
        "rationale": "The active scenario indicates dependency failure isolated to a dependent route.",
        "mitigations": [
            {
                "action_type": "SWITCH_DEPENDENCY_TO_MOCK",
                "params": {"service": "target-api", "dependency": "checkout-provider"},
                "expected_effect": "Route calls to a known-good fallback dependency.",
                "risk_score": 0.3,
                "requires_approval": False,
            }
        ],
    },
    "rate_limit": {
        "cause": "Dependency rate limiting",
        "confidence": 0.74,
        "rationale": "The active scenario indicates dependency throttling; traffic should be reduced or backed off.",
        "mitigations": [
            {
                "action_type": "DISABLE_FEATURE_FLAG",
                "params": {"service": "target-api", "flag": "FEATURE_CHECKOUT_ENABLED"},
                "expected_effect": "Temporarily stop the rate-limited path while the system recovers.",
                "risk_score": 0.24,
                "requires_approval": False,
            }
        ],
    },
}


def analyze_incident(conn: Connection, incident_id: str) -> IncidentAnalysis:
    incident = load_incident(conn, incident_id)
    analysis = IncidentAnalysis(
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        status="investigating",
    )

    clear_previous_analysis(conn, incident_id)
    set_incident_status(conn, incident_id, "investigating")
    record_incident_event(
        conn,
        incident_id=incident_id,
        sandbox_id=analysis.sandbox_id,
        event_type="agent.started",
        actor="incident-agent",
        payload={"state": "collect_evidence"},
    )

    analysis.evidence = collect_evidence(conn, analysis.sandbox_id)
    evidence_ids = persist_evidence(conn, incident_id, analysis.evidence)
    record_incident_event(
        conn,
        incident_id=incident_id,
        sandbox_id=analysis.sandbox_id,
        event_type="agent.evidence_collected",
        actor="incident-agent",
        payload={"evidence_count": len(analysis.evidence), "evidence": [e.model_dump() for e in analysis.evidence]},
    )

    set_incident_status(conn, incident_id, "hypothesizing")
    analysis.hypotheses = generate_hypotheses(analysis.evidence)
    persist_hypotheses(conn, incident_id, analysis.hypotheses, evidence_ids)
    persist_top_root_cause(conn, incident_id, analysis.hypotheses)
    record_incident_event(
        conn,
        incident_id=incident_id,
        sandbox_id=analysis.sandbox_id,
        event_type="agent.hypotheses_ranked",
        actor="incident-agent",
        payload={"hypotheses": [h.model_dump() for h in analysis.hypotheses]},
    )

    analysis.mitigations = propose_mitigations(analysis.hypotheses, analysis.evidence)
    analysis.selected_mitigation = select_mitigation(analysis.mitigations)
    persist_mitigations(conn, incident_id, analysis.mitigations, analysis.selected_mitigation)
    record_incident_event(
        conn,
        incident_id=incident_id,
        sandbox_id=analysis.sandbox_id,
        event_type="agent.mitigation_selected",
        actor="incident-agent",
        payload={
            "candidates": [m.model_dump() for m in analysis.mitigations],
            "selected": analysis.selected_mitigation.model_dump() if analysis.selected_mitigation else None,
        },
    )

    set_incident_status(conn, incident_id, "mitigation_selected")
    conn.commit()
    return analysis


def clear_previous_analysis(conn: Connection, incident_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence_items WHERE incident_id = %s", (incident_id,))
        cur.execute("DELETE FROM hypotheses WHERE incident_id = %s", (incident_id,))
        cur.execute("DELETE FROM remediation_actions WHERE incident_id = %s", (incident_id,))


def load_incident(conn: Connection, incident_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sandbox_id, status, title
            FROM incidents
            WHERE id = %s
            """,
            (incident_id,),
        )
        incident = cur.fetchone()

    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")
    return incident


def set_incident_status(conn: Connection, incident_id: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (status, incident_id))


def collect_evidence(conn: Connection, sandbox_id: str) -> list[Evidence]:
    evidence: list[Evidence] = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT service_name, status, latency_ms, detail, checked_at
            FROM health_checks
            WHERE sandbox_id = %s
            ORDER BY checked_at DESC
            LIMIT 5
            """,
            (sandbox_id,),
        )
        health_checks = cur.fetchall()

        cur.execute(
            """
            SELECT service_name, service_type, base_url, health_url, metadata
            FROM sandbox_services
            WHERE sandbox_id = %s
            ORDER BY service_name
            """,
            (sandbox_id,),
        )
        services = cur.fetchall()

        cur.execute(
            """
            SELECT type, actor, payload, ts
            FROM runtime_events
            WHERE sandbox_id = %s
            ORDER BY ts DESC
            LIMIT 10
            """,
            (sandbox_id,),
        )
        runtime_events = cur.fetchall()

    if health_checks:
        latest = health_checks[0]
        evidence.append(
            Evidence(
                source="healthcheck",
                kind="latest_health",
                summary=f"{latest['service_name']} reported {latest['status']}",
                content={
                    "service_name": latest["service_name"],
                    "status": latest["status"],
                    "latency_ms": latest["latency_ms"],
                    "detail": latest["detail"],
                    "checked_at": latest["checked_at"].isoformat(),
                },
                confidence=0.95,
            )
        )

        active_scenarios = latest["detail"].get("active_scenarios") or []
        for scenario in active_scenarios:
            evidence.append(
                Evidence(
                    source="scenario",
                    kind="active_failure_scenario",
                    summary=f"Active injected scenario: {scenario}",
                    content={"scenario": scenario},
                    confidence=0.9,
                )
            )

        checks = latest["detail"].get("checks") or {}
        for check_name, check_detail in checks.items():
            if isinstance(check_detail, dict) and not check_detail.get("ok", True):
                evidence.append(
                    Evidence(
                        source="healthcheck",
                        kind=f"failed_check:{check_name}",
                        summary=f"{check_name} check failed: {check_detail.get('message') or check_detail.get('error')}",
                        content={"check": check_name, "detail": check_detail},
                        confidence=0.88,
                    )
                )

    for service in services:
        evidence.append(
            Evidence(
                source="service_metadata",
                kind="registered_service",
                summary=f"Registered {service['service_type']} service {service['service_name']}",
                content={
                    "service_name": service["service_name"],
                    "service_type": service["service_type"],
                    "base_url": service["base_url"],
                    "health_url": service["health_url"],
                    "metadata": service["metadata"],
                },
                confidence=0.7,
            )
        )

    for event in runtime_events[:5]:
        evidence.append(
            Evidence(
                source="runtime_event",
                kind=event["type"],
                summary=f"{event['type']} by {event['actor']}",
                content={
                    "type": event["type"],
                    "actor": event["actor"],
                    "payload": event["payload"],
                    "ts": event["ts"].isoformat(),
                },
                confidence=0.76,
            )
        )

    return evidence


def generate_hypotheses(evidence: list[Evidence]) -> list[Hypothesis]:
    scenario_indexes = {
        item.content.get("scenario"): index
        for index, item in enumerate(evidence)
        if item.source == "scenario" and item.content.get("scenario")
    }

    hypotheses: list[Hypothesis] = []
    for scenario, evidence_index in scenario_indexes.items():
        rule = SCENARIO_ROOT_CAUSES.get(scenario)
        if rule:
            hypotheses.append(
                Hypothesis(
                    cause=rule["cause"],
                    evidence_indexes=[evidence_index],
                    confidence=rule["confidence"],
                    rationale_summary=rule["rationale"],
                )
            )

    if not hypotheses:
        hypotheses.extend(generate_fallback_hypotheses(evidence))

    return sorted(hypotheses, key=lambda item: item.confidence, reverse=True)


def generate_fallback_hypotheses(evidence: list[Evidence]) -> list[Hypothesis]:
    joined = " ".join(item.summary.lower() for item in evidence)
    if "database" in joined or "connection" in joined:
        return [
            Hypothesis(
                cause="Database dependency failure",
                evidence_indexes=list(range(min(len(evidence), 3))),
                confidence=0.68,
                rationale_summary="Recent evidence references database connectivity or dependency checks.",
            )
        ]

    if "required_env" in joined or "environment" in joined:
        return [
            Hypothesis(
                cause="Missing or invalid runtime configuration",
                evidence_indexes=list(range(min(len(evidence), 3))),
                confidence=0.64,
                rationale_summary="Recent evidence references failed configuration or environment checks.",
            )
        ]

    return [
        Hypothesis(
            cause="Unknown service health regression",
            evidence_indexes=list(range(min(len(evidence), 3))),
            confidence=0.45,
            rationale_summary="The service is unhealthy but the current evidence does not identify a specific known scenario.",
        )
    ]


def propose_mitigations(hypotheses: list[Hypothesis], evidence: list[Evidence]) -> list[MitigationCandidate]:
    candidates: list[MitigationCandidate] = []
    active_scenarios = [
        item.content.get("scenario")
        for item in evidence
        if item.source == "scenario" and item.content.get("scenario")
    ]

    for scenario in active_scenarios:
        rule = SCENARIO_ROOT_CAUSES.get(scenario)
        if not rule:
            continue
        for mitigation in rule["mitigations"]:
            candidates.append(
                MitigationCandidate(
                    rank=len(candidates) + 1,
                    **mitigation,
                )
            )

    if not candidates and hypotheses:
        candidates.append(
            MitigationCandidate(
                action_type="RESTART_SERVICE",
                params={"service": "target-api"},
                expected_effect="Attempt a low-risk restart for an unknown service health regression.",
                risk_score=0.25,
                requires_approval=False,
                rank=1,
            )
        )

    return candidates


def select_mitigation(candidates: list[MitigationCandidate]) -> MitigationCandidate | None:
    for candidate in sorted(candidates, key=lambda item: item.rank):
        if not candidate.requires_approval and candidate.risk_score <= SAFE_AUTONOMOUS_RISK_THRESHOLD:
            return candidate
    return sorted(candidates, key=lambda item: item.rank)[0] if candidates else None


def persist_evidence(conn: Connection, incident_id: str, evidence: list[Evidence]) -> list[Any]:
    evidence_ids = []
    with conn.cursor() as cur:
        for item in evidence:
            cur.execute(
                """
                INSERT INTO evidence_items (incident_id, source, kind, content, confidence)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (incident_id, item.source, item.kind, Jsonb(item.model_dump()), item.confidence),
            )
            evidence_ids.append(cur.fetchone()["id"])
    return evidence_ids


def persist_hypotheses(
    conn: Connection,
    incident_id: str,
    hypotheses: list[Hypothesis],
    evidence_ids: list[Any],
) -> None:
    with conn.cursor() as cur:
        for hypothesis in hypotheses:
            linked_evidence_ids = [
                evidence_ids[index]
                for index in hypothesis.evidence_indexes
                if index < len(evidence_ids)
            ]
            cur.execute(
                """
                INSERT INTO hypotheses (incident_id, cause, evidence_ids, confidence, rationale_summary)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    incident_id,
                    hypothesis.cause,
                    linked_evidence_ids,
                    hypothesis.confidence,
                    hypothesis.rationale_summary,
                ),
            )


def persist_top_root_cause(conn: Connection, incident_id: str, hypotheses: list[Hypothesis]) -> None:
    if not hypotheses:
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE incidents
            SET root_cause = %s
            WHERE id = %s
            """,
            (hypotheses[0].cause, incident_id),
        )


def persist_mitigations(
    conn: Connection,
    incident_id: str,
    mitigations: list[MitigationCandidate],
    selected_mitigation: MitigationCandidate | None,
) -> None:
    with conn.cursor() as cur:
        for mitigation in mitigations:
            status = "selected" if selected_mitigation and mitigation == selected_mitigation else "candidate"
            cur.execute(
                """
                INSERT INTO remediation_actions (
                  incident_id, action_type, params, risk_score, requires_approval, status, result
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    incident_id,
                    mitigation.action_type,
                    Jsonb(mitigation.params),
                    mitigation.risk_score,
                    mitigation.requires_approval,
                    status,
                    Jsonb(
                        {
                            "rank": mitigation.rank,
                            "expected_effect": mitigation.expected_effect,
                            "selection_reason": "highest-ranked safe autonomous mitigation"
                            if status == "selected"
                            else "ranked candidate",
                        }
                    ),
                ),
            )
