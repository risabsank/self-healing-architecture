# MicroVM Runtime

The sandbox runtime layer now separates the control plane from the concrete execution backend. Docker Compose remains the local development runtime, while Firecracker support is modeled as a MicroVM runtime adapter.

## Runtime Interface

Runtime adapters expose:

- `describe(sandbox_id)`,
- `create_snapshot(sandbox_id, snapshot_name)`,
- `restore_snapshot(sandbox_id, snapshot_name)`.

The control API uses the adapter selected by the `sandboxes.runtime` value. Supported runtime names:

```text
docker-compose
firecracker
microvm
```

`microvm` is treated as an alias for the Firecracker adapter.

## Firecracker Boundary

The control API does not run raw Firecracker commands directly. Firecracker requires host-level setup, jailer configuration, TAP networking, kernel/rootfs management, seccomp policy, cgroups, and snapshot files. Those responsibilities belong to a small privileged supervisor process.

The control API talks to that supervisor through:

```text
FIRECRACKER_API_URL=http://firecracker-supervisor:9000
```

Expected supervisor endpoints:

```text
POST /sandboxes/{sandbox_id}/snapshots
POST /sandboxes/{sandbox_id}/snapshots/{snapshot_name}/restore
```

## Snapshot-Based Recovery

Snapshot operations are persisted in `sandbox_snapshots` with:

- sandbox id,
- snapshot name,
- operation,
- status,
- detail payload,
- timestamp.

API routes:

```text
GET  /sandboxes/runtimes
GET  /sandboxes/{sandbox_id}/snapshots
POST /sandboxes/{sandbox_id}/snapshots
POST /sandboxes/{sandbox_id}/snapshots/{snapshot_name}/restore
```

Docker returns `unsupported` for snapshot operations. Firecracker returns `unconfigured` until `FIRECRACKER_API_URL` is set.

## Production Isolation Path

A production MicroVM runtime should provide:

- one MicroVM per target sandbox,
- immutable root filesystem images,
- writable overlay or block device per sandbox,
- network isolation per sandbox,
- snapshot capture after healthy boot,
- snapshot restore as a recovery action,
- supervisor-level audit logs,
- strict allowlisted lifecycle operations,
- no raw shell access from the incident agent.

The same bounded remediation and verification flows continue to apply regardless of whether the target runs in Docker or Firecracker.
