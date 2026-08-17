"""eval_harness — prepare / run / grade / report for orchestra-bench tasks."""

from __future__ import annotations

import json as _json
import shlex
import shutil
import sqlite3
import statistics as _stats
import subprocess as sp
import sys
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Sequence

try:
    import yaml  # type: ignore[import]
except ImportError:
    yaml = None  # fallback to simple parser below


# ── Local imports (resolve relative to this file's repo root) ────────
_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

from __init__ import (  # noqa: E402
    CONTAINER_NAME,
    RESULTS_DIR,
    TASKS_DIR,
    TaskMeta,
    TaskResult,
)


# ── YAML helpers ─────────────────────────────────────────────────────

def _load_yaml(path: Path | str) -> dict:
    path = Path(path)
    if yaml is not None:
        return yaml.safe_load(path.read_text()) or {}
    # Minimal hand-rolled parser for simple key: value YAML (no nesting)
    data: dict[str, object] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        data[key.strip()] = _strip_quotes(value.strip())
    return data


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _parse_json_object_from_stdout(stdout: str) -> dict[str, object]:
    """Best-effort parse of a JSON object embedded in stdout."""
    text = (stdout or "").strip()
    if not text:
        return {}

    decoder = _json.JSONDecoder()
    for start_idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[start_idx:])
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def load_agent_catalog(catalog_path: Path | str) -> dict:
    """Load the benchmark agent catalog YAML."""
    return _load_yaml(catalog_path)


def resolve_catalog_model(
    catalog_path: Path | str,
    role: str | None = None,
) -> dict[str, object]:
    """Resolve the benchmark model from agent-catalog.yaml.

    Uses default_role when role is not specified, then returns a provenance
    snapshot suitable for run metadata.
    """
    catalog = Path(catalog_path)
    data = load_agent_catalog(catalog)
    roles = data.get("roles") or {}
    if not isinstance(roles, dict):
        raise ValueError(f"invalid roles section in {catalog}")

    default_role = str(data.get("default_role") or "builder")
    effective_role = role or default_role or "builder"
    role_config = roles.get(effective_role)
    if not isinstance(role_config, dict):
        raise KeyError(f"role '{effective_role}' not found in {catalog}")

    model = str(role_config.get("model") or "")
    if not model:
        raise ValueError(f"role '{effective_role}' in {catalog} has no model")

    return {
        "role": effective_role,
        "default_role": default_role,
        "model": model,
        "catalog_path": str(catalog),
        "catalog_sha256": sha256(catalog.read_bytes()).hexdigest(),
    }


def _stable_object_sha256(value: object) -> str:
    """Return a stable SHA256 for JSON-serializable provenance data."""
    payload = _json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def _list_relative_files(base_dir: Path | str) -> list[str]:
    """Return sorted relative file paths under *base_dir*."""
    base = Path(base_dir)
    if not base.exists():
        return []

    files: list[str] = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            files.append(path.relative_to(base).as_posix())
    return files


def _digest_file_set(base_dir: Path | str, files: Sequence[str]) -> str:
    """Return a stable digest for the selected files beneath *base_dir*."""
    base = Path(base_dir)
    h = sha256()
    for rel_path in sorted(str(p) for p in files):
        h.update(rel_path.encode("utf-8"))
        h.update(b"\0")
        h.update((base / rel_path).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _summarize_role_models(role_models: dict[str, str]) -> str:
    """Render a compact summary of role→model assignments."""
    if not role_models:
        return "none"
    unique_models = {model for model in role_models.values() if model}
    if len(unique_models) == 1:
        return f"all={next(iter(unique_models))}"
    return ", ".join(f"{role}={model}" for role, model in sorted(role_models.items()))


def collect_catalog_runtime_snapshot(catalog_path: Path | str) -> dict[str, object]:
    """Collect role/model provenance from agent-catalog.yaml."""
    catalog = Path(catalog_path)
    data = load_agent_catalog(catalog)
    roles = data.get("roles") or {}
    if not isinstance(roles, dict):
        return {}

    role_models: dict[str, str] = {}
    enabled_roles: list[str] = []
    for role_name, role_config in sorted(roles.items()):
        if not isinstance(role_config, dict):
            continue
        model = str(role_config.get("model") or "").strip()
        if model:
            role_models[str(role_name)] = model
        if role_config.get("enabled", True):
            enabled_roles.append(str(role_name))

    return {
        "role_models": role_models,
        "role_models_summary": _summarize_role_models(role_models),
        "role_models_sha256": _stable_object_sha256(role_models),
        "enabled_roles": enabled_roles,
        "enabled_roles_summary": ",".join(enabled_roles) if enabled_roles else "none",
    }


def collect_aux_skills_snapshot(skills_dir: Path | str) -> dict[str, object]:
    """Collect benchmark-local auxiliary skill provenance from config/skills."""
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
        "aux_skills_sha256": _digest_file_set(base, files) if files else "",
    }


def collect_orchestra_config_snapshot(config_dir: Path | str) -> dict[str, object]:
    """Collect benchmark-local orchestra config provenance."""
    base = Path(config_dir)
    files = _list_relative_files(base)
    return {
        "orchestra_config_files": files,
        "orchestra_config_sha256": _digest_file_set(base, files) if files else "",
    }


def _parse_pi_list_package_names(stdout: str) -> list[str]:
    """Parse `pi list` output into a stable list of package names."""
    names: list[str] = []
    for raw_line in stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.endswith(":"):
            continue
        if stripped.startswith("/"):
            continue
        source = stripped.split()[0].rstrip("/")
        if ":" not in source and "/" not in source:
            continue
        name = source.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        if name:
            names.append(name)
    return sorted(set(names))


def _package_name_from_source(source: object) -> str:
    text = str(source or "").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _extension_name_from_ref(ref: object) -> str:
    text = str(ref or "").strip()
    if text.startswith(("+", "-")):
        text = text[1:]
    parts = [part for part in text.replace("\\", "/").split("/") if part]
    if "extensions" in parts:
        idx = parts.index("extensions")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if parts:
        leaf = parts[-1]
        if leaf.endswith(('.ts', '.js')) and len(parts) >= 2:
            return parts[-2]
        return leaf.rsplit(".", 1)[0]
    return ""


def _parse_pi_settings_disabled_extensions(settings: object) -> set[str]:
    """Return local/global extension names explicitly disabled in Pi settings."""
    disabled: set[str] = set()
    if not isinstance(settings, dict):
        return disabled
    extensions = settings.get("extensions")
    if isinstance(extensions, list):
        for entry in extensions:
            text = str(entry or "").strip()
            if text.startswith("-"):
                name = _extension_name_from_ref(text)
                if name:
                    disabled.add(name)
    return disabled


def _parse_pi_settings_enabled_plugins(settings: object) -> list[str]:
    """Return plugins/resources enabled in Pi settings.json.

    Pi packages can be present but resource-filtered off, e.g.
    {"source": ".../pi-codegraph", "extensions": ["-index.ts"]}. Global
    extensions use +path/-path references, e.g. +extensions/orchestra/index.ts.
    """
    if not isinstance(settings, dict):
        return []
    enabled: set[str] = set()

    packages = settings.get("packages")
    if isinstance(packages, list):
        for entry in packages:
            if isinstance(entry, str):
                name = _package_name_from_source(entry)
                if name:
                    enabled.add(name)
                continue
            if not isinstance(entry, dict):
                continue
            name = _package_name_from_source(entry.get("source"))
            filters = entry.get("extensions")
            if isinstance(filters, list) and filters:
                has_enabled = any(not str(item).strip().startswith("-") for item in filters)
                has_disabled = any(str(item).strip().startswith("-") for item in filters)
                if name and (has_enabled or not has_disabled):
                    enabled.add(name)
            elif name:
                enabled.add(name)

    extensions = settings.get("extensions")
    if isinstance(extensions, list):
        for entry in extensions:
            text = str(entry or "").strip()
            name = _extension_name_from_ref(text)
            if not name:
                continue
            if text.startswith("-"):
                enabled.discard(name)
            else:
                enabled.add(name)

    return sorted(enabled)


def collect_container_runtime_snapshot() -> dict[str, object]:
    """Collect installed Pi package/extension provenance from the live container."""
    snapshot: dict[str, object] = {}
    if not _docker_ok():
        return snapshot

    package_names: list[str] = []
    try:
        pi_list = _docker_exec("sh", "-lc", "pi list 2>/dev/null || true")
        package_names = _parse_pi_list_package_names(pi_list.stdout)
        snapshot["pi_package_names"] = package_names
        snapshot["pi_packages_summary"] = ",".join(package_names) if package_names else "none"
        snapshot["pi_packages_sha256"] = _stable_object_sha256(package_names)
    except Exception:
        pass

    local_extension_names: list[str] = []
    try:
        ext_result = _docker_exec(
            "sh",
            "-lc",
            "find /root/.pi/agent/extensions -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' 2>/dev/null | sort",
        )
        local_extension_names = sorted({line.strip() for line in ext_result.stdout.splitlines() if line.strip()})
    except Exception:
        pass

    extension_names = sorted(set(package_names) | set(local_extension_names))
    snapshot["pi_extensions"] = extension_names
    snapshot["pi_extensions_summary"] = ",".join(extension_names) if extension_names else "none"
    snapshot["pi_extensions_sha256"] = _stable_object_sha256(extension_names)

    enabled_plugins: list[str] = []
    disabled_extensions: set[str] = set()
    try:
        settings_result = _docker_exec("sh", "-lc", "cat /root/.pi/agent/settings.json 2>/dev/null || true")
        if settings_result.stdout.strip():
            settings_data = _json.loads(settings_result.stdout)
            enabled_plugins = _parse_pi_settings_enabled_plugins(settings_data)
            disabled_extensions = _parse_pi_settings_disabled_extensions(settings_data)
    except Exception:
        pass
    # Locally installed Pi extensions under /root/.pi/agent/extensions are loaded
    # by Pi even when they are not listed in settings.json packages/extensions,
    # unless settings.json explicitly disables them with -extensions/name/...
    enabled_plugins = sorted((set(enabled_plugins) | set(local_extension_names)) - disabled_extensions)
    snapshot["pi_enabled_plugins"] = enabled_plugins
    snapshot["pi_enabled_plugins_summary"] = ",".join(enabled_plugins) if enabled_plugins else "none"
    snapshot["pi_enabled_plugins_sha256"] = _stable_object_sha256(enabled_plugins)

    return snapshot


def collect_runtime_snapshot(
    catalog_path: Path | str,
    orchestra_config_dir: Path | str | None = None,
    skills_dir: Path | str | None = None,
) -> dict[str, object]:
    """Collect benchmark/runtime provenance to persist with each run."""
    catalog = Path(catalog_path)
    root = catalog.parent.parent.parent if catalog.parent.parent.parent.exists() else _REPO_ROOT
    snapshot: dict[str, object] = {}
    snapshot.update(collect_catalog_runtime_snapshot(catalog))
    snapshot.update(collect_orchestra_config_snapshot(orchestra_config_dir or root / "config" / "orchestra"))
    snapshot.update(collect_aux_skills_snapshot(skills_dir or root / "config" / "skills"))
    snapshot.update(collect_container_runtime_snapshot())
    return snapshot


