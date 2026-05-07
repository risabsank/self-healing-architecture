# Self-Healing Runtime

## Reasoning + Memory for Live Software Failures

Self-Healing Runtime is a professional-grade autonomous incident response and software repair platform for live software systems. It monitors running applications inside isolated sandboxes, detects failures, gathers evidence, reasons about likely root causes, retrieves similar past incidents from memory, applies safe bounded mitigations, verifies recovery, and can generate validated code changes that make the system more resilient over time.

Self-Healing Runtime is not a generic chatbot and it is not a collection of static alerting playbooks. The system is designed around long-running agents that behave like careful production incident responders.

## One-Liner

An autonomous runtime that watches live sandboxed apps, diagnoses failures with structured evidence, safely mitigates incidents, validates code-level repairs through CI/CD, rolls them out through canaries, and remembers what worked.

## System Capabilities

The system is designed to be easy to understand while still reflecting production-grade architecture:

1. A small target web service starts healthy.
2. A realistic failure is injected, such as a broken database connection string.
3. The runtime detects the failure through health checks, logs, and service state.
4. An incident session starts automatically.
5. The agent collects evidence and retrieves similar past incidents.
6. The agent generates typed hypotheses and ranks likely root causes.
7. The agent selects a safe mitigation action from an allowlisted interface.
8. The mitigation is applied inside the sandbox to restore service quickly.
9. The runtime verifies recovery with health checks, endpoint checks, dependency probes, and scenario-specific validation.
10. When the failure indicates a durable defect, a repair agent proposes a code or configuration change.
11. The change is validated through tests, static checks, and sandbox verification.
12. A canary deployment receives limited traffic while health and regression signals are monitored.
13. The runtime promotes, rolls back, or quarantines the change based on verification results.
14. The incident summary, evidence, action, code change, rollout result, and outcome are stored in memory.
15. The dashboard displays a replayable incident and release timeline.

The core moment: the service breaks live, the runtime investigates like an incident responder, restores service with a constrained mitigation, proposes a durable fix, validates it through a deployment pipeline, canaries it safely, and leaves behind a complete audit trail.

## Design Principles

- The agent must not blindly run shell commands.
- Every runtime mitigation must go through a bounded action interface.
- Every code change must go through a bounded patch-generation, test, review, and rollout interface.
- Dangerous actions must require human approval or be blocked.
- Autonomous decisions are allowed only when the system has sufficient evidence, low operational risk, passing verification, and rollback coverage.
- The system should log structured reasoning summaries, not hidden chain-of-thought.
- Agent outputs should be typed objects: hypotheses, evidence, mitigation candidates, patch plans, risk scores, verification results, and rollout decisions.
- Incident memory should improve future responses.
- Successful repairs should become regression tests, policy signals, and reusable operational memory.
- The target app should fail in realistic ways.
- The system should evolve from a clear local runtime into a hardened production-style platform.

## Novel Technical Contributions

Self-Healing Runtime is more than “LLM watches logs and restarts services.” The novel part is the combination of agentic reasoning, constrained execution, memory, isolation, and observability.

Key technical contributions:

- **Typed incident reasoning:** the agent emits structured evidence, hypotheses, risk scores, mitigation candidates, patch plans, rollout decisions, and verification results instead of chat messages.
- **Bounded autonomous repair:** the system can act, but only through safe runtime, patch, CI/CD, and rollout interfaces with explicit policy checks.
- **Self-improvement loop:** incidents can produce durable code, configuration, or test changes that are validated before release.
- **Canary-first deployment:** generated changes are released to an isolated canary target and promoted only after automated health and regression checks pass.
- **Incident memory loop:** every resolved incident becomes retrievable operational knowledge for future diagnosis.
- **Sandboxed failure environments:** failures happen in live isolated runtimes, not static examples.
- **Replayable operational traces:** every step of detection, reasoning, mitigation, patch generation, CI validation, rollout, and verification is stored as a timeline.
- **Evaluation harness:** the system can be tested against repeatable failure scenarios and measured with recovery metrics.
- **Runtime abstraction:** Docker is the first backend, but the architecture can evolve toward Firecracker/MicroVM isolation.

## Preferred Technology Stack

