from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: Literal["healthcheck", "runtime_event", "service_metadata", "scenario", "memory"]
    kind: str
    summary: str
    content: dict[str, Any] = Field(default_factory=dict)
    confidence: float


class Hypothesis(BaseModel):
    cause: str
    evidence_indexes: list[int]
    confidence: float
    rationale_summary: str


class MitigationCandidate(BaseModel):
    action_type: str
    params: dict[str, Any]
    expected_effect: str
    risk_score: float
    requires_approval: bool
    rank: int


class IncidentAnalysis(BaseModel):
    incident_id: str
    sandbox_id: str
    status: str
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    mitigations: list[MitigationCandidate] = Field(default_factory=list)
    selected_mitigation: MitigationCandidate | None = None
    reasoning_summary: str | None = None
    reasoning_provider: str = "deterministic"


class LLMIncidentDecision(BaseModel):
    reasoning_summary: str
    hypotheses: list[Hypothesis]
    mitigations: list[MitigationCandidate]


class LLMPatchOperation(BaseModel):
    path: str
    content: str


class LLMRepairDecision(BaseModel):
    change_type: Literal["code_patch", "config_patch", "test_only", "no_durable_change"]
    patch_summary: str
    affected_paths: list[str]
    risk_score: float = Field(ge=0, le=1)
    requires_approval: bool
    verification_plan: list[str]
    rollback_plan: str
    operations: list[LLMPatchOperation] = Field(default_factory=list)