def build_run_metadata(
    task_id: str,
    run_id: str,
    catalog_path: Path | str,
    role: str | None = None,
    orchestra: bool | None = None,
    auto: bool | None = None,
    extra_skills: Sequence[str] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
    runtime_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the run metadata snapshot persisted to .bench_run.json."""
    meta = {
        "run_id": run_id,
        "task_id": task_id,
        **resolve_catalog_model(catalog_path, role=role),
        "orchestra": orchestra,
        "auto": auto,
        "extra_skills": list(extra_skills or []),
        "notes": notes,
    }
    if runtime_snapshot:
        meta.update(runtime_snapshot)
    if catalog_label:
        meta["catalog_path"] = catalog_label
    return meta


# ── Task loader ──────────────────────────────────────────────────────

def discover_tasks(tasks_dir: Path | str | None = None) -> list[Path]:
    """Return paths to task directories that have a task.yaml."""
    base = Path(tasks_dir or _REPO_ROOT / TASKS_DIR).resolve()
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / "task.yaml").is_file():
            out.append(entry)
    return out


def load_task(task_path: Path | str, tasks_dir: Path | str | None = None) -> TaskMeta:
    """Load task metadata from task.yaml into a TaskMeta dataclass."""
    base = Path(tasks_dir or _REPO_ROOT / TASKS_DIR).resolve()
    p = Path(task_path)

    # If it's already an absolute directory, use it directly.
    if str(p).startswith("/") and (p / "task.yaml").is_file():
        yaml_path = p / "task.yaml"
    else:
        # Relative name — resolve under tasks_dir
        task_dir = base / p.name
        yaml_path = task_dir / "task.yaml"

    data = _load_yaml(yaml_path)
    return TaskMeta(
        task_id=data.get("task_id", Path(task_path).name),
        description=data.get("description", ""),
        family=data.get("family", "default"),
        batch=data.get("batch", ""),
        scoring_type=data.get("scoring_type", "pass_fail"),
        timeout_minutes=int(data.get("timeout_minutes", 10)),
        evaluator=data.get("evaluator", "evaluate/run.sh"),
        split=data.get("split", "dev"),
    )


def list_tasks(tasks_dir: Path | str | None = None) -> list[TaskMeta]:
    """Discover and load all tasks."""
    metas: list[TaskMeta] = []
    for task_dir in discover_tasks(tasks_dir):
        try:
            metas.append(load_task(task_dir, tasks_dir))
        except Exception as exc:
            print(f"[bench] warning: failed to load {task_dir.name}: {exc}", file=sys.stderr)
    return metas


# ── Docker helpers ───────────────────────────────────────────────────

def _docker_ok() -> bool:
    """Check docker is available and the container is running."""
    if not shutil.which("docker"):
        return False
    try:
        out = sp.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
            capture_output=True, text=True, check=False,
        )
        return out.stdout.strip() == "true"
    except Exception:
        return False


def _docker_exec(*args: str, env: dict[str, str] | None = None) -> sp.CompletedProcess[str]:
    """Run a command inside the benchmark container."""
    cmd = ["docker", "exec"]
    if env:
        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])
    cmd.append(CONTAINER_NAME)
    cmd.extend(args)
    return sp.run(cmd, capture_output=True, text=True)


def _copy_from_container(container_path: str, host_path: Path) -> bool:
    """Best-effort docker cp from container to host."""
    host_path.parent.mkdir(parents=True, exist_ok=True)
    proc = sp.run(
        ["docker", "cp", f"{CONTAINER_NAME}:{container_path}", str(host_path)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _orchestra_db_run_count(path: Path) -> int | None:
    """Return run count for an Orchestra sqlite DB, or None if unreadable."""
    try:
        con = sqlite3.connect(str(path))
        try:
            row = con.execute("select count(*) from runs").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()
    except Exception:
        return None


def _orchestra_debug_run_count(text: str) -> int | None:
    """Parse the top-level `runs: N` line from `orchestra debug` markdown."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("runs:"):
            raw = stripped.split(":", 1)[1].strip()
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _copy_orchestra_db_preserving_nonempty(container_path: str, host_path: Path, warnings: list[object]) -> bool:
    """Copy Orchestra DB without replacing a non-empty captured DB with empty state."""
    tmp_path = host_path.with_suffix(host_path.suffix + ".tmp")
    if not _copy_from_container(container_path, tmp_path):
        return False

    new_count = _orchestra_db_run_count(tmp_path)
    old_count = _orchestra_db_run_count(host_path) if host_path.exists() else None
    if old_count and old_count > 0 and new_count == 0:
        tmp_path.unlink(missing_ok=True)
        warnings.append("kept earlier non-empty Orchestra state DB; current runtime DB was empty")
        return True

    host_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(host_path)
    return True


def _parse_pi_session_file(path: Path) -> dict[str, object]:
    """Extract session id, token totals, and final context usage from one Pi JSONL session file."""
    out: dict[str, object] = {"file": path.name}
    totals = {"input": 0, "output": 0, "reasoning": 0, "totalTokens": 0}
    context_usage: dict[str, object] = {"api_call_count": 0}
    last_usage: dict[str, int] = {}
    compaction_count = 0
    try:
        for line in path.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            event = _json.loads(line)
            if isinstance(event, dict) and event.get("type") == "compaction":
                compaction_count += 1
            if event.get("type") == "session" and event.get("id"):
                out["session_id"] = event.get("id")
                out["cwd"] = event.get("cwd", "")
            msg = event.get("message") if isinstance(event, dict) else None
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if isinstance(usage, dict):
                call_usage: dict[str, int] = {}
                for key in totals:
                    value = usage.get(key)
                    if isinstance(value, (int, float)):
                        int_value = int(value)
                        totals[key] += int_value
                        call_usage[key] = int_value
                if call_usage:
                    context_usage["api_call_count"] = int(context_usage["api_call_count"]) + 1
                    last_usage = call_usage
    except Exception as exc:
        out["parse_error"] = str(exc)
    out["usage"] = totals
    if last_usage:
        context_usage.update({
            "last_input_tokens": last_usage.get("input", 0),
            "last_total_tokens": last_usage.get("totalTokens", 0),
            "compaction_count": compaction_count,
        })
        out["context_usage"] = context_usage
    return out


def collect_run_artifacts(task_id: str, run_id: str) -> Path:
    """Best-effort collection of Pi sessions and Orchestra debug artifacts.

    Missing Pi/Orchestra artifacts are normal for some runs. This function never
    raises for absent artifacts; it writes an artifact manifest either way.
    """
    run_dir = (_REPO_ROOT / RESULTS_DIR / f"{run_id}-{task_id}").resolve()
    artifacts_dir = run_dir / "artifacts"
    pi_dir = artifacts_dir / "pi-sessions"
    orch_dir = artifacts_dir / "orchestra-debug"
    pi_dir.mkdir(parents=True, exist_ok=True)
    orch_dir.mkdir(parents=True, exist_ok=True)

    workdir = f"/workspace/{run_id}-{task_id}"
    manifest: dict[str, object] = {
        "run_id": run_id,
        "task_id": task_id,
        "workdir": workdir,
        "pi_sessions": [],
        "orchestra": {},
        "warnings": [],
    }

    if _docker_ok():
        find_sessions = _docker_exec(
            "sh", "-c",
            "python3 - <<'PY'\n"
            "import json\n"
            "from pathlib import Path\n"
            f"target = {workdir!r}\n"
            "base = Path('/root/.pi/agent/sessions')\n"
            "for p in sorted(base.rglob('*.jsonl')) if base.exists() else []:\n"
            "    try:\n"
            "        first = p.read_text(errors='replace').splitlines()[0]\n"
            "        data = json.loads(first)\n"
            "        if data.get('cwd') == target:\n"
            "            print(p)\n"
            "    except Exception:\n"
            "        pass\n"
            "PY"
        )
        if find_sessions.returncode == 0:
            for session_path in [p for p in find_sessions.stdout.splitlines() if p.strip()]:
                dest = pi_dir / Path(session_path).name
                if _copy_from_container(session_path, dest):
                    manifest["pi_sessions"].append(_parse_pi_session_file(dest))  # type: ignore[union-attr]
                else:
                    manifest["warnings"].append(f"failed to copy Pi session: {session_path}")  # type: ignore[union-attr]
        elif find_sessions.stderr.strip():
            manifest["warnings"].append(find_sessions.stderr.strip())  # type: ignore[union-attr]

        # Orchestra artifacts: copy only when present. These may not exist if
        # Orchestra was not used, and that should not fail the run.
        orch_checks = {
            "doctor.txt": "orchestra doctor",
            "state/orchestra.db": "test -f /root/.pi/agent/orchestra/state/orchestra.db && echo yes || true",
            "logs": "test -d /root/.pi/agent/orchestra/logs && echo yes || true",
        }
        doctor = _docker_exec("sh", "-c", orch_checks["doctor.txt"])
        (orch_dir / "doctor.txt").write_text((doctor.stdout or "") + (doctor.stderr or ""))
        manifest["orchestra"]["doctor_collected"] = True  # type: ignore[index]

        has_db = _docker_exec("sh", "-c", orch_checks["state/orchestra.db"]).stdout.strip() == "yes"
        if has_db and _copy_orchestra_db_preserving_nonempty(
            "/root/.pi/agent/orchestra/state/orchestra.db",
            orch_dir / "state" / "orchestra.db",
            manifest["warnings"],  # type: ignore[arg-type]
        ):
            manifest["orchestra"]["state_db"] = "orchestra-debug/state/orchestra.db"  # type: ignore[index]

        has_logs = _docker_exec("sh", "-c", orch_checks["logs"]).stdout.strip() == "yes"
        if has_logs and _copy_from_container("/root/.pi/agent/orchestra/logs", orch_dir / "logs"):
            manifest["orchestra"]["logs"] = "orchestra-debug/logs"  # type: ignore[index]
    else:
        manifest["warnings"].append("container not running; skipped artifact collection")  # type: ignore[union-attr]

    # Aggregate simple token totals for reporting.
    totals = {"input": 0, "output": 0, "reasoning": 0, "totalTokens": 0}
    session_ids: list[str] = []
    for session in manifest["pi_sessions"]:  # type: ignore[union-attr]
        if isinstance(session, dict):
            if session.get("session_id"):
                session_ids.append(str(session["session_id"]))
            usage = session.get("usage")
            if isinstance(usage, dict):
                for key in totals:
                    value = usage.get(key)
                    if isinstance(value, (int, float)):
                        totals[key] += int(value)
    # Proper Orchestra trace capture uses `orchestra debug`. Query session-id
    # variants, but expose only authoritative non-empty debug bundles when any
    # variant resolves runs. Empty variant output is retained under debug-empty
    # for troubleshooting, not listed as the primary debug trace.
    debug_files: list[str] = []
    debug_entries: list[tuple[str, Path, int]] = []
    if _docker_ok():
        debug_dir = orch_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        empty_debug_dir = orch_dir / "debug-empty"
        def write_debug_output(debug_proc, debug_path: Path, manifest_name: str) -> None:
            debug_text = (debug_proc.stdout or "") + (debug_proc.stderr or "")
            if debug_proc.returncode == 0 and debug_text.strip():
                run_count = _orchestra_debug_run_count(debug_text)
                debug_path.write_text(debug_text)
                debug_entries.append((manifest_name, debug_path, run_count or 0))
                return
            error_dir = orch_dir / "debug-errors"
            error_dir.mkdir(parents=True, exist_ok=True)
            error_path = error_dir / debug_path.name
            error_path.write_text(debug_text or f"orchestra debug failed with exit code {debug_proc.returncode}\n")
            manifest["warnings"].append(f"orchestra debug failed: {error_path.relative_to(artifacts_dir)}")  # type: ignore[union-attr]

        debug_session_ids: list[str] = []
        seen_debug_session_ids: set[str] = set()
        for session_id in session_ids:
            for candidate in sorted(_session_id_variants(session_id)):
                if candidate not in seen_debug_session_ids:
                    seen_debug_session_ids.add(candidate)
                    debug_session_ids.append(candidate)

        for session_id in debug_session_ids:
            safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in session_id)
            debug_proc = _docker_exec(
                "sh", "-c",
                f"orchestra debug --session-id {shlex.quote(session_id)}",
            )
            debug_path = debug_dir / f"session-{safe_name}.md"
            write_debug_output(debug_proc, debug_path, f"orchestra-debug/debug/{debug_path.name}")
        if not session_ids:
            debug_proc = _docker_exec(
                "sh", "-c",
                f"orchestra debug --run-id {shlex.quote(run_id)}",
            )
            debug_path = debug_dir / f"run-{run_id}.md"
            write_debug_output(debug_proc, debug_path, f"orchestra-debug/debug/{debug_path.name}")
    if debug_entries:
        nonempty_entries = [entry for entry in debug_entries if entry[2] > 0]
        if nonempty_entries:
            empty_debug_dir.mkdir(parents=True, exist_ok=True)
            for _manifest_name, debug_path, run_count in debug_entries:
                if run_count == 0 and debug_path.exists():
                    debug_path.replace(empty_debug_dir / debug_path.name)
            debug_files = [manifest_name for manifest_name, _path, _count in nonempty_entries]
            manifest["orchestra"]["debug_empty"] = [
                f"orchestra-debug/debug-empty/{path.name}"
                for _manifest_name, path, count in debug_entries
                if count == 0
            ]  # type: ignore[index]
            manifest["orchestra"]["debug_authoritative"] = debug_files  # type: ignore[index]
        else:
            debug_files = [manifest_name for manifest_name, _path, _count in debug_entries]
        manifest["orchestra"]["debug"] = debug_files  # type: ignore[index]

    main_context_usage: dict[str, object] = {}
    main_sessions = [
        session for session in manifest["pi_sessions"]  # type: ignore[index]
        if isinstance(session, dict)
        and str(session.get("cwd") or "") == workdir
        and not str(session.get("session_id") or "").startswith("orchestra-worker-")
    ]
    if main_sessions:
        # Use the latest copied main session. Its final API call input token count
        # is the best available snapshot of how full the main conversation context
        # was when the session ended. Max input is kept for sessions that compact.
        main_session = main_sessions[-1]
        context_usage = main_session.get("context_usage")
        if isinstance(context_usage, dict):
            main_context_usage = {
                "session_id": main_session.get("session_id", ""),
                "file": main_session.get("file", ""),
                **context_usage,
            }
            manifest["main_session_context_usage"] = main_context_usage

    token_payload = {
        "input_tokens": totals["input"],
        "output_tokens": totals["output"],
        "reasoning_tokens": totals["reasoning"],
        "total_tokens": totals["totalTokens"],
    }
    if main_context_usage:
        last_input = main_context_usage.get("last_input_tokens")
        last_total = main_context_usage.get("last_total_tokens")
        api_calls = main_context_usage.get("api_call_count")
        if isinstance(last_input, (int, float)):
            token_payload["main_session_context_input_tokens"] = int(last_input)
        if isinstance(last_total, (int, float)):
            token_payload["main_session_context_total_tokens"] = int(last_total)
        if isinstance(api_calls, (int, float)):
            token_payload["main_session_api_call_count"] = int(api_calls)
    (artifacts_dir / "tokens.json").write_text(_json.dumps(token_payload, indent=2) + "\n")
    (artifacts_dir / "pi-sessions.json").write_text(_json.dumps({"session_ids": session_ids, "sessions": manifest["pi_sessions"]}, indent=2) + "\n")
    (artifacts_dir / "manifest.json").write_text(_json.dumps(manifest, indent=2) + "\n")
    return artifacts_dir


