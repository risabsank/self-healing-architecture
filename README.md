# Self-Healing Runtime

## Reasoning + Memory for Live Software Failures

Self-Healing Runtime is a professional-grade autonomous incident response platform for live software systems. It monitors running applications inside isolated sandboxes, detects failures, gathers evidence, reasons about likely root causes, retrieves similar past incidents from memory, applies safe bounded fixes, verifies recovery, and stores the incident outcome for future use.

This project is not a generic chatbot and it is not a collection of static alerting playbooks. The goal is to show a long-running agent behaving like a careful production incident responder.

## One-Liner

An autonomous runtime that watches live sandboxed apps, diagnoses failures with structured evidence, safely applies bounded remediations, verifies recovery, and remembers what worked.

## What The Project Demonstrates

The project should be understandable in a short demo, but deep enough to stand as a serious resume centerpiece:

1. A small target web service starts healthy.
2. A realistic failure is injected, such as a broken database connection string.
3. The runtime detects the failure through health checks, logs, and service state.
4. An incident session starts automatically.
5. The agent collects evidence and retrieves similar past incidents.
6. The agent generates typed hypotheses and ranks likely root causes.
7. The agent selects a safe remediation action from an allowlisted interface.
8. The remediation is applied inside the sandbox.
9. The runtime verifies recovery.
10. The incident summary, evidence, action, and result are stored in memory.
11. The dashboard displays a replayable incident timeline.

The core moment: the service breaks live, the runtime investigates like an incident responder, applies a constrained fix, verifies recovery, and leaves behind a complete audit trail.

## Design Principles

- The agent must not blindly run shell commands.
- Every remediation must go through a bounded action interface.
- Dangerous actions must require human approval or be blocked.
- The system should log structured reasoning summaries, not hidden chain-of-thought.
- Agent outputs should be typed objects: hypotheses, evidence, remediation candidates, risk scores, and verification results.
- Incident memory should improve future responses.
- The target app should fail in realistic ways.
- The system should be built in phases, from a clear local prototype to a hardened production-style platform.

## Novel Technical Contributions

This project is strongest when framed as more than “LLM watches logs and restarts services.” The novel part is the combination of agentic reasoning, constrained execution, memory, isolation, and observability.

Key technical contributions:

- **Typed incident reasoning:** the agent emits structured evidence, hypotheses, risk scores, remediation candidates, and verification results instead of chat messages.
- **Bounded autonomous repair:** the system can act, but only through a safe remediation interface with explicit policy checks.
- **Incident memory loop:** every resolved incident becomes retrievable operational knowledge for future diagnosis.
- **Sandboxed failure environments:** failures happen in live isolated runtimes, not static examples.
- **Replayable operational traces:** every step of detection, reasoning, action, and verification is stored as a timeline.
- **Evaluation harness:** the system can be tested against repeatable failure scenarios and measured with recovery metrics.
- **Runtime abstraction:** Docker is the first backend, but the architecture can evolve toward Firecracker/MicroVM isolation.

## Preferred Technology Stack

- Backend: Python FastAPI
- Agent orchestration: LangGraph or an equivalent state-machine agent framework
- LLM provider: Claude API
- Database: Postgres
- Vector memory: pgvector or Chroma
- Sandbox: Docker for the first runtime backend, with Firecracker/MicroVM support as a major architecture track
- Frontend: Next.js + TypeScript
- Observability: OpenTelemetry-style structured event logs and dashboard timelines
- Target app: intentionally breakable web service with API and database dependency

## System Architecture

```text
┌──────────────────────────┐
│ Next.js Dashboard        │
│ incidents, timeline, UI  │
└────────────┬─────────────┘
             │ REST / SSE / WebSocket
┌────────────▼─────────────┐
│ FastAPI Control API      │
│ incidents, actions, VMs  │
└────────────┬─────────────┘
             │
┌────────────▼─────────────┐
│ Incident Agent           │
│ LangGraph state machine  │
└──────┬──────────┬────────┘
       │          │
       │          └────────────────┐
       │                           │
┌──────▼──────────┐       ┌────────▼─────────┐
│ Postgres        │       │ Vector Memory    │
│ incidents/events│       │ pgvector/Chroma  │
└──────┬──────────┘       └──────────────────┘
       │
┌──────▼──────────┐
│ Sandbox Runtime │
│ Docker first    │
└──────┬──────────┘
       │ bounded actions only
┌──────▼──────────────────┐
│ Breakable Target App    │
│ API + database service  │
└─────────────────────────┘
```

