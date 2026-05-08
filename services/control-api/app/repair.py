from typing import Any, Literal

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.agents.repair_llm import plan_repair_with_claude
from app.core.config import settings
from app.observability import record_incident_event
from app.patching import (
    PatchOperation,
    apply_operations,
    approved_paths,
    build_patch_set,
    ensure_operations_are_allowed,
    path_ownership,
    read_approved_file,
    repo_root,
    rollback_operations,
)
from app.policy import PolicyDecision, evaluate_policy


RepairStatus = Literal[
    "planned",
    "awaiting_approval",
    "approved",
    "patch_applied",
    "rejected",
    "blocked",
    "verified",
    "verification_failed",
    "released",
    "rolled_back",
]
REGRESSION_TEST_PATH = "target-app/api/tests/test_runtime_regressions.py"
TARGET_API_PATH = "target-app/api/main.py"
DEFAULT_TEST_COMMAND = "python -m unittest discover target-app/api/tests"


class RepairPlan(BaseModel):
    change_type: Literal["code_patch", "config_patch", "test_only", "no_durable_change"]
    patch_summary: str
    affected_paths: list[str]
    risk_score: float = Field(ge=0, le=1)
    requires_approval: bool
    verification_plan: list[str]
    rollback_plan: str
    operations: list[PatchOperation] = Field(default_factory=list)


REPAIR_RULES = [
    {
        "tokens": ("database",),
        "summary": "Add regression coverage for unreachable database configuration failures.",
        "test_body": "bad_database_url",
        "verification": "bad_database_url regression test",
    },
    {
        "tokens": ("schema",),
        "summary": "Add regression coverage for schema mismatch health failures.",
        "test_body": "schema_mismatch",
        "verification": "schema_mismatch regression test",
    },
    {
        "tokens": ("feature flag", "rate limit"),
        "summary": "Add regression coverage for checkout feature isolation.",
        "test_body": "checkout_disabled",
        "verification": "checkout feature isolation regression test",
    },
]


REGRESSION_TESTS = {
    "bad_database_url": '''    def test_bad_database_url_marks_health_unhealthy(self):
        main.ACTIVE_SCENARIOS.add("bad_database_url")

        body = main.health()

        self.assertEqual(body["status"], "unhealthy")
        self.assertFalse(body["checks"]["database"]["ok"])
        self.assertIn("simulated database connection failure", body["checks"]["database"]["message"])
''',
    "schema_mismatch": '''    def test_schema_mismatch_marks_health_unhealthy(self):
        main.ACTIVE_SCENARIOS.add("schema_mismatch")

        body = main.health()

        self.assertEqual(body["status"], "unhealthy")
        self.assertFalse(body["checks"]["database"]["ok"])
        self.assertIn("schema mismatch", body["checks"]["database"]["message"])
''',
    "checkout_disabled": '''    def test_disabled_checkout_returns_disabled_status(self):
        main.FEATURE_CHECKOUT_ENABLED = False

        body = main.checkout_probe()

        self.assertEqual(body, {"status": "disabled"})
''',
}


CODE_PATCH_RULES = [
    {
        "tokens": ("feature flag", "checkout"),
        "summary": "Make the checkout feature flag failure degrade safely instead of returning a 500.",
        "old": """    if "bad_feature_flag" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=500, detail="simulated feature flag failure in checkout path")
""",
        "new": """    if "bad_feature_flag" in ACTIVE_SCENARIOS:
        return {"status": "disabled", "reason": "feature flag isolated by durable repair"}
""",
        "test_body": '''    def test_bad_feature_flag_degrades_without_500(self):
        main.ACTIVE_SCENARIOS.add("bad_feature_flag")

        body = main.checkout_probe()

        self.assertEqual(body, {"status": "disabled", "reason": "feature flag isolated by durable repair"})
''',
    },
    {
        "tokens": ("dependency", "unavailable"),
        "summary": "Make checkout dependency outages return a bounded degraded response.",
        "old": """    if "dependency_unavailable" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=503, detail="simulated downstream dependency unavailable")
""",
        "new": """    if "dependency_unavailable" in ACTIVE_SCENARIOS:
        return {"status": "degraded", "dependency": "checkout", "reason": "downstream dependency unavailable"}
""",
        "test_body": '''    def test_dependency_unavailable_degrades_without_exception(self):
        main.ACTIVE_SCENARIOS.add("dependency_unavailable")

        body = main.checkout_probe()

        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["dependency"], "checkout")
''',
    },
    {
        "tokens": ("rate limit", "rate-limit"),
        "summary": "Make checkout rate limits produce a retryable degraded response.",
        "old": """    if "rate_limit" in ACTIVE_SCENARIOS:
        raise HTTPException(status_code=429, detail="simulated dependency rate limit")
""",
        "new": """    if "rate_limit" in ACTIVE_SCENARIOS:
        return {"status": "degraded", "dependency": "checkout", "retryable": True, "reason": "dependency rate limit"}
""",
        "test_body": '''    def test_rate_limit_returns_retryable_degraded_response(self):
        main.ACTIVE_SCENARIOS.add("rate_limit")

        body = main.checkout_probe()

        self.assertEqual(body["status"], "degraded")
        self.assertTrue(body["retryable"])
''',
    },
]


