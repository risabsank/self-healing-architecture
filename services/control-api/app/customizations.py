from __future__ import annotations

import re
import json
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.llm import ClaudeClient
from app.apps import manifest_from_app, register_application, validate_manifest_readiness
from app.models.schemas import (
    ApplicationManifest,
    CustomizationPlanCreate,
    DashboardHintManifest,
    ManifestCustomizationPatch,
    MetricSourceManifest,
    OperatorNoteTemplateManifest,
    ProbeManifest,
    SignalGroupManifest,
    SloTargetManifest,
)


def ensure_customization_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customization_proposals (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
              prompt TEXT NOT NULL,
              proposed_patch JSONB NOT NULL,
              validation_result JSONB NOT NULL,
              status TEXT NOT NULL DEFAULT 'planned',
              planner TEXT NOT NULL DEFAULT 'deterministic',
              error TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              approved_at TIMESTAMPTZ,
              rejected_at TIMESTAMPTZ,
              applied_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_customization_proposals_app_created
            ON customization_proposals (app_id, created_at DESC)
            """
        )
    conn.commit()


def create_customization_proposal(conn: Connection, app: dict[str, Any], payload: CustomizationPlanCreate) -> dict[str, Any]:
    manifest = manifest_from_app(app)
    patch, planner, error = plan_customization(manifest, payload.prompt)
    validation = validate_customization_patch(manifest, patch)
    status = "planned" if validation["status"] == "valid" else "failed"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customization_proposals (app_id, prompt, proposed_patch, validation_result, status, planner, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                manifest.app_id,
                payload.prompt,
                Jsonb(patch.model_dump()),
                Jsonb(validation),
                status,
                planner,
                error,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return serialize_proposal(row)


def list_customization_proposals(conn: Connection, app_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM customization_proposals WHERE app_id = %s ORDER BY created_at DESC",
            (app_id,),
        )
        return [serialize_proposal(row) for row in cur.fetchall()]


def get_customization_proposal(conn: Connection, app_id: str, proposal_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM customization_proposals WHERE app_id = %s AND id = %s",
            (app_id, proposal_id),
        )
        row = cur.fetchone()
    return serialize_proposal(row) if row else None


def approve_customization_proposal(conn: Connection, app: dict[str, Any], proposal_id: str) -> dict[str, Any] | None:
    proposal = get_customization_proposal(conn, app["app_id"], proposal_id)
    if not proposal:
        return None
    if proposal["status"] != "planned":
        raise ValueError(f"Only planned proposals can be approved; current status is {proposal['status']}.")

    manifest = manifest_from_app(app)
    patch = ManifestCustomizationPatch.model_validate(proposal["proposed_patch"])
    validation = validate_customization_patch(manifest, patch)
    if validation["status"] != "valid":
        raise ValueError("Customization proposal is no longer valid for the current manifest.")

    register_application(conn, merge_customization_patch(manifest, patch))
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE customization_proposals
            SET status = 'applied', validation_result = %s, approved_at = now(), applied_at = now()
            WHERE app_id = %s AND id = %s
            RETURNING *
            """,
            (Jsonb(validation), app["app_id"], proposal_id),
        )
        row = cur.fetchone()
    conn.commit()
    return serialize_proposal(row)


