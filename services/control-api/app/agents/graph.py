from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.llm_graph import run_llm_incident_graph
from app.agents.state import Evidence, Hypothesis, IncidentAnalysis, MitigationCandidate
from app.apps import get_application_for_sandbox
from app.core.config import settings
from app.memory import retrieve_similar_memories
from app.observability import record_incident_event


SAFE_AUTONOMOUS_RISK_THRESHOLD = 0.35


def scenario(cause: str, confidence: float, rationale: str, *mitigations: dict[str, Any]) -> dict[str, Any]:
    return {
        "cause": cause,
        "confidence": confidence,
        "rationale": rationale,
        "mitigations": list(mitigations),
    }


def mitigation(
    action_type: str,
    expected_effect: str,
    risk_score: float,
    requires_approval: bool = False,
    **params: Any,
) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "params": {"service": "target-api", **params},
        "expected_effect": expected_effect,
        "risk_score": risk_score,
        "requires_approval": requires_approval,
    }


SCENARIO_ROOT_CAUSES: dict[str, dict[str, Any]] = {
    "bad_database_url": scenario(
        "Broken database connection string",
        0.92,
        "The database health check failed while the process and required environment checks remained healthy.",
        mitigation("SET_ENV_VAR", "Restore database connectivity for the target API.", 0.2, key="DATABASE_URL", value_from="known_good_config"),
        mitigation("RESTART_SERVICE", "Reload service configuration after restoring DATABASE_URL.", 0.18),
    ),
    "missing_required_env": scenario(
        "Missing required environment variable",
        0.9,
        "The required environment check failed before deeper service dependencies were needed.",
        mitigation("SET_ENV_VAR", "Restore the required runtime configuration value.", 0.2, key="TARGET_REQUIRED_SECRET", value_from="known_good_config"),
        mitigation("RESTART_SERVICE", "Reload environment after restoring the missing variable.", 0.18),
    ),
    "schema_mismatch": scenario(
        "Application/schema mismatch after change",
        0.86,
        "The health payload reports a schema mismatch consistent with app code expecting a missing database shape.",
        mitigation("ROLLBACK_CONFIG", "Return the app to a version compatible with the current schema.", 0.42, True, target="previous_known_good_app_version"),
    ),
    "port_conflict": scenario(
        "Service process or port binding conflict",
        0.82,
        "The process check reports a simulated port binding conflict.",
        mitigation("RESTART_SERVICE", "Restart the service to clear the runtime conflict.", 0.22),
    ),
    "bad_feature_flag": scenario(
        "Bad feature flag enabled a broken code path",
        0.8,
        "The active scenario indicates a feature-specific failure that can be isolated by disabling the flag.",
        mitigation("DISABLE_FEATURE_FLAG", "Disable the broken checkout path while preserving core service health.", 0.16, flag="FEATURE_CHECKOUT_ENABLED"),
    ),
    "dependency_unavailable": scenario(
        "Downstream API dependency unavailable",
        0.78,
        "The active scenario indicates dependency failure isolated to a dependent route.",
        mitigation("SWITCH_DEPENDENCY_TO_MOCK", "Route calls to a known-good fallback dependency.", 0.3, dependency="checkout-provider"),
    ),
    "rate_limit": scenario(
        "Dependency rate limiting",
        0.74,
        "The active scenario indicates dependency throttling; traffic should be reduced or backed off.",
        mitigation("DISABLE_FEATURE_FLAG", "Temporarily stop the rate-limited path while the system recovers.", 0.24, flag="FEATURE_CHECKOUT_ENABLED"),
    ),
}


