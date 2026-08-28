"""Thin benchmark CLI entrypoint and wrappers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import resolve_harness_for_role
from .harnesses.command import CommandHarness
from .paths import RepoPaths
from .reporting import (
    build_debug_report,
    collect_results,
    format_dashboard,
    format_debug_report,
    format_run_detail,
    format_runs,
    format_timing,
    format_tokens,
)
from .result import TaskResult, load_result
from .runner import grade_run, run_and_grade
from .runtime import (
    RuntimeEnvironment,
    build_image,
    container_exec,
    doctor as runtime_doctor,
    init_runtime as runtime_init,
    recreate_container,
    start_container,
)
from .tasks import TaskLoadError, list_suites, list_tasks, load_task


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _print_json(payload: Any) -> None:
    sys.stdout.write(_json_dump(payload))


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


def _task_summary_line(task) -> str:  # type: ignore[no-untyped-def]
    description = task.description or ""
    return f"{task.task_id}\t{task.batch}\t{description}".rstrip()


def _result_summary_line(run_paths) -> str:  # type: ignore[no-untyped-def]
    result = _load_result_or_none(run_paths.result_json)
    if result is None:
        return f"{run_paths.run_id}\t{run_paths.task_id}\tpending"
    return f"{run_paths.run_id}\t{run_paths.task_id}\t{result.outcome}\t{result.evaluation.status}"


START_ACTIONS = ("build", "start", "recreate", "init")
CONTAINER_CATALOG_PATH = Path("/bench/orchestra-config/agent-catalog.yaml")
CONTAINER_TASKS_ROOT = Path("/bench/task-materials-visible")
CONTAINER_ROOT = Path("/bench")
CONTAINER_CONTEXT_ENV = "BENCH_IN_CONTAINER"
LEGACY_CONTAINER_CONTEXT_ENV = "BENCH_RUN_CONTEXT"


def _inside_container() -> bool:
    return os.environ.get(CONTAINER_CONTEXT_ENV) in {"1", "true", "yes"} or os.environ.get(
        LEGACY_CONTAINER_CONTEXT_ENV
    ) == "container"


PROJECT_CATALOG_RELPATH = Path("config") / "orchestra" / "agent-catalog.yaml"


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


def cmd_start(args: argparse.Namespace) -> int:
    if args.start_action == "build":
        _print_json(build_image(root=args.root or Path.cwd()))
    elif args.start_action == "start":
        _print_json(start_container(root=args.root or Path.cwd()))
    elif args.start_action == "recreate":
        _print_json(recreate_container(root=args.root or Path.cwd()))
    else:
        # init — configure the live Pi/Orchestra runtime (container-side paths)
        _print_json(runtime_init(RuntimeEnvironment.from_env()))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    tasks = list_tasks(args.tasks_root)
    for task in tasks:
        if args.batch and task.batch != args.batch:
            continue
        print(_task_summary_line(task))
    return 0


def _resolve_catalog_and_harness(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    catalog = Path(args.catalog)
    resolved = resolve_harness_for_role(catalog, role=args.role)
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
    completed = container_exec(
        ["python3", "-m", "bench.cli", *_auto_inner_argv(args)],
        workdir=CONTAINER_ROOT,
        env={CONTAINER_CONTEXT_ENV: "1"},
        verbose=getattr(args, "verbose", False),
    )
    if not getattr(args, "verbose", False):
        _emit_completed_process(completed)
    return completed.returncode


def _run_single_task(
    args: argparse.Namespace,
    task,
    *,
    catalog: Path | None = None,
    resolved: dict[str, object] | None = None,
) -> TaskResult:
    catalog_path, resolved_config = (
        (catalog, resolved) if catalog is not None and resolved is not None else _resolve_catalog_and_harness(args)
    )
    harness = CommandHarness.from_resolved_config(resolved_config)
    return run_and_grade(
        task,
        harness,
        root=args.root,
        run_id=args.run_id,
        catalog_path=catalog_path,
        role=args.role,
        orchestra=args.orchestra,
        auto=args.auto,
        notes=args.notes,
        catalog_label=args.catalog_label,
        model=str(resolved_config.get("model") or ""),
        agent=str(resolved_config.get("agent") or ""),
        profile=str(resolved_config.get("profile") or ""),
        env=dict(resolved_config.get("env") or {}),
    )


def cmd_run(args: argparse.Namespace) -> int:
    if not _inside_container():
        if args.auto:
            return _run_auto_inside_container(args)
        if args.task_id:
            raise ValueError(
                "host-side benchmark runs require --auto; use scripts/02-run --auto <task-or-suite> inside the benchmark container"
            )
    if not args.task_id:
        raise ValueError("a task or suite target is required")
    try:
        task = load_task(args.task_id, args.tasks_root)
    except TaskLoadError:
        return cmd_run_suite(args)
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
                payload["harness"] = resolve_harness_for_role(catalog_path, role=args.role)
        _print_json(payload)
        return 0

    result = _run_single_task(args, task)
    _print_json(result.to_dict())
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    completed = container_exec(
        [args.harness, *args.argv],
        workdir=CONTAINER_ROOT,
        env={CONTAINER_CONTEXT_ENV: "1"},
        verbose=getattr(args, "verbose", False),
    )
    if not getattr(args, "verbose", False):
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


def cmd_run_suite(args: argparse.Namespace) -> int:
    suite_name = str(args.task_id)
    tasks = [task for task in list_tasks(args.tasks_root) if task.batch == suite_name]
    if not tasks:
        raise ValueError(f"unknown target (not a known task or suite): {suite_name}")
    if args.dry_run:
        payload: dict[str, Any] = {
            "suite": suite_name,
            "task_count": len(tasks),
            "tasks": [_task_payload(task) for task in tasks],
            "dry_run": True,
        }
        _print_json(payload)
        return 0

    catalog, resolved = _resolve_catalog_and_harness(args)
    results = [_run_single_task(args, task, catalog=catalog, resolved=resolved).to_dict() for task in tasks]
    _print_json({"suite": suite_name, "task_count": len(tasks), "results": results})
    return 0


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


def _find_report_entry(entries, run_ref: str):  # type: ignore[no-untyped-def]
    run_id, task_id = _run_ref_parts(run_ref)
    for entry in entries:
        if entry.run_id == run_id and entry.task_id == task_id:
            return entry
    return None


def cmd_results(args: argparse.Namespace) -> int:
    entries = collect_results(args.root, tasks_dir=getattr(args, "tasks_root", None))
    view = getattr(args, "results_view", None) or "dashboard"
    if view == "dashboard":
        sys.stdout.write(format_dashboard(entries))
        return 0
    if view == "runs":
        sys.stdout.write(format_runs(entries))
        return 0
    if view == "run":
        entry = _find_report_entry(entries, args.run_ref)
        if entry is None:
            raise ValueError(f"run not found: {args.run_ref}")
        sys.stdout.write(format_run_detail(entry))
        return 0
    if view == "tokens":
        sys.stdout.write(format_tokens(entries))
        return 0
    if view == "timing":
        sys.stdout.write(format_timing(entries))
        return 0
    if view == "debug":
        entry = _find_report_entry(entries, args.run_ref)
        run_paths = _resolve_run_paths(args.root, args.run_ref)
        report = build_debug_report(run_paths, entry=entry)
        sys.stdout.write(format_debug_report(report))
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


def cmd_doctor(_args: argparse.Namespace) -> int:
    return runtime_doctor()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench", description="Benchmark CLI")
    subparsers = parser.add_subparsers(dest="command", metavar="{help,start,run,results,debug,doctor}")

    help_parser = subparsers.add_parser("help", help="show this help message")
    help_parser.set_defaults(_handler=cmd_help)

    start_parser = subparsers.add_parser(
        "start",
        help="build/start/recreate benchmark container or configure the live runtime",
        description=(
            "Actions: build — docker image; start — reuse/start/create long-lived container; "
            "recreate — replace the container; init — in-container Pi/Orchestra config sync."
        ),
    )
    start_parser.add_argument("start_action", choices=list(START_ACTIONS), metavar="{build,start,recreate,init}")
    start_parser.add_argument("--root", type=Path, default=None)
    start_parser.set_defaults(_handler=cmd_start)

    list_parser = subparsers.add_parser("list", help="list tasks")
    list_parser.add_argument("--tasks-root", type=Path, default=None)
    list_parser.add_argument("--batch", default=None)
    list_parser.set_defaults(_handler=cmd_list)

    run_parser = subparsers.add_parser(
        "run", help="prepare and run one task or suite target inside the benchmark container"
    )
    run_parser.add_argument("task_id", nargs="?", metavar="target")
    run_parser.add_argument("--tasks-root", type=Path, default=None)
    run_parser.add_argument("--root", type=Path, default=None)
    run_parser.add_argument("--catalog", type=Path, default=PROJECT_CATALOG_RELPATH)
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--role", default=None)
    run_parser.add_argument("--notes", default="")
    run_parser.add_argument("--catalog-label", default=None)
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
    results_parser.add_argument("--root", type=Path, default=None)
    results_parser.add_argument("--tasks-root", type=Path, default=None)
    results_subparsers = results_parser.add_subparsers(dest="results_view")

    results_dashboard = results_subparsers.add_parser("dashboard", help="show the result dashboard")
    results_dashboard.set_defaults(results_view="dashboard")

    results_runs = results_subparsers.add_parser("runs", help="list runs")
    results_runs.set_defaults(results_view="runs")

    results_run = results_subparsers.add_parser("run", help="show one run")
    results_run.add_argument("run_ref")
    results_run.set_defaults(results_view="run")

    results_tokens = results_subparsers.add_parser("tokens", help="show token summary")
    results_tokens.set_defaults(results_view="tokens")

    results_timing = results_subparsers.add_parser("timing", help="show timing summary")
    results_timing.set_defaults(results_view="timing")

    results_debug = results_subparsers.add_parser("debug", help="show a debug artifact summary")
    results_debug.add_argument("run_ref")
    results_debug.set_defaults(results_view="debug")

    results_parser.set_defaults(_handler=cmd_results)

    debug_parser = subparsers.add_parser("debug", help="show run debug details")
    debug_parser.add_argument("run_ref")
    debug_parser.add_argument("--root", type=Path, default=None)
    debug_parser.set_defaults(_handler=cmd_debug)

    doctor_parser = subparsers.add_parser("doctor", help="check runtime dependencies")
    doctor_parser.set_defaults(_handler=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
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
