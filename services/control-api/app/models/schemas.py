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
    app_id: str | None = None
    service_name: str | None = None
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    trigger_source: str = "manual"


class HealthCheckResult(BaseModel):
    sandbox_id: str
    service_name: str
    status: Literal["healthy", "unhealthy", "unknown"]
    latency_ms: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class AppServiceManifest(BaseModel):
    name: str
    service_type: str = "web"
    base_url: str
    health_url: str
    public_url: str | None = None
    adapter_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProbeManifest(BaseModel):
    name: str
    service: str
    method: Literal["GET", "POST"] = "GET"
    path: str
    expected_status_lt: int = 500
    healthy_status: str | None = None


class SafeActionManifest(BaseModel):
    action_type: str
    service: str
    description: str
    required_params: list[str]
    parameter_allowlists: dict[str, list[str]] = Field(default_factory=dict)
    adapter_path: str
    max_autonomous_risk: float = Field(ge=0, le=1, default=0.35)
    blast_radius: Literal["low", "medium", "high"] = "low"
    rollback_available: bool = True
    approval_required: bool = False
    clears_scenarios: list[str] = Field(default_factory=list)


class RepairPolicyManifest(BaseModel):
    approved_paths: list[str] = Field(default_factory=list)
    path_owners: dict[str, str] = Field(default_factory=dict)
    test_commands: list[list[str]] = Field(default_factory=list)
    build_commands: list[list[str]] = Field(default_factory=list)
    rollback_strategy: str = "Apply generated rollback operations."


class MetricSourceManifest(BaseModel):
    name: str
    description: str | None = None
    unit: str | None = None


class SloTargetManifest(BaseModel):
    name: str
    metric: str
    target: float
    comparator: Literal["<=", ">=", "<", ">", "=="] = "<="
    window: str = "5m"
    severity: Literal["low", "medium", "high", "critical"] = "high"
    description: str | None = None


class ApplicationManifest(BaseModel):
    app_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    display_name: str
    environment: str = "local"
    sandbox_id: str = "local-docker"
    services: list[AppServiceManifest]
    health_checks: list[ProbeManifest] = Field(default_factory=list)
    critical_probes: list[ProbeManifest] = Field(default_factory=list)
    safe_actions: list[SafeActionManifest] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    repair_policy: RepairPolicyManifest = Field(default_factory=RepairPolicyManifest)
    repo: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    canary: dict[str, Any] = Field(default_factory=dict)
    metric_sources: list[MetricSourceManifest] = Field(default_factory=list)
    slo_targets: list[SloTargetManifest] = Field(default_factory=list)


class MetricObservationCreate(BaseModel):
    metric_name: str
    value: float
    unit: str | None = None
    source: str = "api"
    labels: dict[str, Any] = Field(default_factory=dict)


class OperatorNoteCreate(BaseModel):
    note: str = Field(min_length=3)
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    service_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)
