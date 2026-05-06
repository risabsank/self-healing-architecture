# Operator Dashboard

The operator dashboard is a lightweight browser UI for the Self-Healing Runtime control plane. It shows sandbox health, incident state, evidence, hypotheses, guarded remediation actions, verification results, and memory matches from the FastAPI API.

## Run Locally

Start the platform services first:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Then start the dashboard:

```bash
cd apps/dashboard
npm run dev
```

The dashboard listens on `http://localhost:3000` and expects the control API at `http://localhost:8000` by default. The API base URL can be changed from the dashboard toolbar.

## Operator Workflow

1. Confirm the sandbox and target service are healthy.
2. Activate a failure scenario.
3. Watch the runtime create or update an incident.
4. Run incident analysis when additional diagnosis is needed.
5. Review evidence, hypotheses, guardrails, and candidate actions.
6. Approve gated actions when appropriate.
7. Execute the selected bounded action.
8. Confirm verification checks and memory matches update after recovery.
