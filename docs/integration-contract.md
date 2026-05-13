# Integration Contract

This document defines the public contract an application implements to work with Self-Healing Runtime.

## Application Manifest

Each app registers a `self-healing.yaml` manifest. The manifest is the source of truth for observation, mitigation, verification, and durable repair policy.

Required foundations:

- `app_id`, `display_name`, `environment`, and `sandbox_id`
- `services` with `base_url`, `health_url`, optional `public_url`, and optional `adapter_url`
- `health_checks` and `critical_probes`
- `safe_actions` that map to sidecar endpoints

Production-oriented fields:

- `metric_sources`: metrics the app or external monitors can report
- `slo_targets`: thresholds that create SLO evaluations and incidents when breached
- `repair_policy`: approved paths, owners, and test/build commands
- `verification`: checks required after mitigation or repair
- `canary`: probes and traffic assumptions for promotion

## Failure Coverage

Self-Healing Runtime catches observable failures. It can respond to health failures, probe failures, metric/SLO breaches, logs or traces once collected, runtime events, user reports, and operator notes. It cannot guarantee detection of a bug that produces no observable signal.

## Sidecar Adapter

The sidecar is the only runtime mutation interface. It must reject arbitrary shell commands and expose only bounded actions:

```text
GET  /adapter/capabilities
GET  /adapter/state
POST /adapter/actions/{action_type}
POST /adapter/rollback/{rollback_id}
```

The control plane validates action type, service, risk, approval requirements, and parameter allowlists before calling the sidecar.

## Metrics And Notes

Apps or monitors submit metric observations with:

```text
POST /apps/{app_id}/metrics
```

The runtime evaluates matching `slo_targets`, records the result, and creates an incident for breaches.

The control plane accepts manifests as either JSON or YAML:

```text
POST /apps/validate
POST /apps/register
POST /apps/validate-yaml
POST /apps/register-yaml
```

Operators submit human observations with:

```text
POST /apps/{app_id}/notes
```

High-severity notes create incidents. Notes that mention degraded behavior also become incident triggers and later appear as agent evidence.

## Durable Repair

Generated code/config changes are constrained by `repair_policy`. The repair agent may only touch approved paths, must include verification steps, and must pass CI/CD and canary gates before promotion.
