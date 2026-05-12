import ast
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.apps import get_application_for_sandbox, manifest_from_app
from app.observability import record_incident_event
from app.policy import evaluate_policy
from app.repair import get_repair, load_incident, repo_root


CHECK_TIMEOUT_SECONDS = 30
TARGET_BASE_URL = "http://target-api:8001"
UNIT_TEST_COMMAND = ["python", "-m", "unittest", "discover", "target-app/api/tests"]
COMPILE_COMMAND = [
    "python",
    "-X",
    "pycache_prefix=/tmp/self-healing-pycache",
    "-m",
    "compileall",
    "services/control-api/app",
    "target-app/api",
]
DANGEROUS_PATTERNS = ("subprocess", "os.system", "eval(", "exec(", "pickle.loads", "shell=True")
BUILD_MANIFEST = [
    "infra/docker-compose.yml",
    "services/control-api/Dockerfile",
    "target-app/api/Dockerfile",
    "target-app/api/requirements.txt",
]


def ensure_cicd_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_runs (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              repair_change_id UUID REFERENCES repair_changes(id) ON DELETE CASCADE,
              status TEXT NOT NULL,
              runner TEXT NOT NULL,
              checks JSONB NOT NULL DEFAULT '[]'::jsonb,
              started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              completed_at TIMESTAMPTZ,
              logs_ref TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_verification_runs_repair_started
            ON verification_runs (repair_change_id, started_at DESC)
            """
        )
    conn.commit()


def list_verification_runs(conn: Connection, repair_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM verification_runs
            WHERE repair_change_id = %s
            ORDER BY started_at DESC
            """,
            (repair_id,),
        )
        return cur.fetchall()


def run_verification_pipeline(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = require_verifiable_repair(conn, repair_id)
    run = create_run(conn, repair_id)
    checks = execute_checks(conn, repair)
    status = "passed" if all(check["passed"] for check in checks) else "failed"
    updated_run = finish_run(conn, str(run["id"]), status, checks)
    update_repair_verification(conn, repair, status, updated_run)
    conn.commit()
    return updated_run


def require_verifiable_repair(conn: Connection, repair_id: str) -> dict[str, Any]:
    repair = get_repair(conn, repair_id)
    if not repair:
        raise ValueError(f"Repair not found: {repair_id}")
    if repair["status"] not in {"patch_applied", "verified", "verification_failed", "released"}:
        raise ValueError(f"Repair must be patch_applied before verification: {repair['status']}")
    return repair


def create_run(conn: Connection, repair_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO verification_runs (repair_change_id, status, runner)
            VALUES (%s, 'running', 'bounded-ci-verifier')
            RETURNING *
            """,
            (repair_id,),
        )
        run = cur.fetchone()
    conn.commit()
    return run


def finish_run(conn: Connection, run_id: str, status: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE verification_runs
            SET status = %s, checks = %s, completed_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, Jsonb(checks), run_id),
        )
        return cur.fetchone()


def update_repair_verification(
    conn: Connection,
    repair: dict[str, Any],
    status: str,
    run: dict[str, Any],
) -> None:
    repair_status = "released" if status == "passed" and repair["status"] == "released" else (
        "verified" if status == "passed" else "verification_failed"
    )
    result = {
        **(repair["result"] or {}),
        "ci_cd": {
            "status": status,
            "verification_run_id": str(run["id"]),
            "checks": run["checks"],
            "autonomy": verification_policy(repair, status).model_dump(),
        },
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE repair_changes
            SET status = %s, result = %s, updated_at = now()
            WHERE id = %s
            """,
            (repair_status, Jsonb(result), repair["id"]),
        )

    incident = load_incident(conn, str(repair["incident_id"]))
    record_incident_event(
        conn,
        incident_id=str(incident["id"]),
        sandbox_id=incident["sandbox_id"],
        event_type=f"verification.{status}",
        actor="ci-cd-verifier",
        payload={
            "repair_change_id": str(repair["id"]),
            "verification_run_id": str(run["id"]),
            "status": status,
            "checks": run["checks"],
        },
    )


def execute_checks(conn: Connection, repair: dict[str, Any]) -> list[dict[str, Any]]:
    root = repo_root()
    affected_paths = repair["affected_paths"] or []
    incident = load_incident(conn, str(repair["incident_id"]))
    app = get_application_for_sandbox(conn, incident["sandbox_id"]) if incident else None
    manifest = manifest_from_app(app)
    app_unit_commands = (manifest.repair_policy.test_commands if manifest else []) or [UNIT_TEST_COMMAND]
    # Release eligibility is intentionally a fixed set of bounded gates.
    checks = [
        *[run_command_check(f"unit_tests_{index + 1}", command, root) for index, command in enumerate(app_unit_commands)],
        run_command_check("static_compile", COMPILE_COMMAND, root),
        static_ast_check(root, affected_paths),
        security_scan(root, affected_paths),
        build_manifest_check(root),
        integration_health_check(manifest),
        sandbox_replay_check(manifest),
    ]
    return checks


def verification_policy(repair: dict[str, Any], status: str):
    return evaluate_policy(
        capability="ci_cd_verification",
        action_type="bounded_release_gates",
        risk_score=0.1 if status == "passed" else 0.6,
        evidence_count=len((repair.get("result") or {}).get("applied") or [repair]),
        rollback_available=True,
        blast_radius="low",
        max_autonomous_risk=0.5,
    )


def run_command_check(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            timeout=CHECK_TIMEOUT_SECONDS,
            check=False,
        )
        passed = completed.returncode == 0
        detail = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": trim(completed.stdout),
            "stderr": trim(completed.stderr),
        }
    except Exception as exc:
        passed = False
        detail = {"error": type(exc).__name__, "message": str(exc), "command": command}

    return check_result(name, passed, detail, start)


