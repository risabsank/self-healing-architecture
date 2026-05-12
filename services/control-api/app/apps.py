from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.models.schemas import ApplicationManifest


DEFAULT_APP_MANIFEST = {
    "app_id": "breakable-target",
    "display_name": "Breakable Target API",
    "environment": "local",
    "sandbox_id": "local-docker",
    "dependencies": ["postgres", "checkout-provider"],
    "services": [
        {
            "name": "target-api",
            "service_type": "fastapi",
            "base_url": "http://target-api:8001",
            "health_url": "http://target-api:8001/health",
            "public_url": "http://localhost:8001",
            "adapter_url": "http://target-adapter:8010",
            "metadata": {"role": "reference-app"},
        }
    ],
    "health_checks": [{"name": "health", "service": "target-api", "path": "/health", "healthy_status": "healthy"}],
    "critical_probes": [
        {"name": "metadata", "service": "target-api", "path": "/metadata"},
        {"name": "items", "service": "target-api", "path": "/items"},
        {"name": "checkout", "service": "target-api", "path": "/checkout"},
    ],
    "safe_actions": [
        {
            "action_type": "SET_ENV_VAR",
            "service": "target-api",
            "description": "Restore a known-good runtime configuration value.",
            "required_params": ["service", "key", "value_from"],
            "parameter_allowlists": {"key": ["DATABASE_URL", "TARGET_REQUIRED_SECRET"]},
            "adapter_path": "/adapter/actions/SET_ENV_VAR",
            "clears_scenarios": ["bad_database_url", "missing_required_env"],
        },
        {
            "action_type": "RESTART_SERVICE",
            "service": "target-api",
            "description": "Request a bounded service restart.",
            "required_params": ["service"],
            "parameter_allowlists": {},
            "adapter_path": "/adapter/actions/RESTART_SERVICE",
            "clears_scenarios": ["port_conflict"],
        },
        {
            "action_type": "DISABLE_FEATURE_FLAG",
            "service": "target-api",
            "description": "Disable an allowlisted feature flag.",
            "required_params": ["service", "flag"],
            "parameter_allowlists": {"flag": ["FEATURE_CHECKOUT_ENABLED"]},
            "adapter_path": "/adapter/actions/DISABLE_FEATURE_FLAG",
            "clears_scenarios": ["bad_feature_flag", "rate_limit"],
        },
        {
            "action_type": "SWITCH_DEPENDENCY_TO_MOCK",
            "service": "target-api",
            "description": "Route a dependency to an allowlisted fallback.",
            "required_params": ["service", "dependency"],
            "parameter_allowlists": {"dependency": ["checkout-provider"]},
            "adapter_path": "/adapter/actions/SWITCH_DEPENDENCY_TO_MOCK",
            "clears_scenarios": ["dependency_unavailable", "rate_limit"],
        },
        {
            "action_type": "ROLLBACK_CONFIG",
            "service": "target-api",
            "description": "Return runtime configuration to a previous known-good version.",
            "required_params": ["service", "target"],
            "parameter_allowlists": {"target": ["previous_known_good_app_version"]},
            "adapter_path": "/adapter/actions/ROLLBACK_CONFIG",
            "max_autonomous_risk": 0.0,
            "blast_radius": "medium",
            "approval_required": True,
            "clears_scenarios": ["schema_mismatch"],
        },
    ],
    "repair_policy": {
        "approved_paths": ["target-app/api/tests", "target-app/api/main.py", "target-app/api/requirements.txt"],
        "path_owners": {
            "target-app/api/main.py": "target-api",
            "target-app/api/tests/": "target-api-tests",
            "target-app/api/requirements.txt": "target-api",
        },
        "test_commands": [["python", "-m", "unittest", "discover", "target-app/api/tests"]],
        "build_commands": [],
        "rollback_strategy": "Apply generated rollback operations.",
    },
    "repo": {"root": "/workspace", "kind": "local"},
    "verification": {
        "commands": [["python", "-m", "unittest", "discover", "target-app/api/tests"]],
        "sandbox_replay": {"scenario": "bad_database_url"},
    },
    "canary": {
        "environment": "local-docker-canary",
        "traffic_percentage": 10.0,
        "probes": [
            {"name": "health", "service": "target-api", "path": "/health", "healthy_status": "healthy"},
            {"name": "metadata", "service": "target-api", "path": "/metadata"},
            {"name": "items", "service": "target-api", "path": "/items"},
            {"name": "checkout", "service": "target-api", "path": "/checkout"},
        ],
    },
}