- Backend: Python FastAPI
- Agent orchestration: LangGraph or an equivalent state-machine agent framework
- LLM provider: Claude API
- Database: Postgres
- Vector memory: pgvector or Chroma
- Sandbox: Docker for the first runtime backend, with Firecracker/MicroVM support as a major architecture track
- Frontend: lightweight operator dashboard, with a path to Next.js + TypeScript as the interface grows
- Observability: OpenTelemetry-style structured event logs and dashboard timelines
- Target app: intentionally breakable web service with API and database dependency

## System Architecture

```text
┌──────────────────────────┐
│ Operator Dashboard       │
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
       │          ├────────────────┐
       │          │                │
       │          ▼                ▼
┌──────▼──────────┐       ┌───────────────┐
│ Repair Agent    │       │ Vector Memory │
│ patch planning  │       │ pgvector      │
└──────┬──────────┘       └───────────────┘
       │
┌──────▼──────────┐
│ CI/CD Verifier  │
│ tests + scans   │
└──────┬──────────┘
       │
┌──────▼──────────┐
│ Canary Rollout  │
│ promote/rollback│
└──────┬──────────┘
       │
┌──────▼──────────┐       ┌────────▼─────────┐
│ Postgres        │       │ Policy Engine    │
│ events/releases │       │ approvals/risk   │
└──────┬──────────┘       └──────────────────┘
       │
┌──────▼──────────┐
│ Sandbox Runtime │
│ Docker first    │
└──────┬──────────┘
       │ bounded runtime actions only
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
8. Select a safe runtime mitigation.
9. Apply the mitigation inside the sandbox through the controlled executor.
10. Verify service recovery with health checks, endpoint checks, dependency checks, and scenario-specific validation.
11. Decide whether the failure requires a durable repair.
12. Generate a bounded code, test, or configuration patch.
13. Run CI checks, regression tests, static analysis, and sandbox verification.
14. Deploy the change to a canary target.
15. Promote, roll back, or quarantine the change based on rollout signals.
16. Store incident summary, evidence, mitigation, patch, rollout, and outcome in memory.
17. Show the full incident and release timeline in the UI.

## Repository Structure

```text
self-healing-architecture/
  apps/
    dashboard/
      index.html
      app.js
      styles.css
      server.mjs

  services/
    control-api/
      app/
        main.py
        api/
          routes/
            health.py
            incidents.py
            observability.py
            sandboxes.py
            scenarios.py
            actions.py
            memory.py
        agents/
          graph.py
          state.py
        core/
          config.py
          db.py
        models/
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

  infra/
    docker-compose.yml
    postgres/
      init.sql

  docs/
    architecture.md
    guarded-runtime-mitigation.md
    incident-agent.md
    walkthrough.md
    system-foundation.md
```

## Local Development

The local runtime can be started with Docker Compose:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Main services:

```text
Dashboard    http://localhost:3000
Control API  http://localhost:8000
Target API   http://localhost:8001
Postgres     localhost:5432
Target DB    localhost:5433
```

Start the operator dashboard in a separate terminal:

```bash
cd apps/dashboard
npm run dev
```

Useful checks:

```text
GET  http://localhost:3000
GET  http://localhost:8000/health
GET  http://localhost:8000/sandboxes/local-docker
POST http://localhost:8000/sandboxes/local-docker/health-check
GET  http://localhost:8001/health
GET  http://localhost:8001/items
```

See `docs/system-foundation.md` for the local foundation runbook.

## Core Services

### Control API

The FastAPI control service owns the incident lifecycle. It exposes APIs for sandboxes, incidents, timelines, memory, mitigation approval, and release approval.

Example routes:

```text
GET    /health
POST   /sandboxes
GET    /sandboxes/{sandbox_id}
GET    /sandboxes/{sandbox_id}/health-history
GET    /sandboxes/{sandbox_id}/timeline
GET    /sandboxes/{sandbox_id}/scenarios
POST   /sandboxes/{sandbox_id}/scenarios/{scenario_name}/activate
POST   /sandboxes/{sandbox_id}/scenarios/{scenario_name}/deactivate
POST   /sandboxes/{sandbox_id}/scenarios/reset

GET    /incidents
POST   /incidents
GET    /incidents/{incident_id}
POST   /incidents/{incident_id}/analyze
GET    /incidents/{incident_id}/timeline
GET    /incidents/{incident_id}/evidence
GET    /incidents/{incident_id}/hypotheses
GET    /incidents/{incident_id}/actions

