# Evaluation Harness

The evaluation harness measures whether the runtime can repeatedly detect, diagnose, mitigate, and verify realistic incidents. It exercises the same control-plane path used by the operator workflow: failure injection, health/degraded detection, incident analysis, bounded mitigation, recovery verification, memory retrieval, and persistent timeline records.

## API

Run the full scenario catalog:

```bash
curl -X POST http://localhost:8000/evaluations/run \
  -H 'Content-Type: application/json' \
  -d '{"repeats": 1}'
```

Run selected scenarios:

```bash
curl -X POST http://localhost:8000/evaluations/run \
  -H 'Content-Type: application/json' \
  -d '{"scenarios": ["bad_database_url", "dependency_unavailable"], "repeats": 2}'
```

Inspect persisted results:

```text
GET /evaluations
GET /evaluations/{run_id}
GET /evaluations/{run_id}/cases
```

## Scenario Catalog

| Scenario | Expected root cause | Expected first action |
| --- | --- | --- |
| `bad_database_url` | Broken database connection string | `SET_ENV_VAR` |
| `missing_required_env` | Missing required environment variable | `SET_ENV_VAR` |
| `schema_mismatch` | Application/schema mismatch after change | `ROLLBACK_CONFIG` |
| `port_conflict` | Service process or port binding conflict | `RESTART_SERVICE` |
| `bad_feature_flag` | Bad feature flag enabled a broken code path | `DISABLE_FEATURE_FLAG` |
| `dependency_unavailable` | Downstream API dependency unavailable | `SWITCH_DEPENDENCY_TO_MOCK` |
| `rate_limit` | Dependency rate limiting | `DISABLE_FEATURE_FLAG` |

Health-affecting scenarios are detected through `/health`. Degraded scenarios are detected through endpoint probes, currently the checkout dependency path.

## Metrics

- `detection_time_ms`: time from scenario activation to the first unhealthy or degraded signal.
- `diagnosis_time_ms`: time spent running the incident agent analysis.
- `recovery_time_ms`: time spent executing the selected bounded mitigation and verification path.
- `diagnosis_accuracy`: percentage of cases where the top hypothesis matches the expected root cause.
- `first_action_success_rate`: percentage of cases where the selected first mitigation passes recovery verification.
- `rollback_rate`: percentage of cases where the selected action is a rollback.
- `memory_usefulness_rate`: percentage of cases with prior memory where retrieved memory participated in a successful recovery.

## Persistence

Each evaluation run is stored in `evaluation_runs` with aggregate metrics. Each scenario attempt is stored in `evaluation_cases` with the incident id, expected root cause, diagnosed root cause, selected action, per-case metrics, and detailed result payload.

The harness intentionally creates normal incidents and incident events, so evaluation cases remain replayable through the same timeline APIs as live incidents.
