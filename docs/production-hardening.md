# Production Hardening

This document describes the operational hardening built into the local control plane and the path toward a production deployment.

## Authentication

The control API supports API-key authentication through either `X-API-Key` or `Authorization: Bearer <token>`.

Local development keeps authentication disabled:

```text
AUTH_ENABLED=false
```

Production deployments should enable it and inject keys from a secret manager:

```text
AUTH_ENABLED=true
API_KEYS_FILE=/run/secrets/control_api_keys
```

The root, `/health`, and OpenAPI documentation routes remain public so load balancers and operators can inspect service readiness.

## Background Workers

Monitoring can run outside the web API process. In Docker Compose, `control-api` serves HTTP while `control-worker` runs the monitor loop:

```text
control-api     FastAPI routes, auth, timelines, actions, evaluations
control-worker  periodic health checks and automatic incident detection
```

This separation keeps request serving predictable and makes worker scaling explicit.

## Migrations

Startup runs SQL migrations from:

```text
infra/postgres/migrations/
```

Applied versions are tracked in `schema_migrations`. Fresh local databases still use `infra/postgres/init.sql`, while migrations handle incremental upgrades for existing deployments.

## Tracing And Structured Logs

Each HTTP request receives or propagates an `x-trace-id`. The API returns the trace id as a response header and emits JSON logs with:

- timestamp,
- level,
- service name,
- trace id,
- request method,
- request path,
- status code,
- duration.

Incident timelines remain the system-of-record for operational replay. Request logs provide infrastructure-level correlation around those timelines.

## Secrets

The runtime supports direct environment variables and Docker/Kubernetes-style file secrets. Any setting can be supplied with a matching `_FILE` variable:

```text
DATABASE_URL_FILE=/run/secrets/control_database_url
API_KEYS_FILE=/run/secrets/control_api_keys
```

If both `DATABASE_URL` and `DATABASE_URL_FILE` are present, the direct environment variable wins.

## Runtime Isolation

The local Docker runtime applies baseline container hardening:

- `no-new-privileges`,
- dropped Linux capabilities for application containers,
- read-only container root filesystems,
- writable `/tmp` through `tmpfs`,
- process count limits,
- separate control database and target database containers.

Docker is still a development runtime. A hardened production runtime should move target execution toward isolated VM or MicroVM backends with snapshotting, per-incident network policy, and disposable canary environments.

## CI

GitHub Actions runs:

- Python dependency installation,
- static compilation for control and target apps,
- target app regression tests,
- Docker Compose config validation,
- container builds.

The in-application CI/CD verifier still controls generated repairs before canary rollout. Repository CI protects human-authored and agent-authored changes before merge.

## Deployment Notes

Production deployments should:

- enable `AUTH_ENABLED`,
- provide API keys and database URLs through a secret manager,
- run `control-worker` separately from `control-api`,
- place the control API behind TLS,
- restrict dashboard origins,
- isolate target runtime networks from the control database,
- ship JSON logs to a centralized log pipeline,
- retain Postgres backups and migration history,
- use a VM or MicroVM runtime for untrusted target workloads.
