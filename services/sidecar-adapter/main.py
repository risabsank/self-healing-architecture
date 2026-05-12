import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


TARGET_BASE_URL = os.getenv("TARGET_BASE_URL", "http://target-api:8001").rstrip("/")
APP_ID = os.getenv("APP_ID", "breakable-target")
SERVICE_NAME = os.getenv("SERVICE_NAME", "target-api")

ACTION_CAPABILITIES = {
    "SET_ENV_VAR": {
        "required_params": ["service", "key", "value_from"],
        "parameter_allowlists": {"key": ["DATABASE_URL", "TARGET_REQUIRED_SECRET"]},
    },
    "RESTART_SERVICE": {"required_params": ["service"], "parameter_allowlists": {}},
    "DISABLE_FEATURE_FLAG": {
        "required_params": ["service", "flag"],
        "parameter_allowlists": {"flag": ["FEATURE_CHECKOUT_ENABLED"]},
    },
    "SWITCH_DEPENDENCY_TO_MOCK": {
        "required_params": ["service", "dependency"],
        "parameter_allowlists": {"dependency": ["checkout-provider"]},
    },
    "ROLLBACK_CONFIG": {
        "required_params": ["service", "target"],
        "parameter_allowlists": {"target": ["previous_known_good_app_version"]},
    },
}


class ActionRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    rollback_id: str | None = None


app = FastAPI(
    title="Self-Healing Sidecar Adapter",
    description="Bounded runtime action adapter for Docker Compose applications.",
    version="0.1.0",
)


@app.get("/adapter/capabilities")
def capabilities():
    return {"app_id": APP_ID, "service": SERVICE_NAME, "actions": ACTION_CAPABILITIES}


@app.get("/adapter/state")
async def state():
    health, scenarios = await fetch_many("/health", "/scenarios")
    return {"app_id": APP_ID, "service": SERVICE_NAME, "health": health, "scenarios": scenarios}


@app.post("/adapter/actions/{action_type}")
async def execute_action(action_type: str, request: ActionRequest):
    validate_action(action_type, request.params)
    params = request.params

    if action_type == "SET_ENV_VAR":
        scenario = {"DATABASE_URL": "bad_database_url", "TARGET_REQUIRED_SECRET": "missing_required_env"}[params["key"]]
        return await target_request("POST", "/runtime/config/restore", {"key": params["key"], "scenario": scenario})
    if action_type == "RESTART_SERVICE":
        return await target_request("POST", "/runtime/restart", {"service": params["service"]})
    if action_type == "DISABLE_FEATURE_FLAG":
        return await target_request("POST", f"/runtime/feature-flags/{params['flag']}/disable", {})
    if action_type == "SWITCH_DEPENDENCY_TO_MOCK":
        return await target_request("POST", f"/runtime/dependencies/{params['dependency']}/switch-to-mock", {})
    if action_type == "ROLLBACK_CONFIG":
        return await target_request("POST", "/runtime/config/rollback", {"target": params["target"]})

    raise HTTPException(status_code=404, detail="Unsupported action")


@app.post("/adapter/rollback/{rollback_id}")
async def rollback(rollback_id: str):
    # The reference adapter has no long-lived runtime rollback state. Real
    # adapters can map rollback ids to platform-native revert operations.
    return {"status": "noop", "rollback_id": rollback_id, "app_id": APP_ID}


def validate_action(action_type: str, params: dict[str, Any]) -> None:
    capability = ACTION_CAPABILITIES.get(action_type)
    if not capability:
        raise HTTPException(status_code=404, detail="Unsupported action")
    if params.get("service") != SERVICE_NAME:
        raise HTTPException(status_code=400, detail="Service is not managed by this adapter")

    missing = [name for name in capability["required_params"] if name not in params]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required params: {', '.join(missing)}")

    for key, allowed in capability["parameter_allowlists"].items():
        if params.get(key) not in allowed:
            raise HTTPException(status_code=400, detail=f"Parameter is not allowlisted: {key}={params.get(key)}")


async def fetch_many(*paths: str) -> tuple[dict[str, Any], ...]:
    return tuple([await target_request("GET", path, None) for path in paths])


async def target_request(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(method, f"{TARGET_BASE_URL}{path}", json=payload)
            body = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Target request failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Target returned non-JSON response") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=body)
    return body
