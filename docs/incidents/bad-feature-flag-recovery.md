# Bad Feature Flag Recovery

This incident walkthrough has moved to the operator runbook:

- [Bad Feature Flag Operator Runbook](bad-feature-flag-operator-runbook.md)

The runbook covers the full recovery path: runtime startup, failure injection,
LLM-backed diagnosis, bounded mitigation through the sidecar adapter, recovery
verification, durable repair planning, CI/CD verification, canary rollout,
incident memory, and repeatable rollback.
