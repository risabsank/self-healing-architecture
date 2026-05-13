# 30-Minute Docker Compose Onboarding

This guide walks through onboarding a simple Docker Compose app with docs only.

## 1. Start Self-Healing Runtime

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
curl -fsS http://localhost:8000/health
```

## 2. Start The Minimal Example App

```bash
docker compose -f examples/minimal-compose-app/docker-compose.yml up -d --build
curl -fsS http://localhost:8080/health
curl -fsS http://localhost:8011/adapter/capabilities
```

## 3. Validate The Manifest

```bash
curl -fsS -X POST http://localhost:8000/apps/validate-yaml \
  -H "content-type: application/x-yaml" \
  --data-binary @examples/minimal-compose-app/self-healing.yaml
```

All readiness checks should pass. Fix any check marked `ok: false` before registering the app.

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

## 6. Inspect The Dashboard

```bash
cd apps/dashboard
npm install
npm run dev
```

Open `http://localhost:3000`, select `my-compose-app`, and verify:

- the user-facing app preview loads,
- onboarding health checks are green,
- SLO status and metric history are visible,
- operator notes link to incidents,
- incidents show trigger source, severity, and typed evidence.

## 7. Next Integration Steps

For your own app, replace the minimal manifest values with your service names, public URL, health checks, user-visible probes, SLOs, sidecar adapter URL, safe actions, approved repair paths, test commands, and canary probes.
