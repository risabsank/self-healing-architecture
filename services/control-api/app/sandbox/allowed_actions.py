from dataclasses import dataclass
from typing import Any

from app.policy import BlastRadius, PolicyDecision, evaluate_policy


class ActionPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class AllowedAction:
    action_type: str
    description: str
    required_params: tuple[str, ...]
    max_autonomous_risk: float
    blast_radius: BlastRadius = "low"
    rollback_available: bool = True
    approval_required: bool = False


ALLOWED_ACTIONS: dict[str, AllowedAction] = {
    "SET_ENV_VAR": AllowedAction(
        action_type="SET_ENV_VAR",
        description="Restore a known-good runtime configuration value.",
        required_params=("service", "key", "value_from"),
        max_autonomous_risk=0.35,
    ),
    "RESTART_SERVICE": AllowedAction(
        action_type="RESTART_SERVICE",
        description="Request a bounded service restart through the sandbox runtime adapter.",
        required_params=("service",),
        max_autonomous_risk=0.35,
    ),
    "DISABLE_FEATURE_FLAG": AllowedAction(
        action_type="DISABLE_FEATURE_FLAG",
        description="Disable a known feature flag through a typed runtime action.",
        required_params=("service", "flag"),
        max_autonomous_risk=0.35,
    ),
    "SWITCH_DEPENDENCY_TO_MOCK": AllowedAction(
        action_type="SWITCH_DEPENDENCY_TO_MOCK",
        description="Route a known dependency to a sandbox fallback implementation.",
        required_params=("service", "dependency"),
        max_autonomous_risk=0.35,
    ),
    "ROLLBACK_CONFIG": AllowedAction(
        action_type="ROLLBACK_CONFIG",
        description="Return runtime configuration to a previous known-good version.",
        required_params=("service", "target"),
        max_autonomous_risk=0.0,
        blast_radius="medium",
        approval_required=True,
    ),
}


RESTORABLE_ENV_KEYS = {
    "DATABASE_URL",
    "TARGET_REQUIRED_SECRET",
}

DISABLEABLE_FLAGS = {
    "FEATURE_CHECKOUT_ENABLED",
}

SWITCHABLE_DEPENDENCIES = {
    "checkout-provider",
}

ROLLBACK_TARGETS = {
    "previous_known_good_app_version",
}

PARAM_ALLOWLISTS = {
    "SET_ENV_VAR": ("key", RESTORABLE_ENV_KEYS, "Environment key is not restorable through this executor"),
    "DISABLE_FEATURE_FLAG": ("flag", DISABLEABLE_FLAGS, "Feature flag is not managed by this executor"),
    "SWITCH_DEPENDENCY_TO_MOCK": ("dependency", SWITCHABLE_DEPENDENCIES, "Dependency is not switchable through this executor"),
    "ROLLBACK_CONFIG": ("target", ROLLBACK_TARGETS, "Rollback target is not allowlisted"),
}


def list_allowed_actions() -> list[dict[str, Any]]:
    return [
        {
            "action_type": action.action_type,
            "description": action.description,
            "required_params": list(action.required_params),
            "max_autonomous_risk": action.max_autonomous_risk,
            "blast_radius": action.blast_radius,
            "rollback_available": action.rollback_available,
            "approval_required": action.approval_required,
        }
        for action in ALLOWED_ACTIONS.values()
    ]


def validate_action_policy(
    action_type: str,
    params: dict[str, Any],
    risk_score: float,
    requires_approval: bool,
    manifest_action: dict[str, Any] | None = None,
) -> tuple[AllowedAction, PolicyDecision]:
    if manifest_action:
        return validate_manifest_action_policy(action_type, params, risk_score, requires_approval, manifest_action)

    action = ALLOWED_ACTIONS.get(action_type)
    if not action:
        raise ActionPolicyError(f"Action type is not allowlisted: {action_type}")

    missing_params = [key for key in action.required_params if key not in params]
    if missing_params:
        raise ActionPolicyError(f"Action is missing required parameters: {', '.join(missing_params)}")

    validate_param_allowlist(action_type, params)

    policy = evaluate_policy(
        capability="runtime_mitigation",
        action_type=action_type,
        risk_score=risk_score,
        evidence_count=1,
        rollback_available=action.rollback_available,
        blast_radius=action.blast_radius,
        max_autonomous_risk=action.max_autonomous_risk,
        approval_required=action.approval_required or requires_approval,
    )
    if policy.decision == "blocked":
        raise ActionPolicyError("; ".join(policy.reasons))
    if policy.decision == "approval_required" and not requires_approval:
        raise ActionPolicyError("Action requires approval before execution")

    return action, policy


def validate_manifest_action_policy(
    action_type: str,
    params: dict[str, Any],
    risk_score: float,
    requires_approval: bool,
    manifest_action: dict[str, Any],
) -> tuple[AllowedAction, PolicyDecision]:
    if manifest_action["action_type"] != action_type:
        raise ActionPolicyError(f"Action type is not allowlisted for this app: {action_type}")

    missing_params = [key for key in manifest_action.get("required_params", []) if key not in params]
    if missing_params:
        raise ActionPolicyError(f"Action is missing required parameters: {', '.join(missing_params)}")

    for key, allowed_values in (manifest_action.get("parameter_allowlists") or {}).items():
        if params.get(key) not in allowed_values:
            raise ActionPolicyError(f"Parameter is not allowlisted for this app: {key}={params.get(key)}")

    action = AllowedAction(
        action_type=manifest_action["action_type"],
        description=manifest_action.get("description") or "Application-scoped bounded action.",
        required_params=tuple(manifest_action.get("required_params") or ()),
        max_autonomous_risk=float(manifest_action.get("max_autonomous_risk", 0.35)),
        blast_radius=manifest_action.get("blast_radius", "low"),
        rollback_available=bool(manifest_action.get("rollback_available", True)),
        approval_required=bool(manifest_action.get("approval_required", False)),
    )
    policy = evaluate_policy(
        capability="runtime_mitigation",
        action_type=action_type,
        risk_score=risk_score,
        evidence_count=1,
        rollback_available=action.rollback_available,
        blast_radius=action.blast_radius,
        max_autonomous_risk=action.max_autonomous_risk,
        approval_required=action.approval_required or requires_approval,
    )
    if policy.decision == "blocked":
        raise ActionPolicyError("; ".join(policy.reasons))
    if policy.decision == "approval_required" and not requires_approval:
        raise ActionPolicyError("Action requires approval before execution")
    return action, policy


def validate_param_allowlist(action_type: str, params: dict[str, Any]) -> None:
    rule = PARAM_ALLOWLISTS.get(action_type)
    if not rule:
        return
    key, allowed_values, message = rule
    if params[key] not in allowed_values:
        raise ActionPolicyError(f"{message}: {params[key]}")
