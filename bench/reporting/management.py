"""Mutable result-management helpers for the public results CLI."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from bench.paths import RepoPaths
from bench.result import TaskResult, load_result, write_json_atomic
import bench.runner as runner_module
from bench.tasks import load_task

from .queries import ReportEntry, collect_results, filter_results, sort_results


@dataclass(frozen=True)
class ComparisonGroup:
    suite: str
    model: str
    orchestra: str
    runs: int
    passed: int
    failed: int
    total_tokens: int | float | None = None
    avg_tokens: float | None = None
    total_elapsed_seconds: float | None = None
    avg_elapsed_seconds: float | None = None


def _fmt_number(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _display_run_dir(entry: ReportEntry, root: Path | str | None = None) -> str:
    run_dir = entry.path.parent
    if root is not None:
        try:
            return str(run_dir.relative_to(Path(root)))
        except ValueError:
            pass
    return str(run_dir)


def describe_filters(
    *,
    task: str | None = None,
    suite: str | None = None,
    model: str | None = None,
    orchestra: bool | None = None,
    sort: str | None = None,
    reverse: bool | None = None,
    limit: int | None = None,
) -> str:
    parts: list[str] = []
    if task is not None:
        parts.append(f"task={task}")
    if suite is not None:
        parts.append(f"suite={suite}")
    if model is not None:
        parts.append(f"model={model}")
    if orchestra is not None:
        parts.append(f"orchestra={_fmt_bool(orchestra)}")
    if sort is not None:
        order = "desc" if reverse is not False else "asc"
        parts.append(f"sort={sort} {order}")
    if limit is not None:
        parts.append(f"limit={limit}")
    return ", ".join(parts) if parts else "all results"


def select_results(
    results_dir: Path | str | None = None,
    *,
    tasks_dir: Path | str | None = None,
    task: str | None = None,
    suite: str | None = None,
    model: str | None = None,
    orchestra: bool | None = None,
    sort: str = "finished_at",
    reverse: bool = True,
    limit: int | None = None,
) -> list[ReportEntry]:
    entries = collect_results(results_dir, tasks_dir=tasks_dir)
    entries = filter_results(entries, task=task, suite=suite, model=model, orchestra=orchestra)
    entries = sort_results(entries, key=sort, reverse=reverse)
    if limit is not None:
        if limit <= 0:
            return []
        entries = entries[:limit]
    return entries


def compare_results(entries: Iterable[ReportEntry]) -> dict[str, Any]:
    rows = list(entries)
    grouped: dict[tuple[str, str, str], list[ReportEntry]] = {}
    for entry in rows:
        key = (entry.batch or "unlabeled", entry.model or "n/a", _fmt_bool(entry.orchestra))
        grouped.setdefault(key, []).append(entry)

    groups: list[ComparisonGroup] = []
    for (suite, model, orchestra), group_rows in sorted(grouped.items()):
        tokens = [float(row.total_tokens) for row in group_rows if row.total_tokens is not None]
        elapsed = [float(row.elapsed_seconds) for row in group_rows if row.elapsed_seconds is not None]
        groups.append(
            ComparisonGroup(
                suite=suite,
                model=model,
                orchestra=orchestra,
                runs=len(group_rows),
                passed=sum(1 for row in group_rows if row.outcome == "pass"),
                failed=sum(1 for row in group_rows if row.outcome != "pass"),
                total_tokens=sum(tokens) if tokens else None,
                avg_tokens=(sum(tokens) / len(tokens)) if tokens else None,
                total_elapsed_seconds=sum(elapsed) if elapsed else None,
                avg_elapsed_seconds=(sum(elapsed) / len(elapsed)) if elapsed else None,
            )
        )

    passed = sum(1 for row in rows if row.outcome == "pass")
    failed = len(rows) - passed
    return {
        "runs": len(rows),
        "passed": passed,
        "failed": failed,
        "groups": [
            {
                "suite": group.suite,
                "model": group.model,
                "orchestra": group.orchestra,
                "runs": group.runs,
                "passed": group.passed,
                "failed": group.failed,
                "total_tokens": group.total_tokens,
                "avg_tokens": group.avg_tokens,
                "total_elapsed_seconds": group.total_elapsed_seconds,
                "avg_elapsed_seconds": group.avg_elapsed_seconds,
            }
            for group in groups
        ],
    }


def format_compare_results(summary: dict[str, Any]) -> str:
    body = [
        "compare",
        f"runs: {_fmt_number(summary.get('runs'))}",
        f"passed: {_fmt_number(summary.get('passed'))}",
        f"failed: {_fmt_number(summary.get('failed'))}",
    ]
    groups = summary.get("groups")
    if isinstance(groups, list) and groups:
        body.append("groups:")
        for group in groups:
            if not isinstance(group, dict):
                continue
            body.append(
                "- "
                + " ".join(
                    [
                        f"suite={group.get('suite') or 'unlabeled'}",
                        f"model={group.get('model') or 'n/a'}",
                        f"orchestra={group.get('orchestra') or 'n/a'}",
                        f"runs={_fmt_number(group.get('runs'))}",
                        f"pass={_fmt_number(group.get('passed'))}",
                        f"fail={_fmt_number(group.get('failed'))}",
                        f"tokens={_fmt_number(group.get('total_tokens'))}",
                        f"avg_tokens={_fmt_number(group.get('avg_tokens'))}",
                        f"elapsed_seconds={_fmt_number(group.get('total_elapsed_seconds'))}",
                        f"avg_elapsed_seconds={_fmt_number(group.get('avg_elapsed_seconds'))}",
                    ]
                )
            )
    return "\n".join(body) + "\n"


def format_delete_preview(entries: Sequence[ReportEntry], *, root: Path | str | None = None, confirmed: bool = False) -> str:
    action = "DELETE" if confirmed else "WOULD DELETE"
    mode = "delete" if confirmed else "dry-run"
    body = [
        "delete",
        f"mode        : {mode}",
        f"selected    : {len(entries)}",
    ]
    for entry in entries:
        body.append(f"{action} {_display_run_dir(entry, root=root)}")
    return "\n".join(body) + "\n"


def format_rescore_report(entries: Sequence[ReportEntry], results: Sequence[TaskResult], *, root: Path | str | None = None) -> str:
    body = ["rescore", f"selected    : {len(entries)}"]
    for entry, result in zip(entries, results, strict=False):
        body.append(
            "- "
            + " ".join(
                [
                    _display_run_dir(entry, root=root),
                    f"outcome={result.outcome or 'n/a'}",
                    f"evaluation={result.evaluation.status or 'n/a'}",
                    f"score={entry.score_display or 'n/a'}",
                ]
            )
        )
    return "\n".join(body) + "\n"


def _make_deletable(path: Path) -> None:
    """Best-effort permission repair so the host user can unlink container-written trees."""

    def _open_up(target: Path, write_bits: int) -> None:
        try:
            mode = stat.S_IMODE(target.lstat().st_mode)
            if (mode & write_bits) != write_bits:
                os.chmod(target, mode | write_bits)
        except OSError:
            pass

    for current, dirnames, filenames in os.walk(path, topdown=False):
        base = Path(current)
        for name in [*dirnames, *filenames]:
            _open_up(base / name, 0o300 if (base / name).is_dir() else 0o200)
    _open_up(path, 0o300)


def _rmtree_with_chmod(run_dir: Path) -> None:
    def _onerror(func, path, exc_info):  # type: ignore[no-untyped-def]
        target = Path(path)
        try:
            mode = stat.S_IMODE(target.lstat().st_mode)
            os.chmod(target, mode | (0o300 if target.is_dir() else 0o200))
            parent = target.parent
            parent_mode = stat.S_IMODE(parent.lstat().st_mode)
            os.chmod(parent, parent_mode | 0o300)
        except OSError:
            raise exc_info[1]
        func(path)

    shutil.rmtree(run_dir, onerror=_onerror)


def _delete_run_dir_via_container(run_dir: Path) -> None:
    """Delete through the benchmark container (root) when host permissions are not enough."""
    if run_dir.parent.name != "results":
        raise RuntimeError(
            f"cannot delete {run_dir}: files are owned by another user and this results dir is not the mounted /bench/results path"
        )
    from bench.runtime import container_exec

    command = [
        "python3",
        "-c",
        "import shutil, sys; shutil.rmtree(sys.argv[1])",
        f"/bench/results/{run_dir.name}",
    ]
    completed = container_exec(command, workdir="/bench", verbose=False)
    if completed.returncode != 0:
        stderr = (getattr(completed, "stderr", None) or "").strip()
        detail = f" ({stderr})" if stderr else ""
        raise RuntimeError(f"container-side delete failed for {run_dir.name}{detail}")


def _delete_run_dir(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    if not run_dir.exists():
        return
    _make_deletable(run_dir)
    try:
        _rmtree_with_chmod(run_dir)
    except (PermissionError, OSError):
        _delete_run_dir_via_container(run_dir)
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RuntimeError(f"could not fully delete {run_dir}; re-run with more permission or fix ownership")


def delete_results(entries: Sequence[ReportEntry], *, root: Path | str | None = None, confirmed: bool = False) -> list[Path]:
    deleted: list[Path] = []
    for entry in entries:
        run_dir = entry.path.parent
        deleted.append(run_dir)
        if confirmed:
            _delete_run_dir(run_dir)
    return deleted


def delete_all_result_dirs(results_dir: Path | str, *, confirmed: bool = False) -> list[Path]:
    base = Path(results_dir)
    if not base.is_dir():
        return []
    run_dirs = sorted(path for path in base.iterdir() if path.is_dir())
    if confirmed:
        for run_dir in run_dirs:
            _delete_run_dir(run_dir)
    return run_dirs


def rescore_results(
    entries: Sequence[ReportEntry],
    *,
    root: Path | str | None = None,
    tasks_dir: Path | str | None = None,
) -> list[TaskResult]:
    repo_root = Path(root) if root is not None else Path.cwd()
    resolved_tasks_dir = Path(tasks_dir) if tasks_dir is not None else repo_root / "tasks"
    results: list[TaskResult] = []
    for entry in entries:
        run_paths = RepoPaths(repo_root).run(entry.run_id, entry.task_id)
        task = load_task(entry.task_id, tasks_root=resolved_tasks_dir)
        prior_result = load_result(entry.path)
        # Resolve at call time so a test that patches bench.runner.grade_run cannot leak a stale binding here.
        rescored = runner_module.grade_run(task, run_paths, prior_result=prior_result)
        if rescored.evaluation.status != "ok":
            write_json_atomic(entry.path, prior_result)
            results.append(prior_result)
        else:
            results.append(rescored)
    return results


__all__ = [
    "ComparisonGroup",
    "compare_results",
    "delete_results",
    "describe_filters",
    "format_compare_results",
    "format_delete_preview",
    "format_rescore_report",
    "rescore_results",
    "select_results",
]