GET    /actions/allowed
POST   /actions/{action_id}/approve
POST   /actions/{action_id}/reject
POST   /actions/{action_id}/execute
POST   /incidents/{incident_id}/actions/execute-selected

GET    /incidents/{incident_id}/repairs
POST   /incidents/{incident_id}/repairs/plan
GET    /repairs/{repair_id}
POST   /repairs/{repair_id}/approve
POST   /repairs/{repair_id}/reject
POST   /repairs/{repair_id}/apply
GET    /repairs/{repair_id}/verification-runs
POST   /repairs/{repair_id}/verify

GET    /releases
GET    /releases/{release_id}
GET    /releases/{release_id}/checks
POST   /releases/{release_id}/approve
POST   /releases/{release_id}/rollback

GET    /memory/incidents
GET    /memory/search?query=database

GET    /events
GET    /events/stream
```

### Incident Agent

The incident agent is a state machine, not an open-ended chatbot. The current implementation uses deterministic rules over typed evidence; the same interface can later be backed by LangGraph and an LLM provider. It moves through explicit states:

```text
detect_failure
  -> start_incident
  -> collect_evidence
  -> retrieve_memory
  -> generate_hypotheses
  -> rank_root_causes
  -> propose_mitigations
  -> guardrail_check
  -> apply_action OR require_approval OR block
  -> verify_recovery
  -> decide_durable_repair
  -> plan_patch OR skip_patch
  -> generate_patch
  -> run_ci_verification
  -> deploy_canary
  -> promote OR rollback OR quarantine
  -> store_memory
  -> close_incident
```

### Repair Agent

The repair agent handles durable improvements after immediate service recovery. It does not freely edit arbitrary files. It receives a bounded repair request with an incident summary, evidence, affected component, allowed write paths, test commands, rollback strategy, and deployment policy.

Repair requests should produce typed objects:

```json
{
  "repair_type": "code_patch",
  "affected_component": "target-api",
  "allowed_paths": [
    "target-app/api/main.py",
    "target-app/api/tests/"
  ],
  "patch_summary": "Add defensive database connection handling and regression coverage for unavailable database hosts.",
  "risk_score": 0.34,
  "requires_approval": false,
  "verification_plan": [
    "unit tests",
    "integration health check",
    "sandbox replay of bad_database_url"
  ],
  "rollback_plan": "Restore previous image and route traffic away from canary."
}
```

The repair agent can propose and apply patches only through the code repair interface. The CI/CD verifier decides whether a generated change is eligible for canary rollout.

### Sandbox Runtime

The initial runtime uses Docker. Each target app runs inside a controlled environment with its own service containers, configuration, logs, and failure injection hooks.

The architecture should leave room for a future Firecracker or MicroVM backend:

- Docker runtime for local development and fast iteration.
- Runtime interface that can later support MicroVM creation, snapshotting, and teardown.
- Same bounded runtime mitigation API regardless of sandbox implementation.

### Bounded Mitigation Executor

The agent never receives raw shell access. It can only request typed runtime mitigation operations from an allowlist.

Example allowed actions:

```python
from enum import Enum

class AllowedAction(str, Enum):
    SET_ENV_VAR = "SET_ENV_VAR"
    RESTART_SERVICE = "RESTART_SERVICE"
    ROLLBACK_CONFIG = "ROLLBACK_CONFIG"
    DISABLE_FEATURE_FLAG = "DISABLE_FEATURE_FLAG"
    SWITCH_DEPENDENCY_TO_MOCK = "SWITCH_DEPENDENCY_TO_MOCK"
```

The current executor intentionally excludes arbitrary shell commands, unbounded filesystem writes, database mutations, and free-form Docker operations. Each action is validated against required parameters, risk score, approval policy, and a target-specific runtime adapter.

Code and release operations are separate from runtime mitigation actions:

```python
class AllowedRepairAction(str, Enum):
    CREATE_PATCH_BRANCH = "create_patch_branch"
    APPLY_BOUNDED_PATCH = "apply_bounded_patch"
    ADD_REGRESSION_TEST = "add_regression_test"
    RUN_TEST_SUITE = "run_test_suite"
    BUILD_ARTIFACT = "build_artifact"
    DEPLOY_CANARY = "deploy_canary"
    PROMOTE_CANARY = "promote_canary"
    ROLLBACK_CANARY = "rollback_canary"
