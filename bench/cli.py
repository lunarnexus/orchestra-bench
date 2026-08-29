"""Thin benchmark CLI entrypoint and wrappers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from .config import resolve_harness_for_role
from .harnesses.command import CommandHarness
from .paths import RepoPaths
from .reporting import (
    build_debug_report,
    compare_results,
    describe_filters,
    format_compare_results,
    format_dashboard,
    format_debug_report,
    format_delete_preview,
    format_rescore_report,
    format_run_detail,
    format_runs,
    format_timing,
    format_tokens,
    delete_results,
    rescore_results,
    select_results,
)
from .result import TaskResult, load_result
from .runner import grade_run, run_and_grade
from .runtime import (
    container_exec,
    doctor as runtime_doctor,
    load_runtime_config_summary,
    prepare_startup,
)
from .tasks import TaskLoadError, list_suites, list_tasks, load_task


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _print_json(payload: Any) -> None:
    sys.stdout.write(_json_dump(payload))


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


def _task_summary_line(task) -> str:  # type: ignore[no-untyped-def]
    description = task.description or ""
    return f"{task.task_id}\t{task.batch}\t{description}".rstrip()


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


CONTAINER_CATALOG_PATH = Path("/bench/orchestra-config/agent-catalog.yaml")
CONTAINER_TASKS_ROOT = Path("/bench/task-materials-visible")
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
                "usage: scripts/02-run [--verbose] [--auto <task-or-suite>] pi|hermes|opencode <args...>",
                "",
                "Public operator wrapper for harness passthrough and automatic benchmark runs.",
                "",
                "Modes:",
                "  harness passthrough: scripts/02-run pi config",
                "  automatic runs:      scripts/02-run --auto smoke",
                "",
                "Options:",
                "  -h, --help              show this help message and exit",
                "  --auto <task-or-suite>  run and score an automatic task or suite",
                "  --verbose               stream the full session output",
                "",
                "Examples:",
                "  scripts/02-run pi config",
                "  scripts/02-run pi --help",
                "  scripts/02-run hermes --help",
                "  scripts/02-run opencode --version",
                "  scripts/02-run --auto smoke-dependent-setup-chain",
                "  scripts/02-run --auto smoke",
                "  scripts/02-run --verbose",
            ]
        )
    )


def _print_public_results_help() -> None:
    print(
        "\n".join(
            [
                "usage: scripts/03-results [dashboard|runs|run|tokens|timing|debug|compare|rescore|delete]",
                "",
                "Inspect, compare, rescore, and safely delete benchmark results.",
                "",
                "supported views: dashboard, list(runs), detail(run), debug, tokens, timing, compare, rescore, delete-preview, delete-confirmation",
                "",
                "examples:",
                "  scripts/03-results",
                "  scripts/03-results runs",
                "  scripts/03-results run 20250101T010203-alpha-run",
                "  scripts/03-results debug 20250101T010203-alpha-run",
                "  scripts/03-results tokens --task alpha-run",
                "  scripts/03-results timing --suite smoke",
                "  scripts/03-results compare --task alpha-run",
                "  scripts/03-results rescore --task alpha-run",
                "  scripts/03-results delete --task alpha-run  # delete-preview",
                "  scripts/03-results delete --task alpha-run --yes  # delete-confirmation",
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
    if token == "--auto":
        args.auto = True
        index += 1
        if index < len(raw_args) and args.task_id is None:
            args.task_id = raw_args[index]
            return index + 1
        return index
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
        dry_run=False,
        verbose=False,
        orchestra=None,
        task_id=None,
        argv=[],
    )
    index = 0
    while index < len(raw_args):
        token = raw_args[index]
        if token in RUN_PUBLIC_TARGETS and not args.auto and args.task_id is None:
            args.task_id = token
            args.argv = list(raw_args[index + 1 :])
            return args
        if token.startswith("-") or token == "--auto":
            index = _consume_run_option(args, raw_args, index)
            continue
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
    sync_summary = _sync_runtime_config_inside_container()
    completed = container_exec(
        ["python3", "-m", "bench.cli", *_auto_inner_argv(args)],
        workdir=CONTAINER_ROOT,
        env={CONTAINER_CONTEXT_ENV: "1", **_runtime_env_from_summary(sync_summary)},
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
    runtime_snapshot: dict[str, object] | None = None
    request_env = dict(resolved_config.get("env") or {})
    if args.auto:
        runtime_snapshot = load_runtime_config_summary() or None
        request_env.update(_runtime_env_from_summary(runtime_snapshot))
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
        runtime_snapshot=runtime_snapshot,
        model=str(resolved_config.get("model") or ""),
        agent=str(resolved_config.get("agent") or ""),
        profile=str(resolved_config.get("profile") or ""),
        env=request_env,
    )


def cmd_run(args: argparse.Namespace) -> int:
    argv = list(getattr(args, "argv", []))
    if args.auto:
        if not _inside_container():
            return _run_auto_inside_container(args)
    elif args.task_id in RUN_PUBLIC_TARGETS:
        passthrough_args = argparse.Namespace(harness=args.task_id, argv=argv, verbose=getattr(args, "verbose", False))
        return cmd_exec(passthrough_args)
    elif not _inside_container():
        if args.task_id:
            raise ValueError(
                "host-side benchmark runs require --auto; use scripts/02-run --auto <task-or-suite> inside the benchmark container"
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
                payload["harness"] = resolve_harness_for_role(catalog_path, role=args.role)
        _print_json(payload)
        return 0

    result = _run_single_task(args, task)
    if args.auto:
        _print_json(_compact_result_payload(result))
    else:
        _print_json(result.to_dict())
    return 0


def _sync_runtime_config_inside_container() -> dict[str, Any]:
    completed = container_exec(
        ["python3", "-m", "bench.runtime", "init-runtime"],
        workdir=CONTAINER_ROOT,
        env={CONTAINER_CONTEXT_ENV: "1"},
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
    results = [_run_single_task(args, task, catalog=catalog, resolved=resolved) for task in resolved_tasks]
    summary = _suite_summary_payload(suite_name, results)
    _print_json(summary)
    return int(summary["return_code"])


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
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--tasks-root", type=Path, default=None)


def _add_results_selection_args(parser: argparse.ArgumentParser, *, include_limit: bool = True) -> None:
    parser.add_argument("--task", default=None)
    parser.add_argument("--suite", default=None)
    parser.add_argument("--model", default=None)
    orchestra_group = parser.add_mutually_exclusive_group()
    orchestra_group.add_argument("--orchestra", dest="orchestra", action="store_true")
    orchestra_group.add_argument("--no-orchestra", dest="orchestra", action="store_false")
    parser.set_defaults(orchestra=None)
    parser.add_argument("--sort", default="finished_at")
    parser.add_argument("--ascending", action="store_true")
    if include_limit:
        parser.add_argument("--limit", type=int, default=None)


def _results_sort_reverse(args: argparse.Namespace) -> bool:
    return not getattr(args, "ascending", False)


def _select_results_for_args(args: argparse.Namespace, *, include_limit: bool = True):
    return select_results(
        args.root,
        tasks_dir=getattr(args, "tasks_root", None),
        task=getattr(args, "task", None),
        suite=getattr(args, "suite", None),
        model=getattr(args, "model", None),
        orchestra=getattr(args, "orchestra", None),
        sort=getattr(args, "sort", "finished_at"),
        reverse=_results_sort_reverse(args),
        limit=getattr(args, "limit", None) if include_limit else None,
    )


def _results_context_line(args: argparse.Namespace, *, include_limit: bool = True) -> str | None:
    limit = getattr(args, "limit", None) if include_limit else None
    sort = getattr(args, "sort", "finished_at")
    reverse = _results_sort_reverse(args)
    context = describe_filters(
        task=getattr(args, "task", None),
        suite=getattr(args, "suite", None),
        model=getattr(args, "model", None),
        orchestra=getattr(args, "orchestra", None),
        sort=sort,
        reverse=reverse,
        limit=limit,
    )
    if (
        getattr(args, "task", None) is None
        and getattr(args, "suite", None) is None
        and getattr(args, "model", None) is None
        and getattr(args, "orchestra", None) is None
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
    if all(getattr(args, name, None) is None for name in ("task", "suite", "model", "orchestra")):
        raise ValueError(f"{action} requires at least one filter")


def _find_report_entry(entries, run_ref: str):  # type: ignore[no-untyped-def]
    run_id, task_id = _run_ref_parts(run_ref)
    for entry in entries:
        if entry.run_id == run_id and entry.task_id == task_id:
            return entry
    return None


def cmd_results(args: argparse.Namespace) -> int:
    view = getattr(args, "results_view", None) or "dashboard"
    if view == "dashboard":
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
            raise ValueError(f"run not found: {args.run_ref}")
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
    if view == "debug":
        entries = _select_results_for_args(args, include_limit=False)
        entry = _find_report_entry(entries, args.run_ref)
        if entry is None:
            raise ValueError(f"run not found: {args.run_ref}")
        run_paths = _resolve_run_paths(args.root, args.run_ref)
        report = build_debug_report(run_paths, entry=entry)
        _print_results_context(args, include_limit=False)
        sys.stdout.write(format_debug_report(report))
        return 0
    if view == "compare":
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
        _require_results_filter(args, "delete")
        entries = _select_results_for_args(args)
        _print_results_context(args)
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


def cmd_doctor(_args: argparse.Namespace) -> int:
    return runtime_doctor()


def _run_main(raw_args: Sequence[str]) -> int:
    if raw_args and raw_args[0] in {"-h", "--help", "help"}:
        _print_run_help()
        return 0
    return cmd_run(_parse_run_argv(raw_args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench", description="Benchmark CLI")
    subparsers = parser.add_subparsers(dest="command", metavar="{help,start,run,results,debug,doctor}")

    help_parser = subparsers.add_parser("help", help="show this help message")
    help_parser.set_defaults(_handler=cmd_help)

    start_parser = subparsers.add_parser(
        "start",
        help="complete benchmark container setup",
        description="Build the image, recreate the container, and sync runtime config.",
    )
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
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
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
    _add_results_runtime_args(results_parser)
    _add_results_selection_args(results_parser)
    results_subparsers = results_parser.add_subparsers(dest="results_view")

    results_dashboard = results_subparsers.add_parser("dashboard", help="show the result dashboard")
    _add_results_runtime_args(results_dashboard)
    _add_results_selection_args(results_dashboard)
    results_dashboard.set_defaults(results_view="dashboard")

    results_runs = results_subparsers.add_parser("runs", help="list runs")
    _add_results_runtime_args(results_runs)
    _add_results_selection_args(results_runs)
    results_runs.set_defaults(results_view="runs")

    results_run = results_subparsers.add_parser("run", help="show one run")
    results_run.add_argument("run_ref")
    _add_results_runtime_args(results_run)
    _add_results_selection_args(results_run, include_limit=False)
    results_run.set_defaults(results_view="run")

    results_tokens = results_subparsers.add_parser("tokens", help="show token summary")
    _add_results_runtime_args(results_tokens)
    _add_results_selection_args(results_tokens)
    results_tokens.set_defaults(results_view="tokens")

    results_timing = results_subparsers.add_parser("timing", help="show timing summary")
    _add_results_runtime_args(results_timing)
    _add_results_selection_args(results_timing)
    results_timing.set_defaults(results_view="timing")

    results_debug = results_subparsers.add_parser("debug", help="show a debug artifact summary")
    results_debug.add_argument("run_ref")
    _add_results_runtime_args(results_debug)
    _add_results_selection_args(results_debug, include_limit=False)
    results_debug.set_defaults(results_view="debug")

    results_compare = results_subparsers.add_parser("compare", help="compare filtered results")
    _add_results_runtime_args(results_compare)
    _add_results_selection_args(results_compare)
    results_compare.set_defaults(results_view="compare")

    results_rescore = results_subparsers.add_parser("rescore", help="regrade filtered results")
    _add_results_runtime_args(results_rescore)
    _add_results_selection_args(results_rescore)
    results_rescore.set_defaults(results_view="rescore")

    results_delete = results_subparsers.add_parser("delete", help="delete filtered results")
    _add_results_runtime_args(results_delete)
    _add_results_selection_args(results_delete)
    results_delete.add_argument("--yes", action="store_true")
    results_delete.set_defaults(results_view="delete")

    results_parser.set_defaults(_handler=cmd_results)

    debug_parser = subparsers.add_parser("debug", help="show run debug details")
    debug_parser.add_argument("run_ref")
    debug_parser.add_argument("--root", type=Path, default=None)
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
