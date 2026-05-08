from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RuntimeOperation:
    status: str
    message: str
    detail: dict

    def payload(self) -> dict:
        return {"message": self.message, **self.detail}


class SandboxRuntime(Protocol):
    runtime: str

    def describe(self, sandbox_id: str) -> dict:
        ...

    def create_snapshot(self, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
        ...

    def restore_snapshot(self, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
        ...


def common_capabilities(snapshot_restore: bool) -> dict[str, bool]:
    return {
        "health_checks": True,
        "failure_injection": True,
        "runtime_mitigation": True,
        "snapshot_restore": snapshot_restore,
    }


def unsupported_snapshot(runtime: str, action: str, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
    return RuntimeOperation(
        status="unsupported",
        message=f"{runtime} runtime does not provide VM snapshot {action}.",
        detail={"sandbox_id": sandbox_id, "snapshot_name": snapshot_name},
    )
