# Bad Feature Flag Recovery

This walkthrough exercises the full self-healing loop for a feature-gated checkout failure:

```text
inject bad_feature_flag
-> detect degraded checkout behavior
-> diagnose with Claude-backed incident reasoning
-> select bounded mitigation
-> verify runtime recovery
-> generate durable patch with Claude-backed repair planning
-> preview diff and path owners
-> approve and apply patch
-> run verification gates
-> release through synthetic canary
-> store and retrieve incident memory
-> roll back local files for repeatability
```

The flow is intentionally incident-specific. It avoids arbitrary shell access and uses only Control API endpoints.

## Prerequisites

1. Configure Claude-backed reasoning in `.env`:

```env
LLM_REASONING_ENABLED=true
ANTHROPIC_API_KEY=your-anthropic-key
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

2. Start the runtime:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

3. Optional: start the dashboard in another terminal:

```bash
cd apps/dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

## Run the Walkthrough

From the repository root:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py
```

To build/start the stack as part of the run:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --start-stack
```

By default, the script rolls back the generated local patch at the end so the walkthrough can be run repeatedly. To leave the patch applied for inspection:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --keep-patch
```

For offline development only, deterministic fallback can be allowed:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --allow-deterministic
```

The full walkthrough should use Claude-backed reasoning and should not pass `--allow-deterministic`.

## Expected Output

The run should report:

- `llm_enabled: True`
- `reasoning_provider: claude`
- `selected_action: DISABLE_FEATURE_FLAG`
- `repair_planning_provider: claude`
- `change_type: code_patch`
- `requires_approval: True`
- a diff touching only approved target-app paths
- successful verification gates
- canary decision `promote`
- at least one searchable memory match

## What To Watch In The Dashboard

During the run, the dashboard should show:

- the `bad_feature_flag` incident in the incident list
- evidence from scenario/degraded checkout probes
- Claude-generated reasoning summary and hypotheses
- bounded remediation action with policy metadata
- durable repair record with path owners and diff preview
- CI verification result
- canary rollout signals
- memory match after the incident is stored

## Safety Boundaries Exercised

This incident uses the same safety boundaries as normal operation:

- Runtime recovery uses a bounded action, not shell access.
- Generated patches are restricted to approved repository paths.
- Every touched path must have an owner rule.
- Risky code patches require approval before application.
- Verification gates must pass before canary rollout.
- Canary promotion is based on health probes.
- The local patch is rolled back by default so repeated runs start from the same source state.

## Troubleshooting

If the script exits with `Claude-backed reasoning is not configured`, confirm the environment variables are present in `.env`, then rebuild the control services:

```bash
docker compose -f infra/docker-compose.yml up -d --build control-api control-worker
```

If verification fails, inspect the returned check list. The most common causes are:

- the local patch was already applied from a previous run
- the target app tests were edited manually
- Docker services are running stale images

Reset the local patch by running the rollback endpoint for the repair shown in the script output, or restore the changed files manually if the process was interrupted before rollback.
