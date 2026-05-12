# Bad Feature Flag Operator Runbook

This runbook explains how to run the full bad feature flag recovery flow from a clean workstation. It is intended for operators, reviewers, and engineers who want to see the complete self-healing lifecycle working end to end.

The flow exercises:

```text
runtime startup
-> failure injection
-> incident detection
-> LLM-backed diagnosis
-> bounded mitigation
-> recovery verification
-> durable repair planning
-> diff preview and approval
-> CI/CD verification
-> canary rollout
-> incident memory write and retrieval
-> rollback of local generated files
```

The system uses only public Control API endpoints during the run. The agent does not execute arbitrary shell commands against the target runtime.

## Requirements

Install these locally:

- Docker Desktop, with Compose support.
- Python 3.12 or newer for the incident runner script.
- Node.js 20 or newer if you want to run the dashboard.
- A Claude API key for the full LLM-backed flow.

The project can be run without Claude by passing `--allow-deterministic`, but the strongest run should use Claude-backed incident reasoning and repair planning.

## Repository Setup

From the repository root:

```bash
cp .env.example .env
```

Edit `.env` and keep the local runtime defaults:

```env
POSTGRES_DB=self_healing
POSTGRES_USER=self_healing
POSTGRES_PASSWORD=self_healing
CONTROL_DATABASE_URL=postgresql://self_healing:self_healing@postgres:5432/self_healing

TARGET_POSTGRES_DB=target_app
TARGET_POSTGRES_USER=target_app
TARGET_POSTGRES_PASSWORD=target_app
TARGET_DATABASE_URL=postgresql://target_app:target_app@target-db:5432/target_app
TARGET_REQUIRED_SECRET=runtime-foundation-secret

MONITOR_INTERVAL_SECONDS=10
TARGET_API_BASE_URL=http://target-api:8001

REPAIR_APPROVED_PATHS=target-app/api/tests/,target-app/api/main.py,target-app/api/requirements.txt,infra/docker-compose.yml
REPAIR_PATH_OWNERS=target-app/api/main.py:target-api,target-app/api/tests/:target-api-tests,target-app/api/requirements.txt:target-api,infra/docker-compose.yml:platform-runtime

AUTH_ENABLED=false
LOG_LEVEL=INFO
```

Enable Claude-backed reasoning:

```env
LLM_REASONING_ENABLED=true
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-sonnet-4-5
ANTHROPIC_API_URL=https://api.anthropic.com/v1/messages
ANTHROPIC_TIMEOUT_SECONDS=30
```

Do not commit `.env`.

## Start The Runtime

Build and start the runtime:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Confirm all services are running:

```bash
docker compose -f infra/docker-compose.yml ps
```

Expected services:

- `postgres`
- `target-db`
- `target-api`
- `control-api`
- `control-worker`

Check the Control API:

```bash
curl -fsS http://localhost:8000/health
```

Expected result:

- top-level `status` is `healthy`
- `checks.database.ok` is `true`
- target service status is `healthy`
- `checks.reasoning.llm_enabled` is `true`
- `checks.reasoning.anthropic_key_configured` is `true`

If `llm_enabled` is `false`, confirm `.env` was edited and rebuild `control-api` and `control-worker`.

## Start The Dashboard

The incident flow can run without the dashboard, but the dashboard makes the system easier to inspect.

In a second terminal:

```bash
cd apps/dashboard
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

Keep this page open while the incident runner executes. You should see incident state, evidence, hypotheses, mitigation actions, repair plans, verification checks, rollout decisions, and memory matches update as records are created.

## Run The Incident Flow

From the repository root:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py
```

The script performs the full lifecycle:

1. Waits for the Control API to become healthy.
2. Confirms Claude-backed reasoning is configured.
3. Resets any active target app scenarios.
4. Injects the `bad_feature_flag` failure through the evaluation harness.
5. Lets the incident agent collect evidence and diagnose the incident.
6. Applies the selected bounded mitigation, `DISABLE_FEATURE_FLAG`.
7. Verifies runtime recovery.
8. Asks the durable repair agent to generate a bounded patch.
9. Shows the patch diff and path ownership metadata.
10. Approves and applies the repair through the repair interface.
11. Runs verification gates.
12. Releases the repair through the synthetic canary gate.
13. Confirms incident memory was written and is searchable.
14. Rolls back generated local files so the run is repeatable.

## Successful Output

A successful run should include values like:

```text
control_api: healthy
llm_enabled: True
anthropic_key_configured: True
reasoning_provider: claude
diagnosed_root_cause: Bad feature flag enabled a broken code path
selected_action: DISABLE_FEATURE_FLAG
first_action_success: True
incident_status: resolved
repair_status: awaiting_approval
repair_planning_provider: claude
change_type: code_patch
requires_approval: True
verification_status: passed
rollout_status: promoted
decision: promote
memory_matches: 1
rollback_status: rolled_back
```

