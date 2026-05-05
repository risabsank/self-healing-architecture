# Incident Agent

The incident agent turns an unhealthy service observation into structured operational analysis.

It currently runs as a deterministic state machine inside the control API. The implementation is intentionally typed and auditable so it can later be backed by LangGraph or an LLM provider without changing the public behavior.

## Responsibilities

- Collect evidence from recent health checks, runtime events, service metadata, and active failure scenarios.
- Persist evidence as structured records.
- Generate root-cause hypotheses.
- Rank hypotheses by confidence.
- Propose safe mitigation candidates.
- Select the safest eligible mitigation.
- Write each decision to the incident timeline.

## Automatic Analysis

When the monitor observes an unhealthy health check, it creates an incident and invokes the incident agent automatically.

The resulting incident includes:

- evidence records,
- ranked hypotheses,
- mitigation candidates,
- one selected mitigation,
- timeline events describing the analysis.

## Manual Analysis

An incident can also be analyzed manually:

```bash
curl -X POST http://localhost:8000/incidents/{incident_id}/analyze
```

Useful inspection endpoints:

```text
GET http://localhost:8000/incidents/{incident_id}/timeline
GET http://localhost:8000/incidents/{incident_id}/evidence
GET http://localhost:8000/incidents/{incident_id}/hypotheses
GET http://localhost:8000/incidents/{incident_id}/actions
```

## State Machine

```text
detected
-> investigating
-> collect evidence
-> hypothesizing
-> rank hypotheses
-> propose mitigations
-> select mitigation
-> mitigation_selected
```

## Safety Boundary

The incident agent does not execute shell commands and does not directly mutate the target service. It only selects a typed mitigation candidate. Execution belongs to the bounded mitigation runtime.

Selected mitigations include:

- action type,
- parameters,
- expected effect,
- risk score,
- approval requirement,
- ranking metadata.
