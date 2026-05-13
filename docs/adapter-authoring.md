# Sidecar Adapter Authoring Guide

The sidecar adapter is the runtime mutation boundary. The incident agent never receives arbitrary shell access; it can only request actions declared in the app manifest and exposed by the adapter.

## Required Endpoints

```text
GET  /adapter/capabilities
GET  /adapter/state
POST /adapter/actions/{action_type}
POST /adapter/rollback/{rollback_id}
```

## Capabilities Response

```json
{
  "app_id": "my-compose-app",
  "service": "web",
  "actions": {
    "RESTART_SERVICE": {
      "required_params": ["service"],
      "parameter_allowlists": {}
    }
  }
}
```

## Action Request

```json
{
  "params": {
    "service": "web"
  }
}
```

The adapter must reject:

- unknown action types,
- unknown services,
- missing required parameters,
- unallowlisted parameter values,
- arbitrary command strings.

## Minimal Implementation

See `examples/minimal-compose-app/adapter/main.py` for a compact FastAPI adapter that exposes `RESTART_SERVICE` and proxies it to a bounded runtime endpoint on the app.

## Safety Expectations

- Keep actions reversible when possible.
- Return structured JSON for every action.
- Include rollback ids when a platform-specific rollback exists.
- Keep platform credentials in the adapter environment, not in the manifest.
- Treat the manifest as a public contract, not as a secret store.
