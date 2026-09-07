from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from .config import load_catalog, resolve_harness_for_role


def _stable_object_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def _list_relative_files(base_dir: Path | str) -> list[str]:
    base = Path(base_dir)
    if not base.exists():
        return []
    files: list[str] = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            files.append(path.relative_to(base).as_posix())
    return files


def _digest_file_set(base_dir: Path | str, files: list[str]) -> str:
    base = Path(base_dir)
    if not files:
        return ""
    h = sha256()
    for rel_path in sorted(files):
        h.update(rel_path.encode("utf-8"))
        h.update(b"\0")
        h.update((base / rel_path).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def snapshot_files(base_dir: Path | str) -> dict[str, object]:
    files = [path for path in _list_relative_files(base_dir) if Path(path).name != ".gitkeep"]
    return {
        "files": files,
        "sha256": _digest_file_set(base_dir, files),
    }


def snapshot_orchestra_config(config_dir: Path | str) -> dict[str, object]:
    snapshot = snapshot_files(config_dir)
    return {
        "orchestra_config_files": snapshot["files"],
        "orchestra_config_sha256": snapshot["sha256"],
    }


def snapshot_aux_skills(skills_dir: Path | str) -> dict[str, object]:
    base = Path(skills_dir)
    files = [path for path in _list_relative_files(base) if Path(path).name != ".gitkeep"]
    skill_names: set[str] = set()
    for rel_path in files:
        parts = Path(rel_path).parts
        if not parts:
            continue
        if len(parts) >= 2 and parts[-1] == "SKILL.md":
            skill_names.add(parts[-2])
        else:
            skill_names.add(parts[0])
    names = sorted(skill_names)
    return {
        "aux_skill_names": names,
        "aux_skills_enabled": bool(names),
        "aux_skills_summary": ",".join(names) if names else "none",
        "aux_skills_sha256": _digest_file_set(base, files),
    }


def snapshot_catalog_runtime(catalog_path: Path | str) -> dict[str, object]:
    catalog = load_catalog(catalog_path)
    role_models: dict[str, str] = {}
    catalog_roles: list[str] = []
    for role_name, role_config in sorted(catalog.roles.items()):
        catalog_roles.append(role_name)
        if role_config.model:
            role_models[role_name] = role_config.model
    return {
        "role_models": role_models,
        "role_models_summary": _summarize_role_models(role_models),
        "role_models_sha256": _stable_object_sha256(role_models),
        "catalog_roles": catalog_roles,
        "catalog_roles_summary": ",".join(catalog_roles) if catalog_roles else "none",
    }


def _summarize_role_models(role_models: dict[str, str]) -> str:
    if not role_models:
        return "none"
    unique_models = {model for model in role_models.values() if model}
    if len(unique_models) == 1:
        return f"all={next(iter(unique_models))}"
    return ", ".join(f"{role}={model}" for role, model in sorted(role_models.items()))


def orchestra_tools_executed_from_events(run_dir: Path | str) -> bool | None:
    """Observed Orchestra tool execution, derived only from actual harness events.

    True when a non-error ``orch_dispatch`` tool execution completed in the run's
    harness event log; False when the event log exists but records no such
    execution; None when there is no readable event source (unproven). Never
    inferred from CLI flags or configured availability.
    """
    events_path = Path(run_dir) / "artifacts" / "harness" / "events.jsonl"
    if not events_path.is_file():
        return None
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if str(event.get("type") or "") != "tool_execution_end":
            continue
        if str(event.get("toolName") or "") != "orch_dispatch":
            continue
        if event.get("isError"):
            continue
        return True
    return False


def build_run_metadata(
    task_id: str,
    run_id: str,
    catalog_path: Path | str,
    role: str | None = None,
    orchestra: bool | None = None,
    auto: bool | None = None,
    extra_skills: list[str] | tuple[str, ...] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
    runtime_snapshot: dict[str, object] | None = None,
    no_orchestra: bool | None = None,
    no_orch_on: bool | None = None,
    orchestra_tools_available: bool | None = None,
    orchestra_tools_executed: bool | None = None,
) -> dict[str, object]:
    meta = {
        "run_id": run_id,
        "task_id": task_id,
        **resolve_harness_for_role(catalog_path, role=role),
        "orchestra": orchestra,
        # Explicit mode flags so the three auto modes are distinguishable from raw JSON alone.
        "no_orchestra": bool(no_orchestra) if no_orchestra is not None else None,
        "no_orch_on": bool(no_orch_on) if no_orch_on is not None else None,
        # /orch on was requested for this run when Orchestra mode was effective and the skip flag was not set.
        "orch_on_requested": (
            (bool(orchestra) and not bool(no_orch_on))
            if orchestra is not None or no_orch_on is not None
            else None
        ),
        # null when tool availability cannot be determined at provenance construction time
        "orchestra_tools_available": (
            bool(orchestra_tools_available) if orchestra_tools_available is not None else None
        ),
        # Observed execution, separate from configured availability: true only on an actual
        # non-error orch_dispatch tool event. Filled in by the runner after grading.
        "orchestra_tools_executed": (
            bool(orchestra_tools_executed) if orchestra_tools_executed is not None else None
        ),
        # Filled in by the runner after grading when dispatch/tool activity can be inspected.
        "tool_orchestration_without_orch_on": None,
        "auto": auto,
        "extra_skills": list(extra_skills or []),
        "notes": notes,
    }
    if runtime_snapshot:
        meta.update(runtime_snapshot)
    if catalog_label:
        meta["catalog_path"] = catalog_label
    return meta


# Backwards-compatible aliases for V1-style callers/tests.
def collect_catalog_runtime_snapshot(catalog_path: Path | str) -> dict[str, object]:
    return snapshot_catalog_runtime(catalog_path)


def collect_aux_skills_snapshot(skills_dir: Path | str) -> dict[str, object]:
    return snapshot_aux_skills(skills_dir)


def collect_orchestra_config_snapshot(config_dir: Path | str) -> dict[str, object]:
    return snapshot_orchestra_config(config_dir)