## Core Workflow

1. Monitor target app health.
2. Detect failure through metrics, logs, or health checks.
3. Start an incident session.
4. Collect evidence from logs, config, recent deploy metadata, service state, and previous incidents.
5. Generate hypotheses.
6. Retrieve similar incidents from memory.
7. Rank possible root causes.
8. Select a safe remediation action.
9. Apply the fix inside the sandbox through the controlled executor.
10. Verify recovery.
11. Store incident summary, evidence, action, and outcome in memory.
12. Show the full timeline in the UI.

## Repository Structure

```text
self-healing-architecture/
  apps/
    dashboard/
      app/
      components/
      lib/
        api.ts

  services/
    control-api/
      app/
        main.py
        api/
          routes/
            health.py
            incidents.py
            sandboxes.py
            actions.py
            timeline.py
        agents/
          graph.py
          prompts.py
          state.py
          tools.py
        core/
          config.py
          db.py
          telemetry.py
        memory/
          retriever.py
          writer.py
        models/
          action.py
          incident.py
          memory.py
        observability/
          event_log.py
          schemas.py
        sandbox/
          action_executor.py
          allowed_actions.py
          docker_runtime.py
      pyproject.toml

  target-app/
    api/
      main.py
      requirements.txt
      Dockerfile
    db/
      init.sql
    scenarios/
      break_db_url.py
      break_env_var.py
      break_feature_flag.py
      break_schema.py

  infra/
    docker-compose.yml
    postgres/
      init.sql

  docs/
    architecture.md
    demo-script.md
    roadmap.md
    firecracker-notes.md
```

## Local Development

Phase 1 can be run locally with Docker Compose:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Main services:

```text
Control API  http://localhost:8000
Target API   http://localhost:8001
Postgres     localhost:5432
Target DB    localhost:5433
```

Useful checks:

```text
GET  http://localhost:8000/health
GET  http://localhost:8000/sandboxes/local-docker
POST http://localhost:8000/sandboxes/local-docker/health-check
GET  http://localhost:8001/health
GET  http://localhost:8001/items
```

See `docs/phase-1-system-foundation.md` for the Phase 1 runbook.

## Core Services

### Control API

The FastAPI control service owns the incident lifecycle. It exposes APIs for sandboxes, incidents, timelines, memory, and remediation approval.

Example routes:

```text
GET    /health
POST   /sandboxes
GET    /sandboxes/{sandbox_id}
POST   /sandboxes/{sandbox_id}/scenario/{scenario_name}

GET    /incidents
POST   /incidents
GET    /incidents/{incident_id}
GET    /incidents/{incident_id}/timeline
GET    /incidents/{incident_id}/evidence
GET    /incidents/{incident_id}/hypotheses
GET    /incidents/{incident_id}/actions

POST   /actions/{action_id}/approve
POST   /actions/{action_id}/reject

GET    /memory/search?query=...
POST   /memory/reindex

GET    /events/stream
```

### Incident Agent

The incident agent is a state machine, not an open-ended chatbot. It moves through explicit phases:

```text
detect_failure
  -> start_incident
  -> collect_evidence
  -> retrieve_memory
  -> generate_hypotheses
  -> rank_root_causes
  -> propose_remediations
  -> guardrail_check
  -> apply_action OR require_approval OR block
  -> verify_recovery
  -> store_memory
  -> close_incident
```

### Sandbox Runtime

The initial runtime uses Docker. Each target app runs inside a controlled environment with its own service containers, configuration, logs, and failure injection hooks.

The architecture should leave room for a future Firecracker or MicroVM backend:

- Docker runtime for local development and fast iteration.
- Runtime interface that can later support MicroVM creation, snapshotting, and teardown.
- Same bounded remediation API regardless of sandbox implementation.