def ensure_app_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
              app_id TEXT PRIMARY KEY,
              sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
              display_name TEXT NOT NULL,
              environment TEXT NOT NULL,
              manifest JSONB NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_applications_sandbox ON applications (sandbox_id, status)")
    conn.commit()
    register_application(conn, ApplicationManifest.model_validate(DEFAULT_APP_MANIFEST))


def register_application(conn: Connection, manifest: ApplicationManifest) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO applications (app_id, sandbox_id, display_name, environment, manifest, status)
            VALUES (%s, %s, %s, %s, %s, 'active')
            ON CONFLICT (app_id) DO UPDATE
            SET sandbox_id = EXCLUDED.sandbox_id,
                display_name = EXCLUDED.display_name,
                environment = EXCLUDED.environment,
                manifest = EXCLUDED.manifest,
                status = 'active',
                updated_at = now()
            RETURNING *
            """,
            (
                manifest.app_id,
                manifest.sandbox_id,
                manifest.display_name,
                manifest.environment,
                Jsonb(manifest.model_dump()),
            ),
        )
        app = cur.fetchone()
        for service in manifest.services:
            metadata = {
                **service.metadata,
                "app_id": manifest.app_id,
                "public_url": service.public_url,
                "adapter_url": service.adapter_url,
            }
            cur.execute(
                """
                INSERT INTO sandbox_services (sandbox_id, service_name, service_type, base_url, health_url, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (sandbox_id, service_name) DO UPDATE
                SET service_type = EXCLUDED.service_type,
                    base_url = EXCLUDED.base_url,
                    health_url = EXCLUDED.health_url,
                    metadata = EXCLUDED.metadata
                """,
                (
                    manifest.sandbox_id,
                    service.name,
                    service.service_type,
                    service.base_url,
                    service.health_url,
                    Jsonb(metadata),
                ),
            )
    conn.commit()
    return serialize_app(app)


def list_applications(conn: Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM applications ORDER BY created_at DESC")
        return [serialize_app(row) for row in cur.fetchall()]


def get_application(conn: Connection, app_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM applications WHERE app_id = %s", (app_id,))
        row = cur.fetchone()
    return serialize_app(row) if row else None


def get_application_for_sandbox(conn: Connection, sandbox_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM applications
            WHERE sandbox_id = %s AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (sandbox_id,),
        )
        row = cur.fetchone()
    return serialize_app(row) if row else None


def manifest_from_app(app: dict[str, Any] | None) -> ApplicationManifest | None:
    return ApplicationManifest.model_validate(app["manifest"]) if app else None


def safe_action(manifest: ApplicationManifest | None, action_type: str, service: str) -> dict[str, Any] | None:
    if not manifest:
        return None
    for action in manifest.safe_actions:
        if action.action_type == action_type and action.service == service:
            return action.model_dump()
    return None


def service_manifest(manifest: ApplicationManifest | None, service_name: str) -> dict[str, Any] | None:
    if not manifest:
        return None
    for service in manifest.services:
        if service.name == service_name:
            return service.model_dump()
    return None


def app_probes(manifest: ApplicationManifest | None, section: str) -> list[dict[str, Any]]:
    if not manifest:
        return []
    if section == "canary":
        return list((manifest.canary or {}).get("probes") or [])
    if section == "verification":
        return list((manifest.verification or {}).get("probes") or [])
    return [probe.model_dump() for probe in manifest.critical_probes]


def serialize_app(app: dict[str, Any]) -> dict[str, Any]:
    return {
        **app,
        "created_at": app["created_at"].isoformat() if app.get("created_at") else None,
        "updated_at": app["updated_at"].isoformat() if app.get("updated_at") else None,
    }
