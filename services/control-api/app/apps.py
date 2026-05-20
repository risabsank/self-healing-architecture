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
    "metric_sources": [
        {"name": "availability", "description": "Fraction of successful user-visible probes.", "unit": "ratio"},
        {"name": "latency_p95_ms", "description": "95th percentile user-visible request latency.", "unit": "ms"},
        {"name": "error_rate", "description": "Fraction of failed user-visible requests.", "unit": "ratio"},
    ],
    "slo_targets": [
        {
            "name": "checkout-latency",
            "metric": "latency_p95_ms",
            "target": 500,
            "comparator": "<=",
            "window": "5m",
            "severity": "high",
            "description": "Checkout p95 latency should remain below 500ms.",
        },
        {
            "name": "user-visible-error-rate",
            "metric": "error_rate",
            "target": 0.02,
            "comparator": "<=",
            "window": "5m",
            "severity": "critical",
            "description": "User-visible errors should stay below 2%.",
        },
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metric_observations (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
              metric_name TEXT NOT NULL,
              value DOUBLE PRECISION NOT NULL,
              unit TEXT,
              source TEXT NOT NULL,
              labels JSONB NOT NULL DEFAULT '{}'::jsonb,
              observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_slo_evaluations (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
              slo_name TEXT NOT NULL,
              metric_name TEXT NOT NULL,
              status TEXT NOT NULL,
              target DOUBLE PRECISION NOT NULL,
              observed_value DOUBLE PRECISION NOT NULL,
              comparator TEXT NOT NULL,
              slo_window TEXT NOT NULL,
              observation_id UUID REFERENCES app_metric_observations(id) ON DELETE SET NULL,
              incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
              detail JSONB NOT NULL DEFAULT '{}'::jsonb,
              evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_operator_notes (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
              sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
              service_name TEXT,
              severity TEXT NOT NULL,
              note TEXT NOT NULL,
              tags JSONB NOT NULL DEFAULT '[]'::jsonb,
              metric_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
              incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_metrics_app_observed ON app_metric_observations (app_id, observed_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_slo_app_evaluated ON app_slo_evaluations (app_id, evaluated_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_notes_app_created ON app_operator_notes (app_id, created_at DESC)")
        cur.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS app_id TEXT")
        cur.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS service_name TEXT")
        cur.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'medium'")
        cur.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS trigger_source TEXT NOT NULL DEFAULT 'unknown'")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_incidents_app_open ON incidents (app_id, service_name, status, detected_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_incidents_trigger_source ON incidents (trigger_source, detected_at DESC)")
    conn.commit()
    register_application(conn, ApplicationManifest.model_validate(DEFAULT_APP_MANIFEST))


def register_application(conn: Connection, manifest: ApplicationManifest) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM sandbox_services
            WHERE metadata->>'app_id' = %s
              AND NOT service_name = ANY(%s)
            """,
            (manifest.app_id, [service.name for service in manifest.services]),
        )
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


def deactivate_application(conn: Connection, app_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE applications
            SET status = 'inactive', updated_at = now()
            WHERE app_id = %s
            RETURNING *
            """,
            (app_id,),
        )
        app = cur.fetchone()
        if not app:
            conn.rollback()
            return None
        cur.execute("DELETE FROM sandbox_services WHERE metadata->>'app_id' = %s", (app_id,))
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


def validate_manifest_readiness(manifest: ApplicationManifest) -> dict[str, Any]:
    services = {service.name: service for service in manifest.services}
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str) -> None:
        checks.append({"name": name, "ok": ok, "message": message})

    add("services", bool(manifest.services), "At least one service is declared.")
    add("health_checks", bool(manifest.health_checks), "At least one health check is declared.")
    add("critical_probes", bool(manifest.critical_probes), "At least one user-visible critical probe is declared.")
    add("safe_actions", bool(manifest.safe_actions), "At least one bounded safe action is declared.")
    add("metric_sources", bool(manifest.metric_sources), "At least one metric source is declared.")
    add("slo_targets", bool(manifest.slo_targets), "At least one SLO target is declared.")
    add("repair_policy", bool(manifest.repair_policy.approved_paths and manifest.repair_policy.test_commands), "Repair policy declares approved paths and test commands.")
    add("canary", bool((manifest.canary or {}).get("probes")), "Canary probes are declared.")

    for service in manifest.services:
        add(f"service:{service.name}:health_url", bool(service.health_url), f"{service.name} has a health URL.")
        add(f"service:{service.name}:adapter_url", bool(service.adapter_url), f"{service.name} has a sidecar adapter URL.")

    for probe in [*manifest.health_checks, *manifest.critical_probes]:
        add(f"probe:{probe.name}:service", probe.service in services, f"{probe.name} references a declared service.")

    declared_metrics = {metric.name for metric in manifest.metric_sources}
    for slo in manifest.slo_targets:
        add(f"slo:{slo.name}:metric", slo.metric in declared_metrics, f"{slo.name} references a declared metric source.")

    declared_signals = (
        declared_metrics
        | {probe.name for probe in [*manifest.health_checks, *manifest.critical_probes]}
        | {slo.name for slo in manifest.slo_targets}
        | {group.name for group in manifest.signal_groups}
    )
    declared_groups = {group.name for group in manifest.signal_groups}
    for template in manifest.operator_note_templates:
        add(f"note_template:{template.name}:service", not template.service_name or template.service_name in services, f"{template.name} references a declared service or no service.")
        for metric in template.metric_refs:
            add(f"note_template:{template.name}:metric:{metric}", metric in declared_metrics, f"{template.name} references a declared metric source.")
    for hint in manifest.dashboard_hints:
        add(f"dashboard_hint:{hint.name}:signal", not hint.signal_ref or hint.signal_ref in declared_signals, f"{hint.name} references a declared signal.")
        add(f"dashboard_hint:{hint.name}:group", not hint.group or hint.group in declared_groups, f"{hint.name} references a declared signal group.")

    for action in manifest.safe_actions:
        add(f"action:{action.action_type}:service", action.service in services, f"{action.action_type} references a declared service.")
        add(f"action:{action.action_type}:adapter_path", bool(action.adapter_path), f"{action.action_type} has an adapter path.")

    failures = [check for check in checks if not check["ok"]]
    return {
        "app_id": manifest.app_id,
        "status": "valid" if not failures else "invalid",
        "checks": checks,
        "summary": f"{len(checks) - len(failures)}/{len(checks)} readiness checks passed.",
    }


def serialize_app(app: dict[str, Any]) -> dict[str, Any]:
    return {
        **app,
        "created_at": app["created_at"].isoformat() if app.get("created_at") else None,
        "updated_at": app["updated_at"].isoformat() if app.get("updated_at") else None,
    }