### Bounded Remediation Executor

The agent never receives raw shell access. It can only request typed remediation operations from an allowlist.

Example allowed actions:

```python
from enum import Enum

class AllowedAction(str, Enum):
    SET_ENV_VAR = "set_env_var"
    RESTART_SERVICE = "restart_service"
    ROLLBACK_CONFIG = "rollback_config"
    DISABLE_FEATURE_FLAG = "disable_feature_flag"
    RUN_DB_MIGRATION = "run_db_migration"
    SCALE_REPLICA = "scale_replica"
    SWITCH_DEPENDENCY_TO_MOCK = "switch_dependency_to_mock"
```

Safe action example:

```json
{
  "action_type": "SET_ENV_VAR",
  "params": {
    "service": "target-api",
    "key": "DATABASE_URL",
    "value_from": "known_good_config"
  },
  "risk_score": 0.2,
  "requires_approval": false
}
```

Blocked action example:

```json
{
  "action_type": "RUN_ARBITRARY_COMMAND",
  "params": {
    "command": "rm -rf /tmp/app"
  },
  "decision": "blocked",
  "reason": "Action type is not allowlisted"
}
```

## Data Model

```sql
CREATE TABLE incidents (
  id UUID PRIMARY KEY,
  sandbox_id TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  root_cause TEXT,
  final_summary TEXT
);

CREATE TABLE incident_events (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload JSONB NOT NULL
);

CREATE TABLE evidence_items (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  content JSONB NOT NULL,
  confidence FLOAT
);

CREATE TABLE hypotheses (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  cause TEXT NOT NULL,
  evidence_ids UUID[],
  confidence FLOAT NOT NULL,
  rationale_summary TEXT NOT NULL
);

CREATE TABLE remediation_actions (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  action_type TEXT NOT NULL,
  params JSONB NOT NULL,
  risk_score FLOAT NOT NULL,
  requires_approval BOOLEAN NOT NULL,
  status TEXT NOT NULL,
  result JSONB
);

CREATE TABLE incident_memories (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  summary TEXT NOT NULL,
  root_cause TEXT,
  successful_action JSONB,
  failed_actions JSONB,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## Agent State Definition

```python
from typing import Literal, TypedDict
from pydantic import BaseModel

class Evidence(BaseModel):
    source: Literal[
        "healthcheck",
        "logs",
        "metrics",
        "config",
        "deploy",
        "sandbox",
        "memory",
    ]
    kind: str
    summary: str
    raw_ref: str | None = None
    confidence: float

class Hypothesis(BaseModel):
    cause: str
    evidence: list[str]
    confidence: float
    rationale_summary: str

class RemediationCandidate(BaseModel):
    action_type: str
    params: dict
    expected_effect: str
    risk_score: float
    requires_approval: bool

class VerificationResult(BaseModel):
    recovered: bool
    checks: list[dict]
    notes: str

class IncidentState(TypedDict):
    incident_id: str
    sandbox_id: str
    status: str
    evidence: list[Evidence]
    similar_incidents: list[dict]
    hypotheses: list[Hypothesis]
    candidates: list[RemediationCandidate]
    selected_action: RemediationCandidate | None
    verification: VerificationResult | None
```

## Incident Loop Pseudocode

```python
import time

def monitor_loop(sandbox_id: str):
    while True:
        health = monitor.check_target(sandbox_id)

        if health.status == "unhealthy":
            incident = incidents.create(
                sandbox_id=sandbox_id,
                title=health.summary,
            )

            state = {
                "incident_id": incident.id,
                "sandbox_id": sandbox_id,
                "status": "investigating",
                "evidence": [],
                "similar_incidents": [],
                "hypotheses": [],
                "candidates": [],
                "selected_action": None,
                "verification": None,
            }

            incident_graph.invoke(state)

        time.sleep(5)