def reject_customization_proposal(conn: Connection, app_id: str, proposal_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE customization_proposals
            SET status = 'rejected', rejected_at = now()
            WHERE app_id = %s AND id = %s
            RETURNING *
            """,
            (app_id, proposal_id),
        )
        row = cur.fetchone()
    conn.commit()
    return serialize_proposal(row) if row else None


def plan_customization(manifest: ApplicationManifest, prompt: str) -> tuple[ManifestCustomizationPatch, str, str | None]:
    try:
        patch = ClaudeClient().complete_json(customization_system_prompt(), customization_prompt(manifest, prompt), ManifestCustomizationPatch)
        return patch, "claude", None
    except Exception as exc:
        return deterministic_patch(manifest, prompt), "deterministic", str(exc)


def deterministic_patch(manifest: ApplicationManifest, prompt: str) -> ManifestCustomizationPatch:
    service = manifest.services[0].name
    text = prompt.lower()
    keyword = first_keyword(text) or "custom"
    route = first_route(text) or f"/{keyword}"
    topic = slugify(route.strip("/") or first_keyword(text) or "custom")
    latency_target = first_number(text) or 750.0

    metric_name = f"{topic}_latency_p95_ms" if "latency" in text or "slow" in text else f"{topic}_error_rate"
    unit = "ms" if metric_name.endswith("_ms") else "ratio"
    target = latency_target if unit == "ms" else 0.02
    comparator = "<="

    probe = ProbeManifest(name=f"{topic}-probe", service=service, path=route)
    metric = MetricSourceManifest(name=metric_name, description=f"Custom signal generated from operator request: {prompt}", unit=unit)
    slo = SloTargetManifest(
        name=f"{topic}-slo",
        metric=metric_name,
        target=target,
        comparator=comparator,
        window="5m",
        severity="high",
        description=f"Custom SLO for {route}.",
    )
    group = SignalGroupManifest(
        name=f"{topic}-signals",
        label=f"{topic.replace('-', ' ').title()} Signals",
        description="Custom reliability signals added by the runtime customization planner.",
        signals=[probe.name, metric.name, slo.name],
        priority=30,
    )
    note_template = OperatorNoteTemplateManifest(
        name=f"{topic}-degradation-note",
        label=f"Report {topic.replace('-', ' ')} degradation",
        note=f"Users are reporting degraded behavior around {route}.",
        severity="high",
        service_name=service,
        tags=["customization", topic],
        metric_refs=[metric.name],
    )
    hint = DashboardHintManifest(
        name=f"{topic}-hint",
        title=f"Watch {topic.replace('-', ' ')}",
        description=f"Monitor {route} through its custom probe, metric, SLO, and operator-note template.",
        signal_ref=slo.name,
        group=group.name,
        priority=30,
    )
    return ManifestCustomizationPatch(
        summary=f"Add custom runtime coverage for {route}.",
        critical_probes=[probe],
        metric_sources=[metric],
        slo_targets=[slo],
        verification_probes=[probe],
        canary_probes=[probe],
        signal_groups=[group],
        operator_note_templates=[note_template],
        dashboard_hints=[hint],
    )


def validate_customization_patch(manifest: ApplicationManifest, patch: ManifestCustomizationPatch) -> dict[str, Any]:
    services = {service.name for service in manifest.services}
    metrics = {metric.name for metric in manifest.metric_sources} | {metric.name for metric in patch.metric_sources}
    groups = {group.name for group in manifest.signal_groups} | {group.name for group in patch.signal_groups}
    signals = metrics | {probe.name for probe in [*manifest.critical_probes, *patch.critical_probes]} | {slo.name for slo in [*manifest.slo_targets, *patch.slo_targets]} | groups
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str) -> None:
        checks.append({"name": name, "ok": ok, "message": message})

    add("summary", bool(patch.summary), "Patch includes a human-readable summary.")
    for probe in [*patch.critical_probes, *patch.verification_probes, *patch.canary_probes]:
        add(f"probe:{probe.name}:service", probe.service in services, f"{probe.name} references a declared service.")
        add(f"probe:{probe.name}:path", probe.path.startswith("/"), f"{probe.name} uses an absolute HTTP path.")
    for slo in patch.slo_targets:
        add(f"slo:{slo.name}:metric", slo.metric in metrics, f"{slo.name} references a declared or generated metric.")
    for template in patch.operator_note_templates:
        add(f"note_template:{template.name}:service", not template.service_name or template.service_name in services, f"{template.name} references a declared service or no service.")
        for metric in template.metric_refs:
            add(f"note_template:{template.name}:metric:{metric}", metric in metrics, f"{template.name} references a declared or generated metric.")
    for hint in patch.dashboard_hints:
        add(f"dashboard_hint:{hint.name}:signal", not hint.signal_ref or hint.signal_ref in signals, f"{hint.name} references a known signal.")
        add(f"dashboard_hint:{hint.name}:group", not hint.group or hint.group in groups, f"{hint.name} references a known signal group.")

    duplicate_names = duplicate_patch_names(patch)
    add("unique_generated_names", not duplicate_names, f"Generated names are unique. Duplicates: {', '.join(duplicate_names) or 'none'}.")

    failures = [check for check in checks if not check["ok"]]
    return {
        "status": "valid" if not failures else "invalid",
        "checks": checks,
        "summary": f"{len(checks) - len(failures)}/{len(checks)} customization checks passed.",
    }


def merge_customization_patch(manifest: ApplicationManifest, patch: ManifestCustomizationPatch) -> ApplicationManifest:
    data = manifest.model_dump()
    merge_named(data, "critical_probes", [item.model_dump() for item in patch.critical_probes])
    merge_named(data, "metric_sources", [item.model_dump() for item in patch.metric_sources])
    merge_named(data, "slo_targets", [item.model_dump() for item in patch.slo_targets])
    merge_named(data, "signal_groups", [item.model_dump() for item in patch.signal_groups])
    merge_named(data, "operator_note_templates", [item.model_dump() for item in patch.operator_note_templates])
    merge_named(data, "dashboard_hints", [item.model_dump() for item in patch.dashboard_hints])

    data.setdefault("verification", {})
    data["verification"]["probes"] = merge_probe_list(data["verification"].get("probes") or [], patch.verification_probes)
    data.setdefault("canary", {})
    data["canary"]["probes"] = merge_probe_list(data["canary"].get("probes") or [], patch.canary_probes)
    return ApplicationManifest.model_validate(data)


def merge_named(data: dict[str, Any], key: str, additions: list[dict[str, Any]]) -> None:
    by_name = {item.get("name"): item for item in data.get(key, [])}
    for item in additions:
        by_name[item["name"]] = item
    data[key] = list(by_name.values())


def merge_probe_list(existing: list[dict[str, Any]], additions: list[ProbeManifest]) -> list[dict[str, Any]]:
    by_name = {item.get("name"): item for item in existing}
    for item in additions:
        by_name[item.name] = item.model_dump()
    return list(by_name.values())


def duplicate_patch_names(patch: ManifestCustomizationPatch) -> list[str]:
    names = [
        *[item.name for item in patch.critical_probes],
        *[item.name for item in patch.metric_sources],
        *[item.name for item in patch.slo_targets],
        *[item.name for item in patch.signal_groups],
        *[item.name for item in patch.operator_note_templates],
        *[item.name for item in patch.dashboard_hints],
    ]
    return sorted({name for name in names if names.count(name) > 1})


def customization_system_prompt() -> str:
    return """
You generate manifest-only reliability customizations for a self-healing runtime.
Return only JSON matching the requested schema.
Do not generate application source code, shell commands, or new sidecar actions.
Only add probes, metric sources, SLO targets, verification probes, canary probes,
operator-note templates, signal groups, and dashboard hints.
All probes must reference an existing service name from the manifest and use HTTP paths.
Keep names stable, lowercase, and dash/underscore separated.
""".strip()


def customization_prompt(manifest: ApplicationManifest, prompt: str) -> str:
    return f"""
Application manifest:
{manifest.model_dump_json(indent=2)}

Required output JSON schema:
{json.dumps(ManifestCustomizationPatch.model_json_schema(), indent=2)}

Developer customization request:
{prompt}

Create a small, reviewable manifest customization patch. Prefer one custom signal group,
one or two probes, one metric source, one SLO target, one note template, and one dashboard hint.
""".strip()


def first_route(text: str) -> str | None:
    match = re.search(r"(/[a-z0-9_./-]*)", text)
    return match.group(1).rstrip("/") or "/" if match else None


def first_number(text: str) -> float | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)", text)
    return float(matches[-1]) if matches else None


def first_keyword(text: str) -> str | None:
    for word in re.findall(r"[a-z0-9]+", text):
        if word not in {"monitor", "watch", "users", "report", "slow", "after", "deploy", "error", "errors"}:
            return word
    return None


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "custom"


def serialize_proposal(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "approved_at": row["approved_at"].isoformat() if row.get("approved_at") else None,
        "rejected_at": row["rejected_at"].isoformat() if row.get("rejected_at") else None,
        "applied_at": row["applied_at"].isoformat() if row.get("applied_at") else None,
    }
