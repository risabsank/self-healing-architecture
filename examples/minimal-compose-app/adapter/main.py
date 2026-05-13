import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP_ID = os.getenv("APP_ID", "my-compose-app")
SERVICE_NAME = os.getenv("SERVICE_NAME", "web")
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://web:8080").rstrip("/")

app = FastAPI(title="Minimal Self-Healing Adapter")


class ActionRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


@app.get("/adapter/capabilities")
def capabilities():
    return {
        "app_id": APP_ID,
        "service": SERVICE_NAME,
        "actions": {
            "RESTART_SERVICE": {
                "required_params": ["service"],
                "parameter_allowlists": {},
            }
        },
    }


@app.get("/adapter/state")
async def state():
    return {"app_id": APP_ID, "service": SERVICE_NAME, "health": await target("GET", "/health")}


@app.post("/adapter/actions/{action_type}")
async def action(action_type: str, request: ActionRequest):
    if action_type != "RESTART_SERVICE":
        raise HTTPException(status_code=404, detail="Unsupported action")
    if request.params.get("service") != SERVICE_NAME:
        raise HTTPException(status_code=400, detail="Service is not managed by this adapter")
    return await target("POST", "/runtime/restart")


@app.post("/adapter/rollback/{rollback_id}")
def rollback(rollback_id: str):
    return {"status": "noop", "rollback_id": rollback_id}


async def target(method: str, path: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.request(method, f"{WEB_BASE_URL}{path}")
            body = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Target request failed: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=body)
    return body
