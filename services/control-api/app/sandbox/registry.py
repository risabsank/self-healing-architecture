from app.sandbox.docker_runtime import DockerRuntime
from app.sandbox.firecracker_runtime import FirecrackerRuntime
from app.sandbox.runtime import SandboxRuntime


RUNTIMES: dict[str, SandboxRuntime] = {
    "docker-compose": DockerRuntime(),
    "firecracker": FirecrackerRuntime(),
    "microvm": FirecrackerRuntime(),
}


def runtime_for(name: str) -> SandboxRuntime:
    return RUNTIMES.get(name, DockerRuntime())


def list_runtimes() -> list[dict]:
    return [
        runtime.describe(sandbox_id=f"{runtime_name}-template")
        for runtime_name, runtime in sorted(RUNTIMES.items())
        if runtime_name != "microvm"
    ]