def static_ast_check(root: Path, paths: list[str]) -> dict[str, Any]:
    start = time.perf_counter()
    findings = []
    for path in python_paths(root, paths):
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            findings.append({"path": relative(root, path), "line": exc.lineno, "message": exc.msg})
    return check_result("static_ast", not findings, {"findings": findings}, start)


def security_scan(root: Path, paths: list[str]) -> dict[str, Any]:
    start = time.perf_counter()
    findings = []
    for path in changed_text_paths(root, paths):
        text = path.read_text(errors="ignore")
        for token in DANGEROUS_PATTERNS:
            if token in text:
                findings.append({"path": relative(root, path), "token": token})
    return check_result("security_scan", not findings, {"findings": findings}, start)


def build_manifest_check(root: Path) -> dict[str, Any]:
    start = time.perf_counter()
    missing = [path for path in BUILD_MANIFEST if not (root / path).exists()]
    return check_result("build_manifest", not missing, {"missing": missing}, start)


def integration_health_check(manifest=None) -> dict[str, Any]:
    start = time.perf_counter()
    health_url = first_service(manifest).get("health_url") if manifest else f"{TARGET_BASE_URL}/health"
    try:
        body = request_json("GET", health_url)
        passed = body.get("status") == "healthy"
        detail = {"status": body.get("status"), "active_scenarios": body.get("active_scenarios")}
    except Exception as exc:
        passed = False
        detail = {"error": type(exc).__name__, "message": str(exc)}
    return check_result("integration_health", passed, detail, start)


def sandbox_replay_check(manifest=None) -> dict[str, Any]:
    start = time.perf_counter()
    service = first_service(manifest)
    base_url = service.get("base_url", TARGET_BASE_URL)
    scenario = ((manifest.verification or {}).get("sandbox_replay") or {}).get("scenario", "bad_database_url") if manifest else "bad_database_url"
    try:
        request_json("POST", f"{base_url}/scenarios/{scenario}/activate")
        unhealthy = request_json("GET", service.get("health_url", f"{base_url}/health"))
        request_json("POST", f"{base_url}/scenarios/reset")
        healthy = request_json("GET", service.get("health_url", f"{base_url}/health"))
        passed = unhealthy.get("status") == "unhealthy" and healthy.get("status") == "healthy"
        detail = {
            "replayed_scenario": scenario,
            "during_replay": unhealthy.get("status"),
            "after_reset": healthy.get("status"),
        }
    except Exception as exc:
        try:
            request_json("POST", f"{base_url}/scenarios/reset")
        except Exception:
            pass
        passed = False
        detail = {"error": type(exc).__name__, "message": str(exc)}
    return check_result("sandbox_replay", passed, detail, start)


def request_json(method: str, url: str) -> dict[str, Any]:
    with httpx.Client(timeout=8) as client:
        response = client.request(method, url)
        response.raise_for_status()
        return response.json()


def first_service(manifest) -> dict[str, Any]:
    if not manifest or not manifest.services:
        return {"base_url": TARGET_BASE_URL, "health_url": f"{TARGET_BASE_URL}/health"}
    return manifest.services[0].model_dump()


def python_paths(root: Path, paths: list[str]) -> list[Path]:
    candidates = changed_text_paths(root, paths)
    if not candidates:
        candidates = [root / "services/control-api/app", root / "target-app/api"]
    files = []
    for path in candidates:
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        elif path.suffix == ".py":
            files.append(path)
    return files


def changed_text_paths(root: Path, paths: list[str]) -> list[Path]:
    return [(root / path).resolve() for path in paths if (root / path).exists()]


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def check_result(name: str, passed: bool, detail: dict[str, Any], start: float) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "duration_ms": int((time.perf_counter() - start) * 1000),
        "detail": detail,
    }


def trim(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text
