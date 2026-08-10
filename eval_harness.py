"""eval_harness — prepare / run / grade / report for orchestra-bench tasks."""

from __future__ import annotations

import json as _json
import shlex
import shutil
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


def build_run_metadata(
    task_id: str,
    run_id: str,
    catalog_path: Path | str,
    role: str | None = None,
    orchestra: bool | None = None,
    extra_skills: Sequence[str] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
) -> dict[str, object]:
    """Build the run metadata snapshot persisted to .bench_run.json."""
    meta = {
        "run_id": run_id,
        "task_id": task_id,
        **resolve_catalog_model(catalog_path, role=role),
        "orchestra": orchestra,
        "extra_skills": list(extra_skills or []),
        "notes": notes,
    }
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


def _parse_pi_session_file(path: Path) -> dict[str, object]:
    """Extract session id and token totals from one Pi JSONL session file."""
    out: dict[str, object] = {"file": path.name}
    totals = {"input": 0, "output": 0, "reasoning": 0, "totalTokens": 0}
    try:
        for line in path.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            event = _json.loads(line)
            if event.get("type") == "session" and event.get("id"):
                out["session_id"] = event.get("id")
                out["cwd"] = event.get("cwd", "")
            msg = event.get("message") if isinstance(event, dict) else None
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if isinstance(usage, dict):
                for key in totals:
                    value = usage.get(key)
                    if isinstance(value, (int, float)):
                        totals[key] += int(value)
    except Exception as exc:
        out["parse_error"] = str(exc)
    out["usage"] = totals
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
        if has_db and _copy_from_container("/root/.pi/agent/orchestra/state/orchestra.db", orch_dir / "state" / "orchestra.db"):
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
    # Proper Orchestra trace capture uses `orchestra debug`. It may legitimately
    # report zero runs when the user did not use Orchestra.
    debug_files: list[str] = []
    if _docker_ok():
        debug_dir = orch_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        for session_id in session_ids:
            safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in session_id)
            debug_proc = _docker_exec(
                "sh", "-c",
                f"orchestra debug --session-id {shlex.quote(session_id)}",
            )
            debug_text = (debug_proc.stdout or "") + (debug_proc.stderr or "")
            debug_path = debug_dir / f"session-{safe_name}.md"
            debug_path.write_text(debug_text)
            debug_files.append(f"orchestra-debug/debug/{debug_path.name}")
        if not session_ids:
            debug_proc = _docker_exec(
                "sh", "-c",
                f"orchestra debug --run-id {shlex.quote(run_id)}",
            )
            debug_text = (debug_proc.stdout or "") + (debug_proc.stderr or "")
            debug_path = debug_dir / f"run-{run_id}.md"
            debug_path.write_text(debug_text)
            debug_files.append(f"orchestra-debug/debug/{debug_path.name}")
    if debug_files:
        manifest["orchestra"]["debug"] = debug_files  # type: ignore[index]

    token_payload = {
        "input_tokens": totals["input"],
        "output_tokens": totals["output"],
        "reasoning_tokens": totals["reasoning"],
        "total_tokens": totals["totalTokens"],
    }
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

    bench_env: dict[str, str] = {
        "BENCH_RUN_ID": run_id,
        "BENCH_TASK_ID": task_id,
    }

    evaluator_host = _REPO_ROOT / TASKS_DIR / task_id / evaluator_script
    if not evaluator_host.is_file():
        raise FileNotFoundError(f"evaluator not found: {evaluator_host}")

    eval_tmp = f"/tmp/bench-eval-{run_id}-{task_id}"
    _docker_exec("rm", "-rf", eval_tmp, env=bench_env)
    _docker_exec("mkdir", "-p", f"{eval_tmp}/evaluate", env=bench_env)
    cp_proc = sp.run(
        ["docker", "cp", str(evaluator_host), f"{CONTAINER_NAME}:{eval_tmp}/evaluate/run.sh"],
        capture_output=True,
        text=True,
    )
    if cp_proc.returncode != 0:
        raise RuntimeError(cp_proc.stderr.strip() or cp_proc.stdout.strip() or "docker cp evaluator failed")

    # Remove stale result.json before evaluator runs. If the evaluator prints
    # JSON instead of writing a file, fallback parsing must use this run's
    # stdout rather than a previous result file.
    pre_result_dir = Path(RESULTS_DIR).resolve() / f"{run_id}-{task_id}"
    pre_result_path = pre_result_dir / "result.json"
    if pre_result_path.exists():
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
    result_dir = Path(RESULTS_DIR).resolve() / f"{run_id}-{task_id}"
    if not (result_dir.is_absolute()):
        result_dir = _REPO_ROOT / RESULTS_DIR / f"{run_id}-{task_id}"

    result_path = result_dir / "result.json"
    task_result: TaskResult
    if result_path.exists():
        task_result = TaskResult.from_json(result_path)
    else:
        # Fallback — construct from evaluator output. Evaluators commonly print
        # JSON to stdout instead of writing result.json directly.
        stdout = result_proc.stdout.strip()
        parsed: dict[str, object] = {}
        try:
            maybe = _json.loads(stdout) if stdout else {}
            if isinstance(maybe, dict):
                parsed = maybe
        except Exception:
            parsed = {}

        score = str(parsed.get("score") or ("pass" if result_proc.returncode == 0 else "fail"))
        checks = parsed.get("checks") if isinstance(parsed.get("checks"), dict) else {}
        details = parsed.get("details") if isinstance(parsed.get("details"), str) else stdout[-500:]
        task_result = TaskResult(
            task_id=task_id,
            run_id=run_id,
            score=score,
            checks=checks,
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

    if task_result.elapsed_seconds is None:
        started_epoch = task_result.run_meta.get("started_epoch") if isinstance(task_result.run_meta, dict) else None
        if isinstance(started_epoch, (int, float)) and started_epoch > 0:
            task_result.elapsed_seconds = max(0.0, time.time() - float(started_epoch))

    # Best-effort artifact capture: Pi sessions, token totals, Orchestra traces.
    # Missing artifacts are expected when Orchestra was not used.
    collect_run_artifacts(task_id, run_id)
    ingest_artifacts(task_result)

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
    base = Path(base_dir or RESULTS_DIR).resolve()
    run_dir = base / f"{result.run_id}-{result.task_id}"
    if not run_dir.is_dir():
        return result

    artifacts_dir = run_dir / "artifacts"
    token_file = artifacts_dir / "tokens.json"
    if token_file.is_file():
        try:
            data = _json.loads(token_file.read_text())
            tokens: dict[str, object] = {}
            for key in _ARTIFACT_TOKEN_KEYS:
                if key in data and isinstance(data[key], (int, float)):
                    tokens[key] = data[key]

            # Also map to a simple 'total' if not already present
            if "total" not in tokens and "total_tokens" in tokens:
                tokens["total"] = int(tokens["total_tokens"])

            result.tokens = {**result.tokens, **tokens}
        except Exception as exc:
            print(f"[bench] warning: failed to parse tokens from {token_file}: {exc}",
                  file=sys.stderr)

    sessions_file = artifacts_dir / "pi-sessions.json"
    if sessions_file.is_file():
        try:
            data = _json.loads(sessions_file.read_text())
            session_ids = data.get("session_ids") if isinstance(data, dict) else None
            if isinstance(session_ids, list):
                result.run_meta["pi_session_ids"] = [str(s) for s in session_ids]
        except Exception as exc:
            print(f"[bench] warning: failed to parse Pi sessions from {sessions_file}: {exc}",
                  file=sys.stderr)

    manifest_file = artifacts_dir / "manifest.json"
    if manifest_file.is_file():
        try:
            data = _json.loads(manifest_file.read_text())
            if isinstance(data, dict) and isinstance(data.get("orchestra"), dict):
                result.run_meta["orchestra_artifacts"] = data["orchestra"]
        except Exception as exc:
            print(f"[bench] warning: failed to parse artifact manifest from {manifest_file}: {exc}",
                  file=sys.stderr)

    # Timing artifact (elapsed_seconds) — ingested if present and not already set
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
    base = Path(base_dir or RESULTS_DIR).resolve()
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
    for key in ("role", "model", "orchestra", "catalog_sha256", "catalog_path"):
        if key not in provenance:
            continue
        value = provenance[key]
        if key == "orchestra":
            value = "on" if value else "off"
        parts.append(f"{key}={value}")

    for key in sorted(k for k in provenance if k not in {"role", "model", "orchestra", "catalog_sha256", "catalog_path"}):
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
