# System Foundation

This document describes the local runtime foundation for Self-Healing Runtime.

The foundation includes:

- FastAPI control plane
- Postgres schema for sandboxes, services, health checks, incidents, timelines, and future repair records
- Docker Compose runtime
- Intentionally breakable target app
- Basic health monitoring loop

## Services

```text
control-api   http://localhost:8000
target-api    http://localhost:8001
postgres      localhost:5432
target-db     localhost:5433
```

## Start The Stack

From the repository root:

```bash
docker compose -f infra/docker-compose.yml up --build
```

## Useful Endpoints

Control API:

```text
GET  http://localhost:8000/
GET  http://localhost:8000/health
GET  http://localhost:8000/sandboxes
GET  http://localhost:8000/sandboxes/local-docker
POST http://localhost:8000/sandboxes/local-docker/health-check
GET  http://localhost:8000/incidents
```

Target API:

```text
GET  http://localhost:8001/
GET  http://localhost:8001/health
GET  http://localhost:8001/metadata
GET  http://localhost:8001/items
GET  http://localhost:8001/checkout
```

## Verification

1. `GET /health` on the control API should report the database check and target service health.
2. `GET /sandboxes/local-docker` should show the Docker runtime descriptor, registered `target-api` service, and latest health check.
3. `GET /health` on the target API should report the required environment variable and database dependency.
4. The `health_checks` table should receive new rows from the background monitor.

## Current Scope

The current foundation does not implement autonomous diagnosis, runtime mitigation, code repair, CI/CD verification, or canary rollout yet. It provides the live substrate required by those capabilities:

- a control plane,
- an observable target service,
- a sandbox registry,
- persistent health checks,
- a database schema ready for incidents, evidence, actions, and memory,
- and a runtime boundary that can later support patch validation and canary deployment.

The intended architecture separates immediate recovery from durable improvement. Runtime mitigations restore service quickly, while code and configuration changes should be validated through tests, sandbox replay, and canary rollout before promotion.