def analyze_incident(conn: Connection, incident_id: str) -> IncidentAnalysis:
    incident = load_incident(conn, incident_id)
    analysis = IncidentAnalysis(
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        status="investigating",
    )

    clear_previous_analysis(conn, incident_id)
    transition(conn, analysis, "investigating", "agent.started", {"state": "collect_evidence"})

    analysis.evidence = collect_evidence(conn, analysis.sandbox_id)
    evidence_ids = persist_evidence(conn, incident_id, analysis.evidence)
    record_agent_event(conn, analysis, "agent.evidence_collected", {
        "evidence_count": len(analysis.evidence),
        "evidence": [e.model_dump() for e in analysis.evidence],
    })

    set_incident_status(conn, incident_id, "hypothesizing")
    analysis = reason_about_incident(conn, analysis)
    persist_hypotheses(conn, incident_id, analysis.hypotheses, evidence_ids)
    persist_top_root_cause(conn, incident_id, analysis.hypotheses)
    record_agent_event(conn, analysis, "agent.hypotheses_ranked", {
        "hypotheses": [h.model_dump() for h in analysis.hypotheses],
        "reasoning_provider": analysis.reasoning_provider,
        "reasoning_summary": analysis.reasoning_summary,
    })

    if not analysis.mitigations:
        analysis.mitigations = propose_mitigations(analysis.hypotheses, analysis.evidence)
    analysis.selected_mitigation = select_mitigation(analysis.mitigations)
    persist_mitigations(conn, incident_id, analysis.mitigations, analysis.selected_mitigation)
    record_agent_event(conn, analysis, "agent.mitigation_selected", {
        "candidates": [m.model_dump() for m in analysis.mitigations],
        "selected": analysis.selected_mitigation.model_dump() if analysis.selected_mitigation else None,
    })

    set_incident_status(conn, incident_id, "mitigation_selected")
    conn.commit()
    return analysis


def reason_about_incident(conn: Connection, analysis: IncidentAnalysis) -> IncidentAnalysis:
    if not settings.llm_reasoning_enabled:
        return deterministic_reasoning(analysis)

    try:
        return run_llm_incident_graph(analysis)
    except Exception as exc:
        record_agent_event(conn, analysis, "agent.llm_reasoning_failed", {
            "error": type(exc).__name__,
            "message": str(exc),
            "fallback": "deterministic",
        })
        return deterministic_reasoning(analysis)


def deterministic_reasoning(analysis: IncidentAnalysis) -> IncidentAnalysis:
    analysis.hypotheses = generate_hypotheses(analysis.evidence)
    analysis.mitigations = propose_mitigations(analysis.hypotheses, analysis.evidence)
    analysis.reasoning_provider = "deterministic"
    analysis.reasoning_summary = "Deterministic rules ranked root causes from health checks, scenarios, and memory."
    return analysis


