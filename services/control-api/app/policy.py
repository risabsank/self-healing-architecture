from dataclasses import dataclass
from typing import Any, Literal


Autonomy = Literal["autonomous", "approval_required", "blocked"]
BlastRadius = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class PolicyDecision:
    decision: Autonomy
    risk_score: float
    reasons: list[str]
    requirements: list[str]
    rollback_available: bool
    blast_radius: BlastRadius

    @property
    def allowed(self) -> bool:
        return self.decision != "blocked"

    def model_dump(self) -> dict[str, Any]:
        return self.__dict__


def evaluate_policy(
    *,
    capability: str,
    action_type: str,
    risk_score: float,
    evidence_count: int,
    rollback_available: bool,
    blast_radius: BlastRadius,
    max_autonomous_risk: float = 0.35,
    min_evidence: int = 1,
    approval_required: bool = False,
) -> PolicyDecision:
    if evidence_count < min_evidence:
        return PolicyDecision(
            "blocked",
            risk_score,
            [f"{capability}:{action_type} has insufficient evidence"],
            [f"at least {min_evidence} evidence item(s) required"],
            rollback_available,
            blast_radius,
        )

    if risk_score >= 0.85:
        return PolicyDecision(
            "blocked",
            risk_score,
            [f"{capability}:{action_type} risk is too high"],
            ["human redesign required"],
            rollback_available,
            blast_radius,
        )

    if blast_radius == "high" and not rollback_available:
        return PolicyDecision(
            "blocked",
            risk_score,
            [f"{capability}:{action_type} has high blast radius without rollback"],
            ["rollback plan required"],
            rollback_available,
            blast_radius,
        )

    reasons = approval_reasons(approval_required, risk_score, max_autonomous_risk, rollback_available, blast_radius)

    if reasons:
        requirements = ["operator approval"]
        if not rollback_available:
            requirements.append("explicit rollback or recovery plan")
        return PolicyDecision("approval_required", risk_score, reasons, requirements, rollback_available, blast_radius)

    return PolicyDecision(
        "autonomous",
        risk_score,
        [f"{capability}:{action_type} is low risk, evidenced, and bounded"],
        [],
        rollback_available,
        blast_radius,
    )


def approval_reasons(
    approval_required: bool,
    risk_score: float,
    max_autonomous_risk: float,
    rollback_available: bool,
    blast_radius: BlastRadius,
) -> list[str]:
    reasons = []
    if approval_required:
        reasons.append("capability requires approval by policy")
    if risk_score > max_autonomous_risk:
        reasons.append(f"risk {risk_score:.2f} exceeds autonomous limit {max_autonomous_risk:.2f}")
    if blast_radius in {"medium", "high"}:
        reasons.append(f"{blast_radius} blast radius requires operator review")
    if not rollback_available:
        reasons.append("rollback is unavailable")
    return reasons
