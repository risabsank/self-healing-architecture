from dataclasses import dataclass
from typing import Any


class ActionPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class AllowedAction:
    action_type: str
    description: str
    required_params: tuple[str, ...]
    max_autonomous_risk: float
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


def list_allowed_actions() -> list[dict[str, Any]]:
    return [
        {
            "action_type": action.action_type,
            "description": action.description,
            "required_params": list(action.required_params),
            "max_autonomous_risk": action.max_autonomous_risk,
            "approval_required": action.approval_required,
        }
        for action in ALLOWED_ACTIONS.values()
    ]


def validate_action_policy(
    action_type: str,
    params: dict[str, Any],
    risk_score: float,
    requires_approval: bool,
) -> AllowedAction:
    action = ALLOWED_ACTIONS.get(action_type)
    if not action:
        raise ActionPolicyError(f"Action type is not allowlisted: {action_type}")

    missing_params = [key for key in action.required_params if key not in params]
    if missing_params:
        raise ActionPolicyError(f"Action is missing required parameters: {', '.join(missing_params)}")

    if action.approval_required and not requires_approval:
        raise ActionPolicyError(f"{action_type} must require approval")

    if not requires_approval and risk_score > action.max_autonomous_risk:
        raise ActionPolicyError(
            f"{action_type} risk score {risk_score} exceeds autonomous limit {action.max_autonomous_risk}"
        )

    if action_type == "SET_ENV_VAR" and params["key"] not in RESTORABLE_ENV_KEYS:
        raise ActionPolicyError(f"Environment key is not restorable through this executor: {params['key']}")

    if action_type == "DISABLE_FEATURE_FLAG" and params["flag"] not in DISABLEABLE_FLAGS:
        raise ActionPolicyError(f"Feature flag is not managed by this executor: {params['flag']}")

    if action_type == "SWITCH_DEPENDENCY_TO_MOCK" and params["dependency"] not in SWITCHABLE_DEPENDENCIES:
        raise ActionPolicyError(f"Dependency is not switchable through this executor: {params['dependency']}")

    if action_type == "ROLLBACK_CONFIG" and params["target"] not in ROLLBACK_TARGETS:
        raise ActionPolicyError(f"Rollback target is not allowlisted: {params['target']}")

    return action