def transition(
    conn: Connection,
    analysis: IncidentAnalysis,
    status: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    set_incident_status(conn, analysis.incident_id, status)
    record_agent_event(conn, analysis, event_type, payload)


def record_agent_event(
    conn: Connection,
    analysis: IncidentAnalysis,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    record_incident_event(
        conn,
        incident_id=analysis.incident_id,
        sandbox_id=analysis.sandbox_id,
        event_type=event_type,
        actor="incident-agent",
        payload=payload,
    )


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
    app = get_application_for_sandbox(conn, sandbox_id)
    app_id = app["app_id"] if app else None

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

        slo_evaluations = []
        operator_notes = []
        if app_id:
            cur.execute(
                """
                SELECT slo_name, metric_name, status, target, observed_value, comparator,
                       slo_window AS window, incident_id, detail, evaluated_at
                FROM app_slo_evaluations
                WHERE app_id = %s
                ORDER BY evaluated_at DESC
                LIMIT 5
                """,
                (app_id,),
            )
            slo_evaluations = cur.fetchall()

            cur.execute(
                """
                SELECT service_name, severity, note, tags, metric_refs, incident_id, created_at
                FROM app_operator_notes
                WHERE app_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (app_id,),
            )
            operator_notes = cur.fetchall()

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

    if app:
        manifest = app["manifest"]
        evidence.append(
            Evidence(
                    source="app_manifest",
                    kind="registered_application",
                    summary=f"Registered app manifest: {app['display_name']}",
                    content={
                        "app_id": app["app_id"],
                        "environment": app["environment"],
                        "services": manifest.get("services", []),
                        "critical_probes": manifest.get("critical_probes", []),
                        "metric_sources": manifest.get("metric_sources", []),
                        "slo_targets": manifest.get("slo_targets", []),
                        "safe_actions": manifest.get("safe_actions", []),
                        "repair_policy": manifest.get("repair_policy", {}),
                    },
                confidence=0.9,
            )
        )

    for evaluation in slo_evaluations:
        if evaluation["status"] == "breached":
            evidence.append(
                Evidence(
                    source="metric_slo",
                    kind="slo_breach",
                    summary=f"{evaluation['slo_name']} breached: {evaluation['metric_name']}={evaluation['observed_value']} {evaluation['comparator']} {evaluation['target']}",
                    content={
                        **evaluation,
                        "evaluated_at": evaluation["evaluated_at"].isoformat(),
                        "incident_id": str(evaluation["incident_id"]) if evaluation.get("incident_id") else None,
                    },
                    confidence=0.86,
                )
            )

    for note in operator_notes:
        evidence.append(
            Evidence(
                source="operator_note",
                kind=f"operator_note:{note['severity']}",
                summary=f"Operator note ({note['severity']}): {note['note']}",
                content={
                    **note,
                    "created_at": note["created_at"].isoformat(),
                    "incident_id": str(note["incident_id"]) if note.get("incident_id") else None,
                },
                confidence=0.72 if note["severity"] in {"info", "low"} else 0.84,
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

    for memory in retrieve_similar_memories(conn, evidence):
        evidence.append(memory_evidence(memory))

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

    if "slo" in joined or "latency" in joined or "error rate" in joined or "operator note" in joined:
        return [
            Hypothesis(
                cause="User-visible service degradation",
                evidence_indexes=list(range(min(len(evidence), 4))),
                confidence=0.66,
                rationale_summary="Recent SLO or operator-note evidence indicates user-visible degradation even if core health is still passing.",
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
        memory_candidate = mitigation_from_memory(evidence)
        if memory_candidate:
            candidates.append(memory_candidate)

    if not candidates and hypotheses:
        restart = manifest_safe_action(evidence, "RESTART_SERVICE")
        service_name = restart.get("service") if restart else primary_service_from_evidence(evidence)
        if restart and service_name:
            candidates.append(
                MitigationCandidate(
                    action_type="RESTART_SERVICE",
                    params={"service": service_name},
                    expected_effect="Attempt the app-declared low-risk restart for an unknown service health regression.",
                    risk_score=min(float(restart.get("max_autonomous_risk") or 0.25), 0.35),
                    requires_approval=bool(restart.get("approval_required", False)),
                    rank=1,
                )
            )

    return candidates


def memory_evidence(memory: dict[str, Any]) -> Evidence:
    return Evidence(
        source="memory",
        kind="similar_incident",
        summary=f"Similar incident memory: {memory['summary']}",
        content=memory,
        confidence=min(0.9, 0.55 + memory["similarity_score"]),
    )


def mitigation_from_memory(evidence: list[Evidence]) -> MitigationCandidate | None:
    for item in evidence:
        if item.source != "memory":
            continue
        action = item.content.get("successful_action") or {}
        if action.get("action_type") and action.get("params"):
            return MitigationCandidate(
                action_type=action["action_type"],
                params=action["params"],
                expected_effect=f"Reuse mitigation from similar incident memory {item.content.get('id')}.",
                risk_score=min(float(action.get("risk_score") or 0.3), 0.35),
                requires_approval=bool(action.get("requires_approval", False)),
                rank=1,
            )
    return None


def manifest_safe_action(evidence: list[Evidence], action_type: str) -> dict[str, Any] | None:
    manifest = next((item.content for item in evidence if item.source == "app_manifest"), {})
    for action in manifest.get("safe_actions") or []:
        if action.get("action_type") == action_type:
            return action
    return None


def primary_service_from_evidence(evidence: list[Evidence]) -> str | None:
    for item in evidence:
        if item.source == "service_metadata" and item.content.get("service_name"):
            return item.content["service_name"]
    manifest = next((item.content for item in evidence if item.source == "app_manifest"), {})
    services = manifest.get("services") or []
    return services[0].get("name") if services else None


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
