from typing import Any, Literal

from pydantic import BaseModel, Field


class SandboxCreate(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    name: str
    runtime: str = "docker-compose"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentCreate(BaseModel):
    sandbox_id: str
    title: str
    status: Literal["detected", "investigating", "resolved", "failed", "blocked"] = "detected"


class HealthCheckResult(BaseModel):
    sandbox_id: str
    service_name: str
    status: Literal["healthy", "unhealthy", "unknown"]
    latency_ms: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
