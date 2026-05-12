#!/usr/bin/env python3
"""Run the bad-feature-flag incident recovery walkthrough.

The script uses only public Control API endpoints. It is intentionally strict:
the incident diagnosis must be produced by the Claude-backed agent path unless
`--allow-deterministic` is passed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API = "http://127.0.0.1:8000"
SCENARIO = "bad_feature_flag"
SANDBOX_ID = "local-docker"


@dataclass
class RunContext:
    api: str
    allow_deterministic: bool
    incident_id: str | None = None
    repair_id: str | None = None
    rollout_id: str | None = None


def main() -> int:
    args = parse_args()
    context = RunContext(args.api.rstrip("/"), args.allow_deterministic)

    if args.start_stack:
        run(["docker", "compose", "-f", "infra/docker-compose.yml", "up", "-d", "--build"])

    wait_for_control_api(context.api, args.timeout)
    assert_llm_ready(context)

    reset_scenarios(context)
    run_incident_response(context)
    inspect_incident(context)
    plan_repair(context)
    approve_apply_verify(context)
    release_through_canary(context, args.traffic)
    confirm_memory(context)

    if not args.keep_patch:
        rollback_generated_patch(context)

    print("\nBad feature flag incident recovery completed.")
    print_kv({
        "incident_id": context.incident_id,
        "repair_id": context.repair_id,
        "canary_rollout_id": context.rollout_id,
        "dashboard": "http://localhost:3000",
    })
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bad-feature-flag recovery walkthrough.")
    parser.add_argument("--api", default=API, help=f"Control API base URL. Default: {API}")
    parser.add_argument("--traffic", type=float, default=10.0, help="Synthetic canary traffic percentage. Default: 10")
    parser.add_argument("--timeout", type=int, default=90, help="Seconds to wait for the Control API. Default: 90")
    parser.add_argument("--start-stack", action="store_true", help="Build and start Docker Compose before running.")
    parser.add_argument("--keep-patch", action="store_true", help="Leave generated local patch files applied after completion.")
    parser.add_argument(
        "--allow-deterministic",
        action="store_true",
        help="Allow deterministic fallback when Claude is not configured. Not recommended for the full walkthrough.",
    )
    return parser.parse_args()


def assert_llm_ready(context: RunContext) -> None:
    health = get(context, "/health")
    reasoning = health.get("checks", {}).get("reasoning", {})
    llm_ready = reasoning.get("llm_enabled") and reasoning.get("anthropic_key_configured")
    if llm_ready or context.allow_deterministic:
        print_kv({
            "llm_enabled": reasoning.get("llm_enabled"),
            "anthropic_key_configured": reasoning.get("anthropic_key_configured"),
            "model": reasoning.get("model"),
        })
        return
    raise SystemExit(
        "Claude-backed reasoning is not configured. Set LLM_REASONING_ENABLED=true "
        "and ANTHROPIC_API_KEY before running this incident walkthrough."
    )


def reset_scenarios(context: RunContext) -> None:
    step("Reset target runtime state")
    post(context, f"/sandboxes/{SANDBOX_ID}/scenarios/reset")


def run_incident_response(context: RunContext) -> None:
    step("Inject bad feature flag and let the LLM incident agent recover service")
    result = post(context, "/evaluations/run", {
        "scenarios": [SCENARIO],
        "repeats": 1,
        "auto_approve_actions": True,
    })
    case = first(result.get("cases"), "evaluation case")
    analysis = case.get("result", {}).get("analysis", {})
    provider = analysis.get("reasoning_provider")
    if provider != "claude" and not context.allow_deterministic:
        raise SystemExit(f"Expected Claude incident reasoning, got {provider!r}")

    context.incident_id = case["incident_id"]
    print_kv({
        "evaluation_status": result["status"],
        "incident_id": context.incident_id,
        "reasoning_provider": provider,
        "diagnosed_root_cause": case.get("diagnosed_root_cause"),
        "selected_action": case.get("selected_action"),
        "first_action_success": case.get("metrics", {}).get("first_action_success"),
    })


def inspect_incident(context: RunContext) -> None:
    step("Inspect structured incident artifacts")
    incident_id = required(context.incident_id, "incident_id")
    incident = get(context, f"/incidents/{incident_id}")
    evidence = get(context, f"/incidents/{incident_id}/evidence").get("evidence", [])
    hypotheses = get(context, f"/incidents/{incident_id}/hypotheses").get("hypotheses", [])
    actions = get(context, f"/incidents/{incident_id}/actions").get("actions", [])
    print_kv({
        "incident_status": incident["status"],
        "root_cause": incident.get("root_cause"),
        "evidence_items": len(evidence),
        "top_hypothesis": hypotheses[0]["cause"] if hypotheses else None,
        "bounded_actions": ", ".join(action["action_type"] for action in actions) or "none",
    })


def plan_repair(context: RunContext) -> None:
    step("Generate durable repair with diff preview")
    repair = post(context, f"/incidents/{required(context.incident_id, 'incident_id')}/repairs/plan")
    context.repair_id = repair["id"]
    result = repair.get("result") or {}
    provider = result.get("planning_provider")
    if provider != "claude" and not context.allow_deterministic:
        raise SystemExit(f"Expected Claude repair planning, got {provider!r}")

    diff = get(context, f"/repairs/{context.repair_id}/diff")
    previews = diff.get("patch_preview", [])
    print_kv({
        "repair_id": context.repair_id,
        "repair_status": repair["status"],
        "repair_planning_provider": provider,
        "change_type": repair["change_type"],
        "requires_approval": repair["requires_approval"],
        "patch_files": ", ".join(item["path"] for item in previews) or "none",
        "owners": ", ".join(f"{item['path']}={item['owner']}" for item in diff.get("path_ownership", [])) or "none",
    })
    if previews:
        print("\nFirst diff preview:\n")
        print(previews[0]["diff"].rstrip())


def approve_apply_verify(context: RunContext) -> None:
    repair_id = required(context.repair_id, "repair_id")
    step("Approve and apply bounded repair")
    approved = post(context, f"/repairs/{repair_id}/approve")
    applied = post(context, f"/repairs/{repair_id}/apply")
    print_kv({
        "approved_status": approved["status"],
        "applied_status": applied["status"],
        "applied_paths": ", ".join(item["path"] for item in applied.get("result", {}).get("applied", [])),
    })

    step("Run verification gates")
    verification = post(context, f"/repairs/{repair_id}/verify")
    checks = verification.get("checks", [])
    if verification["status"] != "passed":
        raise SystemExit(f"Verification failed: {json.dumps(checks, indent=2)}")
    print_kv({
        "verification_status": verification["status"],
        "checks": ", ".join(f"{check['name']}={check['status']}" for check in checks),
    })


def release_through_canary(context: RunContext, traffic: float) -> None:
    step("Release through synthetic canary")
    rollout = post(context, f"/repairs/{required(context.repair_id, 'repair_id')}/canary-rollouts/start?traffic_percentage={traffic}")
    context.rollout_id = rollout["id"]
    signals = rollout.get("health_signals") or {}
    if rollout.get("decision") != "promote":
        raise SystemExit(f"Canary did not promote: {json.dumps(rollout, indent=2)}")
    print_kv({
        "rollout_id": context.rollout_id,
        "rollout_status": rollout["status"],
        "decision": rollout.get("decision"),
        "passed_probes": signals.get("passed"),
        "failed_probes": signals.get("failed"),
        "error_rate": signals.get("error_rate"),
    })


def confirm_memory(context: RunContext) -> None:
    step("Confirm incident memory was written and is searchable")
    incident = get(context, f"/incidents/{required(context.incident_id, 'incident_id')}")
    query = urllib.parse.quote(incident.get("root_cause") or SCENARIO)
    matches = get(context, f"/memory/search?query={query}&limit=3").get("memories", [])
    if not matches:
        raise SystemExit("Expected at least one searchable incident memory")
    print_kv({
        "memory_matches": len(matches),
        "top_memory_root_cause": matches[0].get("root_cause"),
        "top_memory_score": matches[0].get("similarity_score"),
    })


def rollback_generated_patch(context: RunContext) -> None:
    step("Restore local repository files for repeatable walkthroughs")
    rolled_back = post(context, f"/repairs/{required(context.repair_id, 'repair_id')}/rollback")
    print_kv({"rollback_status": rolled_back["status"]})


def wait_for_control_api(api: str, timeout_seconds: int) -> None:
    step("Wait for Control API")
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            health = request_json("GET", f"{api}/health")
            print_kv({"control_api": health.get("status")})
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise SystemExit(f"Control API did not become ready: {last_error}")


def get(context: RunContext, path: str) -> dict[str, Any]:
    return request_json("GET", f"{context.api}{path}")


def post(context: RunContext, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return request_json("POST", f"{context.api}{path}", body)


def request_json(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"{method} {url} failed with {exc.code}: {detail}") from exc


def run(command: list[str]) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True)


def step(title: str) -> None:
    print(f"\n== {title} ==")


def print_kv(values: dict[str, Any]) -> None:
    for key, value in values.items():
        print(f"{key}: {value}")


def first(items: list[dict[str, Any]] | None, label: str) -> dict[str, Any]:
    if not items:
        raise SystemExit(f"Expected at least one {label}")
    return items[0]


def required(value: str | None, label: str) -> str:
    if not value:
        raise SystemExit(f"Missing {label}; previous step did not complete")
    return value


if __name__ == "__main__":
    sys.exit(main())