The exact IDs, timings, and similarity scores will vary.

## Dashboard Checkpoints

During or after the run, inspect these views:

- **Sandbox health:** the target app starts healthy, degrades during `bad_feature_flag`, then returns to healthy.
- **Incident state:** the incident moves through investigation, mitigation selection, verification, repair, rollout, and resolution.
- **Evidence:** scenario metadata, health checks, endpoint probes, and service metadata are captured as structured evidence.
- **Hypotheses:** Claude produces typed root-cause hypotheses with confidence and concise rationale summaries.
- **Actions:** the selected mitigation is an allowlisted runtime action, not a shell command.
- **Policy:** risky code repair requires approval, while low-risk gates can proceed autonomously when policy allows.
- **Repair plan:** the patch touches only approved paths and includes a diff preview.
- **CI/CD checks:** unit tests, static compile, security/static checks, integration health, and sandbox replay pass before rollout.
- **Canary rollout:** the candidate release is probed and promoted only after health signals pass.
- **Memory:** the resolved incident is stored and retrieved as a similar memory.

## Useful Inspection Commands

List incidents:

```bash
curl -fsS http://localhost:8000/incidents
```

Stream recent runtime events:

```bash
curl -fsS http://localhost:8000/events/stream?limit=20
```

Search incident memory:

```bash
curl -fsS "http://localhost:8000/memory/search?query=bad%20feature%20flag&limit=3"
```

List release records:

```bash
curl -fsS http://localhost:8000/releases
```

View container logs:

```bash
docker compose -f infra/docker-compose.yml logs -f control-api control-worker target-api
```

## Offline Development Mode

If you do not have a Claude key available, run:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --allow-deterministic
```

This still validates the runtime, bounded mitigation, verification gates, canary gate, and memory loop. It should not be used as the primary public run because it does not demonstrate LLM-backed reasoning.

## Leaving The Patch Applied

By default, the runner rolls back generated local file changes at the end. To inspect the generated repair in the working tree:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --keep-patch
```

After inspection, use the repair rollback endpoint printed by the run, or restore the affected files intentionally.

## Resetting The Runtime

Reset active target scenarios:

```bash
curl -fsS -X POST http://localhost:8000/sandboxes/local-docker/scenarios/reset
```

Rebuild only the control services after changing `.env` or control API code:

```bash
docker compose -f infra/docker-compose.yml up -d --build control-api control-worker
```

Rebuild the full runtime:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Stop the runtime:

```bash
docker compose -f infra/docker-compose.yml down
```

Stop the runtime and remove local volumes:

```bash
docker compose -f infra/docker-compose.yml down -v
```

Use `down -v` only when you intentionally want to delete local Postgres state and incident history.

## Troubleshooting

### `Claude-backed reasoning is not configured`

Confirm:

- `.env` contains `LLM_REASONING_ENABLED=true`.
- `.env` contains a non-empty `ANTHROPIC_API_KEY`.
- `control-api` and `control-worker` were rebuilt after editing `.env`.

Then run:

```bash
docker compose -f infra/docker-compose.yml up -d --build control-api control-worker
curl -fsS http://localhost:8000/health
```

### Target App Is Unhealthy Before The Run

Reset scenarios:

```bash
curl -fsS -X POST http://localhost:8000/sandboxes/local-docker/scenarios/reset
```

Then check:

```bash
curl -fsS http://localhost:8001/health
curl -fsS http://localhost:8000/health
```

### Verification Fails

Common causes:

- generated patch was already applied from a previous run,
- target app tests were manually edited,
- Docker services are using stale images,
- local dependency state differs from the container state.

Recommended recovery:

```bash
docker compose -f infra/docker-compose.yml up -d --build
python3 scripts/incidents/bad_feature_flag_recovery.py
```

### CI Target App Test Fails With `DATABASE_URL is not configured`

The target app reads `DATABASE_URL` at import time. CI should provide:

```env
DATABASE_URL=postgresql://ci:ci@unused:5432/ci
TARGET_REQUIRED_SECRET=ci-secret
```

The regression test also sets and restores these values to keep the test hermetic.

### Event Stream Closes Early

Rebuild the control API to pick up the latest stream serialization code:

```bash
docker compose -f infra/docker-compose.yml up -d --build control-api control-worker
curl -fsS http://localhost:8000/events/stream?limit=5
```

## Success Criteria

The run is successful when:

- the initial target service is healthy,
- the `bad_feature_flag` incident is detected,
- Claude-backed reasoning produces typed hypotheses,
- the selected mitigation is bounded and allowlisted,
- recovery verification passes,
- a durable patch is generated with a readable diff,
- risky code change approval is enforced,
- CI/CD gates pass,
- canary rollout promotes,
- incident memory is written and retrievable,
- the generated local patch is rolled back unless `--keep-patch` was used.