def ensure_repair_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS repair_changes (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
              status TEXT NOT NULL,
              change_type TEXT NOT NULL,
              branch_name TEXT,
              commit_sha TEXT,
              affected_paths TEXT[] NOT NULL DEFAULT '{}',
              patch_summary TEXT NOT NULL,
              risk_score FLOAT NOT NULL,
              requires_approval BOOLEAN NOT NULL,
              verification_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
              rollback_plan TEXT NOT NULL,
              result JSONB,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_repair_changes_incident_status
            ON repair_changes (incident_id, status)
            """
        )
    conn.commit()


def create_repair_plan(conn: Connection, incident_id: str) -> dict[str, Any]:
    incident = load_incident(conn, incident_id)
    plan = plan_from_incident(conn, incident)
    result = repair_result(plan)
    policy = evaluate_repair_policy(plan)
    status = repair_status_for(policy)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repair_changes (
              incident_id, status, change_type, affected_paths, patch_summary,
              risk_score, requires_approval, verification_plan, rollback_plan, result
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                incident_id,
                status,
                plan.change_type,
                plan.affected_paths,
                plan.patch_summary,
                plan.risk_score,
                plan.requires_approval or policy.decision == "approval_required",
                Jsonb(plan.verification_plan),
                plan.rollback_plan,
                Jsonb({**result, "autonomy": policy.model_dump()}),
            ),
        )
        repair = cur.fetchone()

    record_repair_event(conn, incident, "repair.plan.created", repair)
    conn.commit()
    return repair


def list_repairs(conn: Connection, incident_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM repair_changes
            WHERE incident_id = %s
            ORDER BY created_at DESC
            """,
            (incident_id,),
        )
        return cur.fetchall()


def get_repair(conn: Connection, repair_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM repair_changes WHERE id = %s", (repair_id,))
        return cur.fetchone()


def approve_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    return update_repair_status(conn, repair_id, "approved", "repair.approved")


def reject_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    return update_repair_status(conn, repair_id, "rejected", "repair.rejected")


def repair_diff(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = require_repair(conn, repair_id)
    result = repair_result_view(repair)
    return {
        "repair_change_id": str(repair["id"]),
        **result,
    }


def apply_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = require_repair(conn, repair_id)
    block_reason = repair_block_reason(repair)
    if block_reason:
        return finish_repair(conn, repair, "blocked", "repair.blocked", {"blocked": {"reason": block_reason}})

    plan = RepairPlan.model_validate(repair["result"]["plan"])
    updated = finish_repair(conn, repair, "patch_applied", "repair.patch_applied", {
        "applied": apply_operations(plan.operations),
        "rollback_preview": build_patch_set(rollback_operations(repair))["patch_preview"],
    })
    incident = load_incident(conn, str(updated["incident_id"]))
    update_incident_memory(conn, str(incident["id"]))
    return updated


def rollback_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = require_repair(conn, repair_id)
    if repair["status"] not in {"patch_applied", "verification_failed"}:
        raise ValueError(f"Repair status does not allow rollback: {repair['status']}")
    applied = apply_operations(rollback_operations(repair))
    return finish_repair(conn, repair, "rolled_back", "repair.rolled_back", {"rollback_applied": applied})


def plan_from_incident(conn: Connection, incident: dict[str, Any]) -> RepairPlan:
    return llm_repair_plan(conn, incident) or deterministic_plan_from_incident(incident)


def repair_result(plan: RepairPlan) -> dict[str, Any]:
    ensure_operations_are_allowed(plan.operations)
    return {
        "plan": plan.model_dump(),
        **build_patch_set(plan.operations),
        "approved_paths": approved_paths(),
        "path_ownership": path_ownership(plan.operations),
    }


def repair_result_view(repair: dict[str, Any]) -> dict[str, Any]:
    result = repair["result"] or {}
    return {
        "patch_preview": result.get("patch_preview", []),
        "rollback_preview": result.get("rollback_preview", []),
        "path_ownership": result.get("path_ownership", []),
    }


def llm_repair_plan(conn: Connection, incident: dict[str, Any]) -> RepairPlan | None:
    if not settings.llm_reasoning_enabled:
        return None
    try:
        decision = plan_repair_with_claude(conn, incident, approved_paths())
        return RepairPlan.model_validate(decision.model_dump())
    except Exception:
        return None


def deterministic_plan_from_incident(incident: dict[str, Any]) -> RepairPlan:
    root_cause = (incident.get("root_cause") or incident.get("title") or "").lower()

    code_plan = code_patch_plan(root_cause)
    if code_plan:
        return code_plan

    for rule in REPAIR_RULES:
        if any(token in root_cause for token in rule["tokens"]):
            return regression_plan(rule["summary"], REGRESSION_TESTS[rule["test_body"]], rule["verification"])

    return RepairPlan(
        change_type="no_durable_change",
        patch_summary="No bounded durable repair was identified from current evidence.",
        affected_paths=[],
        risk_score=0.0,
        requires_approval=False,
        verification_plan=["review incident evidence"],
        rollback_plan="No repository changes were planned.",
        operations=[],
    )


def code_patch_plan(root_cause: str) -> RepairPlan | None:
    current = read_approved_file(TARGET_API_PATH)
    if current is None:
        return None

    for rule in CODE_PATCH_RULES:
        if not any(token in root_cause for token in rule["tokens"]):
            continue
        next_content = current.replace(rule["old"], rule["new"])
        if next_content == current:
            return None
        return RepairPlan(
            change_type="code_patch",
            patch_summary=rule["summary"],
            affected_paths=[TARGET_API_PATH, REGRESSION_TEST_PATH],
            risk_score=0.62,
            requires_approval=True,
            verification_plan=[DEFAULT_TEST_COMMAND, "review generated diff before applying"],
            rollback_plan="Apply the generated rollback patch to restore the previous file contents.",
            operations=[
                PatchOperation(path=TARGET_API_PATH, content=next_content),
                PatchOperation(path=REGRESSION_TEST_PATH, content=regression_test_content(rule["test_body"])),
            ],
        )

    return None


def regression_plan(
    summary: str,
    test_body: str,
    verification: str,
) -> RepairPlan:
    return RepairPlan(
        change_type="test_only",
        patch_summary=summary,
        affected_paths=[REGRESSION_TEST_PATH],
        risk_score=0.18,
        requires_approval=False,
        verification_plan=[DEFAULT_TEST_COMMAND, verification],
        rollback_plan=f"Remove or revert {REGRESSION_TEST_PATH}.",
        operations=[PatchOperation(path=REGRESSION_TEST_PATH, content=regression_test_content(test_body))],
    )


def load_incident(conn: Connection, incident_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,))
        incident = cur.fetchone()
    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")
    return incident


def require_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = get_repair(conn, repair_id)
    if not repair:
        raise ValueError(f"Repair not found: {repair_id}")
    return repair


def update_repair_status(conn: Connection, repair_id: str, status: RepairStatus, event_type: str) -> dict[str, Any]:
    repair = require_repair(conn, repair_id)
    return finish_repair(conn, repair, status, event_type)


def finish_repair(
    conn: Connection,
    repair: dict[str, Any],
    status: RepairStatus,
    event_type: str,
    result_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {**(repair["result"] or {}), **(result_update or {})}
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE repair_changes
            SET status = %s, result = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, Jsonb(result), repair["id"]),
        )
        updated = cur.fetchone()
    incident = load_incident(conn, str(repair["incident_id"]))
    record_repair_event(conn, incident, event_type, updated)
    conn.commit()
    return updated