```

Repair actions are constrained by repository path allowlists, test requirements, policy decisions, and rollback plans. A runtime incident may be mitigated autonomously while a durable code repair continues through the validation and canary path.

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

Approval-gated action example:

```json
{
  "action_type": "ROLLBACK_CONFIG",
  "params": {
    "service": "target-api",
    "target": "previous_known_good_app_version"
  },
  "risk_score": 0.42,
  "requires_approval": true,
  "status": "selected"
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

Runtime mitigation execution is replayable through incident events:

```text
agent.mitigation_selected
mitigation.executing
mitigation.awaiting_approval
healthcheck.recorded
verification.started
verification.completed
mitigation.executed
incident.resolved
```

Recovery verification includes:

- target health status,
- target metadata reachability,
- active failure scenario clearance,
- database-backed endpoint checks,
- dependency endpoint checks,
- action-specific assertions such as database connectivity after `DATABASE_URL` restoration or schema compatibility after rollback.

See `docs/guarded-runtime-mitigation.md` for the executor contract and operator workflow.

## Self-Improvement Workflow

The runtime separates immediate recovery from durable improvement.

Immediate recovery focuses on reducing downtime:

```text
detect incident
-> collect evidence
-> apply low-risk mitigation
-> verify service recovery
```

Durable improvement focuses on making the system stronger:

```text
classify durable defect
-> create bounded repair plan
-> generate code/config/test patch
-> run CI/CD verification
-> deploy to canary
-> monitor canary health
-> promote, roll back, or quarantine
-> store repair memory
```

The system should prefer reversible runtime mitigations first. Code changes are generated only when the incident evidence suggests a durable defect, missing guardrail, missing regression test, or configuration weakness.

## CI/CD Verification

Generated changes must pass an automated verification pipeline before they can receive canary traffic.

Recommended checks:

- Unit tests for the modified component.
- Integration tests against dependent services.
- Regression test that reproduces the original incident.
- Static analysis and formatting checks.
- Dependency and security checks.
- Sandbox replay of the failure scenario.
- Health checks against the patched service.
- Rollback plan validation.

Verification output should be structured:

```json
{
  "repair_change_id": "change-123",
  "status": "passed",
  "checks": [
    {
      "name": "unit_tests",
      "status": "passed",
      "duration_ms": 1840
    },
    {
      "name": "sandbox_replay_bad_database_url",
      "status": "passed",
      "duration_ms": 9100
    },
    {
      "name": "rollback_plan",
      "status": "passed",
      "duration_ms": 650
    }
  ]
}
```

## Canary Rollout

The canary system releases generated changes gradually. A change should never be promoted only because tests passed. It must also prove itself under live health signals.

Canary policy:

- Deploy patched artifact to a canary sandbox or canary service instance.
- Route a small percentage of traffic or synthetic probes to the canary.
- Compare canary health against baseline health.
- Monitor error rate, latency, crash loops, dependency failures, and regression checks.
- Promote only if all required health windows pass.
- Roll back automatically if guardrail thresholds are breached.
- Quarantine the change if the signal is inconclusive.

Example rollout decision:

```json
{
  "release_id": "release-123",
  "status": "promoted",
  "traffic_percentage": 10,
  "decision": "promote",
  "health_signals": {
    "error_rate": 0.0,
    "p95_latency_ms": 42,
    "healthcheck_success_rate": 1.0,
    "regression_failures": 0
  }
}
```

## Autonomy Model

The system should make many operational decisions autonomously, but autonomy must be scoped by policy, evidence, and reversibility.

Autonomous by default:

- Collecting logs, metrics, health checks, config snapshots, and recent-change metadata.
- Creating incident records and timeline events.
- Retrieving similar incidents from memory.
- Generating hypotheses and ranking root causes.
- Applying low-risk reversible mitigations.
- Creating low-risk patch plans within approved paths.
- Running tests, sandbox replay, and static checks.
- Rolling back a failing canary.

Approval-gated:

- Database migrations.
- Dependency upgrades.
- Security-sensitive code paths.
- Irreversible data changes.
- Broad refactors.
- Changes without a reliable rollback plan.
- Canary promotion when health signals are incomplete.

Blocked:

- Arbitrary shell execution.
- Unbounded filesystem writes.
- Secret exfiltration.
- Destructive data operations without explicit policy.
- Promotion after failed verification.

Autonomous decisions should be recorded as structured policy decisions:

```json
{
  "decision": "allow_autonomous_canary",
  "risk_score": 0.28,
  "evidence": [
    "patch limited to approved paths",
    "regression test reproduces incident",
    "CI verification passed",
    "rollback plan available"
  ],
  "blocked_reasons": []
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

CREATE TABLE repair_changes (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  status TEXT NOT NULL,
  change_type TEXT NOT NULL,
  branch_name TEXT,
  commit_sha TEXT,
  affected_paths TEXT[] NOT NULL,
  patch_summary TEXT NOT NULL,
  risk_score FLOAT NOT NULL,
  requires_approval BOOLEAN NOT NULL,
  verification_plan JSONB NOT NULL,
  rollback_plan TEXT NOT NULL,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE verification_runs (
  id UUID PRIMARY KEY,
  repair_change_id UUID REFERENCES repair_changes(id),
  status TEXT NOT NULL,
  runner TEXT NOT NULL,
  checks JSONB NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  logs_ref TEXT
);

CREATE TABLE canary_rollouts (
  id UUID PRIMARY KEY,
  repair_change_id UUID REFERENCES repair_changes(id),
  status TEXT NOT NULL,
  target_environment TEXT NOT NULL,
  traffic_percentage FLOAT NOT NULL,
  health_signals JSONB NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  decision TEXT
);

CREATE TABLE incident_memories (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  summary TEXT NOT NULL,
  root_cause TEXT,
  successful_action JSONB,
  failed_actions JSONB,
  repair_change JSONB,
  rollout_result JSONB,
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

class RepairPlan(BaseModel):
    repair_type: Literal["code_patch", "config_patch", "test_only", "no_durable_change"]
    affected_component: str
    allowed_paths: list[str]
    patch_summary: str
    risk_score: float
    requires_approval: bool
    verification_plan: list[str]
    rollback_plan: str

class VerificationRun(BaseModel):
    status: Literal["pending", "running", "passed", "failed", "blocked"]
    checks: list[dict]
    logs_ref: str | None = None

class CanaryRollout(BaseModel):
    status: Literal["pending", "running", "promoted", "rolled_back", "quarantined"]
    traffic_percentage: float
    health_signals: list[dict]
    decision_summary: str | None = None

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
    repair_plan: RepairPlan | None
    ci_verification: VerificationRun | None
    canary_rollout: CanaryRollout | None
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
                "repair_plan": None,
                "ci_verification": None,
                "canary_rollout": None,
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

Example repair event:

```json
{
  "type": "repair.plan.created",
  "actor": "repair-agent",
  "payload": {
    "repair_type": "code_patch",
    "affected_component": "target-api",
    "patch_summary": "Add regression coverage and defensive handling for database connectivity failures.",
    "risk_score": 0.34,
    "verification_plan": [
      "unit tests",
      "integration tests",
      "sandbox replay",
      "canary health checks"
    ],
    "autonomy_decision": "eligible_for_autonomous_canary",
    "rationale_summary": "The change is limited to the target API, has a rollback path, and is covered by regression tests that reproduce the incident."
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

Likely runtime mitigation:

- Restore `DATABASE_URL` from known-good config.
- Restart the target API.
- Verify `/health` and a database-backed endpoint.

Potential durable improvement:

- Add clearer startup validation for database configuration.
- Add regression coverage for bad database hosts.
- Improve health-check error classification.

### 2. Bad Feature Flag

A feature flag enables a broken code path.

Symptoms:

- One endpoint starts returning `500`.
- Logs reference a feature-specific error.
- Recent change metadata shows a flag update.

Likely runtime mitigation:

- Disable the feature flag.
- Verify the affected endpoint.

Potential durable improvement:

- Add contract tests for the flagged path.
- Add feature-flag rollout checks before enabling by default.

### 3. Schema Mismatch After Deploy

The app expects a database column or table that does not exist.

Symptoms:

- SQL errors in logs.
- Health may be partially degraded.
- Recent deploy metadata indicates a new app version.

Likely runtime mitigation:

- Low risk: roll back the app version.
- Medium risk: run a known migration with human approval.

Potential durable improvement:

- Add migration compatibility checks to CI.
- Add deploy gate that verifies app/schema compatibility.

### 4. API Dependency Unavailable

An external dependency or mock service is down.

Symptoms:

- Timeouts or connection errors.
- Affected routes fail while core app health may remain healthy.

Likely runtime mitigation:

- Switch to fallback mock dependency.
- Restart or reconfigure the dependent service.

Potential durable improvement:

- Add circuit breaker behavior.
- Add dependency timeout and fallback tests.

### 5. Port Conflict

The app cannot bind to its expected port.

Symptoms:

- Process crash loop.
- Logs include address already in use.

Likely runtime mitigation:

- Restart conflicting service.
- Restore expected port config.

Potential durable improvement:

- Add preflight port checks.
- Add clearer startup diagnostics.

### 6. Memory Leak Or Crash Loop

The app repeatedly exits after memory usage climbs.

Symptoms:

- Container restarts.
- Increasing memory metrics.
- Repeated crash signatures in logs.

Likely runtime mitigation:

- Restart service as temporary recovery.
- Roll back recent deploy if crash began after deployment.

Potential durable improvement:

- Add leak reproduction tests or stress checks.
- Add memory budget alerting and rollback gates.

### 7. Rate Limit Induced Failure

The target app exceeds a dependency rate limit.

Symptoms:

- HTTP `429` from dependency.
- Retry storm in logs.

Likely runtime mitigation:

- Enable backoff flag.
- Switch to cached or mocked dependency.

Potential durable improvement:

- Add exponential backoff behavior.
- Add dependency rate-limit simulation to tests.

## Memory Design

Memory should answer: “Have we seen something like this before, what restored service, what durable repair worked, and what should be tested next time?”

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
  "evidence": [
    {
      "source": "healthcheck",
      "kind": "failed_check:database",
      "confidence": 0.88
    }
  ],
  "successful_action": {
    "type": "SET_ENV_VAR",
    "params": {
      "key": "DATABASE_URL",
      "value_source": "known_good_config"
    }
  },
  "repair_change": {
    "type": "code_patch",
    "summary": "Added database configuration validation and regression coverage for unreachable database hosts.",
    "verification": "ci_passed",
    "rollout": "canary_promoted"
  },
  "verification": {
    "recovered": true,
    "checks": [
      "GET /health returned 200",
      "GET /items returned 200",
      "bad_database_url regression test passed"
    ]
  }
}
```

When a later incident is analyzed, similar memories are retrieved from stored symptoms, evidence, and root cause text. Matching memories become structured evidence with `source: "memory"` and can influence fallback mitigation selection when the current incident does not match a known scenario.

Operational fact memory example:

```json
{
  "sandbox_id": "local-docker",
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
- Selected runtime mitigation
- Generated repair plan
- CI/CD verification results
- Canary rollout status
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
08:01:23  Runtime mitigation selected: restore env var
08:01:25  Guardrail approved low-risk action
08:01:30  Service restarted
08:01:35  Verification passed
08:01:36  Durable repair needed: yes
08:01:45  Patch generated with regression test
08:02:10  CI verification passed
08:02:35  Canary deployed at 10 percent
08:03:35  Canary promoted
08:03:36  Incident and repair memory stored
```

## Capability Roadmap

Self-Healing Runtime is organized as a set of platform capabilities. Each capability should be implemented with working code, documentation, tests, and observable behavior.

### System Foundation

Build the control plane and local runtime.

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

### Failure Modeling

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
  "safe_mitigations": [
    "SET_ENV_VAR",
    "RESTART_SERVICE"
  ]
}
```

### Incident System And Timeline

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

This capability makes the system auditable. A user should be able to inspect exactly what the runtime saw, what it decided, what it did, and whether the action worked.

### Guarded Mitigation Runtime

Build the safety layer that makes autonomous repair credible.

Goals:

- Implement the bounded action executor.
- Add allowlisted mitigation actions.
- Add risk scoring.
- Add approval gates.
- Block unknown or dangerous actions.
- Log every requested, approved, rejected, blocked, and executed action.

The important architectural rule:

```text
Agent -> typed mitigation request -> policy/guardrail check -> executor -> verification
```

The agent should never get direct shell access.

### Durable Code Repair

Generate bounded source, configuration, and regression-test changes when incident evidence indicates a durable defect.

Goals:

- Add a repair agent with path-scoped write permissions.
- Convert incident evidence into a structured repair plan.
- Generate patches only within approved repository paths.
- Add or update regression tests that reproduce the incident.
- Attach a rollback plan to every generated change.
- Record patch summaries, affected paths, risk scores, and verification results.

Autonomous patch generation should be allowed only for low-risk, well-scoped changes. Larger changes, migrations, dependency upgrades, and security-sensitive edits should require approval.

### CI/CD Verification

Validate generated changes before they can affect live traffic.

Goals:

- Run unit, integration, and regression tests.
- Replay the original failure scenario against the patched artifact.
- Run formatting, static analysis, and security checks.
- Build deployable artifacts.
- Store structured verification results.
- Block canary rollout when verification fails.

This capability gives the system a way to improve itself without relying on trust in the agent alone.

### Canary Release Management

Release generated changes gradually with automated rollback.

Goals:

- Deploy patched artifacts to canary environments.
- Route synthetic probes or limited traffic to canaries.
- Compare canary health against baseline health.
- Promote changes only after required health windows pass.
- Roll back automatically when error, latency, or availability thresholds are breached.
- Quarantine uncertain releases for review.

Canary rollout is the bridge between autonomous repair and operational safety.

### Agentic Diagnosis

Build the reasoning system as a state machine.

Goals:

- Implement the LangGraph incident agent.
- Collect evidence from health checks, logs, config, service state, recent changes, and memory.
- Generate typed hypotheses.
- Rank root causes.
- Propose mitigation candidates.
- Select an action based on confidence, risk, and policy.
- Verify recovery after execution.

The agent should produce structured outputs, not free-form chat responses. This is central to making the system credible and auditable.

### Incident Memory

Give the system long-term learning behavior.

Goals:

- Store resolved incident summaries.
- Embed incident symptoms, root causes, and outcomes.
- Retrieve similar incidents during diagnosis.
- Track which mitigations succeeded or failed.
- Use memory to improve ranking and action selection.

Memory should not simply store logs. It should store compressed operational knowledge:

- What happened.
- How it presented.
- What evidence mattered.
- What fix worked.
- What verification proved recovery.
- What should be avoided next time.

### Observability Dashboard

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

### MicroVM And Isolation Track

Move beyond Docker as the only sandbox story.

Goals:

- Define a runtime interface independent of Docker.
- Document Firecracker/MicroVM architecture.
- Prototype snapshot-based sandbox startup.
- Compare Docker vs MicroVM isolation tradeoffs.
- Add sandbox lifecycle events.

This capability moves the system beyond isolated agent behavior and into a stronger runtime architecture.

### Policy And Safety Engine

Make mitigation and repair governance explicit.

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

### Evaluation Framework

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

This capability shows engineering rigor by measuring behavior across repeatable failure conditions.

### Production Hardening

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

This capability makes the system more complete, maintainable, and suitable for real operational environments.

### Public Release Package

Prepare the repository for public review, evaluation, and external contribution.

Goals:

- Write a strong README.
- Add architecture diagrams.
- Add a short technical walkthrough.
- Add a technical blog post.
- Add evaluation results.
- Add screenshots.
- Add design tradeoff notes.
- Add future architecture notes.

The public positioning should be:

```text
Self-Healing Runtime combines sandboxed execution, agentic diagnosis,
bounded mitigation, durable repair, canary rollout, incident memory,
and observability to recover and improve intentionally broken services.
```

## Example Recovery Scenario

The broken `DATABASE_URL` scenario is a useful first end-to-end scenario.

Why this scenario works well:

- It is easy for viewers to understand.
- The failure is realistic.
- Evidence is clear in logs and config.
- The mitigation is safe and bounded.
- Verification can include health checks, database-backed endpoints, and regression tests.
- The durable improvement path can add configuration validation, clearer diagnostics, and test coverage.
- Re-running the failure can show memory-assisted diagnosis and stronger preventive behavior.

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

The system succeeds if an operator can watch it:

1. Detect a real failure.
2. Explain the likely cause with structured evidence.
3. Choose a safe bounded mitigation.
4. Apply the mitigation without arbitrary shell access.
5. Verify recovery.
6. Generate a durable repair when the failure indicates a code or configuration defect.
7. Validate the repair through CI/CD checks and sandbox replay.
8. Release the repair through canary rollout with automatic rollback.
9. Remember the incident, mitigation, repair, rollout, and outcome for future diagnosis.

That end-to-end loop is the core product.
