import difflib
import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.core.config import settings


class PatchOperation(BaseModel):
    path: str
    content: str
    mode: Literal["create_or_replace", "delete"] = "create_or_replace"


def build_patch_set(operations: list[PatchOperation]) -> dict[str, Any]:
    return {
        "patch_preview": [patch_preview(operation) for operation in operations],
        "rollback_operations": [operation.model_dump() for operation in rollback_operations_from_current_files(operations)],
    }


def apply_operations(operations: list[PatchOperation], previews: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    # All durable repairs pass through this boundary: approved paths only,
    # known owners only, and no arbitrary shell access.
    ensure_operations_are_allowed(operations)
    ensure_current_hashes_match(previews or [])
    applied = []
    for operation in operations:
        target = resolve_repo_path(operation.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_text() if target.exists() else None
        if operation.mode == "delete":
            if target.exists():
                target.unlink()
        else:
            target.write_text(operation.content)
        applied.append(operation_result(operation, previous))
    return applied


def ensure_current_hashes_match(previews: list[dict[str, Any]]) -> None:
    for preview in previews:
        current = read_approved_file(preview["path"])
        expected = preview.get("previous_sha256")
        actual = sha256_text(current)
        if actual != expected:
            raise ValueError(f"Repair target changed after preview generation: {preview['path']}")


def patch_preview(operation: PatchOperation) -> dict[str, Any]:
    previous = read_approved_file(operation.path)
    next_content = "" if operation.mode == "delete" else operation.content
    return {
        "path": operation.path,
        "mode": operation.mode,
        "owner": owner_for_path(operation.path),
        "previous_sha256": sha256_text(previous),
        "new_sha256": None if operation.mode == "delete" else sha256_text(operation.content),
        "diff": unified_diff(operation.path, previous, next_content),
    }


def rollback_operations_from_current_files(operations: list[PatchOperation]) -> list[PatchOperation]:
    rollback = []
    for operation in operations:
        previous = read_approved_file(operation.path)
        rollback.append(PatchOperation(
            path=operation.path,
            content=previous or "",
            mode="create_or_replace" if previous is not None else "delete",
        ))
    return rollback


def rollback_operations(repair: dict[str, Any]) -> list[PatchOperation]:
    return [PatchOperation.model_validate(operation) for operation in (repair["result"] or {}).get("rollback_operations", [])]


def path_ownership(operations: list[PatchOperation]) -> list[dict[str, str]]:
    return [{"path": operation.path, "owner": owner_for_path(operation.path)} for operation in operations]


def ensure_operations_are_allowed(operations: list[PatchOperation]) -> None:
    for operation in operations:
        if not is_approved_path(operation.path):
            raise ValueError(f"Repair operation is outside approved paths: {operation.path}")
        if owner_for_path(operation.path) == "unowned":
            raise ValueError(f"Repair operation has no path owner rule: {operation.path}")


def approved_paths() -> list[str]:
    return [normalize_relative(path) for path in settings.repair_approved_paths.split(",") if path.strip()]


def read_approved_file(path: str) -> str | None:
    if not is_approved_path(path):
        raise ValueError(f"Repair read is outside approved paths: {path}")
    target = resolve_repo_path(path)
    return target.read_text() if target.exists() else None


def repo_root() -> Path:
    configured = Path(settings.repair_repo_root)
    return configured if configured.exists() else Path(__file__).resolve().parents[3]


def operation_result(operation: PatchOperation, previous: str | None) -> dict[str, Any]:
    return {
        "path": operation.path,
        "mode": operation.mode,
        "previous_sha256": sha256_text(previous),
        "new_sha256": None if operation.mode == "delete" else sha256_text(operation.content),
    }


def unified_diff(path: str, previous: str | None, next_content: str) -> str:
    before = [] if previous is None else previous.splitlines(keepends=True)
    after = next_content.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}"))


def owner_for_path(path: str) -> str:
    normalized = normalize_relative(path)
    matches = [
        (prefix, owner)
        for prefix, owner in path_owner_rules().items()
        if normalized == prefix or normalized.startswith(f"{prefix}/")
    ]
    return max(matches, key=lambda item: len(item[0]))[1] if matches else "unowned"


def path_owner_rules() -> dict[str, str]:
    rules = {}
    for entry in settings.repair_path_owners.split(","):
        if ":" not in entry:
            continue
        path, owner = entry.split(":", 1)
        rules[normalize_relative(path)] = owner.strip()
    return rules


def is_approved_path(path: str) -> bool:
    normalized = normalize_relative(path)
    return any(normalized == approved or normalized.startswith(f"{approved}/") for approved in approved_paths())


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


def sha256_text(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest() if text is not None else None
