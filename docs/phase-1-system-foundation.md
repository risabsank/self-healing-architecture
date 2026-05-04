# Phase 1: System Foundation

Phase 1 establishes the runnable local foundation for Self-Healing Runtime:

- FastAPI control plane
- Postgres schema for sandboxes, services, health checks, incidents, and timelines
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

## What To Verify

1. `GET /health` on the control API should report the database check and target service health.
2. `GET /sandboxes/local-docker` should show the Docker runtime descriptor, registered `target-api` service, and latest health check.
3. `GET /health` on the target API should report the required environment variable and database dependency.
4. The `health_checks` table should receive new rows from the background monitor.

## Phase 1 Boundary

This phase does not implement autonomous diagnosis or remediation yet. It creates the live substrate those later phases need:

- a control plane,
- an observable target service,
- a sandbox registry,
- persistent health checks,
- and a database schema ready for incidents, evidence, actions, and memory.
