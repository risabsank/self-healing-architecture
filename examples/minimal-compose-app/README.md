# Minimal Compose App

This example shows the smallest useful onboarding shape for an external Docker Compose web app.

Copy `self-healing.yaml`, update the service URLs and adapter URL, then register it with:

```bash
curl -X POST http://localhost:8000/apps/register-yaml \
  -H "content-type: application/x-yaml" \
  --data-binary @self-healing.yaml
```

The app must also provide a sidecar adapter that implements the bounded adapter API documented in `docs/integration-contract.md`.
