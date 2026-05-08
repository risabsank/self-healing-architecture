from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.sandbox.runtime import RuntimeOperation, common_capabilities


@dataclass(frozen=True)
class FirecrackerRuntime:
    runtime: str = "firecracker"

    def describe(self, sandbox_id: str) -> dict:
        configured = bool(settings.firecracker_api_url)
        return {
            "sandbox_id": sandbox_id,
            "runtime": self.runtime,
            "isolation": "microvm",
            "configured": configured,
            "capabilities": {
                **common_capabilities(snapshot_restore=configured),
                "snapshot_based_recovery": configured,
            },
            "notes": "Requires an external Firecracker supervisor API." if not configured else None,
        }

    def create_snapshot(self, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
        return self.supervisor_request("POST", f"/sandboxes/{sandbox_id}/snapshots", {"name": snapshot_name})

    def restore_snapshot(self, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
        return self.supervisor_request("POST", f"/sandboxes/{sandbox_id}/snapshots/{snapshot_name}/restore", {})

    def supervisor_request(self, method: str, path: str, payload: dict) -> RuntimeOperation:
        if not settings.firecracker_api_url:
            return RuntimeOperation(
                status="unconfigured",
                message="Firecracker supervisor URL is not configured.",
                detail={"required_setting": "FIRECRACKER_API_URL"},
            )

        try:
            with httpx.Client(timeout=settings.firecracker_timeout_seconds) as client:
                response = client.request(method, f"{settings.firecracker_api_url}{path}", json=payload)
                body = response.json()
        except Exception as exc:
            return RuntimeOperation(
                status="failed",
                message="Firecracker supervisor request failed.",
                detail={"error": type(exc).__name__, "message": str(exc)},
            )

        if response.status_code >= 400:
            return RuntimeOperation(status="failed", message="Firecracker supervisor rejected request.", detail=body)

        return RuntimeOperation(status="accepted", message="Firecracker supervisor accepted request.", detail=body)