def repair_block_reason(repair: dict[str, Any]) -> str | None:
    if repair["requires_approval"] and repair["status"] != "approved":
        return "Repair requires approval before patch application"
    if repair["status"] not in {"planned", "approved"}:
        return f"Repair status does not allow application: {repair['status']}"
    return None


def evaluate_repair_policy(plan: RepairPlan) -> PolicyDecision:
    return evaluate_policy(
        capability="durable_repair",
        action_type=plan.change_type,
        risk_score=plan.risk_score,
        evidence_count=1,
        rollback_available=plan.change_type == "no_durable_change" or plan.rollback_plan != "No repository changes were planned.",
        blast_radius="low" if plan.change_type == "test_only" else "medium",
        max_autonomous_risk=0.35,
        approval_required=plan.requires_approval,
    )


def repair_status_for(policy: PolicyDecision) -> RepairStatus:
    if policy.decision == "blocked":
        return "blocked"
    if policy.decision == "approval_required":
        return "awaiting_approval"
    return "planned"


def record_repair_event(conn: Connection, incident: dict[str, Any], event_type: str, repair: dict[str, Any]) -> None:
    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type=event_type,
        actor="repair-agent",
        payload={
            "repair_change_id": str(repair["id"]),
            "status": repair["status"],
            "change_type": repair["change_type"],
            "affected_paths": repair["affected_paths"],
            "patch_summary": repair["patch_summary"],
            "risk_score": repair["risk_score"],
            "requires_approval": repair["requires_approval"],
        },
    )


def update_incident_memory(conn: Connection, incident_id: str) -> None:
    # Local import avoids a module cycle: memory imports repair metadata.
    from app.memory import write_incident_memory

    write_incident_memory(conn, incident_id)
    conn.commit()


def regression_test_content(test_body: str) -> str:
    current = read_approved_file(REGRESSION_TEST_PATH)
    if not current:
        return regression_test_file(test_body)

    signature = test_body.strip().splitlines()[0].strip()
    if signature in current:
        return current

    marker = '\n\nif __name__ == "__main__":'
    if marker not in current:
        return regression_test_file(test_body)
    return current.replace(marker, f"\n{test_body}{marker}")


def regression_test_file(test_body: str) -> str:
    return f'''"""Regression tests generated by the durable repair agent."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class RuntimeRegressionTests(unittest.TestCase):
    def tearDown(self):
        main.ACTIVE_SCENARIOS.clear()
        main.FEATURE_CHECKOUT_ENABLED = True

{test_body}

if __name__ == "__main__":
    unittest.main()
'''
