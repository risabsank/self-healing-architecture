from dataclasses import dataclass

from app.sandbox.runtime import RuntimeOperation, common_capabilities, unsupported_snapshot


@dataclass(frozen=True)
class DockerRuntime:
    runtime: str = "docker-compose"

    def describe(self, sandbox_id: str) -> dict:
        return {
            "sandbox_id": sandbox_id,
            "runtime": self.runtime,
            "isolation": "docker-containers",
            "capabilities": common_capabilities(snapshot_restore=False),
        }

    def create_snapshot(self, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
        return unsupported_snapshot("Docker Compose", "capture", sandbox_id, snapshot_name)

    def restore_snapshot(self, sandbox_id: str, snapshot_name: str) -> RuntimeOperation:
        return unsupported_snapshot("Docker Compose", "restore", sandbox_id, snapshot_name)
