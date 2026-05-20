# Docker Compose Quickstart

This guide shows how to run Self-Healing Runtime and onboard the minimal external Compose app.

## 1. Start The Runtime

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
curl -fsS http://localhost:8000/health
```

The health response should report a healthy control API, database, and reference target service.

## 2. Start The Minimal App

```bash
docker compose -f examples/minimal-compose-app/docker-compose.yml up -d --build
curl -fsS http://localhost:8080/health
curl -fsS http://localhost:8011/adapter/capabilities
```

The app listens on `http://localhost:8080`. Its sidecar adapter listens on `http://localhost:8011`.

## 3. Validate The Manifest

```bash
curl -fsS -X POST http://localhost:8000/apps/validate-yaml \
  -H "content-type: application/x-yaml" \
  --data-binary @examples/minimal-compose-app/self-healing.yaml
```

Fix any readiness check with `"ok": false` before registering the app.

## 4. Register The App

```bash
curl -fsS -X POST http://localhost:8000/apps/register-yaml \
  -H "content-type: application/x-yaml" \
  --data-binary @examples/minimal-compose-app/self-healing.yaml
```

Confirm registration:

```bash
curl -fsS http://localhost:8000/apps/my-compose-app
curl -fsS http://localhost:8000/apps/my-compose-app/validation
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/health-check
```

## 5. Send Reliability Signals

Submit a healthy metric:

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/metrics \
  -H "content-type: application/json" \
  -d '{"metric_name":"latency_p95_ms","value":250,"unit":"ms","source":"quickstart"}'
```

Submit a breaching metric:

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/metrics \
  -H "content-type: application/json" \
  -d '{"metric_name":"latency_p95_ms","value":1200,"unit":"ms","source":"quickstart"}'
```

Submit an operator note:

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/notes \
  -H "content-type: application/json" \
  -d '{"severity":"high","service_name":"web","note":"Users are reporting a slow homepage after deploy.","tags":["quickstart"]}'
```

The SLO breach and high-severity note should create or correlate into an incident for `my-compose-app`.

## 6. Open The Dashboard

```bash
cd apps/dashboard
npm run dev
```

Open `http://localhost:3000`, select `my-compose-app`, and verify:

- the user-facing app preview loads,
- onboarding health checks are visible,
- SLO status and metric history appear,
- operator notes appear,
- incidents show trigger source, severity, app, and service.

## 7. Customize Runtime Coverage

Use the dashboard `Customize runtime` panel, or call the API directly, to generate app-specific manifest additions:

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/customizations/plan \
  -H "content-type: application/json" \
  -d '{"prompt":"Monitor checkout latency and create an incident if p95 exceeds 900ms."}'
```

Review the returned preview. If it looks correct, approve it:

```bash
curl -fsS -X POST http://localhost:8000/apps/my-compose-app/customizations/{proposal_id}/approve
```

The approval updates only manifest-owned reliability configuration such as probes, metrics, SLOs, note templates, dashboard hints, verification probes, and canary probes.

## 8. Adapt This To Your App

For your own app, copy `examples/minimal-compose-app/self-healing.yaml` and update:

- app id and display name,
- service URLs,
- health checks and critical probes,
- metric sources and SLO targets,
- sidecar adapter URL,
- safe actions,
- approved repair paths and test commands,
- canary probes.

Then implement the sidecar adapter contract described in [adapter-authoring.md](adapter-authoring.md).

## Unregister The Minimal App

When you stop the minimal app, unregister it so its `web` service is removed from health monitoring:

```bash
curl -fsS -X DELETE http://localhost:8000/apps/my-compose-app
```