# ── Harness flow ─────────────────────────────────────────────────────

def prepare(task_id: str, run_id: str | None = None) -> dict[str, str]:
    """Reset container workspace and prepare for a task run.

    Returns env vars (run_id, workdir path) the caller should pass through.
    """
    if not _docker_ok():
        raise RuntimeError(
            f"Container '{CONTAINER_NAME}' is not running. "
            "Run 'scripts/build-env start' first."
        )

    run_id = run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    bench_env: dict[str, str] = {
        "BENCH_RUN_ID": run_id,
        "BENCH_TASK_ID": task_id,
    }

    # Reset workspace first
    _docker_exec("bench-entrypoint", "reset", env=bench_env)

    return {"run_id": run_id}


def run_task(
    task_id: str,
    command: Sequence[str] | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    """Run a task inside the container.

    If *command* is given it's exec'd in the workdir after setup.
    Returns env vars including run_id and workdir.
    """
    if not _docker_ok():
        raise RuntimeError(f"Container '{CONTAINER_NAME}' not running.")

    run_id = run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    bench_env: dict[str, str] = {
        "BENCH_RUN_ID": run_id,
        "BENCH_TASK_ID": task_id,
    }

    workdir = f"/workspace/{run_id}-{task_id}"

    # Set up workdir via entrypoint + optionally exec command in same shell
    if command:
        cmds = "; ".join(command)
        setup_cmd = (f"bench-entrypoint run {task_id}; cd {workdir}; {cmds}")
        result = _docker_exec("bash", "-c", setup_cmd, env=bench_env)
        if result.returncode != 0 and result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
    else:
        _docker_exec("bench-entrypoint", "run", task_id, env=bench_env)

    return {"run_id": run_id, "workdir": workdir}


def grade(
    task_id: str,
    run_id: str,
    task_meta: TaskMeta | None = None,
) -> TaskResult:
    """Run the evaluator inside the container and return a TaskResult."""
    if not _docker_ok():
        raise RuntimeError(f"Container '{CONTAINER_NAME}' not running.")

    task_meta = task_meta or load_task(task_id)
    evaluator_script = task_meta.evaluator  # e.g. "evaluate/run.sh"

    eval_tmp = f"/tmp/bench-eval-{run_id}-{task_id}"
    eval_dir = f"{eval_tmp}/evaluate"
    bench_env: dict[str, str] = {
        "BENCH_RUN_ID": run_id,
        "BENCH_TASK_ID": task_id,
        "BENCH_REPO_ROOT": eval_dir,
        "BENCH_TASKS": str(_REPO_ROOT / TASKS_DIR),
    }

    evaluator_host = _REPO_ROOT / TASKS_DIR / task_id / evaluator_script
    if not evaluator_host.is_file():
        raise FileNotFoundError(f"evaluator not found: {evaluator_host}")

    _docker_exec("rm", "-rf", eval_tmp, env=bench_env)
    _docker_exec("mkdir", "-p", eval_dir, env=bench_env)

    support_files = {
        evaluator_host: f"{eval_dir}/run.sh",
        _REPO_ROOT / "capability_helpers.py": f"{eval_dir}/capability_helpers.py",
        _REPO_ROOT / "rubric_helpers.py": f"{eval_dir}/rubric_helpers.py",
    }
    for host_path, container_path in support_files.items():
        if not host_path.is_file():
            raise FileNotFoundError(f"evaluator support file not found: {host_path}")
        cp_proc = sp.run(
            ["docker", "cp", str(host_path), f"{CONTAINER_NAME}:{container_path}"],
            capture_output=True,
            text=True,
        )
        if cp_proc.returncode != 0:
            raise RuntimeError(
                cp_proc.stderr.strip()
                or cp_proc.stdout.strip()
                or f"docker cp failed: {host_path.name}"
            )

    # Remove stale result.json before evaluator runs. If the evaluator prints
    # JSON instead of writing a file, fallback parsing must use this run's
    # stdout rather than a previous result file.
    pre_result_dir = (_REPO_ROOT / RESULTS_DIR / f"{run_id}-{task_id}").resolve()
    pre_result_path = pre_result_dir / "result.json"
    previous_result: TaskResult | None = None
    if pre_result_path.exists():
        try:
            previous_result = TaskResult.from_json(pre_result_path)
        except Exception:
            previous_result = None
        pre_result_path.unlink()

    eval_cmd = (
        "bench-entrypoint",
        "eval",
        task_id,
        "bash",
        f"{eval_tmp}/evaluate/run.sh",
    )
    result_proc = _docker_exec(*eval_cmd, env=bench_env)
    _docker_exec("rm", "-rf", eval_tmp, env=bench_env)

    # Read the result.json written by the evaluator into /bench/results/
    result_dir = (_REPO_ROOT / RESULTS_DIR / f"{run_id}-{task_id}").resolve()

    result_path = result_dir / "result.json"
    task_result: TaskResult
    if result_path.exists():
        task_result = TaskResult.from_json(result_path)
    else:
        # Fallback — construct from evaluator output. Evaluators commonly print
        # JSON to stdout instead of writing result.json directly.
        stdout = result_proc.stdout.strip()
        parsed = _parse_json_object_from_stdout(stdout)

        if not parsed and result_proc.returncode != 0:
            raise RuntimeError(
                result_proc.stderr.strip()
                or result_proc.stdout.strip()
                or f"evaluator failed without JSON for {run_id}-{task_id}"
            )
        if not parsed and previous_result is not None:
            task_result = previous_result
        else:
            score = str(parsed.get("score") or ("pass" if result_proc.returncode == 0 else "fail"))
            checks = parsed.get("checks") if isinstance(parsed.get("checks"), dict) else {}
            score_numeric = parsed.get("score_numeric")
            rubric = parsed.get("rubric") if isinstance(parsed.get("rubric"), dict) else {}
            orchestration_checks = parsed.get("orchestration_checks") if isinstance(parsed.get("orchestration_checks"), dict) else {}
            efficiency = parsed.get("efficiency") if isinstance(parsed.get("efficiency"), dict) else {}
            details = parsed.get("details") if isinstance(parsed.get("details"), str) else stdout[-500:]
            task_result = TaskResult(
                task_id=task_id,
                run_id=run_id,
                score=score,
                checks=checks,
                score_numeric=float(score_numeric) if isinstance(score_numeric, (int, float)) else None,
                rubric=rubric,
                orchestration_checks=orchestration_checks,
                efficiency=efficiency,
                details=details,
            )

    # Enrich with task metadata snapshot
    task_result.task_meta = {
        "family": task_meta.family,
        "batch": task_meta.batch,
        "scoring_type": task_meta.scoring_type,
    }

    # Propagate dev/holdout split from task config into result
    if not task_result.split and task_meta.split:
        task_result.split = task_meta.split

    # Enrich with operator run metadata (.bench_run.json) if present
    _enrich_result_with_bench_run(task_result)

    run_meta = task_result.run_meta if isinstance(task_result.run_meta, dict) else {}
    started_epoch = run_meta.get("started_epoch")
    completed_epoch = run_meta.get("completed_epoch")
    previous_elapsed = (
        previous_result.elapsed_seconds
        if previous_result is not None and previous_result.elapsed_seconds is not None
        else None
    )

    if task_result.elapsed_seconds is None:
        if isinstance(started_epoch, (int, float)) and isinstance(completed_epoch, (int, float)):
            task_result.elapsed_seconds = max(0.0, float(completed_epoch) - float(started_epoch))
        elif previous_elapsed is not None:
            task_result.elapsed_seconds = previous_elapsed

    # Best-effort artifact capture: Pi sessions, token totals, Orchestra traces.
    # Missing artifacts are expected when Orchestra was not used.
    collect_run_artifacts(task_id, run_id)
    ingest_artifacts(task_result)

    if task_result.elapsed_seconds is None:
        if isinstance(started_epoch, (int, float)) and started_epoch > 0:
            task_result.elapsed_seconds = max(0.0, time.time() - float(started_epoch))

    return task_result


def report(result: TaskResult) -> str:
    """Return a human-readable one-line summary of the result."""
    status = "PASS" if result.is_pass() else "FAIL"
    return f"[{status}] {result.task_id} ({result.run_id}) — score={result.score}"


def run_full(
    task_id: str,
    command: Sequence[str] | None = None,
    run_id: str | None = None,
) -> TaskResult:
    """Full flow: prepare → run → grade → report.

    Returns the written TaskResult.
    """
    print(f"[bench] preparing task={task_id} ...")
    prep = prepare(task_id, run_id=run_id)
    run_id = prep["run_id"]

    if command:
        print(f"[bench] running task={task_id} (command provided) ...")
        ctx = run_task(task_id, command=command, run_id=run_id)
    else:
        print(f"[bench] skipping run step for {task_id} (no command)")

    # Load metadata
    meta = load_task(task_id)

    print(f"[bench] grading task={task_id} ...")
    result = grade(task_id, run_id, task_meta=meta)

    # Persist structured result
    dest = result.write_json()
    print(report(result))
    print(f"  → {dest}")
    return result


# ── Artifact ingestion ──────────────────────────────────────────────

_ARTIFACT_TOKEN_KEYS = (
    "total_tokens", "prompt_tokens", "completion_tokens",
    "input_tokens", "output_tokens", "reasoning_tokens",
    "parent_tokens", "worker_tokens",
    "main_session_context_input_tokens", "main_session_context_total_tokens",
    "main_session_api_call_count",
)


def ingest_artifacts(
    result: TaskResult,
    base_dir: Path | str | None = None,
) -> TaskResult:
    """Enrich a TaskResult with data from artifact files if available.

    Looks for <base_dir>/<run_id>-<task_id>/artifacts/tokens.json and other
    known artifact paths. Returns the (possibly enriched) result — never raises.
    Missing artifacts are silently skipped so results remain meaningful even
    when token data is absent.
    """
    base = Path(base_dir or (_REPO_ROOT / RESULTS_DIR)).resolve()
    run_dir = base / f"{result.run_id}-{result.task_id}"
    if not run_dir.is_dir():
        return result

    artifacts_dir = run_dir / "artifacts"
    token_file = artifacts_dir / "tokens.json"
    if token_file.is_file():
        try:
            data = _json.loads(token_file.read_text())
            tokens: dict[str, object] = {}
            existing_tokens = result.tokens if isinstance(result.tokens, dict) else {}
            for key in _ARTIFACT_TOKEN_KEYS:
                if key in data and isinstance(data[key], (int, float)):
                    value = data[key]
                    existing_value = existing_tokens.get(key)
                    if value > 0 or not isinstance(existing_value, (int, float)) or existing_value <= 0:
                        tokens[key] = value

            # Also map to a simple 'total' if not already present
            existing_total = existing_tokens.get("total")
            if "total" in data and isinstance(data["total"], (int, float)):
                value = data["total"]
                if value > 0 or not isinstance(existing_total, (int, float)) or existing_total <= 0:
                    tokens["total"] = int(value)
            elif "total_tokens" in tokens:
                value = tokens["total_tokens"]
                if value > 0 or not isinstance(existing_total, (int, float)) or existing_total <= 0:
                    tokens["total"] = int(value)

            result.tokens = {**result.tokens, **tokens}
        except Exception as exc:
            print(f"[bench] warning: failed to parse tokens from {token_file}: {exc}",
                  file=sys.stderr)

    sessions_file = artifacts_dir / "pi-sessions.json"
    if sessions_file.is_file():
        try:
            data = _json.loads(sessions_file.read_text())
            session_ids = data.get("session_ids") if isinstance(data, dict) else None
            if isinstance(session_ids, list) and session_ids:
                result.run_meta["pi_session_ids"] = [str(s) for s in session_ids]
        except Exception as exc:
            print(f"[bench] warning: failed to parse Pi sessions from {sessions_file}: {exc}",
                  file=sys.stderr)

    if not result.run_meta.get("pi_session_ids"):
        session_ids_from_files: list[str] = []
        pi_sessions_dir = artifacts_dir / "pi-sessions"
        if pi_sessions_dir.is_dir():
            for path in sorted(pi_sessions_dir.glob("*.jsonl")):
                stem = path.stem
                session_id = stem.split("_", 1)[1] if "_" in stem else stem
                if session_id and session_id not in session_ids_from_files:
                    session_ids_from_files.append(session_id)
        if session_ids_from_files:
            result.run_meta["pi_session_ids"] = session_ids_from_files

    manifest_file = artifacts_dir / "manifest.json"
    if manifest_file.is_file():
        try:
            data = _json.loads(manifest_file.read_text())
            if isinstance(data, dict) and isinstance(data.get("orchestra"), dict):
                result.run_meta["orchestra_artifacts"] = data["orchestra"]
        except Exception as exc:
            print(f"[bench] warning: failed to parse artifact manifest from {manifest_file}: {exc}",
                  file=sys.stderr)

    # Timing artifact (elapsed_seconds) — ingested if present and not already set.
    # If no timing artifact exists, fall back to the operator run start time before
    # efficiency is computed so real Pi runs still get elapsed comparisons.
    if result.elapsed_seconds is None:
        timing_file = artifacts_dir / "timing.json"
        if timing_file.is_file():
            try:
                data = _json.loads(timing_file.read_text())
                for key in ("elapsed_seconds", "duration_seconds", "wall_time"):
                    if key in data and isinstance(data[key], (int, float)):
                        result.elapsed_seconds = float(data[key])
                        break
            except Exception as exc:
                print(f"[bench] warning: failed to parse timing from {timing_file}: {exc}",
                      file=sys.stderr)

    if result.elapsed_seconds is None:
        run_meta = result.run_meta if isinstance(result.run_meta, dict) else {}
        started_epoch = run_meta.get("started_epoch")
        if isinstance(started_epoch, (int, float)) and started_epoch > 0:
            result.elapsed_seconds = max(0.0, time.time() - float(started_epoch))

    # Orchestra process diagnostics — best-effort, non-fatal.
    try:
        orch_checks = extract_orchestration_checks(result, base_dir=base)
        if orch_checks:
            result.orchestration_checks.update(orch_checks)
    except Exception as exc:
        print(f"[bench] warning: failed to extract orchestration checks: {exc}",
              file=sys.stderr)

    try:
        if not result.efficiency:
            result.efficiency = compare_efficiency(result, base)
    except Exception as exc:
        print(f"[bench] warning: failed to compare efficiency: {exc}",
              file=sys.stderr)

    apply_process_penalties(result)
    result.category_scores = compute_category_scores(result)
    return result


def _enrich_result_with_bench_run(
    result: TaskResult,
    base_dir: Path | str | None = None,
) -> TaskResult:
    """Read .bench_run.json from the run's results directory and merge into run_meta.

    build-task writes this config file before a manual Pi session. If it exists,
    its operator-facing fields (model, orchestra, extra_skills, notes) are merged
    into result.run_meta so the final result.json carries full provenance.

    Never raises — missing or malformed config files are silently skipped.
    """
    base = Path(base_dir or (_REPO_ROOT / RESULTS_DIR)).resolve()
    run_dir = base / f"{result.run_id}-{result.task_id}"
    if not run_dir.is_dir():
        return result

    config_file = run_dir / ".bench_run.json"
    if not config_file.is_file():
        return result

    try:
        data = _json.loads(config_file.read_text())
    except Exception as exc:
        print(f"[bench] warning: failed to parse .bench_run.json from {config_file}: {exc}",
              file=sys.stderr)
        return result

    if not isinstance(data, dict):
        return result

    # Merge benchmark metadata into run_meta (non-destructive)
    for key, value in data.items():
        if key in {"run_id", "task_id"} or value is None:
            continue
        result.run_meta[key] = value

    return result


# ── Collect / summarize results ──────────────────────────────────────


# ── Orchestra process artifact extraction (Slice 3) ───────────────


def _parse_pi_session_dispatches(pi_sessions_dir: Path) -> list[dict[str, object]]:
    """Extract orch_dispatch tool calls from Pi session JSONL files.

    Returns a list of dicts with keys: role, goal, task_label.
    Missing or malformed sessions are silently skipped.
    """
    dispatches: list[dict[str, object]] = []
    if not pi_sessions_dir.is_dir():
        return dispatches

    for jsonl_file in sorted(pi_sessions_dir.glob("*.jsonl")):
        try:
            text = jsonl_file.read_text(errors="replace")
        except Exception:
            continue

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                event = _json.loads(line)
            except (ValueError, TypeError):
                continue

            msg = event.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue

            content = msg.get("content")
            if not isinstance(content, list):
                continue

            for item in content:
                if not isinstance(item, dict):
                    continue
                tc_type = item.get("type") == "toolCall"
                tool_name = item.get("name", "")
                arguments = item.get("arguments")
                if (tc_type and tool_name == "orch_dispatch" and isinstance(arguments, dict)):
                    dispatches.append({
                        "role": str(arguments.get("role", "unknown")),
                        "goal": str(arguments.get("goal", "")),
                        "task_label": str(arguments.get("taskLabel", arguments.get("task_label", ""))),
                    })

    return dispatches


def _count_pi_session_compactions(pi_sessions_dir: Path) -> int:
    """Count explicit Pi compaction events across copied session JSONL files."""
    if not pi_sessions_dir.is_dir():
        return 0

    count = 0
    for jsonl_file in sorted(pi_sessions_dir.glob("*.jsonl")):
        try:
            text = jsonl_file.read_text(errors="replace")
        except Exception:
            continue

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                event = _json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(event, dict) and event.get("type") == "compaction":
                count += 1

    return count


def _count_pi_session_worker_successes(pi_sessions_dir: Path) -> int:
    """Count orchestra worker success return markers seen in copied Pi sessions."""
    if not pi_sessions_dir.is_dir():
        return 0

    count = 0
    for jsonl_file in sorted(pi_sessions_dir.glob("*.jsonl")):
        try:
            text = jsonl_file.read_text(errors="replace")
        except Exception:
            continue

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                event = _json.loads(line)
            except (ValueError, TypeError):
                continue

            msg = event.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                text_value = str(item.get("text", ""))
                if text_value.startswith("[orchestra:") and " success]" in text_value:
                    count += 1
                    break

    return count


def _parse_orchestra_logs(orchestra_debug_dir: Path) -> list[dict[str, object]]:
    """Extract structured events from Orchestra debug log JSONL files.

    Returns a flat list of event dicts. Missing or malformed logs are skipped.
    """
    events: list[dict[str, object]] = []
    if not orchestra_debug_dir.is_dir():
        return events

    logs_dir = orchestra_debug_dir / "logs"
    if not logs_dir.is_dir():
        # Try direct .jsonl files in the debug dir itself
        for jsonl_file in sorted(orchestra_debug_dir.glob("*.jsonl")):
            _read_jsonl_events(jsonl_file, events)
        return events

    for jsonl_file in sorted(logs_dir.rglob("*.jsonl")):
        _read_jsonl_events(jsonl_file, events)
    return events


def _session_id_variants(session_id: object) -> set[str]:
    """Return comparable forms for Pi parent/worker session ids."""
    raw = str(session_id or "").strip()
    if not raw:
        return set()
    variants = {raw}
    if raw.startswith("pi:"):
        variants.add(raw[3:])
    else:
        variants.add(f"pi:{raw}")
    return variants



def _load_orchestration_session_ids(
    result: TaskResult,
    artifacts_dir: Path,
) -> set[str]:
    """Load parent/worker Pi session ids for the current run."""
    session_ids: set[str] = set()

    run_meta = result.run_meta if isinstance(result.run_meta, dict) else {}
    raw_ids = run_meta.get("pi_session_ids")
    if isinstance(raw_ids, list):
        for session_id in raw_ids:
            session_ids.update(_session_id_variants(session_id))

    if session_ids:
        return session_ids

    sessions_file = artifacts_dir / "pi-sessions.json"
    if sessions_file.is_file():
        try:
            data = _json.loads(sessions_file.read_text())
            raw_ids = data.get("session_ids") if isinstance(data, dict) else None
            if isinstance(raw_ids, list):
                for session_id in raw_ids:
                    session_ids.update(_session_id_variants(session_id))
        except Exception:
            pass

    if session_ids:
        return session_ids

    pi_sessions_dir = artifacts_dir / "pi-sessions"
    if pi_sessions_dir.is_dir():
        for path in pi_sessions_dir.glob("*.jsonl"):
            stem = path.stem
            # Session filenames are timestamp_sessionid.jsonl. Worker ids may
            # contain underscores; split only on the timestamp separator.
            if "_" in stem:
                session_ids.update(_session_id_variants(stem.split("_", 1)[1]))
            else:
                session_ids.update(_session_id_variants(stem))

    if session_ids:
        return session_ids

    manifest_file = artifacts_dir / "manifest.json"
    if manifest_file.is_file():
        try:
            data = _json.loads(manifest_file.read_text())
            sessions = data.get("pi_sessions") if isinstance(data, dict) else None
            if isinstance(sessions, list):
                for session in sessions:
                    if isinstance(session, dict):
                        session_ids.update(_session_id_variants(session.get("session_id")))
        except Exception:
            pass

    return session_ids



def _filter_orchestra_events_for_run(
    events: list[dict[str, object]],
    session_ids: set[str],
) -> list[dict[str, object]]:
    """Prefer events linked to the current parent/worker Pi sessions."""
    if not events or not session_ids:
        return events

    relevant_run_ids: set[str] = set()
    has_session_linkage = False
    for event in events:
        orchestrator_session_id = str(event.get("orchestrator_session_id", "")).strip()
        worker_session_id = str(event.get("worker_session_id", "")).strip()
        if orchestrator_session_id or worker_session_id:
            has_session_linkage = True
        if orchestrator_session_id in session_ids or worker_session_id in session_ids:
            run_id = str(event.get("run_id", "")).strip()
            if run_id:
                relevant_run_ids.add(run_id)

    if not relevant_run_ids:
        return [] if has_session_linkage else events

    filtered = []
    for event in events:
        run_id = str(event.get("run_id", "")).strip()
        if run_id in relevant_run_ids:
            filtered.append(event)
    return filtered



def _read_jsonl_events(jsonl_path: Path, out: list[dict[str, object]]) -> None:
    """Read one JSONL file and append valid event dicts to *out*."""
    try:
        text = jsonl_path.read_text(errors="replace")
    except Exception:
        return

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = _json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and "event" in event:
            out.append(event)


def extract_orchestration_checks(
    result: TaskResult,
    base_dir: Path | str | None = None,
) -> dict[str, object]:
    """Extract orchestration process diagnostics from artifacts.

    Best-effort extraction — missing or malformed artifact files never cause
    an error. Returns a dict suitable for ``result.orchestration_checks`` with
    keys:

      - target_role_dispatched (bool): whether the expected role was dispatched
      - worker_completed (bool): at least one worker exited successfully
      - dispatch_count (int): total number of orch_dispatch calls found
      - roles_dispatched (list[str]): unique roles that were dispatched
      - timeouts (int): count of timeout events in Orchestra logs
      - retries (int): count of retry events in Orchestra logs
      - scope_blockers (int): count of scope.blocked events
      - same_slice_redispatches (int): dispatches with duplicate goals
      - premature_completion (bool): dispatched but result suggests no integration
      - missing_expected_role (bool): target role expected but not found anywhere
    """
    base = Path(base_dir or (_REPO_ROOT / RESULTS_DIR)).resolve()
    run_dir = base / f"{result.run_id}-{result.task_id}"
    if not run_dir.is_dir():
        return {}

    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return {}

    checks: dict[str, object] = {}

    # ── 1. Parse Pi session dispatches / compactions ─────────────────
    pi_sessions_dir = artifacts_dir / "pi-sessions"
    dispatches = _parse_pi_session_dispatches(pi_sessions_dir)
    checks["compaction_count"] = _count_pi_session_compactions(pi_sessions_dir)
    worker_success_returns = _count_pi_session_worker_successes(pi_sessions_dir)

    roles_dispatched: list[str] = []
    goals_seen: dict[str, int] = {}
    for d in dispatches:
        role = str(d.get("role", "unknown"))
        if role not in roles_dispatched:
            roles_dispatched.append(role)
        goal = str(d.get("goal", "")).strip()
        goals_seen[goal] = goals_seen.get(goal, 0) + 1

    checks["dispatch_count"] = len(dispatches)
    checks["roles_dispatched"] = roles_dispatched

    # Same-slice redispatches: goals dispatched more than once
    same_slice_redispatches = sum(v - 1 for v in goals_seen.values() if v > 1)
    checks["same_slice_redispatches"] = max(0, same_slice_redispatches)

    # ── 2. Parse Orchestra log events ───────────────────────
    orchestra_debug_dir = artifacts_dir / "orchestra-debug"
    orch_events = _parse_orchestra_logs(orchestra_debug_dir)
    orchestration_session_ids = _load_orchestration_session_ids(result, artifacts_dir)
    orch_events = _filter_orchestra_events_for_run(orch_events, orchestration_session_ids)

    timeouts: int = 0
    retries: int = 0
    scope_blockers: int = 0
    worker_exits_ok: bool = False
    worker_started_count: int = 0
    worker_exit_count: int = 0
    roles_from_logs: list[str] = []

    for event in orch_events:
        evt_type = str(event.get("event", ""))
        if evt_type == "worker.timeout":
            timeouts += 1
        elif evt_type == "retry.requested":
            retries += 1
        elif evt_type == "scope.blocked":
            scope_blockers += 1
        elif evt_type == "worker.started":
            worker_started_count += 1
            role = str(event.get("role", ""))
            if role and role not in roles_from_logs:
                roles_from_logs.append(role)
        elif evt_type == "worker.exited":
            worker_exit_count += 1
            exit_code = event.get("exit_code")
            if isinstance(exit_code, (int, float)) and exit_code == 0:
                worker_exits_ok = True
        elif evt_type == "run.created":
            role = str(event.get("role", ""))
            if role and role not in roles_from_logs:
                roles_from_logs.append(role)

    checks["timeouts"] = timeouts
    checks["retries"] = retries
    checks["scope_blockers"] = scope_blockers
    checks["worker_completed"] = worker_exits_ok or worker_success_returns > 0
    checks["worker_running_without_exit"] = worker_started_count > worker_exit_count and worker_success_returns == 0
    has_orchestra_log_evidence = bool(orch_events)

    task_meta = result.task_meta if isinstance(result.task_meta, dict) else {}
    family = str(task_meta.get("family", "") or "").lower()
    batch = str(task_meta.get("batch", "") or "").lower()
    capability_task = (
        family == "capability"
        or batch.startswith("capability-")
        or result.task_id.startswith("cap-")
    )
    checks["no_orchestration"] = capability_task and len(dispatches) == 0 and not roles_from_logs

    # ── 3. Target role dispatched check ─────────────────────
    target_role = str(result.run_meta.get("target_role", "") or "").lower().strip()
    all_dispatch_roles = set(r.lower() for r in roles_dispatched)
    all_log_roles = set(r.lower() for r in roles_from_logs)

    if target_role:
        checks["target_role_dispatched"] = (
            target_role in all_dispatch_roles or target_role in all_log_roles
        )
        # Missing expected role: no evidence of the target at all
        checks["missing_expected_role"] = not checks["target_role_dispatched"]
    else:
        checks["target_role_dispatched"] = len(dispatches) > 0 or len(roles_from_logs) > 0
        checks["missing_expected_role"] = False

    # ── 4. Premature completion / fallback detection ───────
    has_answer_check = "answer_exists" in result.checks
    has_answer = result.checks.get("answer_exists") is True
    checks["fallback_answer_after_dispatch"] = (
        bool(dispatches)
        and has_answer
        and not checks["worker_completed"]
        and has_orchestra_log_evidence
    )
    checks["premature_completion"] = bool(dispatches) and has_answer_check and not has_answer

    return checks


# ── Collect / summarize results ───────────────────────────────────────
def collect_results(
    results_dir: Path | str | None = None,
) -> list[TaskResult]:
    """Scan the results directory and load all result.json files."""
    base = Path(results_dir or _REPO_ROOT / RESULTS_DIR).resolve()
    if not base.is_dir():
        return []

    current_task_ids: set[str] | None = None
    if base == (_REPO_ROOT / RESULTS_DIR).resolve():
        current_task_ids = {meta.task_id for meta in list_tasks()}

    results: list[TaskResult] = []
    for entry in sorted(base.iterdir()):
        result_path = entry / "result.json"
        if result_path.is_file():
            try:
                result = TaskResult.from_json(result_path)
                if current_task_ids is not None and result.task_id not in current_task_ids:
                    continue
                results.append(result)
            except Exception as exc:
                print(f"[bench] warning: skip {result_path}: {exc}", file=sys.stderr)
    return results


def summarize_results(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Return a summary dict over all collected results."""
    results = collect_results(results_dir)
    total = len(results)
    passed = sum(1 for r in results if r.is_pass())
    failed = total - passed

    by_task: dict[str, list[TaskResult]] = {}
    for r in results:
        by_task.setdefault(r.task_id, []).append(r)

    task_summaries: list[dict] = []
    for tid, runs in sorted(by_task.items()):
        p = sum(1 for r in runs if r.is_pass())
        task_summaries.append({
            "task_id": tid,
            "runs": len(runs),
            "passed": p,
            "failed": len(runs) - p,
        })

    return {
        "total_runs": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed}/{total}" if total else "N/A",
        "tasks": task_summaries,
    }


def print_summary(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Print a summary table and return the summary dict."""
    summary = summarize_results(results_dir)

    print("\n=== orchestra-bench results ===")
    print(f"  total runs : {summary['total_runs']}")
    print(f"  passed     : {summary['passed']}")
    print(f"  failed     : {summary['failed']}")
    print(f"  pass rate  : {summary['pass_rate']}")

    if summary["tasks"]:
        print("\n  task breakdown:")
        for ts in summary["tasks"]:
            status = f"{ts['passed']}/{ts['runs']}"
            print(f"    {ts['task_id']:30s} {status}")

    return summary


def summarize_results_with_meta(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Return a summary that includes run metadata provenance.

    Groups runs by catalog/runtime provenance and reports pass/fail per group.
    The summary keeps the older by_model key as a compatibility alias, but the
    underlying grouping now distinguishes role/catalog/orchestra/config details
    whenever they are available in run_meta.
    """
    results = collect_results(results_dir)
    total = len(results)
    passed = sum(1 for r in results if r.is_pass())
    failed = total - passed

    by_provenance: dict[tuple[tuple[str, object], ...], list[TaskResult]] = {}
    provenance_by_key: dict[tuple[tuple[str, object], ...], dict[str, object]] = {}
    for r in results:
        provenance = _extract_run_provenance(r.run_meta)
        key = tuple(
            (name, _normalize_provenance_value(value))
            for name, value in sorted(provenance.items())
        )
        by_provenance.setdefault(key, []).append(r)
        provenance_by_key[key] = provenance

    provenance_summaries: list[dict] = []
    for key in sorted(by_provenance):
        runs = by_provenance[key]
        provenance = provenance_by_key[key]
        p = sum(1 for r in runs if r.is_pass())
        orchestra_on = sum(
            1 for r in runs if (r.run_meta or {}).get("orchestra") is True
        )
        orchestra_off = len(runs) - orchestra_on
        provenance_summaries.append({
            "group": _provenance_label(provenance),
            "provenance": provenance,
            "runs": len(runs),
            "passed": p,
            "failed": len(runs) - p,
            "orchestra_on": orchestra_on,
            "orchestra_off": orchestra_off,
        })

    return {
        "total_runs": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed}/{total}" if total else "N/A",
        "by_provenance": provenance_summaries,
        "by_model": provenance_summaries,
    }


# ── Repeated-trial aggregation ─────────────────────────────────────

def aggregate_repeated_trials(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Aggregate repeated trials grouped by task_id.

    For each task with multiple runs, compute:
      - run count (runs)
      - pass/fail counts and pass_rate (0.0–1.0)
      - elapsed time stats when available (mean, min, max)
      - token totals across all trials when available

    Returns a dict with 'tasks' list containing per-task aggregates.
    """
    import statistics as _stats  # noqa: PLC0415

    results = collect_results(results_dir)
    by_task: dict[str, list[TaskResult]] = {}
    for r in results:
        by_task.setdefault(r.task_id, []).append(r)

    task_aggregates: list[dict] = []
    for tid, runs in sorted(by_task.items()):
        passed = sum(1 for r in runs if r.is_pass())
        total_runs = len(runs)

        # Elapsed time stats (only from runs that have timing data)
        elapsed_vals: list[float] = [
            r.elapsed_seconds for r in runs if r.elapsed_seconds is not None
        ]

        # Token totals across trials
        token_totals: dict[str, int | float] = {}
        has_tokens = False
        for r in runs:
            for k, v in r.tokens.items():
                if isinstance(v, (int, float)):
                    token_totals[k] = token_totals.get(k, 0) + v
                    has_tokens = True

        entry: dict[str, object] = {
            "task_id": tid,
            "runs": total_runs,
            "passed": passed,
            "failed": total_runs - passed,
            "pass_rate": round(passed / total_runs, 4) if total_runs else 0.0,
        }

        # Timing stats
        if elapsed_vals:
            entry["elapsed_mean"] = round(_stats.mean(elapsed_vals), 2)
            entry["elapsed_min"] = round(min(elapsed_vals), 2)
            entry["elapsed_max"] = round(max(elapsed_vals), 2)
            if len(elapsed_vals) >= 2:
                entry["elapsed_stddev"] = round(
                    _stats.stdev(elapsed_vals), 2
                )
        else:
            entry["elapsed_mean"] = None

        # Token summary
        if has_tokens:
            entry["tokens_total"] = token_totals.get("total", 0)
            if "parent_tokens" in token_totals:
                entry["parent_tokens"] = int(token_totals["parent_tokens"])
            if "worker_tokens" in token_totals:
                entry["worker_tokens"] = int(token_totals["worker_tokens"])

        # Split label (use most common, or first non-empty)
        splits = [r.split for r in runs if r.split]
        if splits:
            entry["split"] = _most_common(splits)

        task_aggregates.append(entry)

    total_runs_all = len(results)
    passed_all = sum(1 for r in results if r.is_pass())

    return {
        "total_runs": total_runs_all,
        "passed": passed_all,
        "failed": total_runs_all - passed_all,
        "pass_rate": f"{passed_all}/{total_runs_all}" if total_runs_all else "N/A",
        "tasks": task_aggregates,
    }


def _print_aggregate(data: dict) -> None:
    """Print the repeated-trial aggregation table."""
    print("\n=== orchestra-bench aggregated results ===")
    print(f"  total runs : {data['total_runs']}")
    print(f"  passed     : {data['passed']}")
    print(f"  failed     : {data['failed']}")

    if data.get("tasks"):
        print(f"\n  {'task':<30s} {'runs':>5s} {'pass%':>7s} {'elapsed_mean':>12s} {'split':>10s}")
        print("  " + "-" * 70)

        for t in data["tasks"]:
            pass_pct = f"{t['pass_rate']*100:.0f}%"
            elapsed_str = f"{t.get('elapsed_mean', '') or '—':>10s}s"
            if isinstance(t.get("elapsed_mean"), (int, float)):
                elapsed_str = f"{t['elapsed_mean']:.1f}s"
            else:
                elapsed_str = "         —"
            split_val = t.get("split", "")

            print(f"  {t['task_id']:<30s} {t['runs']:>5d} {pass_pct:>7s} {elapsed_str:>12s} {split_val:>10s}")

            if t.get("tokens_total"):
                line = f"    tokens: total={int(t['tokens_total'])}"
                if "parent_tokens" in t or "worker_tokens" in t:
                    line += f" | parent={t.get('parent_tokens', 0)} worker={t.get('worker_tokens', 0)}"
                print(line)


def _most_common(items: list[str]) -> str:
    """Return the most common string in a list."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return max(counts, key=counts.get) if counts else ""


_PROVENANCE_FIELDS = (
    "role",
    "default_role",
    "model",
    "catalog_path",
    "catalog_sha256",
    "orchestra",
    "extra_skills",
    "role_models_summary",
    "role_models_sha256",
    "enabled_roles_summary",
    "aux_skill_names",
    "aux_skills_enabled",
    "aux_skills_summary",
    "aux_skills_sha256",
    "orchestra_config_sha256",
    "pi_package_names",
    "pi_packages_summary",
    "pi_packages_sha256",
    "pi_extensions",
    "pi_extensions_summary",
    "pi_extensions_sha256",
    "config_path",
    "config_sha256",
    "config_version",
    "image_id",
    "image_digest",
    "image_name",
    "container_id",
    "container_name",
    "runtime_id",
    "runtime_version",
    "pi_version",
    "orchestra_version",
)


def _normalize_provenance_value(value: object) -> object:
    """Return a stable, JSON-friendly value for grouping keys."""
    if isinstance(value, dict):
        return tuple(
            (str(k), _normalize_provenance_value(v))
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        normalized = [_normalize_provenance_value(v) for v in value]
        return tuple(sorted(normalized, key=repr))
    if isinstance(value, set):
        return tuple(sorted(_normalize_provenance_value(v) for v in value))
    return value


def _extract_run_provenance(run_meta: dict[str, object] | None) -> dict[str, object]:
    """Pull comparison-relevant provenance fields from run metadata."""
    meta = run_meta or {}
    provenance: dict[str, object] = {}
    for key in _PROVENANCE_FIELDS:
        value = meta.get(key)
        if value is not None and value != "":
            provenance[key] = value
    if not provenance:
        model = meta.get("model")
        if model not in (None, ""):
            provenance["model"] = model
        else:
            provenance["model"] = "unknown"
    return provenance


def _provenance_label(provenance: dict[str, object]) -> str:
    """Render a compact human-readable label for provenance groups."""
    parts: list[str] = []
    for key in (
        "role",
        "model",
        "orchestra",
        "role_models_summary",
        "pi_packages_summary",
        "pi_extensions_summary",
        "aux_skills_summary",
        "catalog_sha256",
        "catalog_path",
    ):
        if key not in provenance:
            continue
        value = provenance[key]
        if key == "orchestra":
            value = "on" if value else "off"
        parts.append(f"{key}={value}")

    handled = {
        "role",
        "model",
        "orchestra",
        "role_models_summary",
        "pi_packages_summary",
        "pi_extensions_summary",
        "aux_skills_summary",
        "catalog_sha256",
        "catalog_path",
    }
    for key in sorted(k for k in provenance if k not in handled):
        parts.append(f"{key}={provenance[key]}")

    return " | ".join(parts) if parts else "unknown"


# ── Dev vs holdout split reporting ─────────────────────────────

def summarize_results_with_splits(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Summarize results grouped by dev/holdout split.

    Tasks with split='dev' go into the development bucket;
    tasks with split='holdout' go into holdout; unlabeled tasks
    are placed in 'unlabeled'. Each bucket gets its own pass/fail summary.
    """
    results = collect_results(results_dir)

    buckets: dict[str, list[TaskResult]] = {
        "dev": [],
        "holdout": [],
        "unlabeled": [],
    }

    for r in results:
        split_val = getattr(r, "split", None) or ""
        if split_val == "holdout":
            buckets["holdout"].append(r)
        elif split_val == "dev":
            buckets["dev"].append(r)
        else:
            buckets["unlabeled"].append(r)

    def _bucket_summary(label: str, items: list[TaskResult]) -> dict:
        total = len(items)
        passed = sum(1 for r in items if r.is_pass())
        return {
            "label": label,
            "runs": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else None,
        }

    dev_summary = _bucket_summary("dev", buckets["dev"])
    holdout_summary = _bucket_summary("holdout", buckets["holdout"])
    unlabeled_summary = _bucket_summary("unlabeled", buckets["unlabeled"])

    total_runs = len(results)
    passed_all = sum(1 for r in results if r.is_pass())

    return {
        "total_runs": total_runs,
        "passed": passed_all,
        "failed": total_runs - passed_all,
        "pass_rate": f"{passed_all}/{total_runs}" if total_runs else "N/A",
        "splits": {
            "dev": dev_summary,
            "holdout": holdout_summary,
            "unlabeled": unlabeled_summary,
        },
    }


def print_split_summary(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Print a split-aware summary table and return the dict."""
    summary = summarize_results_with_splits(results_dir)

    print("\n=== orchestra-bench results (with splits) ===")
    print(f"  total runs : {summary['total_runs']}")
    print(f"  passed     : {summary['passed']}")
    print(f"  failed     : {summary['failed']}")

    for label in ("dev", "holdout"):
        bucket = summary["splits"][label]
        rate_str = f"{bucket['pass_rate']*100:.0f}%" if bucket["pass_rate"] is not None else "N/A"
        print(f"\n  [{label.upper()}] runs={bucket['runs']} passed={bucket['passed']}/{bucket['runs']} ({rate_str})")

    unlabeled = summary["splits"]["unlabeled"]
    if unlabeled["runs"] > 0:
        rate_str = f"{unlabeled['pass_rate']*100:.0f}%" if unlabeled["pass_rate"] is not None else "N/A"
        print(f"\n  [UNLABELED] runs={unlabeled['runs']} passed={unlabeled['passed']}/{unlabeled['runs']} ({rate_str})")

    return summary


# ── Run comparison support ────────────────────────────────────────

def compare_runs(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Compare runs grouped by catalog/runtime provenance.

    Groups all collected results by the provenance fields available in run_meta
    (role, model, catalog/config hashes, orchestra flag, and related runtime
    identifiers). For each group, computes pass rate and timing/token stats.
    Returns a comparison dict suitable for CLI output or further analysis.
    """
    import statistics as _stats  # noqa: PLC0415

    results = collect_results(results_dir)

    by_group: dict[tuple[tuple[str, object], ...], list[TaskResult]] = {}
    provenance_by_group: dict[tuple[tuple[str, object], ...], dict[str, object]] = {}
    for r in results:
        provenance = _extract_run_provenance(r.run_meta)
        group_key = tuple(
            (name, _normalize_provenance_value(value))
            for name, value in sorted(provenance.items())
        )
        by_group.setdefault(group_key, []).append(r)
        provenance_by_group[group_key] = provenance

    groups: list[dict] = []
    for group_key in sorted(by_group):
        runs = by_group[group_key]
        provenance = provenance_by_group[group_key]
        total = len(runs)
        passed = sum(1 for r in runs if r.is_pass())

        elapsed_vals = [
            r.elapsed_seconds for r in runs
            if getattr(r, "elapsed_seconds", None) is not None
        ]

        token_total = 0
        has_tokens = False
        parent_sum = 0
        worker_sum = 0
        for r in runs:
            t = r.tokens or {}
            if "total" in t and isinstance(t["total"], (int, float)):
                token_total += int(t["total"])
                has_tokens = True
            elif "total_tokens" in t and isinstance(t["total_tokens"], (int, float)):
                token_total += int(t["total_tokens"])
                has_tokens = True
            parent_sum += t.get("parent_tokens", 0) if isinstance(t.get("parent_tokens"), (int, float)) else 0
            worker_sum += t.get("worker_tokens", 0) if isinstance(t.get("worker_tokens"), (int, float)) else 0

        entry: dict[str, object] = {
            "group": _provenance_label(provenance),
            "provenance": provenance,
            "runs": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
        }

        if elapsed_vals:
            entry["elapsed_mean"] = round(_stats.mean(elapsed_vals), 2)
        else:
            entry["elapsed_mean"] = None

        if has_tokens:
            entry["tokens_total"] = token_total
            if parent_sum > 0 or worker_sum > 0:
                entry["parent_tokens"] = int(parent_sum)
                entry["worker_tokens"] = int(worker_sum)

        # Split breakdown within this group
        splits: dict[str, int] = {}
        for r in runs:
            s = getattr(r, "split", None) or "unlabeled"
            if s not in ("dev", "holdout"):
                s = "unlabeled"
            splits[s] = splits.get(s, 0) + 1
        entry["splits"] = {k: v for k, v in sorted(splits.items())}

        groups.append(entry)

    return {
        "total_runs": len(results),
        "groups": groups,
    }


def print_comparison(
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Print a comparison table across model/config groups."""
    comparison = compare_runs(results_dir)

    print("\n=== orchestra-bench run comparison ===")
    print(f"  total runs : {comparison['total_runs']}")

    if not comparison["groups"]:
        print("  (no results to compare)")
        return comparison

    # Print header
    print(f"\n  {'group':<30s} {'runs':>5s} {'pass%':>7s} {'elapsed_mean':>12s}")
    print("  " + "-" * 60)

    for g in comparison["groups"]:
        group_name = str(g["group"])
        pass_pct = f"{g['pass_rate']*100:.0f}%" if g.get('pass_rate') else "N/A"
        elapsed_str = f"{g['elapsed_mean']:.1f}s" if g.get('elapsed_mean') is not None else "—"

        splits_info = ", ".join(
            f"{k}={v}" for k, v in sorted(g.get("splits", {}).items())
        )

        print(f"  {group_name:<30s} {g['runs']:>5d} {pass_pct:>7s} {elapsed_str:>12s}")
        if splits_info:
            print(f"    splits: {splits_info}")

        if g.get("tokens_total"):
            print(f"    tokens: total={g['tokens_total']}", end="")
            if "parent_tokens" in g or "worker_tokens" in g:
                parent_val = g.get("parent_tokens", 0)
                worker_val = g.get("worker_tokens", 0)
                print(f" | parent={parent_val} worker={worker_val}", end="")
            print()

    return comparison


# ── Historical efficiency helpers ─────────────────────────────────
def _get_total_tokens(tokens: dict[str, object] | None) -> int | None:
    """Extract total token count from a tokens dict.

    Prefers 'total', falls back to 'total_tokens'. Returns None if absent.
    """
    if not tokens or not isinstance(tokens, dict):
        return None
    for key in ("total", "total_tokens"):
        val = tokens.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    return None


def _classify_position(current: float, mn: float, median: float, mx: float) -> str:
    """Classify where *current* sits relative to min/median/max history.

    Returns one of: new-low, low, normal, high, new-high.
    When all values are equal, exact matches are normal and outliers are new.
    """
    if current < mn:
        return "new-low"
    if current > mx:
        return "new-high"

    if mn == mx:
        return "normal"

    # Within [min, max]: classify by which side of median and how far
    lower_mid = (mn + median) / 2
    upper_mid = (median + mx) / 2

    if current <= lower_mid:
        return "low"
    if current >= upper_mid:
        return "high"
    return "normal"


def compare_efficiency(
    result: TaskResult,
    results_dir: Path | str | None = None,
) -> dict[str, object]:
    """Compare a run against prior comparable results for the same task.

    Returns an efficiency comparison dict with token and elapsed stats:

    .. code-block:: python

        {
            "tokens": { "min": 800, "median": 1200, "max": 2000,
                        "current": 950, "position": "low", "count": 3 },
            "elapsed": { "min": 25.0, "median": 40.0, "max": 80.0,
                         "current": 35.0, "position": "normal", "count": 3 },
            # Optional — present only when ≥ 2 pass-only prior runs exist
            "pass_only": { ...same shape... },
        }

    When no prior comparable runs exist for a metric, that metric returns
    ``position: "insufficient-history"`` with empty stats.

    The current run is excluded from history statistics (min/median/max).
    Missing token or elapsed data in either the current run or historical runs
    are handled gracefully — only runs with valid values contribute to each stat.
    """
    base = Path(results_dir or (_REPO_ROOT / RESULTS_DIR)).resolve()
    task_id = result.task_id
    run_id = result.run_id

    # Gather all results for this task (including current)
    all_results: list[TaskResult] = []
    if base.is_dir():
        for entry in sorted(base.iterdir()):
            result_path = entry / "result.json"
            if not result_path.is_file():
                continue
            try:
                r = TaskResult.from_json(result_path)
                if r.task_id == task_id:
                    all_results.append(r)
            except Exception:
                pass

    # Prior runs = everything except the current run
    prior: list[TaskResult] = [
        r for r in all_results if not (r.run_id == run_id and r.task_id == task_id)
    ]

    # Token values from history — only runs with real token totals (like pass-only)
    hist_tokens: list[int] = []
    for r in prior:
        val = _get_total_tokens(r.tokens) if isinstance(r.tokens, dict) else None
        if val is not None:
            hist_tokens.append(val)

    # Elapsed values from history (None kept as-is → excluded from stats but counted)
    hist_elapsed: list[float] = [
        r.elapsed_seconds for r in prior
        if getattr(r, "elapsed_seconds", None) is not None
    ]

    # Current values
    cur_token = _get_total_tokens(result.tokens) if isinstance(result.tokens, dict) else 0
    cur_elapsed: float | None = (
        result.elapsed_seconds if getattr(result, "elapsed_seconds", None) is not None else None
    )

    def _token_block(values: list[int], current: int | None) -> dict[str, object]:
        if len(values) < 1:
            return {
                "min": None,
                "median": None,
                "max": None,
                "current": current,
                "position": "insufficient-history",
                "count": len(values),
            }
        mn = min(values)
        mx = max(values)
        med = _stats.median(values)
        pos = _classify_position(float(current or 0), float(mn), float(med), float(mx)) if current is not None else "insufficient-history"
        return {
            "min": mn,
            "median": int(med) if isinstance(med, (int, float)) else med,
            "max": mx,
            "current": current,
            "position": pos,
            "count": len(values),
        }

    def _elapsed_block(values: list[float], current: float | None) -> dict[str, object]:
        if len(values) < 1:
            return {
                "min": None,
                "median": None,
                "max": None,
                "current": round(current, 2) if current is not None else None,
                "position": "insufficient-history",
                "count": len(values),
            }
        mn = min(values)
        mx = max(values)
        med = _stats.median(values)
        pos = _classify_position(current or 0.0, float(mn), float(med), float(mx)) if current is not None else "insufficient-history"
        return {
            "min": round(mn, 2),
            "median": round(med, 2),
            "max": round(mx, 2),
            "current": round(current, 2) if current is not None else None,
            "position": pos,
            "count": len(values),
        }

    out: dict[str, object] = {
        "tokens": _token_block(hist_tokens, cur_token),
        "elapsed": _elapsed_block(hist_elapsed, cur_elapsed),
    }

    # Pass-only history (when ≥ 1 prior pass run exists)
    pass_prior = [r for r in prior if r.is_pass()]
    pass_tokens: list[int] = []
    for r in pass_prior:
        val = _get_total_tokens(r.tokens) if isinstance(r.tokens, dict) else None
        if val is not None:
            pass_tokens.append(val)
    pass_elapsed: list[float] = [
        r.elapsed_seconds for r in pass_prior
        if getattr(r, "elapsed_seconds", None) is not None
    ]

    if len(pass_tokens) >= 1 or len(pass_elapsed) >= 1:
        out["pass_only"] = {
            "tokens": _token_block(pass_tokens, cur_token),
            "elapsed": _elapsed_block(pass_elapsed, cur_elapsed),
        }

    return out


def _efficiency_block_for_penalties(efficiency: dict[str, object] | None, metric: str) -> dict[str, object] | None:
    """Pick the strongest available history block for process penalties."""
    if not isinstance(efficiency, dict):
        return None
    pass_only = efficiency.get("pass_only")
    if isinstance(pass_only, dict) and isinstance(pass_only.get(metric), dict):
        return pass_only.get(metric)
    block = efficiency.get(metric)
    return block if isinstance(block, dict) else None


def _collect_process_penalties(result: TaskResult) -> list[tuple[str, float, str]]:
    """Collect process penalties for orchestration/efficiency signals."""
    penalties: list[tuple[str, float, str]] = []
    orchestration_checks = result.orchestration_checks or {}
    orchestra_enabled = (result.run_meta or {}).get("orchestra") is not False

    if orchestration_checks.get("missing_expected_role") is True:
        penalties.append(("missing_expected_role", 0.10, "missing expected role"))
    if orchestration_checks.get("premature_completion") is True:
        penalties.append(("premature_completion", 0.10, "premature completion"))
    if orchestration_checks.get("fallback_answer_after_dispatch") is True:
        penalties.append(("fallback_answer_after_dispatch", 0.08, "fallback answer after dispatch"))
    if orchestration_checks.get("worker_running_without_exit") is True:
        penalties.append(("worker_running_without_exit", 0.08, "worker still running / no exit"))
    if orchestra_enabled and orchestration_checks.get("no_orchestration") is True:
        penalties.append(("no_orchestration", 0.10, "no orchestration"))

    for key, weight, label in (
        ("timeouts", 0.04, "timeout"),
        ("retries", 0.03, "retry"),
    ):
        value = orchestration_checks.get(key)
        if isinstance(value, (int, float)) and value > 0:
            count = int(value)
            penalties.append((key, min(weight * count, weight * 3), f"{count} {label}{'' if count == 1 else 's'}"))

    for metric in ("tokens", "elapsed"):
        block = _efficiency_block_for_penalties(result.efficiency, metric)
        if not isinstance(block, dict):
            continue
        position = str(block.get("position") or "")
        if position == "high":
            penalties.append((f"{metric}_high", 0.03, f"high {metric}"))
        elif position == "new-high":
            penalties.append((f"{metric}_new_high", 0.05, f"very high {metric}"))

    return penalties


def _position_score(position: str) -> float | None:
    mapping = {
        "new-low": 1.0,
        "low": 0.75,
        "normal": 0.5,
        "high": 0.25,
        "new-high": 0.0,
    }
    return mapping.get(position)


def _positive_rubric_ratio(rubric: dict[str, object] | None) -> float | None:
    if not isinstance(rubric, dict) or not rubric:
        return None
    total_score = 0.0
    total_max = 0.0
    for name, value in rubric.items():
        if name == "process_penalties" or not isinstance(value, dict):
            continue
        score = value.get("score")
        max_score = value.get("max")
        if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
            total_score += float(score)
            total_max += float(max_score)
    if total_max <= 0:
        return None
    return max(0.0, min(1.0, total_score / total_max))


def compute_category_scores(result: TaskResult) -> dict[str, object]:
    """Build category score views over the same run evidence."""
    intelligence = _positive_rubric_ratio(result.rubric)
    if intelligence is None and result.score_numeric is not None:
        intelligence = max(0.0, min(1.0, float(result.score_numeric)))

    speed = None
    elapsed_block = _efficiency_block_for_penalties(result.efficiency, "elapsed")
    if isinstance(elapsed_block, dict):
        speed = _position_score(str(elapsed_block.get("position") or ""))

    efficiency = None
    token_block = _efficiency_block_for_penalties(result.efficiency, "tokens")
    if isinstance(token_block, dict):
        efficiency = _position_score(str(token_block.get("position") or ""))

    process = None
    if (result.run_meta or {}).get("orchestra") is not False:
        penalties = _collect_process_penalties(result)
        process_penalty_total = min(sum(weight for name, weight, _ in penalties if not name.startswith("tokens_") and not name.startswith("elapsed_")), 0.25)
        process = max(0.0, min(1.0, 1.0 - (process_penalty_total / 0.25)))

    def _norm(value: float | None) -> float | None:
        return round(value, 6) if isinstance(value, (int, float)) else None

    return {
        "intelligence": _norm(intelligence),
        "speed": _norm(speed),
        "efficiency": _norm(efficiency),
        "process": _norm(process),
    }


def apply_process_penalties(result: TaskResult) -> TaskResult:
    """Apply soft process penalties to score_numeric/rubric without changing pass/fail."""
    if result.score_numeric is None:
        return result
    if (result.orchestration_checks or {}).get("process_penalty_applied") is True:
        return result

    penalties = _collect_process_penalties(result)
    total_penalty = round(min(sum(weight for _, weight, _ in penalties), 0.25), 4)
    result.orchestration_checks["process_penalty_applied"] = True
    result.orchestration_checks["process_penalty_total"] = total_penalty
    result.orchestration_checks["process_penalty_reasons"] = [label for _, _, label in penalties]

    if total_penalty <= 0:
        return result

    result.score_numeric = round(max(0.0, min(1.0, result.score_numeric - total_penalty)), 4)
    result.rubric = dict(result.rubric or {})
    result.rubric["process_penalties"] = {
        "score": -total_penalty,
        "max": 0.0,
        "checks": {name: False for name, _, _ in penalties},
        "details": [label for _, _, label in penalties],
    }
    return result


def format_rubric_summary(rubric: dict[str, object] | None) -> str:
    """Return a concise one-line rubric summary for reporting."""
    if not isinstance(rubric, dict) or not rubric:
        return "no rubric score"

    parts: list[str] = []
    for name, value in rubric.items():
        if not isinstance(value, dict):
            continue
        score = value.get("score")
        max_score = value.get("max")
        if isinstance(score, (int, float)) and isinstance(max_score, (int, float)):
            parts.append(f"{name}={score:.4f}/{max_score:.4f}")
    return "; ".join(parts) if parts else "no rubric score"


def orchestration_warnings(orchestration_checks: dict[str, object] | None) -> list[str]:
    """Return human-readable orchestration warnings for notable issues."""
    if not isinstance(orchestration_checks, dict) or not orchestration_checks:
        return []

    warnings: list[str] = []
    if orchestration_checks.get("missing_expected_role") is True:
        warnings.append("missing expected role")
    if orchestration_checks.get("premature_completion") is True:
        warnings.append("premature completion")
    if orchestration_checks.get("fallback_answer_after_dispatch") is True:
        warnings.append("fallback answer after dispatch")
    if orchestration_checks.get("worker_running_without_exit") is True:
        warnings.append("worker still running / no exit")
    if orchestration_checks.get("no_orchestration") is True:
        warnings.append("no orchestration")

    for key, singular, plural in (
        ("timeouts", "timeout", "timeouts"),
        ("retries", "retry", "retries"),
        ("scope_blockers", "scope blocker", "scope blockers"),
        ("same_slice_redispatches", "same-slice redispatch", "same-slice redispatches"),
        ("compaction_count", "compaction", "compactions"),
    ):
        value = orchestration_checks.get(key)
        if isinstance(value, (int, float)) and value > 0:
            count = int(value)
            label = singular if count == 1 else plural
            warnings.append(f"{count} {label}")

    return warnings


def format_efficiency_summary(
    result: TaskResult,
    results_dir: Path | str | None = None,
) -> list[str]:
    """Return concise token/elapsed efficiency summary lines."""
    efficiency = result.efficiency if isinstance(result.efficiency, dict) and result.efficiency else compare_efficiency(result, results_dir)
    if not isinstance(efficiency, dict):
        return []

    lines: list[str] = []
    for metric in ("tokens", "elapsed"):
        block = efficiency.get(metric)
        if not isinstance(block, dict):
            continue
        if block.get("position") == "insufficient-history":
            continue
        lines.append(
            f"{metric} {block.get('position')} "
            f"(current={block.get('current')}, min={block.get('min')}, median={block.get('median')}, max={block.get('max')}, n={block.get('count')})"
        )
    return lines


# ── CLI entry (when run directly) ────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """Simple CLI wrapper for the harness."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="orchestra-bench",
        description="Lightweight benchmark harness for Orchestra.",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="List available tasks")
    p_list.add_argument("--tasks-dir", default=None)

    # run-task (full flow)
    p_run = sub.add_parser("run-task", help="Prepare, run, grade a task")
    p_run.add_argument("task_id")
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--cmd", "-c", nargs="+", dest="run_cmd",
                       default=None, help="Command(s) to exec in workdir after setup")

    # eval-task (grade only — run already happened externally)
    p_eval = sub.add_parser("eval-task", help="Grade a task that was already executed")
    p_eval.add_argument("task_id")
    p_eval.add_argument("--run-id", default=None, required=True,
                        help="Run id of the completed execution (required for eval)")

    p_collect = sub.add_parser("collect-results", help="Collect and summarize results")
    p_collect.add_argument("--results-dir", default=None)
    p_collect.add_argument("--splits", action="store_true",
                           help="Show dev/holdout split breakdown in summary")

    # compare (run comparison across model/config groups)
    p_compare = sub.add_parser("compare", help="Compare runs grouped by model/config")
    p_compare.add_argument("--results-dir", default=None)
    p_compare.add_argument("--aggregate", action="store_true",
                           help="Show repeated-trial aggregation per task")

    args = parser.parse_args(argv)

    if args.command == "list":
        tasks = list_tasks(args.tasks_dir)
        if not tasks:
            print("[bench] no tasks found (need task.yaml in each task dir)")
            return 1
        for meta in tasks:
            tags: list[str] = []
            for t in (meta.batch, meta.family if meta.family != "default" else ""):
                if t and t not in tags:
                    tags.append(t)
            tag = f"({'/'.join(tags)})" if tags else ""
            print(f"  {meta.task_id:30s} {tag} — {meta.description}")
        return 0

    if args.command == "run-task":
        try:
            result = run_full(
                task_id=args.task_id,
                command=args.run_cmd,
                run_id=args.run_id,
            )
            return 0 if result.is_pass() else 1
        except RuntimeError as exc:
            print(f"[bench] error: {exc}", file=sys.stderr)
            return 2

    if args.command == "eval-task":
        try:
            meta = load_task(args.task_id)
            result = grade(args.task_id, args.run_id, task_meta=meta)
            dest = result.write_json()
            print(report(result))
            print(f"  → {dest}")
            return 0 if result.is_pass() else 1
        except RuntimeError as exc:
            print(f"[bench] error: {exc}", file=sys.stderr)
            return 2

    if args.command == "collect-results":
        if getattr(args, 'splits', False):
            print_split_summary(args.results_dir)
        else:
            print_summary(args.results_dir)
        return 0

    if args.command == "compare":
        if getattr(args, 'aggregate', False):
            agg = aggregate_repeated_trials(args.results_dir)
            _print_aggregate(agg)
        else:
            print_comparison(args.results_dir)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
