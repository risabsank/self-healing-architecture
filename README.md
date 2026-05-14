# Self-Healing Runtime

Self-Healing Runtime is an open-source reliability add-on for Docker Compose applications. It observes registered services, detects observable failures, creates incidents, reasons over structured evidence, applies bounded mitigations through sidecar adapters, verifies recovery, and records what happened for future incidents.

The runtime is designed for **observable failure response**. It can react to health check failures, critical probe failures, metric/SLO breaches, runtime events, and operator notes. It does not claim to detect hidden bugs that produce no observable signal.

## What It Does

- Registers applications through a `self-healing.yaml` manifest.
- Monitors service health, critical routes, metrics, SLOs, and operator notes.
- Creates and correlates incidents by app, service, severity, and trigger source.
- Uses typed incident evidence, hypotheses, mitigation candidates, and verification results.
- Supports Claude-backed reasoning with deterministic fallback for local/CI runs.
- Executes runtime fixes only through manifest-declared sidecar adapter actions.
- Supports durable repair planning with path ownership, diff preview, CI verification, rollback, and canary rollout.
- Shows the full lifecycle in a developer dashboard with an embedded user-facing app preview.

## Documentation

Start here:

- [Docker Compose quickstart](docs/quickstart-compose.md): run the runtime and onboard the minimal app.
- [Integration contract](docs/integration-contract.md): manifest fields, API routes, failure coverage, and repair expectations.
- [Sidecar adapter guide](docs/adapter-authoring.md): how to expose bounded runtime actions safely.
- [Reference incident runbook](docs/reference-incident.md): run the full bad-feature-flag incident flow.
- [Minimal app example](examples/minimal-compose-app/README.md): smallest external Compose app integration.

## Architecture

```text
Developer Dashboard
  -> FastAPI Control API
  -> Postgres

Control Worker
  -> health checks
  -> probes
  -> signal ingestion

Incident Agent
  -> typed evidence
  -> hypotheses
  -> mitigation candidates
  -> memory retrieval

Guarded Executor
  -> policy checks
  -> sidecar adapter
  -> verification

Repair Pipeline
  -> bounded patch
  -> diff preview
  -> CI verification
  -> canary rollout
```

The bundled target app is a reference integration. External applications integrate with the same runtime by providing a manifest and a sidecar adapter.

## Quickstart

Copy the environment template and start the local runtime:

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
curl -fsS http://localhost:8000/health
```

Start the dashboard:

```bash
cd apps/dashboard
npm run dev
```

Open `http://localhost:3000`.

For a complete onboarding path with an external example app, follow [docs/quickstart-compose.md](docs/quickstart-compose.md).

## Registering An App

Applications register a `self-healing.yaml` manifest:

```bash
curl -fsS -X POST http://localhost:8000/apps/validate-yaml \
  -H "content-type: application/x-yaml" \
  --data-binary @examples/minimal-compose-app/self-healing.yaml

curl -fsS -X POST http://localhost:8000/apps/register-yaml \
  -H "content-type: application/x-yaml" \
  --data-binary @examples/minimal-compose-app/self-healing.yaml
```

The manifest declares:

- services and health URLs,
- user-visible probes,
- metrics and SLO targets,
- safe sidecar actions,
- approved repair paths and owners,
- verification commands,
- canary probes and promotion policy.

## Safety Model

The runtime deliberately separates reasoning from mutation:

- Agents propose typed objects; they do not run shell commands.
- Runtime actions must be declared in the manifest.
- Action parameters are validated against allowlists.
- Risky actions require approval or are blocked.
- Sidecar adapters expose bounded endpoints only.
- Code/config repairs are limited to approved paths.
- CI and canary checks gate durable changes before release.

## Main API Areas

```text
GET  /health

GET  /apps
POST /apps/validate-yaml
POST /apps/register-yaml
POST /apps/{app_id}/health-check
POST /apps/{app_id}/metrics
GET  /apps/{app_id}/slo-status
POST /apps/{app_id}/notes

GET  /incidents
POST /incidents/{incident_id}/analyze
GET  /incidents/{incident_id}/timeline
GET  /incidents/{incident_id}/evidence
GET  /incidents/{incident_id}/hypotheses
GET  /incidents/{incident_id}/actions

POST /incidents/{incident_id}/actions/execute-selected
POST /actions/{action_id}/approve
POST /actions/{action_id}/execute

POST /incidents/{incident_id}/repairs/plan
GET  /repairs/{repair_id}/diff
POST /repairs/{repair_id}/approve
POST /repairs/{repair_id}/apply
POST /repairs/{repair_id}/verify
POST /repairs/{repair_id}/canary-rollouts/start
```

## Repository Layout

```text
apps/dashboard/                 developer and user-facing console
services/control-api/            FastAPI control plane, agents, repair pipeline
target-app/                      intentionally breakable reference app
target-app/sidecar-adapter/      reference bounded action adapter
examples/minimal-compose-app/    smallest external app integration
infra/                           Docker Compose and Postgres schema
docs/                            user-facing setup and integration docs
scripts/incidents/               repeatable incident walkthroughs
```

## Claude-Backed Reasoning

Local and CI runs can work deterministically. To use Claude-backed incident and repair reasoning, configure:

```env
LLM_REASONING_ENABLED=true
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-sonnet-4-5
ANTHROPIC_API_URL=https://api.anthropic.com/v1/messages
```

The API health response reports whether LLM reasoning is enabled and whether a key is configured. A valid provider key is still required for the strict LLM incident runbook.

## Testing

Run the main local checks:

```bash
docker compose -f infra/docker-compose.yml config --quiet
docker compose -f examples/minimal-compose-app/docker-compose.yml config --quiet
docker compose -f infra/docker-compose.yml exec -T control-api python -m unittest discover tests
docker compose -f infra/docker-compose.yml exec -T target-api python -m unittest discover tests
docker compose -f infra/docker-compose.yml exec -T target-adapter python -m unittest discover tests
node --check apps/dashboard/app.js
```

## FAQ

**Can it catch every error?**
No. It responds to failures that become observable through checks, probes, metrics, logs, traces, exceptions, user reports, operator notes, or declared invariants.

**Can it run arbitrary commands to fix things?**
No. Runtime mutation goes through sidecar adapter endpoints declared in the manifest.

**Can it change application code?**
Yes, but only through bounded repair policies, approved paths, diff preview, CI verification, rollback support, and canary rollout.

**Is Docker required?**
Docker Compose is the primary open-source integration path today. The runtime is structured so stronger isolation backends can be added behind the runtime interface.
