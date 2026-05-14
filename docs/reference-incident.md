# Reference Incident: Bad Feature Flag Recovery

This runbook executes the full reference flow against the bundled breakable target app.

The flow covers:

```text
runtime startup
-> failure injection
-> incident detection
-> LLM-backed diagnosis when Claude is configured
-> bounded mitigation through the sidecar adapter
-> recovery verification
-> durable repair planning
-> diff preview
-> CI verification
-> canary rollout
-> incident memory
-> rollback of generated local changes
```

## Requirements

- Docker Desktop with Compose support.
- Python 3.12 or newer.
- Node.js 20 or newer for the dashboard.
- A valid Claude API key for the strict LLM-backed flow.

The project can run without Claude by passing `--allow-deterministic`, but the strict reference incident expects Claude-backed reasoning and repair planning.

## Configure Environment

```bash
cp .env.example .env
```

For Claude-backed reasoning, set:

```env
LLM_REASONING_ENABLED=true
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-sonnet-4-5
ANTHROPIC_API_URL=https://api.anthropic.com/v1/messages
ANTHROPIC_TIMEOUT_SECONDS=30
```

Do not commit `.env`.

## Start The Runtime

```bash
docker compose -f infra/docker-compose.yml up -d --build
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
```

Optional dashboard:

```bash
cd apps/dashboard
npm run dev
```

Open `http://localhost:3000`.

## Run The Incident Flow

Strict Claude-backed run:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py
```

Deterministic local run:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --allow-deterministic
```

Start the stack from the script:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --start-stack
```

Keep generated patches applied for inspection:

```bash
python3 scripts/incidents/bad_feature_flag_recovery.py --keep-patch
```

## What To Look For

The script should report:

- Control API health.
- LLM readiness when strict mode is used.
- Injected `bad_feature_flag` scenario.
- Incident id.
- Reasoning provider.
- Diagnosed root cause.
- Selected bounded action.
- Recovery verification result.
- Durable repair id.
- CI verification result.
- Canary rollout id.
- Stored memory result.

In the dashboard, inspect:

- incident timeline,
- evidence,
- hypotheses,
- action guardrails,
- verification checks,
- repair diff preview,
- CI checks,
- canary rollout,
- memory matches.

## Common Issues

If the script says Claude reasoning was expected but got deterministic reasoning, check:

```bash
curl -fsS http://localhost:8000/health
docker compose -f infra/docker-compose.yml logs --tail=100 control-api
```

The health response can confirm whether LLM reasoning is enabled and whether a key is configured. A configured key must still be valid with Anthropic; `401 Unauthorized` means the provider rejected the key.

If the target app is already degraded, reset it:

```bash
curl -fsS -X POST http://localhost:8000/sandboxes/local-docker/scenarios/reset
```

If dashboard data looks stale, use the dashboard refresh button or reload the page.
