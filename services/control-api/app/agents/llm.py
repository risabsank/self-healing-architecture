import json
import re
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings


DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
MODEL_ALIASES = {
    # Older local docs used this alias. Anthropic now returns 404 for it in
    # some accounts/regions, so normalize it before sending the request.
    "claude-3-5-sonnet-latest": DEFAULT_ANTHROPIC_MODEL,
}


class AnthropicAPIError(RuntimeError):
    pass


class ClaudeClient:
    def __init__(self) -> None:
        self.enabled = settings.llm_reasoning_enabled and bool(settings.anthropic_api_key)
        self.model = resolve_model(settings.anthropic_model)

    def complete_json(self, system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if not self.enabled:
            raise RuntimeError("Claude reasoning is not configured")

        response = self.request(system, prompt)
        return schema.model_validate(json.loads(extract_json(response)))

    def request(self, system: str, prompt: str) -> str:
        body = {
            "model": self.model,
            "max_tokens": 1600,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with httpx.Client(timeout=settings.anthropic_timeout_seconds) as client:
            response = client.post(settings.anthropic_api_url, headers=headers, json=body)
            raise_for_anthropic_status(response, self.model)
            payload = response.json()

        return extract_text(payload)


def resolve_model(model: str | None) -> str:
    configured = (model or DEFAULT_ANTHROPIC_MODEL).strip()
    return MODEL_ALIASES.get(configured, configured)


def raise_for_anthropic_status(response: httpx.Response, model: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:600] if response.text else ""
        raise AnthropicAPIError(
            f"Anthropic request failed with HTTP {response.status_code} for model {model!r}: {detail}"
        ) from exc


def extract_text(payload: dict[str, Any]) -> str:
    parts = payload.get("content") or []
    text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
    if not text:
        raise ValueError("Claude response did not contain text")
    return text.strip()


def extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def incident_system_prompt() -> str:
    return """
You are an autonomous incident response agent for a sandboxed software runtime.
Return only valid JSON matching the requested schema.
Do not include hidden chain-of-thought. Use concise structured reasoning summaries.
Only propose actions from this allowlist:
SET_ENV_VAR, RESTART_SERVICE, DISABLE_FEATURE_FLAG, SWITCH_DEPENDENCY_TO_MOCK, ROLLBACK_CONFIG.
All mitigation params must include the affected service name from the evidence or app manifest.
Risk scores must be between 0 and 1.
""".strip()


def repair_system_prompt() -> str:
    return """
You are a durable repair planner for a self-healing runtime.
Return only valid JSON matching the requested schema.
Do not include hidden chain-of-thought. Use concise repair summaries.
Generate real bounded patches when evidence clearly supports a code/config repair.
Use only approved repository paths supplied in the prompt.
Each operation must replace the full file content for one approved path.
Prefer small, reviewable edits. Risky code changes must set requires_approval=true.
""".strip()
