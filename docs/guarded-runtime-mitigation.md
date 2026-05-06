# Guarded Runtime Mitigation

The guarded runtime mitigation layer is the execution boundary between agent reasoning and the sandboxed target application.

The incident agent can propose and select a mitigation, but it cannot execute arbitrary commands, mutate files directly, or call Docker freely. Execution is handled by a bounded executor that accepts only typed, allowlisted actions.

## Execution Contract

```text
incident agent
-> selected remediation_action row
-> action policy validation
-> approval gate when required
-> target-specific runtime adapter
-> recovery verification suite
-> incident timeline events
```

## Allowed Actions

The current runtime supports these bounded actions:

```text
SET_ENV_VAR
RESTART_SERVICE
DISABLE_FEATURE_FLAG
SWITCH_DEPENDENCY_TO_MOCK
ROLLBACK_CONFIG
```

Each action has:

- required parameters,
- maximum autonomous risk,
- approval policy,
- target runtime adapter,
- structured execution result,
- timeline events.

## API Surface

```text
GET  /actions/allowed
POST /actions/{action_id}/approve
POST /actions/{action_id}/reject
POST /actions/{action_id}/execute
POST /incidents/{incident_id}/actions/execute-selected
```

The selected-action endpoint is intended for the autonomous recovery loop. Direct action execution is useful for operator tooling and tests.

## Autonomous Actions

Low-risk reversible actions can execute without approval when their risk score is below the action policy threshold.

Example:

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

For the local target app, this routes through `POST /runtime/config/restore` and clears the corresponding injected failure. The executor then runs the recovery verification suite and records the verification result.

## Approval-Gated Actions

Higher-risk actions are selected but blocked until an operator approves them.

Example:

```json
{
  "action_type": "ROLLBACK_CONFIG",
  "params": {
    "service": "target-api",
    "target": "previous_known_good_app_version"
  },
  "risk_score": 0.42,
  "requires_approval": true
}
```

Execution flow:

```text
POST /actions/{action_id}/execute
-> 409 Action requires approval before execution
POST /actions/{action_id}/approve
POST /actions/{action_id}/execute
```

## Blocked Actions

Unknown or unsafe actions are rejected by policy before reaching the sandbox runtime.

Examples of blocked behavior:

- arbitrary shell commands,
- unknown action types,
- unmanaged environment keys,
- unmanaged feature flags,
- unmanaged dependencies,
- rollback targets outside the allowlist,
- autonomous execution above the configured risk threshold.

## Timeline Events

Mitigation execution writes structured events to the incident timeline:

```text
mitigation.executing
mitigation.awaiting_approval
healthcheck.recorded
verification.started
verification.completed
verification.failed
mitigation.executed
mitigation.failed
mitigation.blocked
mitigation.approved
mitigation.rejected
```

Runtime-level events are also stored in `runtime_events` so the sandbox timeline can show both the action and the target response.

## Recovery Verification

The executor does not treat a runtime action as recovered just because the action request succeeded. After every mitigation, it runs a structured verification suite:

```text
health_check
metadata_check
scenario_clearance
database_backed_endpoint
dependency_probe
action-specific checks
```

Action-specific checks include:

- `SET_ENV_VAR` with `DATABASE_URL`: database health is restored and `/items` works.
- `SET_ENV_VAR` with `TARGET_REQUIRED_SECRET`: required environment validation passes.
- `RESTART_SERVICE`: process health returns to normal.
- `DISABLE_FEATURE_FLAG`: checkout no longer fails from the broken flag or rate limit.
- `SWITCH_DEPENDENCY_TO_MOCK`: checkout dependency behavior is healthy.
- `ROLLBACK_CONFIG`: schema-compatible endpoints work after rollback.

The incident resolves only when the verification status is `passed`. If the action executes but verification fails, the incident remains in `verifying` for further analysis or another mitigation.

## Local Validation Flow

1. Activate a failure:

```bash
curl -X POST http://localhost:8000/sandboxes/local-docker/scenarios/bad_database_url/activate
```

2. Trigger or wait for health monitoring:

```bash
curl -X POST http://localhost:8000/sandboxes/local-docker/health-check
```

3. Inspect the latest incident and selected action:

```bash
curl http://localhost:8000/incidents
curl http://localhost:8000/incidents/{incident_id}/actions
```

4. Execute the selected bounded action:

```bash
curl -X POST http://localhost:8000/incidents/{incident_id}/actions/execute-selected
```

5. Verify recovery and replay the timeline:

```bash
curl http://localhost:8000/sandboxes/local-docker/health-history
curl http://localhost:8000/incidents/{incident_id}/timeline
```

This flow demonstrates the core safety property: the agent diagnoses and selects a mitigation, while execution remains constrained to a small set of auditable runtime operations.
