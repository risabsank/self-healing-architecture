# Integration Contract

This document defines what an application must provide to work with Self-Healing Runtime.

## Failure Coverage

The runtime responds to **observable failures**. It can create incidents from:

- health check failures,
- critical probe failures,
- metric and SLO breaches,
- runtime events,
- operator notes,
- user reports or support observations submitted as notes,
- logs, traces, or exceptions once collectors are added.

It cannot reliably detect a hidden bug unless that bug produces an observable signal.

## Application Manifest

Each app registers a `self-healing.yaml` manifest. The manifest is the source of truth for observation, safe runtime actions, durable repair, verification, and rollout policy.

Required top-level fields:

```yaml
app_id: my-compose-app
display_name: My Compose App
environment: local
sandbox_id: local-docker
services: []
health_checks: []
critical_probes: []
safe_actions: []
metric_sources: []
slo_targets: []
repair_policy: {}
verification: {}
canary: {}
repo: {}
```

## Services

Services tell the runtime where the app runs and where its sidecar adapter lives.

```yaml
services:
  - name: web
    service_type: web
    base_url: http://host.docker.internal:8080
    health_url: http://host.docker.internal:8080/health
    public_url: http://localhost:8080
    adapter_url: http://host.docker.internal:8011
```

`public_url` is used by the dashboard app preview. `adapter_url` is used for bounded runtime actions.

## Health Checks And Critical Probes

Health checks should be cheap readiness checks. Critical probes should represent user-visible behavior.

```yaml
health_checks:
  - name: health
    service: web
    method: GET
    path: /health
    healthy_status: healthy
    expected_status_lt: 500

critical_probes:
  - name: homepage
    service: web
    method: GET
    path: /
    expected_status_lt: 500
```

## Metrics And SLOs

Metric sources define what can be reported. SLO targets define thresholds that create SLO evaluations and incidents when breached.

```yaml
metric_sources:
  - name: latency_p95_ms
    unit: ms
  - name: error_rate
    unit: ratio

slo_targets:
  - name: homepage-latency
    metric: latency_p95_ms
    comparator: <=
    target: 750
    window: 5m
    severity: high
```

Submit observations:

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/metrics \
  -H "content-type: application/json" \
  -d '{"metric_name":"latency_p95_ms","value":1200,"unit":"ms","source":"load-test"}'
```

## Operator Notes

Operator notes let humans turn user reports or behavioral observations into structured evidence.

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/notes \
  -H "content-type: application/json" \
  -d '{"severity":"high","service_name":"web","note":"Users are reporting slow checkout after deploy.","tags":["support"]}'
```

High-severity notes create incidents. Notes that mention degraded behavior can also trigger incidents.

## Safe Actions

Safe actions define the only runtime mutations the agent can request.

```yaml
safe_actions:
  - action_type: RESTART_SERVICE
    service: web
    description: Restart the web service through the sidecar adapter.
    adapter_path: /adapter/actions/RESTART_SERVICE
    blast_radius: low
    required_params: [service]
    approval_required: false
    rollback_available: true
    max_autonomous_risk: 0.25
    parameter_allowlists: {}
```

The control plane validates action type, service, risk score, approval requirement, rollback availability, and parameter allowlists before calling the sidecar adapter.

## Repair Policy

Repair policy constrains generated code and config changes.

```yaml
repair_policy:
  approved_paths:
    - app/
    - tests/
  path_owners:
    app/: app-team
    tests/: app-team
  test_commands:
    - ["python", "-m", "unittest", "discover", "tests"]
  build_commands: []
  rollback_strategy: Apply generated rollback operations.
```

Generated repairs must stay inside approved paths, expose a diff preview, pass verification, and support rollback or quarantine.

## Verification And Canary

Verification defines checks after mitigation or repair. Canary defines promotion probes.

```yaml
verification:
  commands:
    - ["python", "-m", "unittest", "discover", "tests"]

canary:
  environment: local-canary
  traffic_percentage: 10
  probes:
    - name: health
      service: web
      path: /health
      healthy_status: healthy
```

## Manifest API

The control plane accepts JSON and YAML manifests:

```text
POST /apps/validate
POST /apps/register
POST /apps/validate-yaml
POST /apps/register-yaml
GET  /apps/{app_id}/validation
```

Use `validate-yaml` before registration so missing services, probes, SLOs, safe actions, or repair policy fields are reported clearly.

## Sidecar Adapter

The sidecar adapter is the runtime mutation boundary. It must expose only bounded actions:

```text
GET  /adapter/capabilities
GET  /adapter/state
POST /adapter/actions/{action_type}
POST /adapter/rollback/{rollback_id}
```

See [adapter-authoring.md](adapter-authoring.md) for implementation details.
