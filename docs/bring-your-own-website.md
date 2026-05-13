# Bring Your Own Website

Self-Healing Runtime is designed as a Docker Compose-first reliability add-on. A team can keep its existing web application, add a `self-healing.yaml` manifest, expose a bounded sidecar adapter, and let the runtime observe, diagnose, mitigate, verify, and remember observable failures.

The runtime does not catch every hidden bug automatically. It responds to failures that are visible through health checks, critical probes, metrics, SLO breaches, logs, traces, exceptions, operator notes, user reports, or other declared signals.

## Quickstart

1. Clone this repository and start the runtime:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

2. Copy the reference manifest:

```bash
cp examples/breakable-target/self-healing.yaml ./self-healing.yaml
```

3. Update the manifest with your app id, service URLs, health URLs, public URL, probes, safe actions, metrics, SLO targets, repair paths, and canary probes.

4. Add a sidecar adapter to your Compose file. The adapter must expose bounded actions only; it must not accept arbitrary shell commands.

5. Register the app:

```bash
curl -X POST http://localhost:8000/apps/register \
  -H "content-type: application/json" \
  --data @self-healing.json
```

YAML manifests can be converted to JSON with `yq -o=json self-healing.yaml > self-healing.json`.

6. Confirm the runtime can see your app:

```bash
curl http://localhost:8000/apps
curl -X POST http://localhost:8000/apps/YOUR_APP_ID/health-check
```

7. Send a metric or operator note:

```bash
curl -X POST http://localhost:8000/apps/YOUR_APP_ID/metrics \
  -H "content-type: application/json" \
  -d '{"metric_name":"latency_p95_ms","value":850,"unit":"ms","source":"load-test","labels":{"route":"/checkout"}}'

curl -X POST http://localhost:8000/apps/YOUR_APP_ID/notes \
  -H "content-type: application/json" \
  -d '{"severity":"high","service_name":"web","note":"Users are reporting slow checkout after the deploy.","tags":["support","checkout"]}'
```

## Manifest Responsibilities

The manifest declares how the runtime should observe and safely affect your app:

- `services`: app service URLs, health URLs, public preview URLs, and sidecar adapter URLs.
- `health_checks`: low-cost checks for basic service health.
- `critical_probes`: user-visible routes or workflows such as login, checkout, API reads, and dashboard loading.
- `metric_sources`: named metrics the app or pipeline can report.
- `slo_targets`: thresholds that turn metric observations into healthy or breached evaluations.
- `safe_actions`: bounded mitigations the sidecar can execute.
- `repair_policy`: approved repo paths, owners, tests, builds, and rollback strategy.
- `verification`: checks required after mitigation or generated repair.
- `canary`: probes and traffic assumptions for promotion decisions.

See `docs/30-minute-compose-onboarding.md` for a runnable onboarding walkthrough, `examples/breakable-target/self-healing.yaml` for a complete reference, and `examples/minimal-compose-app/self-healing.yaml` for a compact starting point.

## Sidecar Adapter Contract

The sidecar must expose:

```text
GET  /adapter/capabilities
GET  /adapter/state
POST /adapter/actions/{action_type}
POST /adapter/rollback/{rollback_id}
```

Each action request receives typed parameters declared in the manifest. The adapter maps those parameters to safe local operations such as restart, restore config, disable feature flag, dependency fallback, or rollback. It should reject unknown services, unknown actions, and unallowlisted parameters.

See `docs/adapter-authoring.md` for endpoint shapes and a minimal implementation.

## Metrics, SLOs, And Notes

Metrics are intentionally API-first in the current OSS path. Your app, CI job, load test, synthetic monitor, or external collector can submit observations to:

```text
POST /apps/{app_id}/metrics
GET  /apps/{app_id}/metrics
GET  /apps/{app_id}/slo-status
```

When a metric breaches a declared SLO, the runtime records the evaluation and creates an incident. During incident analysis, SLO breaches become structured evidence with source `metric_slo`.

Operator notes are submitted to:

```text
POST /apps/{app_id}/notes
GET  /apps/{app_id}/notes
```

High or critical notes create incidents immediately. Medium notes can also create incidents when they contain degradation language such as slow, latency, error, failing, outage, or down. During incident analysis, notes become structured evidence with source `operator_note`.

## Dashboard

The dashboard has two console layers:

- **User-facing console:** embeds the registered app’s `public_url`, so operators can see the customer-facing experience.
- **Developer-facing console:** shows the self-healing state, SLOs, metrics, notes, incidents, evidence, hypotheses, actions, verification, canary rollout, and memory matches.

Start it with:

```bash
cd apps/dashboard
npm install
npm run dev
```
