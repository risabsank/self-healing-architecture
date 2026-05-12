# Bring Your Own Website

Self-Healing Runtime can now onboard Docker Compose applications through an application manifest and a sidecar adapter. The bundled breakable target is the reference integration; it is registered as `breakable-target` and described in `examples/breakable-target/self-healing.yaml`.

## Integration Contract

An onboarded app provides:

- a `self-healing.yaml` manifest,
- one or more service URLs and health checks,
- critical probes that represent user-visible behavior,
- a sidecar adapter URL for bounded runtime actions,
- safe action allowlists and parameter allowlists,
- repo path ownership and test commands for durable repair,
- canary probes and success criteria.

The control plane stores the manifest through:

```text
POST /apps/register
GET  /apps
GET  /apps/{app_id}
POST /apps/{app_id}/health-check
```

## Sidecar Adapter

The sidecar exposes a small bounded API:

```text
GET  /adapter/capabilities
GET  /adapter/state
POST /adapter/actions/{action_type}
POST /adapter/rollback/{rollback_id}
```

The adapter never accepts arbitrary shell commands. It maps declared safe actions to platform-specific operations such as restart, config restore, feature flag disable, dependency fallback, or rollback.

## Reference Flow

The existing bad feature flag recovery path now goes through the registered app manifest and sidecar adapter:

```text
breakable-target manifest
-> target-adapter capabilities
-> app-scoped action policy
-> bounded adapter action
-> manifest-defined verification probes
-> manifest-defined canary probes
-> app-scoped repair policy
```

For a new Docker Compose website, copy `examples/breakable-target/self-healing.yaml`, update service URLs, probes, action allowlists, and repair paths, then register the manifest through `POST /apps/register`.
