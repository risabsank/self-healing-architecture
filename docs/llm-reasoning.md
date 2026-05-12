# LLM-Backed Reasoning

The incident agent can use Claude for structured diagnosis and bounded mitigation planning. The Claude path is feature-flagged so local runs and CI remain deterministic when no API key is configured.

## Configuration

```text
LLM_REASONING_ENABLED=true
ANTHROPIC_API_KEY=<secret>
ANTHROPIC_MODEL=claude-sonnet-4-5
```

File-secret injection is also supported:

```text
ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_api_key
```

## Incident Reasoning Flow

When enabled, incident analysis runs through a LangGraph-compatible state machine:

```text
build_prompt
-> call_claude
-> apply_decision
```

If the `langgraph` package is installed, the nodes run through `StateGraph`. If it is unavailable, the same nodes run sequentially. This keeps the production integration path clear without breaking local development.

Claude must return JSON that validates against Pydantic models:

- `LLMIncidentDecision`
- `Hypothesis`
- `MitigationCandidate`

The agent stores:

- typed evidence,
- typed hypotheses,
- typed mitigation candidates,
- `reasoning_provider`,
- a concise `reasoning_summary`.

The prompt explicitly asks for structured summaries and forbids hidden chain-of-thought.

## Repair Planning

The durable repair planner can also call Claude. It validates output against `LLMRepairDecision`, then converts it into the existing `RepairPlan` object.

Claude receives:

- incident title,
- root cause,
- final summary,
- persisted evidence,
- attempted actions,
- approved write paths.

If Claude is unavailable or returns invalid JSON, the system falls back to deterministic regression-test planning.

## Safety Boundaries

Claude does not execute actions. It only proposes typed objects.

Runtime mitigation still goes through:

- allowlisted action types,
- risk scores,
- approval policy,
- bounded executor adapters,
- recovery verification.

Repair planning still goes through:

- approved path checks,
- CI/CD verification,
- canary rollout policy,
- rollback or quarantine.
