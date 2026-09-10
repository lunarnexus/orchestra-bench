"""Thin benchmark CLI entrypoint and wrappers."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import load_catalog, resolve_harness_for_role
from .harnesses.base import HarnessArtifactPaths
from .harnesses.command import CommandHarness
from .harnesses.pi_rpc import PiRpcHarness
from .paths import RepoPaths
from .reporting import (
    build_debug_report,
    compare_results,
    delete_all_result_dirs,
    describe_filters,
    delete_results,
    filter_results as filter_report_entries,
    format_compare_results,
    format_dashboard,
    format_debug_report,
    format_delete_preview,
    format_rescore_report,
    format_run_detail,
    format_runs,
    format_session_debug,
    format_session_raw,
    format_timing,
    format_tokens,
    rescore_results,
    select_results,
)
from .reporting.debug import format_child_session_section
from .reporting.formatters import format_comparison_results
from .reporting.queries import compare_selected_results, parse_since_filter
from .artifacts import EvaluatorArtifactPaths
from .result import HarnessResult, TaskResult, load_result, write_json_atomic
from .runner import grade_run, prepare_run, run_and_grade
from .runtime import (
    _now_run_id,
    container_exec,
    doctor as runtime_doctor,
    load_runtime_config_summary,
    prepare_startup,
)
from .tasks import TaskLoadError, list_suites, list_tasks, load_task
from .workspace import workspace_dir


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _print_json(payload: Any) -> None:
    sys.stdout.write(_json_dump(payload))


def _bench_log(message: str, *, flush: bool = False) -> None:
    print(f"[{datetime.now().strftime('%H:%M')}] {message}", flush=flush)


def _parse_json_summary_from_stdout(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            summary, end = decoder.raw_decode(stdout, index)
        except ValueError:
            continue
        if stdout[end:].strip():
            continue
        if not isinstance(summary, dict):
            raise RuntimeError("in-container runtime config summary must be an object")
        return {str(key): value for key, value in summary.items()}
    raise RuntimeError("in-container runtime config sync did not return a JSON summary")


def _runtime_env_from_summary(summary: dict[str, Any] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if not summary:
        return env
    home_dir = summary.get("home_dir")
    if not isinstance(home_dir, str) or not home_dir:
        pi_runtime_dir = summary.get("pi_runtime_dir")
        if isinstance(pi_runtime_dir, str) and pi_runtime_dir:
            home_dir = str(Path(pi_runtime_dir).parent.parent)
    if isinstance(home_dir, str) and home_dir:
        env["HOME"] = home_dir
    for summary_key, env_name in (
        ("pi_runtime_dir", "PI_CODING_AGENT_DIR"),
        ("orchestra_runtime_dir", "PI_ORCHESTRA_RUNTIME_DIR"),
    ):
        value = summary.get(summary_key)
        if isinstance(value, str) and value:
            env[env_name] = value
    return env


def _run_ref_parts(run_ref: str) -> tuple[str, str]:
    name = Path(run_ref).name
    if name.endswith(".json"):
        name = Path(name).stem
    if "-" not in name:
        raise ValueError(f"run reference must look like RUN_ID-TASK_ID: {run_ref!r}")
    run_id, task_id = name.split("-", 1)
    return run_id, task_id


def _resolve_run_paths(root: Path | str | None, run_ref: str):
    run_id, task_id = _run_ref_parts(run_ref)
    return RepoPaths(Path.cwd() if root is None else root).run(run_id, task_id)


def _load_result_or_none(path: Path) -> object | None:
    if not path.is_file():
        return None
    return load_result(path)


def _task_payload(task) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "task_id": task.task_id,
        "description": task.description,
        "family": task.family,
        "batch": task.batch,
        "scoring_type": task.scoring_type,
        "timeout_minutes": task.timeout_minutes,
        "evaluator": task.evaluator,
        "split": task.split,
        "task_dir": str(task.task_dir),
        "task_yaml_path": str(task.task_yaml_path),
        "prd_path": str(task.prd_path),
        "prompt_path": str(task.prompt_path),
        "fixture_path": str(task.fixture_path) if task.fixture_path is not None else None,
        "kb_dir_path": str(task.kb_dir_path) if task.kb_dir_path is not None else None,
        "kb_md_path": str(task.kb_md_path) if task.kb_md_path is not None else None,
        "evaluate_path": str(task.evaluate_path),
    }


def _task_display_line(task) -> str:  # type: ignore[no-untyped-def]
    description = task.description or ""
    batch = task.batch or "unbatched"
    label = batch
    if task.family and task.family not in {batch, "default"}:
        label = f"{batch}/{task.family}"
    return f"{task.task_id:<36} ({label}) {description}".rstrip()


def _task_summary_line(task) -> str:  # type: ignore[no-untyped-def]
    return _task_display_line(task)


def _task_display_lines(task, *, width: int = 88) -> list[str]:  # type: ignore[no-untyped-def]
    batch = task.batch or "unbatched"
    label = batch
    if task.family and task.family not in {batch, "default"}:
        label = f"{batch}/{task.family}"
    first = f"  {task.task_id:<34} ({label})"
    description = (task.description or "").strip()
    if not description:
        return [first.rstrip()]
    wrapped = textwrap.wrap(description, width=max(32, width - 6))
    return [first.rstrip(), *(f"      {line}" for line in wrapped)]


def _result_summary_line(run_paths) -> str:  # type: ignore[no-untyped-def]
    result = _load_result_or_none(run_paths.result_json)
    if result is None:
        return f"{run_paths.run_id}\t{run_paths.task_id}\tpending"
    return f"{run_paths.run_id}\t{run_paths.task_id}\t{result.outcome}\t{result.evaluation.status}"


def _compact_result_payload(result: TaskResult) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    payload: dict[str, Any] = {
        "run_id": result.run_id,
        "task_id": result.task_id,
        "batch": result.batch,
        "outcome": result.outcome,
        "evaluation": {
            "status": result.evaluation.status,
            "score": result.evaluation.score,
        },
    }
    result_json = details.get("result_json")
    if isinstance(result_json, str) and result_json:
        payload["result_json"] = result_json
    artifacts = details.get("artifacts")
    if isinstance(artifacts, dict) and artifacts:
        payload["artifacts"] = artifacts
    return payload


def _auto_score_display(result: TaskResult) -> str:
    if result.score_display:
        return result.score_display
    if result.score_numeric is not None:
        return f"{round(float(result.score_numeric)):.0f}/100"
    try:
        entries = select_results(task=result.task_id, limit=None)
    except Exception:
        entries = []
    for entry in entries:
        if entry.run_id == result.run_id and entry.task_id == result.task_id and entry.score_display:
            return entry.score_display
    return "n/a"


def _print_auto_result(result: TaskResult) -> None:
    details = result.details if isinstance(result.details, dict) else {}
    score = _auto_score_display(result)
    _bench_log(f"auto result: {result.task_id} -> {result.outcome} (score={score}, evaluator={result.evaluation.status})", flush=True)
    if result.harness.status != "ok" and result.harness.error:
        _bench_log(f"reason: {result.harness.error}", flush=True)
    provenance = details.get("provenance")
    if isinstance(provenance, dict):
        auto_gate = provenance.get("auto_gate")
        if isinstance(auto_gate, dict) and not auto_gate.get("safe_to_grade", True):
            reason = auto_gate.get("reason") or "blocked"
            _bench_log(f"blocked: auto gate {reason}", flush=True)
    result_json = details.get("result_json")
    if isinstance(result_json, str) and result_json:
        _bench_log(f"result: {result_json}", flush=True)
    artifacts = details.get("artifacts")
    if isinstance(artifacts, dict):
        harness = artifacts.get("harness")
        if isinstance(harness, dict):
            root = harness.get("root")
            if isinstance(root, str) and root:
                _bench_log(f"artifacts: {root}", flush=True)


def _suite_summary_payload(suite_name: str, results: list[TaskResult]) -> dict[str, Any]:
    failed = sum(1 for result in results if result.outcome != "pass")
    payload = {
        "suite": suite_name,
        "policy": "continue",
        "task_count": len(results),
        "passed": len(results) - failed,
        "failed": failed,
        "return_code": 1 if failed else 0,
        "results": [_compact_result_payload(result) for result in results],
    }
    return payload


def _resolve_auto_target(args: argparse.Namespace):
    target = str(args.task_id)
    try:
        task = load_task(target, args.tasks_root)
    except TaskLoadError:
        task = None

    suite_tasks = [task for task in list_tasks(args.tasks_root) if task.batch == target]
    if task is not None and suite_tasks:
        raise ValueError(f"target is ambiguous (matches both a task and a suite): {target}")
    if task is not None:
        return task
    if suite_tasks:
        return suite_tasks
    raise ValueError(f"unknown target (not a known task or suite): {target}")


def _load_task_if_exists(task_id: str | None, tasks_root: Path | None) -> object | None:
    if not task_id:
        return None
    try:
        return load_task(task_id, tasks_root)
    except TaskLoadError:
        return None


def _prepare_task_workdir(task_id: str, env: dict[str, str]) -> Path:
    completed = container_exec(
        ["python3", "-m", "bench.runtime", "prepare-workdir", task_id],
        workdir=CONTAINER_ROOT,
        env=env,
        verbose=False,
    )
    if completed.returncode != 0:
        _emit_completed_process(completed)
        raise RuntimeError(f"task workspace prep failed ({completed.returncode})")
    stdout = str(getattr(completed, "stdout", "") or "").strip()
    if not stdout:
        raise RuntimeError("task workspace prep did not return a workspace path")
    workdir = Path(stdout.splitlines()[-1].strip())
    return workdir


def _collect_pi_sessions_from_container(sync_summary: dict[str, Any], run_dir: Path) -> None:
    home_dir = str(sync_summary.get("home_dir") or "")
    if not home_dir:
        return
    source = Path(home_dir) / ".pi" / "agent" / "sessions"
    target = Path("/bench/results") / run_dir.name / "artifacts" / "pi-sessions"
    script = "\n".join(
        [
            "set -eu",
            f"src={shlex.quote(str(source))}",
            f"dst={shlex.quote(str(target))}",
            "[ -d \"$src\" ] || exit 0",
            "mkdir -p \"$dst\"",
            "cp -a \"$src\"/. \"$dst\"/",
            "if [ -n \"${BENCH_HOST_UID:-}\" ] && [ -n \"${BENCH_HOST_GID:-}\" ]; then",
            "  chown -R \"$BENCH_HOST_UID:$BENCH_HOST_GID\" \"$dst\"",
            "fi",
        ]
    )
    container_exec(["sh", "-lc", script], workdir=CONTAINER_ROOT, env={CONTAINER_CONTEXT_ENV: "1"}, verbose=False)


def _session_cwd(path: Path) -> str:
    try:
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        payload = json.loads(first)
    except (OSError, IndexError, json.JSONDecodeError):
        return ""
    return str(payload.get("cwd") or "") if isinstance(payload, dict) else ""


def _collect_pi_sessions_local(home_dir: str | Path | None, artifacts_dir: Path, *, workspace: Path | None = None) -> dict[str, Any]:
    """Copy pi session files from a runtime home on this filesystem into run artifacts."""
    record_path = artifacts_dir / "pi-sessions-collection.json"

    def _record(status: str, reason: str = "", error: str = "", source: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if source:
            payload["source"] = source
        if reason:
            payload["reason"] = reason
        if error:
            payload["error"] = error
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return dict(payload)

    home = str(home_dir or "").strip()
    if not home:
        return _record("unavailable", reason="missing_home_dir")
    source = Path(home) / ".pi" / "agent" / "sessions"
    target = artifacts_dir / "pi-sessions"
    try:
        if not source.is_dir():
            return _record("unavailable", reason="source_missing")
        if workspace is None:
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            workspace_text = str(workspace)
            for path in source.rglob("*.jsonl"):
                if _session_cwd(path) != workspace_text:
                    continue
                dest = target / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
    except OSError as exc:
        return _record("unavailable", reason="copy_failed", error=str(exc))
    return _record("collected", source=str(source))


def _sync_task_workspace_from_container(workdir: Path, run_dir: Path) -> None:
    target = Path("/bench/results") / run_dir.name / "workspace"
    script = "\n".join(
        [
            "set -eu",
            f"src={shlex.quote(str(workdir))}",
            f"dst={shlex.quote(str(target))}",
            "[ -d \"$src\" ] || exit 0",
            "rm -rf \"$dst\"",
            "mkdir -p \"$dst\"",
            "cp -a \"$src\"/. \"$dst\"/",
            "if [ -n \"${BENCH_HOST_UID:-}\" ] && [ -n \"${BENCH_HOST_GID:-}\" ]; then",
            "  chown -R \"$BENCH_HOST_UID:$BENCH_HOST_GID\" \"$dst\"",
            "fi",
        ]
    )
    completed = container_exec(["sh", "-lc", script], workdir=CONTAINER_ROOT, env={CONTAINER_CONTEXT_ENV: "1"}, verbose=False)
    if completed.returncode != 0:
        _emit_completed_process(completed)
        raise RuntimeError(f"task workspace sync failed ({completed.returncode})")


def _run_task_session(
    args: argparse.Namespace,
    task,
    *,
    harness: str,
) -> int:
    prompt_text = task.prompt_path.read_text(encoding="utf-8").rstrip()
    catalog_path = Path(args.catalog) if getattr(args, "catalog", None) is not None else None
    if catalog_path is not None and not catalog_path.is_file():
        catalog_path = None
    run_id = args.run_id or _now_run_id()
    sync_summary = _sync_runtime_config_inside_container(
        run_id=run_id,
        orchestra_tools_enabled=False if args.orchestra is False else None,
    )
    prepared = prepare_run(
        task,
        root=args.root,
        run_id=run_id,
        catalog_path=catalog_path,
        role=args.role,
        orchestra=args.orchestra,
        notes=args.notes,
        catalog_label=args.catalog_label,
        runtime_snapshot=sync_summary,
    )
    _bench_log(f"task: {task.task_id}")
    _bench_log(f"prompt: {task.prompt_path.name}")
    print(prompt_text)
    _bench_log("opening harness...")
    workdir = _prepare_task_workdir(
        task.task_id,
        {
            CONTAINER_CONTEXT_ENV: "1",
            "BENCH_RUN_ID": prepared.run_paths.run_id,
        },
    )
    env = {CONTAINER_CONTEXT_ENV: "1"}
    command = [harness]
    if harness == "pi":
        env.update(_runtime_env_from_summary(sync_summary))
        _, resolved = _resolve_catalog_and_harness(args)
        model = str(resolved.get("model") or "").strip()
        if model:
            command.extend(["--model", model])
    interactive = _has_interactive_tty()
    transcript_path = _passthrough_transcript_path(harness) if interactive else None
    completed = container_exec(
        command,
        workdir=workdir,
        env=env,
        verbose=getattr(args, "verbose", False),
        interactive=interactive,
        tty=interactive,
        transcript_path=transcript_path,
    )
    if not getattr(args, "verbose", False) and not interactive:
        payload: dict[str, Any] = {
            "container": "orchestra-bench-runner",
            "command": command,
            "returncode": completed.returncode,
        }
        if getattr(completed, "stdout", None):
            payload["stdout"] = completed.stdout
        if getattr(completed, "stderr", None):
            payload["stderr"] = completed.stderr
        _print_json(payload)
    stdout_text = str(getattr(completed, "stdout", None) or "")
    stderr_text = str(getattr(completed, "stderr", None) or "")
    harness_artifacts = HarnessArtifactPaths.for_run_paths(prepared.run_paths)
    harness_artifacts.root.mkdir(parents=True, exist_ok=True)
    if transcript_path is not None and Path(transcript_path).is_file():
        shutil.copy2(transcript_path, harness_artifacts.transcript_path)
    elif stdout_text or stderr_text:
        harness_artifacts.transcript_path.write_text(stdout_text + stderr_text, encoding="utf-8")
    if stdout_text or stderr_text:
        harness_artifacts.log_path.write_text(stdout_text + stderr_text, encoding="utf-8")
    _sync_task_workspace_from_container(workdir, prepared.run_paths.run_dir)
    _collect_pi_sessions_from_container(sync_summary, prepared.run_paths.run_dir)
    harness_status = "ok" if completed.returncode == 0 else "lifecycle_failed"
    harness_result = HarnessResult(
        status=harness_status,
        exit_code=completed.returncode,
        error="" if completed.returncode == 0 else f"command exited with code {completed.returncode}",
        details={
            "command": command,
            "workdir": str(workdir),
            "stdout": stdout_text,
            "stderr": stderr_text,
            "artifacts": {
                "summary": str(harness_artifacts.summary_path),
                "transcript": str(harness_artifacts.transcript_path),
                "events": str(harness_artifacts.events_path),
                "log": str(harness_artifacts.log_path),
                "pi_sessions": str(prepared.run_paths.artifacts_dir / "pi-sessions"),
            },
        },
    )
    harness_artifacts.summary_path.write_text(
        json.dumps(harness_result.__dict__, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial_result = TaskResult(
        run_meta=prepared.run_meta,
        harness=harness_result,
        outcome="not_run" if completed.returncode == 0 else "error",
        details={"bench_run_json": str(prepared.run_paths.bench_run_json)},
    )
    write_json_atomic(prepared.run_paths.result_json, partial_result)
    if harness_result.status != "ok":
        _bench_log(f"harness failed: {harness_result.error or 'lifecycle_failed'}")
        _bench_log(f"result: {prepared.run_paths.result_json}")
        _bench_log(f"artifacts: {prepared.run_paths.artifacts_dir}")
        return int(completed.returncode)
    result = grade_run(task, prepared.run_paths, prior_result=partial_result)
    result.details = {
        **(result.details if isinstance(result.details, dict) else {}),
        "result_json": str(prepared.run_paths.result_json),
        "artifacts": {
            "run_dir": str(prepared.run_paths.run_dir),
            "workspace": str(prepared.run_paths.run_dir / "workspace"),
            "bench_run_json": str(prepared.run_paths.bench_run_json),
            "evaluator": {
                "root": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).root),
                "stdout": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).stdout_path),
                "stderr": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).stderr_path),
                "log": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).log_path),
                "result": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).result_json_path),
            },
        },
    }
    _bench_log(f"graded: {result.outcome} (score={result.evaluation.score or 'n/a'}, evaluator={result.evaluation.status})")
    _bench_log(f"result: {prepared.run_paths.result_json}")
    _bench_log(f"artifacts: {prepared.run_paths.artifacts_dir}")
    return int(completed.returncode)


CONTAINER_CATALOG_PATH = Path("/bench/orchestra-config/agent-catalog.yaml")
CONTAINER_TASKS_ROOT = Path("/bench/task-materials-source")
CONTAINER_ROOT = Path("/bench")
CONTAINER_CONTEXT_ENV = "BENCH_IN_CONTAINER"
LEGACY_CONTAINER_CONTEXT_ENV = "BENCH_RUN_CONTEXT"
RUN_PUBLIC_TARGETS = {"pi", "hermes", "opencode"}
PROJECT_CATALOG_RELPATH = Path("config") / "orchestra" / "agent-catalog.yaml"


def _repo_root() -> Path:
    cwd = Path.cwd().resolve()
    if cwd.name == "scripts" and cwd.parent != cwd:
        return cwd.parent
    return cwd


def _has_interactive_tty() -> bool:
    return all(bool(getattr(stream, "isatty", lambda: False)()) for stream in (sys.stdin, sys.stdout, sys.stderr))


def _passthrough_transcript_path(harness: str) -> Path:
    safe_harness = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in harness)
    filename = f"{time.time_ns()}-{safe_harness}.typescript"
    return _repo_root() / "artifacts" / "02-run" / filename


def _inside_container() -> bool:
    return os.environ.get(CONTAINER_CONTEXT_ENV) in {"1", "true", "yes"} or os.environ.get(
        LEGACY_CONTAINER_CONTEXT_ENV
    ) == "container"


def _build_run_help_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench run",
        description="Dispatch a harness passthrough or automatic benchmark target.",
    )
    parser.add_argument("--tasks-root", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=PROJECT_CATALOG_RELPATH)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--role", default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--catalog-label", default=None)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    orchestra_group = parser.add_mutually_exclusive_group()
    orchestra_group.add_argument("--orchestra", dest="orchestra", action="store_true")
    orchestra_group.add_argument("--no-orchestra", dest="orchestra", action="store_false")
    parser.set_defaults(orchestra=None)
    parser.add_argument("target", nargs="?", metavar="target")
    parser.add_argument("argv", nargs=argparse.REMAINDER, metavar="...")
    return parser


def _print_run_help() -> None:
    print(
        "\n".join(
            [
                "usage:",
                "  02-run <pi|hermes|opencode> [task-id|args...]",
                "  02-run --auto [pi|hermes|opencode] <task-or-suite|all> [--verbose]",
                "  02-run --list         list suites with their tasks",
                "",
                "Open a manual harness session in the container, or run and score a task/suite/all automatically.",
                "If the first argument after pi/hermes/opencode is a known task id, 02-run opens that task session and prints Prompt.md first.",
                "Automatic runs default to the catalog role/harness; 02-run --auto smoke keeps that default, while 02-run --auto pi smoke selects Pi explicitly.",
                "",
                "Discovery:",
                "  02-run --list         list suites with their tasks",
                "",
                "Options:",
                "  --auto <task-or-suite|all>  run and score an automatic task, suite, or all suites",
                "  --verbose               stream the full session output for a real target",
                "Orchestra tools are available by default.",
                "  --no-orchestra          disable Orchestra tools for this run (only opt-out)",
                "",
                "Examples:",
                "  02-run pi smoke-dependent-setup-chain",
                "  02-run pi config",
                "  02-run hermes --version",
                "  02-run --auto smoke-dependent-setup-chain",
                "  02-run --auto pi smoke-dependent-setup-chain",
                "  02-run --auto hermes smoke",
                "  02-run --auto opencode smoke",
                "  02-run --auto smoke",
                "  02-run --auto all",
                "  02-run --auto smoke --verbose",
            ]
        )
    )


def _print_public_results_help() -> None:
    print(
        "\n".join(
            [
                "usage: scripts/03-results [command] [run-id]",
                "",
                "Show benchmark results. Bare scripts/03-results prints the dashboard and recent runs.",
                "",
                "common commands:",
                "  scripts/03-results dash         dashboard + recent runs",
                "  scripts/03-results runs         recent runs only",
                "  scripts/03-results run <id>     details for one run; timestamp prefix is ok",
                "  scripts/04-debug <run-id> orch|full|raw",
                "  scripts/03-results comp <a> <b>  compare two selectors (alias of compare)",
                "",
                "other commands: tokens, timing, compare, rescore, delete",
                "",
                "examples:",
                "  scripts/03-results",
                "  scripts/03-results dash --suite smoke",
                "  scripts/03-results run 20260830T035857",
                "  scripts/04-debug 20260830T035857 orch",
                "  scripts/04-debug 20260830T035857 full",
                "  scripts/03-results delete --task smoke-dependent-setup-chain",
                "  scripts/03-results delete --task smoke-dependent-setup-chain --yes",
                "  scripts/03-results delete --all --yes",
            ]
        )
    )


def _consume_run_option(args: argparse.Namespace, raw_args: Sequence[str], index: int) -> int:
    token = raw_args[index]
    if token == "--tasks-root":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--tasks-root requires a path")
        args.tasks_root = Path(raw_args[index])
        return index + 1
    if token == "--root":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--root requires a path")
        args.root = Path(raw_args[index])
        return index + 1
    if token == "--catalog":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--catalog requires a path")
        args.catalog = Path(raw_args[index])
        return index + 1
    if token == "--run-id":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--run-id requires a value")
        args.run_id = raw_args[index]
        return index + 1
    if token == "--role":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--role requires a value")
        args.role = raw_args[index]
        return index + 1
    if token == "--notes":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--notes requires a value")
        args.notes = raw_args[index]
        return index + 1
    if token == "--catalog-label":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--catalog-label requires a value")
        args.catalog_label = raw_args[index]
        return index + 1
    if token == "--auto-harness":
        index += 1
        if index >= len(raw_args):
            raise ValueError("--auto-harness requires a value")
        args.auto_harness = raw_args[index]
        return index + 1
    if token == "--auto":
        args.auto = True
        index += 1
        if index + 1 < len(raw_args) and raw_args[index] in RUN_PUBLIC_TARGETS and not raw_args[index + 1].startswith("-"):
            args.auto_harness = raw_args[index]
            args.task_id = raw_args[index + 1]
            return index + 2
        if index < len(raw_args) and args.task_id is None:
            args.task_id = raw_args[index]
            return index + 1
        return index
    if token == "--list":
        args.list = True
        return index + 1
    if token == "--raw":
        args.raw = True
        return index + 1
    if token == "--dry-run":
        args.dry_run = True
        return index + 1
    if token == "--verbose":
        args.verbose = True
        return index + 1
    if token == "--orchestra":
        args.orchestra = True
        return index + 1
    if token == "--no-orchestra":
        args.orchestra = False
        return index + 1
    raise ValueError(f"unknown option: {token}")


def _parse_run_argv(raw_args: Sequence[str]) -> argparse.Namespace:
    args = argparse.Namespace(
        tasks_root=None,
        root=None,
        catalog=PROJECT_CATALOG_RELPATH,
        run_id=None,
        role=None,
        notes="",
        catalog_label=None,
        auto=False,
        auto_harness=None,
        list=False,
        raw=False,
        dry_run=False,
        verbose=False,
        orchestra=None,
        task_id=None,
        argv=[],
    )
    index = 0
    while index < len(raw_args):
        token = raw_args[index]
        if token.startswith("-") or token == "--auto":
            index = _consume_run_option(args, raw_args, index)
            continue
        if args.list:
            raise ValueError(f"unexpected argument after discovery flag: {token}")
        if token in RUN_PUBLIC_TARGETS and not args.auto and args.task_id is None:
            args.task_id = token
            args.argv = list(raw_args[index + 1 :])
            return args
        if args.task_id is None:
            args.task_id = token
            index += 1
            continue
        if args.auto:
            raise ValueError(f"unexpected argument after --auto target: {token}")
        raise ValueError(f"unexpected argument: {token}")
    return args


def _container_catalog_path(catalog: Path) -> Path:
    if catalog.parts[-2:] == ("orchestra", "agent-catalog.yaml"):
        return CONTAINER_CATALOG_PATH
    return catalog


def _emit_completed_process(completed) -> None:  # type: ignore[no-untyped-def]
    if getattr(completed, "stdout", None):
        sys.stdout.write(str(completed.stdout))
    if getattr(completed, "stderr", None):
        sys.stderr.write(str(completed.stderr))


def cmd_help(parser: argparse.ArgumentParser, _args: argparse.Namespace) -> int:
    parser.print_help()
    return 0


def _print_start_summary(summary: dict[str, object]) -> None:
    runtime = summary.get("runtime") if isinstance(summary.get("runtime"), dict) else {}
    print("Setup complete:")
    print(f"  image: {summary.get('image')}")
    print(f"  container: {summary.get('container')}")
    print(f"  pi runtime dir: {runtime.get('pi_runtime_dir')}")
    print(f"  orchestra runtime dir: {runtime.get('orchestra_runtime_dir')}")


def cmd_start(args: argparse.Namespace) -> int:
    summary = prepare_startup(
        root=args.root or Path.cwd(),
        progress=lambda message: print(message, flush=True),
        stream_build_output=True,
    )
    _print_start_summary(summary)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    tasks = list_tasks(args.tasks_root)
    batch = getattr(args, "batch", None)
    if batch is not None:
        tasks = [task for task in tasks if task.batch == batch]
    _print_grouped_task_list(tasks, args.tasks_root)
    return 0


def _print_grouped_task_list(tasks, tasks_root: Path | None) -> None:  # type: ignore[no-untyped-def]
    suites = list_suites(tasks_root)
    grouped: dict[str, list[Any]] = {}
    for task in tasks:
        grouped.setdefault(task.batch or "unbatched", []).append(task)

    lines: list[str] = []

    def add_section(title: str, section_tasks: list[Any]) -> None:
        if not section_tasks:
            return
        if lines:
            lines.append("")
        lines.append(f"[{title}]")
        for task in section_tasks:
            lines.extend(_task_display_lines(task))

    for suite in suites:
        add_section(suite, sorted(grouped.pop(suite, []), key=lambda task: task.task_id))

    add_section("unbatched", sorted(grouped.pop("unbatched", []), key=lambda task: task.task_id))

    for batch in sorted(grouped):
        add_section(batch, sorted(grouped[batch], key=lambda task: task.task_id))

    if lines:
        print("\n".join(lines))


def _print_run_list(args: argparse.Namespace) -> int:
    batch = getattr(args, "batch", None)
    tasks = [task for task in list_tasks(args.tasks_root) if not batch or task.batch == batch]
    _print_grouped_task_list(tasks, args.tasks_root)
    return 0


def _resolve_catalog_and_harness(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    catalog = Path(args.catalog)
    resolved = resolve_harness_for_role(catalog, role=args.role)
    requested_harness = getattr(args, "auto_harness", None)
    if requested_harness and resolved.get("harness") != requested_harness:
        catalog_data = load_catalog(catalog)
        harness_config = next(
            (config for config in catalog_data.harness_configs.values() if config.harness == requested_harness),
            None,
        )
        if harness_config is None:
            raise KeyError(f"harness '{requested_harness}' not found in {catalog}")
        resolved = dict(resolved)
        resolved["harness_config"] = harness_config.name
        resolved["harness"] = harness_config.harness
        resolved["backend"] = harness_config.harness
        resolved["command"] = list(harness_config.command)
    return catalog, resolved


def _auto_inner_argv(args: argparse.Namespace) -> list[str]:
    if not args.task_id:
        raise ValueError("--auto requires a task or suite target")
    inner_args: list[str] = ["run", "--root", str(CONTAINER_ROOT), "--tasks-root", str(CONTAINER_TASKS_ROOT)]
    inner_args.append(str(args.task_id))
    if args.run_id is not None:
        inner_args.extend(["--run-id", args.run_id])
    if args.role is not None:
        inner_args.extend(["--role", args.role])
    if args.notes:
        inner_args.extend(["--notes", args.notes])
    catalog_label = args.catalog_label if args.catalog_label is not None else str(args.catalog)
    if catalog_label:
        inner_args.extend(["--catalog-label", catalog_label])
    inner_catalog = _container_catalog_path(Path(args.catalog))
    inner_args.extend(["--catalog", str(inner_catalog)])
    if getattr(args, "auto_harness", None) is not None:
        inner_args.extend(["--auto-harness", str(args.auto_harness)])
    if args.orchestra is True:
        inner_args.append("--orchestra")
    elif args.orchestra is False:
        inner_args.append("--no-orchestra")
    if getattr(args, "verbose", False):
        inner_args.append("--verbose")
    if getattr(args, "dry_run", False):
        inner_args.append("--dry-run")
    if getattr(args, "auto", False):
        inner_args.append("--auto")
    return inner_args


def _run_auto_inside_container(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    run_id = args.run_id or _now_run_id()
    args.run_id = run_id
    sync_summary = _sync_runtime_config_inside_container(
        run_id=run_id,
        orchestra_tools_enabled=False if args.orchestra is False else None,
    )
    completed = container_exec(
        ["python3", "-m", "bench.cli", *_auto_inner_argv(args)],
        workdir=CONTAINER_ROOT,
        env={CONTAINER_CONTEXT_ENV: "1", **_runtime_env_from_summary(sync_summary), "BENCH_RUN_ID": run_id},
        verbose=True,
    )
    return completed.returncode


def _derive_orchestra_tools_available(
    backend: str,
    runtime_snapshot: dict[str, object] | None,
) -> bool | None:
    """Return tool availability only when the selected backend/runtime proves it."""
    if backend != "pi" or runtime_snapshot is None:
        return None
    enabled = runtime_snapshot.get("orchestra_tools_enabled_by_default")
    return enabled if isinstance(enabled, bool) else None


def _run_single_task(
    args: argparse.Namespace,
    task,
    *,
    catalog: Path | None = None,
    resolved: dict[str, object] | None = None,
    stream_output: bool = False,
) -> TaskResult:
    catalog_path, resolved_config = (
        (catalog, resolved)
        if catalog is not None and resolved is not None
        else _resolve_catalog_and_harness(args)
    )
    backend = str(resolved_config.get("backend") or resolved_config.get("harness") or "")
    catalog_orchestra_enabled = bool(resolved_config.get("enabled")) or args.orchestra is True
    tools_enabled = False if args.orchestra is False else None
    no_orchestra = args.orchestra is False if args.auto else None
    orchestra_tools_available = None
    # Orchestra tools are exposed by runtime config; no explicit enable command is sent.
    effective_orchestra = bool(args.auto and backend == "pi" and catalog_orchestra_enabled and args.orchestra is not False)
    if args.auto and backend == "pi":
        model = str(resolved_config.get("model") or args.model or "")
        rpc_command = ["pi"] + (["--model", model] if model else []) + ["--mode", "rpc"]
        harness = PiRpcHarness(rpc_command, env=resolved_config.get("env") or {})
    else:
        harness = CommandHarness.from_resolved_config(resolved_config)
    runtime_snapshot: dict[str, object] | None = None
    request_env = dict(resolved_config.get("env") or {})
    if args.auto:
        runtime_snapshot = load_runtime_config_summary() or None
        request_env.update(_runtime_env_from_summary(runtime_snapshot))
        orchestra_tools_available = _derive_orchestra_tools_available(backend, runtime_snapshot)
    on_settled: Callable[[Any], None] | None = None
    if args.auto and backend == "pi":

        def on_settled(prepared):  # type: ignore[no-untyped-def]
            home_dir = str((runtime_snapshot or {}).get("home_dir") or "")
            _collect_pi_sessions_local(home_dir, prepared.run_paths.artifacts_dir, workspace=workspace_dir(prepared.run_paths))

    return run_and_grade(
        task,
        harness,
        root=args.root,
        run_id=args.run_id,
        catalog_path=catalog_path,
        role=args.role,
        orchestra=effective_orchestra,
        auto=args.auto,
        notes=args.notes,
        catalog_label=args.catalog_label,
        runtime_snapshot=runtime_snapshot,
        no_orchestra=no_orchestra,
        orchestra_tools_available=orchestra_tools_available,
        model=str(resolved_config.get("model") or ""),
        agent=str(resolved_config.get("agent") or ""),
        profile=str(resolved_config.get("profile") or ""),
        env=request_env,
        stream_output=stream_output,
        request_metadata={"orchestra_tools_enabled": tools_enabled},
        on_settled=on_settled,
    )


def cmd_run(args: argparse.Namespace) -> int:
    argv = list(getattr(args, "argv", []))
    if getattr(args, "list", False):
        return _print_run_list(args)
    if args.auto and str(args.task_id) == "all":
        return cmd_run_all_suites(args)
    if args.auto:
        if not _inside_container():
            return _run_auto_inside_container(args)
    elif args.task_id in RUN_PUBLIC_TARGETS:
        candidate_task_id = argv[0] if argv else None
        candidate_task = None if getattr(args, "raw", False) else _load_task_if_exists(candidate_task_id, args.tasks_root)
        if candidate_task is not None:
            if len(argv) > 1:
                raise ValueError("manual task sessions accept only <task-id>; use --raw for passthrough")
            return _run_task_session(args, candidate_task, harness=str(args.task_id))
        passthrough_args = argparse.Namespace(harness=args.task_id, argv=argv, verbose=getattr(args, "verbose", False))
        return cmd_exec(passthrough_args)
    elif not _inside_container():
        if args.task_id:
            raise ValueError(
                "host-side benchmark runs require --auto; use 02-run --auto <task-or-suite> inside the benchmark container"
            )
    if not args.task_id:
        raise ValueError("a task, suite, or harness target is required")
    resolved_target = _resolve_auto_target(args)
    if isinstance(resolved_target, list):
        return cmd_run_suite(args, tasks=resolved_target)

    task = resolved_target
    if args.dry_run:
        payload: dict[str, Any] = {
            "task": _task_payload(task),
            "run_id": args.run_id,
            "run_dir": str(RepoPaths(Path.cwd() if args.root is None else args.root).run(args.run_id or "", task.task_id).run_dir)
            if args.run_id
            else "",
            "dry_run": True,
        }
        catalog_path = Path(args.catalog) if args.catalog is not None else None
        if catalog_path is not None:
            payload["catalog"] = str(catalog_path)
            if catalog_path.is_file():
                _, resolved_harness = _resolve_catalog_and_harness(args)
                payload["harness"] = resolved_harness
        _print_json(payload)
        return 0

    if args.auto:
        _bench_log(f"auto: {task.task_id}", flush=True)
        result = _run_single_task(args, task, stream_output=getattr(args, "verbose", False))
        _print_auto_result(result)
        return 0 if result.outcome == "pass" else 1

    result = _run_single_task(args, task)
    _print_json(result.to_dict())
    return 0


def _sync_runtime_config_inside_container(run_id: str | None = None, *, orchestra_tools_enabled: bool | None = None) -> dict[str, Any]:
    env = {CONTAINER_CONTEXT_ENV: "1"}
    if run_id:
        env["BENCH_RUN_ID"] = run_id
    if orchestra_tools_enabled is not None:
        env["BENCH_ORCHESTRA_TOOLS_DEFAULT"] = "1" if orchestra_tools_enabled else "0"
    completed = container_exec(
        ["python3", "-m", "bench.runtime", "init-runtime"],
        workdir=CONTAINER_ROOT,
        env=env,
        verbose=False,
    )
    if completed.returncode != 0:
        _emit_completed_process(completed)
        raise RuntimeError(f"in-container runtime config sync failed ({completed.returncode})")
    stdout = getattr(completed, "stdout", None) or ""
    return _parse_json_summary_from_stdout(stdout)


def cmd_exec(args: argparse.Namespace) -> int:
    sync_summary = _sync_runtime_config_inside_container()
    env = {CONTAINER_CONTEXT_ENV: "1"}
    if args.harness == "pi":
        # Point the interactive session at the run-scoped runtime dirs that the
        # in-container sync just populated from the regular config mounts.
        env.update(_runtime_env_from_summary(sync_summary))
    interactive = _has_interactive_tty()
    transcript_path = _passthrough_transcript_path(args.harness) if interactive else None
    completed = container_exec(
        [args.harness, *args.argv],
        workdir=CONTAINER_ROOT,
        env=env,
        verbose=getattr(args, "verbose", False),
        interactive=interactive,
        tty=interactive,
        transcript_path=transcript_path,
    )
    if not getattr(args, "verbose", False) and not interactive:
        payload: dict[str, Any] = {
            "container": "orchestra-bench-runner",
            "command": [args.harness, *args.argv],
            "returncode": completed.returncode,
        }
        if getattr(completed, "stdout", None):
            payload["stdout"] = completed.stdout
        if getattr(completed, "stderr", None):
            payload["stderr"] = completed.stderr
        _print_json(payload)
    return int(completed.returncode)


def cmd_run_suite(args: argparse.Namespace, tasks: list[Any] | None = None) -> int:
    suite_name = str(args.task_id)
    resolved_tasks = tasks if tasks is not None else [task for task in list_tasks(args.tasks_root) if task.batch == suite_name]
    if not resolved_tasks:
        raise ValueError(f"unknown target (not a known task or suite): {suite_name}")
    if args.dry_run:
        payload: dict[str, Any] = {
            "suite": suite_name,
            "policy": "continue",
            "task_count": len(resolved_tasks),
            "tasks": [_task_payload(task) for task in resolved_tasks],
            "dry_run": True,
        }
        _print_json(payload)
        return 0

    catalog, resolved = _resolve_catalog_and_harness(args)
    _bench_log(f"auto suite: {suite_name} ({len(resolved_tasks)} tasks)", flush=True)
    results = []
    for task in resolved_tasks:
        _bench_log(f"auto: {task.task_id}", flush=True)
        result = _run_single_task(args, task, catalog=catalog, resolved=resolved, stream_output=getattr(args, "verbose", False))
        results.append(result)
        _print_auto_result(result)
    summary = _suite_summary_payload(suite_name, results)
    _bench_log(f"suite complete: passed={summary['passed']} failed={summary['failed']}", flush=True)
    return int(summary["return_code"])


def cmd_run_all_suites(args: argparse.Namespace) -> int:
    suites = list_suites(args.tasks_root)
    if not suites:
        raise ValueError("no suites found")
    _bench_log(f"auto all: {len(suites)} suites", flush=True)
    return_code = 0
    for suite in suites:
        suite_args = argparse.Namespace(**vars(args))
        suite_args.task_id = suite
        suite_code = _run_auto_inside_container(suite_args) if not _inside_container() else cmd_run_suite(suite_args)
        if suite_code != 0:
            return_code = 1
    _bench_log(f"all complete: suites={len(suites)} status={'pass' if return_code == 0 else 'fail'}", flush=True)
    return return_code


def cmd_grade(args: argparse.Namespace) -> int:
    run_paths = _resolve_run_paths(args.root, args.run_ref)
    task = load_task(run_paths.task_id, args.tasks_root)
    result = grade_run(task, run_paths, prior_result=_load_result_or_none(run_paths.result_json))
    _print_json(result.to_dict())
    return 0


def cmd_suite(args: argparse.Namespace) -> int:
    tasks = list_tasks(args.tasks_root)
    if args.suite is None:
        for suite in list_suites(args.tasks_root):
            print(suite)
        return 0
    for task in tasks:
        if task.batch == args.suite:
            print(_task_summary_line(task))
    return 0


def _add_results_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--tasks-root", type=Path, default=None, help=argparse.SUPPRESS)


def _add_results_selection_args(parser: argparse.ArgumentParser, *, include_limit: bool = True) -> None:
    parser.add_argument("--task", default=None)
    parser.add_argument("--suite", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--harness", default=None)
    parser.add_argument("--result", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--since", default=None)
    parser.add_argument("--role", default=None)
    orchestra_group = parser.add_mutually_exclusive_group()
    orchestra_group.add_argument("--orchestra", nargs="?", const="yes", choices=("yes", "no"), default=None)
    orchestra_group.add_argument("--no-orchestra", dest="orchestra", action="store_const", const="no", help=argparse.SUPPRESS)
    parser.add_argument("--filter", dest="filters", action="append", default=[], metavar="field:value[,field:value...]")
    parser.add_argument("--sort", default="finished_at")
    parser.add_argument("--ascending", action="store_true")
    if include_limit:
        parser.add_argument("--limit", type=int, default=None)


def _results_sort_reverse(args: argparse.Namespace) -> bool:
    return not getattr(args, "ascending", False)


def _normalize_orchestra_filter(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"", "none"}:
        return None
    if text in {"yes", "true", "1", "y"}:
        return True
    if text in {"no", "false", "0", "n"}:
        return False
    raise ValueError(f"invalid orchestra filter: {value!r}")


def _parse_filter_specs(raw_filters: Sequence[str] | None) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for raw in raw_filters or []:
        for token in str(raw).split(","):
            token = token.strip()
            if not token:
                continue
            if ":" not in token:
                raise ValueError(f"invalid filter expression: {token!r}")
            field, value = token.split(":", 1)
            field = field.strip()
            value = value.strip()
            if not field or not value:
                raise ValueError(f"invalid filter expression: {token!r}")
            parsed.append((field, value))
    return parsed


def _results_filter_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    since = getattr(args, "since", None)
    parsed_since = parse_since_filter(since) if since is not None else None
    return {
        "task": getattr(args, "task", None),
        "suite": getattr(args, "suite", None),
        "model": getattr(args, "model", None),
        "harness": getattr(args, "harness", None),
        "result": getattr(args, "result", None),
        "notes": getattr(args, "notes", None),
        "since": parsed_since,
        "orchestra": _normalize_orchestra_filter(getattr(args, "orchestra", None)),
        "role": getattr(args, "role", None),
        "filters": _parse_filter_specs(getattr(args, "filters", None)),
    }


def _select_results_for_args(args: argparse.Namespace, *, include_limit: bool = True):
    filter_kwargs = _results_filter_kwargs(args)
    entries = select_results(
        args.root,
        tasks_dir=getattr(args, "tasks_root", None),
        task=filter_kwargs.pop("task"),
        suite=filter_kwargs.pop("suite"),
        model=filter_kwargs.pop("model"),
        orchestra=filter_kwargs.pop("orchestra"),
        sort=getattr(args, "sort", "finished_at"),
        reverse=_results_sort_reverse(args),
        limit=None,
    )
    entries = filter_report_entries(entries, **filter_kwargs)
    limit = getattr(args, "limit", None) if include_limit else None
    if limit is not None:
        if limit <= 0:
            return []
        entries = entries[:limit]
    return entries


def _results_context_line(args: argparse.Namespace, *, include_limit: bool = True) -> str | None:
    limit = getattr(args, "limit", None) if include_limit else None
    sort = getattr(args, "sort", "finished_at")
    reverse = _results_sort_reverse(args)
    context = describe_filters(
        task=getattr(args, "task", None),
        suite=getattr(args, "suite", None),
        model=getattr(args, "model", None),
        orchestra=_normalize_orchestra_filter(getattr(args, "orchestra", None)),
        sort=sort,
        reverse=reverse,
        limit=limit,
    )
    extras: list[str] = []
    for key in ("harness", "result", "notes", "since", "role"):
        value = getattr(args, key, None)
        if value is not None:
            extras.append(f"{key}={value}")
    filters = _parse_filter_specs(getattr(args, "filters", None))
    if filters:
        extras.append("filter=" + ",".join(f"{field}:{value}" for field, value in filters))
    if extras:
        context = f"{context}, " + ", ".join(extras) if context != "all results" else ", ".join(extras)
    if (
        getattr(args, "task", None) is None
        and getattr(args, "suite", None) is None
        and getattr(args, "model", None) is None
        and getattr(args, "harness", None) is None
        and getattr(args, "result", None) is None
        and getattr(args, "notes", None) is None
        and getattr(args, "since", None) is None
        and getattr(args, "role", None) is None
        and _normalize_orchestra_filter(getattr(args, "orchestra", None)) is None
        and not filters
        and sort == "finished_at"
        and reverse
        and limit is None
    ):
        return None
    return f"selection: {context}"


def _print_results_context(args: argparse.Namespace, *, include_limit: bool = True) -> None:
    context = _results_context_line(args, include_limit=include_limit)
    if context is not None:
        print(context)


def _require_results_filter(args: argparse.Namespace, action: str) -> None:
    if _results_context_line(args, include_limit=False) is None:
        raise ValueError(f"{action} requires at least one filter")


def _find_report_entry(entries, run_ref: str):  # type: ignore[no-untyped-def]
    ref = Path(run_ref).stem if str(run_ref).endswith(".json") else Path(run_ref).name
    exact = []
    prefix = []
    for entry in entries:
        full = f"{entry.run_id}-{entry.task_id}"
        if ref == full or ref == entry.run_id:
            exact.append(entry)
        elif full.startswith(ref) or entry.run_id.startswith(ref):
            prefix.append(entry)
    matches = exact or prefix
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"run reference is ambiguous: {run_ref}")
    return None



def cmd_results(args: argparse.Namespace) -> int:
    view = getattr(args, "results_view", None) or "dash"
    if view in {"dash", "dashboard"}:
        entries = _select_results_for_args(args)
        _print_results_context(args)
        sys.stdout.write(format_dashboard(entries))
        return 0
    if view == "runs":
        entries = _select_results_for_args(args)
        _print_results_context(args)
        sys.stdout.write(format_runs(entries))
        return 0
    if view == "run":
        entries = _select_results_for_args(args, include_limit=False)
        entry = _find_report_entry(entries, args.run_ref)
        if entry is None:
            sys.stdout.write("no valid scored runs\n")
            return 0
        _print_results_context(args, include_limit=False)
        sys.stdout.write(format_run_detail(entry))
        return 0
    if view == "tokens":
        entries = _select_results_for_args(args)
        _print_results_context(args)
        sys.stdout.write(format_tokens(entries))
        return 0
    if view == "timing":
        entries = _select_results_for_args(args)
        _print_results_context(args)
        sys.stdout.write(format_timing(entries))
        return 0
    if view == "compare":
        selectors = [str(selector) for selector in getattr(args, "selectors", []) if str(selector)]
        if selectors:
            if len(selectors) != 2:
                raise ValueError("comparison requires exactly two selectors")
            entries = _select_results_for_args(args, include_limit=False)
            _print_results_context(args, include_limit=False)
            sys.stdout.write(format_comparison_results(compare_selected_results(entries, selectors[0], selectors[1])))
            return 0
        entries = _select_results_for_args(args)
        _print_results_context(args)
        sys.stdout.write(format_compare_results(compare_results(entries)))
        return 0
    if view == "rescore":
        entries = _select_results_for_args(args)
        _print_results_context(args)
        results = rescore_results(entries, root=args.root, tasks_dir=args.tasks_root)
        sys.stdout.write(format_rescore_report(entries, results, root=args.root))
        return 0
    if view == "delete":
        delete_all = getattr(args, "all", False)
        if not delete_all:
            _require_results_filter(args, "delete")
        entries = _select_results_for_args(args)
        _print_results_context(args)
        if delete_all:
            results_dir = RepoPaths(Path.cwd() if args.root is None else args.root).results_dir
            run_dirs = delete_all_result_dirs(results_dir, confirmed=getattr(args, "yes", False))
            mode = "delete" if getattr(args, "yes", False) else "dry-run"
            action = "DELETE" if getattr(args, "yes", False) else "WOULD DELETE"
            sys.stdout.write("delete\n")
            sys.stdout.write(f"mode        : {mode}\n")
            sys.stdout.write(f"selected    : {len(run_dirs)}\n")
            for run_dir in run_dirs:
                sys.stdout.write(f"{action} {run_dir}\n")
            return 0
        if not getattr(args, "yes", False):
            sys.stdout.write(format_delete_preview(entries, root=args.root, confirmed=False))
            return 0
        delete_results(entries, root=args.root, confirmed=True)
        sys.stdout.write(format_delete_preview(entries, root=args.root, confirmed=True))
        return 0
    raise ValueError(f"unknown results view: {view}")


def cmd_debug(args: argparse.Namespace) -> int:
    run_paths = _resolve_run_paths(args.root, args.run_ref)
    result = _load_result_or_none(run_paths.result_json)
    payload: dict[str, Any] = {
        "run_id": run_paths.run_id,
        "task_id": run_paths.task_id,
        "run_dir": str(run_paths.run_dir),
        "result_json": str(run_paths.result_json),
        "artifacts": {
            "harness": str(run_paths.artifacts_dir / "harness"),
            "evaluator": str(run_paths.artifacts_dir / "evaluator"),
            "pi_rpc": str(run_paths.pi_rpc_dir),
            "orchestra_debug": str(run_paths.orchestra_debug_dir),
        },
    }
    if result is not None:
        payload["result"] = result.to_dict()
    _print_json(payload)
    return 0


def _resolve_selected_run_paths(args: argparse.Namespace, run_ref: str):
    entries = _select_results_for_args(args, include_limit=False)
    entry = _find_report_entry(entries, run_ref)
    if entry is None:
        raise ValueError(f"run not found: {run_ref}")
    return _resolve_run_paths(args.root, f"{entry.run_id}-{entry.task_id}"), entry


def _resolve_public_debug_run_paths(root: Path | str | None, run_ref: str):
    ref = Path(run_ref).stem if str(run_ref).endswith(".json") else Path(run_ref).name
    candidates = RepoPaths(Path.cwd() if root is None else root).list_runs()
    exact = []
    prefix = []
    for run_paths in candidates:
        full_ref = run_paths.run_dir.name
        if ref == full_ref or ref == run_paths.run_id:
            exact.append(run_paths)
        elif full_ref.startswith(ref) or run_paths.run_id.startswith(ref):
            prefix.append(run_paths)
    matches = exact or prefix
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"run reference is ambiguous: {run_ref}")
    raise ValueError(f"run not found: {run_ref}")


def cmd_public_debug(args: argparse.Namespace) -> int:
    run_paths = _resolve_public_debug_run_paths(args.root, args.run_ref)
    view = getattr(args, "debug_view", None) or "orch"
    if view == "raw":
        sys.stdout.write(format_session_raw(run_paths.pi_sessions_dir))
        return 0
    sys.stdout.write(format_session_debug(run_paths.pi_sessions_dir, view=view))
    child_section = format_child_session_section(run_paths)
    if child_section:
        sys.stdout.write(child_section)
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    return runtime_doctor()


def _run_main(raw_args: Sequence[str]) -> int:
    if raw_args and raw_args[0] in {"-h", "--help", "help"}:
        _print_run_help()
        return 0
    return cmd_run(_parse_run_argv(raw_args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench", description="Benchmark CLI")
    subparsers = parser.add_subparsers(dest="command", metavar="{help,start,run,results,04-debug,doctor}")

    help_parser = subparsers.add_parser("help", help="show this help message")
    help_parser.set_defaults(_handler=cmd_help)

    start_parser = subparsers.add_parser(
        "start",
        help="complete benchmark container setup",
        description="Build the image, recreate the container, and sync runtime config.",
    )
    start_parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    start_parser.set_defaults(_handler=cmd_start)

    list_parser = subparsers.add_parser("list", help="list tasks grouped by suite")
    list_parser.add_argument("--tasks-root", type=Path, default=None, help=argparse.SUPPRESS)
    list_parser.add_argument("--batch", default=None)
    list_parser.set_defaults(_handler=cmd_list)

    run_parser = subparsers.add_parser(
        "run", help="prepare and run one task or suite target inside the benchmark container"
    )
    run_parser.add_argument("task_id", nargs="?", metavar="target")
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
    run_parser.add_argument("--tasks-root", type=Path, default=None, help=argparse.SUPPRESS)
    run_parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    run_parser.add_argument("--catalog", type=Path, default=PROJECT_CATALOG_RELPATH)
    run_parser.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    run_parser.add_argument("--role", default=None, help=argparse.SUPPRESS)
    run_parser.add_argument("--notes", default="")
    run_parser.add_argument("--catalog-label", default=None, help=argparse.SUPPRESS)
    run_parser.add_argument("--auto-harness", default=None, help=argparse.SUPPRESS)
    run_parser.add_argument("--auto", action="store_true")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--verbose", action="store_true")
    orchestra_group = run_parser.add_mutually_exclusive_group()
    orchestra_group.add_argument("--orchestra", dest="orchestra", action="store_true")
    orchestra_group.add_argument("--no-orchestra", dest="orchestra", action="store_false")
    run_parser.set_defaults(orchestra=None)
    run_parser.set_defaults(_handler=cmd_run)

    exec_parser = subparsers.add_parser("exec", help=argparse.SUPPRESS)
    exec_parser.add_argument("harness", choices=["pi", "opencode", "hermes"])
    exec_parser.add_argument("argv", nargs=argparse.REMAINDER)
    exec_parser.add_argument("--verbose", action="store_true")
    exec_parser.set_defaults(_handler=cmd_exec)

    grade_parser = subparsers.add_parser("grade", help=argparse.SUPPRESS)
    grade_parser.add_argument("run_ref")
    grade_parser.add_argument("--tasks-root", type=Path, default=None)
    grade_parser.add_argument("--root", type=Path, default=None)
    grade_parser.set_defaults(_handler=cmd_grade)

    suite_parser = subparsers.add_parser("suite", help=argparse.SUPPRESS)
    suite_parser.add_argument("suite", nargs="?")
    suite_parser.add_argument("--tasks-root", type=Path, default=None)
    suite_parser.set_defaults(_handler=cmd_suite)

    results_parser = subparsers.add_parser("results", help="summarize results")
    _add_results_runtime_args(results_parser)
    _add_results_selection_args(results_parser)
    results_parser.set_defaults(results_view="dash")
    results_subparsers = results_parser.add_subparsers(dest="results_view")

    results_dashboard = results_subparsers.add_parser("dash", aliases=("dashboard",), help="show the dashboard")
    _add_results_runtime_args(results_dashboard)
    _add_results_selection_args(results_dashboard)
    results_dashboard.set_defaults(results_view="dash")

    results_runs = results_subparsers.add_parser("runs", help="list runs")
    _add_results_runtime_args(results_runs)
    _add_results_selection_args(results_runs)
    results_runs.set_defaults(results_view="runs")

    results_run = results_subparsers.add_parser("run", help="show one run")
    results_run.add_argument("run_ref")
    _add_results_runtime_args(results_run)
    _add_results_selection_args(results_run, include_limit=False)
    results_run.set_defaults(results_view="run")

    results_tokens = results_subparsers.add_parser("tokens", help="show aggregate token summary")
    _add_results_runtime_args(results_tokens)
    _add_results_selection_args(results_tokens)
    results_tokens.set_defaults(results_view="tokens")

    results_timing = results_subparsers.add_parser("timing", help="show timing summary")
    _add_results_runtime_args(results_timing)
    _add_results_selection_args(results_timing)
    results_timing.set_defaults(results_view="timing")

    results_compare = results_subparsers.add_parser("compare", aliases=("comp",), help="compare filtered results")
    _add_results_runtime_args(results_compare)
    _add_results_selection_args(results_compare)
    results_compare.add_argument("selectors", nargs="*")
    results_compare.set_defaults(results_view="compare")

    results_rescore = results_subparsers.add_parser("rescore", help="regrade filtered results")
    _add_results_runtime_args(results_rescore)
    _add_results_selection_args(results_rescore)
    results_rescore.set_defaults(results_view="rescore")

    results_delete = results_subparsers.add_parser("delete", help="delete filtered results")
    _add_results_runtime_args(results_delete)
    _add_results_selection_args(results_delete)
    results_delete.add_argument("--all", action="store_true", help="allow deleting every run without a filter")
    results_delete.add_argument("--yes", action="store_true")
    results_delete.set_defaults(results_view="delete")

    results_parser.set_defaults(_handler=cmd_results)

    debug_session_parser = subparsers.add_parser("04-debug", help="show a run's Pi session transcript debug")
    debug_session_parser.add_argument("run_ref")
    debug_session_parser.add_argument("debug_view", nargs="?", choices=("orch", "full", "raw"), default="orch")
    debug_session_parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    debug_session_parser.set_defaults(_handler=cmd_public_debug)

    debug_parser = subparsers.add_parser("debug", help=argparse.SUPPRESS)
    debug_parser.add_argument("run_ref")
    debug_parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    debug_parser.set_defaults(_handler=cmd_debug)

    doctor_parser = subparsers.add_parser("doctor", help="check runtime dependencies")
    doctor_parser.set_defaults(_handler=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and raw_argv[0] == "run":
        try:
            return _run_main(raw_argv[1:])
        except Exception as exc:  # pragma: no cover - exercised by CLI smoke on success paths
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if raw_argv and raw_argv[0] == "results" and len(raw_argv) > 1 and raw_argv[1] in {"-h", "--help", "help"}:
        _print_public_results_help()
        return 0
    parser = build_parser()
    args = parser.parse_args(raw_argv)
    if not hasattr(args, "_handler"):
        parser.print_help()
        return 0
    try:
        return int(args._handler(parser, args) if args.command == "help" else args._handler(args))
    except Exception as exc:  # pragma: no cover - exercised by CLI smoke on success paths
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
