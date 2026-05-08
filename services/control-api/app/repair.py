import hashlib
from pathlib import Path
from typing import Any, Literal

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.core.config import settings
from app.observability import record_incident_event
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
]
REGRESSION_TEST_PATH = "target-app/api/tests/test_runtime_regressions.py"
DEFAULT_TEST_COMMAND = "python -m unittest discover target-app/api/tests"


class PatchOperation(BaseModel):
    path: str
    content: str
    mode: Literal["create_or_replace"] = "create_or_replace"


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
    plan = plan_from_incident(incident)
    ensure_operations_are_allowed(plan.operations)
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
                Jsonb({
                    "plan": plan.model_dump(),
                    "approved_paths": approved_paths(),
                    "autonomy": policy.model_dump(),
                }),
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


def apply_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = require_repair(conn, repair_id)
    block_reason = repair_block_reason(repair)
    if block_reason:
        return finish_repair(conn, repair, "blocked", "repair.blocked", {"blocked": {"reason": block_reason}})

    plan = RepairPlan.model_validate(repair["result"]["plan"])
    updated = finish_repair(conn, repair, "patch_applied", "repair.patch_applied", {
        "applied": apply_operations(plan.operations)
    })
    incident = load_incident(conn, str(updated["incident_id"]))
    update_incident_memory(conn, str(incident["id"]))
    return updated


def plan_from_incident(incident: dict[str, Any]) -> RepairPlan:
    root_cause = (incident.get("root_cause") or incident.get("title") or "").lower()

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
        operations=[PatchOperation(path=REGRESSION_TEST_PATH, content=regression_test_file(test_body))],
    )


def apply_operations(operations: list[PatchOperation]) -> list[dict[str, Any]]:
    # This is the durable-repair safety boundary: only approved relative paths
    # are resolved, created, and written.
    ensure_operations_are_allowed(operations)
    applied = []
    for operation in operations:
        target = resolve_repo_path(operation.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_text() if target.exists() else None
        target.write_text(operation.content)
        applied.append({
            "path": operation.path,
            "mode": operation.mode,
            "previous_sha256": sha256_text(previous),
            "new_sha256": sha256_text(operation.content),
        })
    return applied


def ensure_operations_are_allowed(operations: list[PatchOperation]) -> None:
    for operation in operations:
        if not is_approved_path(operation.path):
            raise ValueError(f"Repair operation is outside approved paths: {operation.path}")


def is_approved_path(path: str) -> bool:
    normalized = normalize_relative(path)
    return any(normalized == approved or normalized.startswith(f"{approved}/") for approved in approved_paths())


def approved_paths() -> list[str]:
    return [normalize_relative(path) for path in settings.repair_approved_paths.split(",") if path.strip()]


def resolve_repo_path(path: str) -> Path:
    relative = normalize_relative(path)
    root = repo_root().resolve()
    target = (root / relative).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"Repair path escapes repository root: {path}")
    return target


def normalize_relative(path: str) -> str:
    normalized = Path(path.strip()).as_posix().lstrip("/")
    if normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"Repair path may not contain parent traversal: {path}")
    return normalized


def repo_root() -> Path:
    configured = Path(settings.repair_repo_root)
    return configured if configured.exists() else Path(__file__).resolve().parents[3]


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


def sha256_text(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode()).hexdigest()
