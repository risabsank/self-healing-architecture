from dataclasses import dataclass


@dataclass(frozen=True)
class DockerRuntime:
    """Runtime descriptor for the local Docker Compose sandbox."""

    sandbox_id: str = "local-docker"
    runtime: str = "docker-compose"

    def describe(self) -> dict[str, str]:
        return {
            "sandbox_id": self.sandbox_id,
            "runtime": self.runtime,
            "isolation": "docker-containers",
            "capability": "runtime-foundation",
        }