```

## Structured Reasoning Events

The system should store reasoning summaries that are safe to show in the UI.

Example event:

```json
{
  "type": "hypothesis.generated",
  "actor": "incident-agent",
  "payload": {
    "cause": "Broken database connection string",
    "confidence": 0.86,
    "evidence": [
      "Healthcheck reports database unavailable",
      "Logs contain connection refused to host wrong-db",
      "Recent scenario changed DATABASE_URL"
    ],
    "rationale_summary": "The app is reachable but fails when touching persistence, and the configured database host differs from known-good config."
  }
}
```

## Failure Scenarios

### 1. Wrong Database Connection String

The target app has an invalid `DATABASE_URL`.

Symptoms:

- Health check returns unhealthy.
- Logs contain database connection errors.
- App process may remain alive, but routes requiring persistence fail.

Likely remediation:

- Restore `DATABASE_URL` from known-good config.
- Restart the target API.
- Verify `/health` and a database-backed endpoint.

This should be the primary demo scenario.

### 2. Bad Feature Flag

A feature flag enables a broken code path.

Symptoms:

- One endpoint starts returning `500`.
- Logs reference a feature-specific error.
- Recent change metadata shows a flag update.

Likely remediation:

- Disable the feature flag.
- Verify the affected endpoint.

### 3. Schema Mismatch After Deploy

The app expects a database column or table that does not exist.

Symptoms:

- SQL errors in logs.
- Health may be partially degraded.
- Recent deploy metadata indicates a new app version.

Likely remediation:

- Low risk: roll back the app version.
- Medium risk: run a known migration with human approval.

### 4. API Dependency Unavailable

An external dependency or mock service is down.

Symptoms:

- Timeouts or connection errors.
- Affected routes fail while core app health may remain healthy.

Likely remediation:

- Switch to fallback mock dependency.
- Restart or reconfigure the dependent service.

### 5. Port Conflict

The app cannot bind to its expected port.

Symptoms:

- Process crash loop.
- Logs include address already in use.

Likely remediation:

- Restart conflicting service.
- Restore expected port config.

### 6. Memory Leak Or Crash Loop

The app repeatedly exits after memory usage climbs.

Symptoms:

- Container restarts.
- Increasing memory metrics.
- Repeated crash signatures in logs.

Likely remediation:

- Restart service as temporary recovery.
- Roll back recent deploy if crash began after deployment.

### 7. Rate Limit Induced Failure

The target app exceeds a dependency rate limit.

Symptoms:

- HTTP `429` from dependency.
- Retry storm in logs.

Likely remediation:

- Enable backoff flag.
- Switch to cached or mocked dependency.

## Memory Design

Memory should answer: “Have we seen something like this before, and what worked?”

Incident memory example:

```json
{
  "summary": "Target API returned 500 because DATABASE_URL pointed at the wrong host.",
  "symptoms": [
    "healthcheck failed",
    "database connection refused",
    "database-backed endpoint failed"
  ],
  "root_cause": "bad database connection string",
  "successful_action": {
    "type": "SET_ENV_VAR",
    "params": {
      "key": "DATABASE_URL",
      "value_source": "known_good_config"
    }
  },
  "verification": {
    "recovered": true,
    "checks": [
      "GET /health returned 200",
      "GET /items returned 200"
    ]
  }
}
```

Operational fact memory example:

```json
{
  "sandbox_id": "demo-001",
  "service": "target-api",
  "known_good_config": {
    "DATABASE_URL": "postgresql://app:app@target-db:5432/app"
  },
  "safe_actions": [
    "SET_ENV_VAR",
    "RESTART_SERVICE",
    "DISABLE_FEATURE_FLAG"
  ]
}
```

## Dashboard Requirements

The dashboard should focus on the incident timeline, not chat.

Primary views:

- Sandbox health
- Current incident status
- Live timeline
- Evidence panel
- Hypotheses and confidence scores
- Memory matches
- Selected remediation action
- Guardrail decision
- Verification result
- Past incident replay

Timeline event examples:

```text
08:01:12  Health check failed
08:01:13  Incident started
08:01:15  Logs collected
08:01:16  Config inspected
08:01:18  Similar incident found
08:01:21  Hypothesis ranked: bad DATABASE_URL
08:01:23  Remediation selected: restore env var
08:01:25  Guardrail approved low-risk action
08:01:30  Service restarted
08:01:35  Verification passed
08:01:36  Incident memory stored
```

## Project Phases

This project should be developed as a serious systems project, not a short-lived demo. Each phase should leave behind something concrete: working code, documentation, tests, evaluation results, and a story that can be explained on a resume or in an interview.

### Phase 1: System Foundation

Build the basic control plane and local runtime.

Goals:

- Create the monorepo structure.
- Implement the FastAPI control service.
- Add Postgres with migrations.
- Create the intentionally breakable target app.
- Run the target app and dependencies through Docker Compose.
- Add basic health checks and service metadata.

Key outputs:

- `services/control-api`
- `target-app`
- `infra/docker-compose.yml`
- Basic `/health`, `/sandboxes`, and `/incidents` APIs

### Phase 2: Failure Modeling

Create realistic, reproducible software failures.

Goals:

- Implement controlled failure injection.
- Model failures as structured scenario objects.
- Capture recent-change metadata for each failure.
- Make every failure reproducible and resettable.

Initial scenarios:

- Broken database connection string.
- Missing environment variable.
- Bad feature flag.
- Schema mismatch after deploy.
- API dependency outage.
- Port conflict.
- Crash loop.
- Rate-limit induced failure.

Key output:

```json
{
  "scenario": "bad_database_url",
  "description": "DATABASE_URL points to an unreachable host.",
  "expected_symptoms": [
    "healthcheck fails",
    "database-backed endpoints return 500",
    "logs contain connection refused"
  ],
  "likely_root_cause": "bad database connection string",
  "safe_remediations": [
    "SET_ENV_VAR",
    "RESTART_SERVICE"
  ]
}
```

### Phase 3: Incident System And Timeline

Turn failures into structured incidents.

Goals:

- Create incident lifecycle states.
- Store structured event logs.
- Add evidence, hypothesis, action, and verification records.
- Expose a replayable incident timeline through the API.
- Stream live events to the frontend.

Incident states:

```text
detected
investigating
hypothesizing
awaiting_approval
remediating
verifying
resolved
failed
blocked
```

This phase makes the project auditable. A user should be able to inspect exactly what the runtime saw, what it decided, what it did, and whether the action worked.

### Phase 4: Guarded Remediation Runtime

Build the safety layer that makes autonomous repair credible.

Goals:

- Implement the bounded action executor.
- Add allowlisted remediation actions.
- Add risk scoring.
- Add approval gates.
- Block unknown or dangerous actions.
- Log every requested, approved, rejected, blocked, and executed action.

The important architectural rule:

```text
Agent -> typed remediation request -> policy/guardrail check -> executor -> verification
```

The agent should never get direct shell access.

### Phase 5: Agentic Diagnosis

Build the reasoning system as a state machine.

Goals:

- Implement the LangGraph incident agent.
- Collect evidence from health checks, logs, config, service state, recent changes, and memory.
- Generate typed hypotheses.
- Rank root causes.
- Propose remediation candidates.
- Select an action based on confidence, risk, and policy.
- Verify recovery after execution.

The agent should produce structured outputs, not free-form chat responses. This is one of the most important parts of making the project feel professional.

### Phase 6: Incident Memory

Give the system long-term learning behavior.

Goals:

- Store resolved incident summaries.
- Embed incident symptoms, root causes, and outcomes.
- Retrieve similar incidents during diagnosis.
- Track which remediations succeeded or failed.
- Use memory to improve ranking and action selection.

Memory should not simply store logs. It should store compressed operational knowledge:

- What happened.
- How it presented.
- What evidence mattered.
- What fix worked.
- What verification proved recovery.
- What should be avoided next time.

### Phase 7: Observability Dashboard

Build a serious operator-facing UI.

Goals:

- Show sandbox health.
- Show live incidents.
- Render timeline events.
- Display evidence and hypotheses.
- Show memory matches.
- Show action risk and approval state.
- Show verification checks.
- Support incident replay.

The dashboard should not be a chatbot interface. It should feel like a compact incident command center.

### Phase 8: MicroVM And Isolation Track

Move beyond Docker as the only sandbox story.

Goals:

- Define a runtime interface independent of Docker.
- Document Firecracker/MicroVM architecture.
- Prototype snapshot-based sandbox startup.
- Compare Docker vs MicroVM isolation tradeoffs.
- Add sandbox lifecycle events.

This phase is valuable because it turns the project from “agent demo” into a real systems architecture project.

### Phase 9: Policy And Safety Engine

Make remediation governance explicit.

Goals:

- Add a policy layer for action authorization.
- Support static rules first.
- Optionally add OPA/Rego later.
- Add risk classes for actions.
- Require approval for schema migrations, rollbacks, and dependency switching.
- Block destructive, unknown, or irreversible actions.

Example policy:

```json
{
  "action_type": "RUN_DB_MIGRATION",
  "default_decision": "requires_approval",
  "max_auto_risk_score": 0.3,
  "required_evidence": [
    "schema_error_in_logs",
    "known_migration_available"
  ]
}
```

### Phase 10: Evaluation Framework

Prove the system works with repeatable experiments.

Goals:

- Create a scenario test harness.
- Run each failure scenario multiple times.
- Measure detection time.
- Measure diagnosis accuracy.
- Measure successful recovery rate.
- Measure unsafe action block rate.
- Compare performance with and without memory.

Suggested metrics:

```text
mean_time_to_detect
mean_time_to_diagnose
mean_time_to_recover
root_cause_accuracy
first_action_success_rate
unsafe_action_block_rate
memory_retrieval_hit_rate
```

This phase makes the project much stronger for resumes because it shows engineering rigor, not just a flashy demo.

### Phase 11: Production Hardening

Turn the system into something that looks and behaves like a real platform.

Goals:

- Add authentication for dashboard/API access.
- Add background workers for monitoring loops.
- Add task queue support.
- Add database migrations.
- Add integration tests.
- Add structured logging.
- Add OpenTelemetry-compatible spans/events.
- Add CI checks.
- Add deployment documentation.

This phase makes the project feel complete and maintainable.

### Phase 12: Public Portfolio Package

Prepare the project for resume, GitHub, and interviews.

Goals:

- Write a strong README.
- Add architecture diagrams.
- Add a short demo video.
- Add a technical blog post.
- Add evaluation results.
- Add screenshots.
- Add design tradeoff notes.
- Add “what I would build next” documentation.

The final portfolio story should be:

```text
I built a self-healing runtime that combines sandboxed execution,
agentic diagnosis, bounded remediation, incident memory, and
observability to recover intentionally broken services.
```

## Recommended First Demo Scenario

Use the broken `DATABASE_URL` scenario first.

Why this scenario works well:

- It is easy for viewers to understand.
- The failure is realistic.
- Evidence is clear in logs and config.
- The remediation is safe and bounded.
- Verification is straightforward.
- Re-running the failure can demonstrate memory improving response.

Demo flow:

1. Show healthy app.
2. Trigger `bad_db_url`.
3. Watch the health indicator fail.
4. Show the agent collecting logs, config, and memory.
5. Show the top hypothesis: broken database connection string.
6. Show selected remediation: restore known-good `DATABASE_URL` and restart service.
7. Show guardrail approval because the action is low risk.
8. Show verification passing.
9. Show incident memory stored.
10. Trigger the same issue again and show faster diagnosis using memory.

## Advanced Extensions

- Firecracker or MicroVM runtime backend.
- Snapshot and restore sandbox states.
- Multi-agent architecture with monitor, diagnostician, safety officer, and executor roles.
- Open Policy Agent guardrails.
- Git deploy metadata integration.
- GitHub pull request or commit correlation.
- OpenTelemetry export.
- Incident replay simulator.
- Post-incident report generation.
- Human approval UI for medium-risk actions.
- Automatic chaos scheduler for periodic failure injection.

## Success Criteria

The project succeeds if a viewer can watch the system:

1. Detect a real failure.
2. Explain the likely cause with structured evidence.
3. Choose a safe bounded remediation.
4. Apply the fix without arbitrary shell access.
5. Verify recovery.
6. Remember the incident for future diagnosis.

That end-to-end loop is the core product.
