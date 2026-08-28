from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, write_json_atomic


def _write_task(task_root: Path, task_id: str, *, batch: str = "smoke") -> None:
    task_dir = task_root / task_id
    (task_dir / "evaluate").mkdir(parents=True, exist_ok=True)
    (task_dir / "PRD.md").write_text("prd\n", encoding="utf-8")
    (task_dir / "Prompt.md").write_text("prompt\n", encoding="utf-8")
    (task_dir / "evaluate" / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "\n".join(
            [
                f"task_id: {task_id}",
                "description: synthetic task",
                "family: synthetic",
                f"batch: {batch}",
                "scoring_type: pass_fail",
                "timeout_minutes: 10",
                "evaluator: evaluate/run.sh",
                "split: dev",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_result(
    results_root: Path,
    run_id: str,
    task_id: str,
    *,
    batch: str = "",
    model: str = "",
    orchestra: bool | None = None,
    started_at: str = "2025-01-01T00:00:00Z",
    finished_at: str = "2025-01-01T00:10:00Z",
    total_tokens: int | None = None,
    elapsed_seconds: float | None = None,
) -> Path:
    result = TaskResult(
        run_meta=RunMeta(run_id=run_id, task_id=task_id, batch=batch, started_at=started_at, finished_at=finished_at),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass"),
        outcome="pass",
        details={
            "provenance": {"model": model, "orchestra": orchestra},
            "tokens": {"total": total_tokens} if total_tokens is not None else {},
            "timing": {"elapsed_seconds": elapsed_seconds} if elapsed_seconds is not None else {},
        },
    )
    path = results_root / f"{run_id}-{task_id}" / "result.json"
    return write_json_atomic(path, result)


@pytest.fixture()
def reporting_data(tmp_path: Path) -> Path:
    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    _write_task(tasks_root, "task-b", batch="capability-easy")
    _write_result(
        results_root,
        "20250101T010101",
        "task-a",
        batch="",
        model="model-a",
        orchestra=True,
        finished_at="2025-01-01T00:20:00Z",
        total_tokens=120,
        elapsed_seconds=12.5,
    )
    _write_result(
        results_root,
        "20250101T010102",
        "task-b",
        batch="",
        model="model-b",
        orchestra=False,
        finished_at="2025-01-01T00:10:00Z",
        total_tokens=240,
        elapsed_seconds=24.0,
    )
    _write_result(
        results_root,
        "20250101T010103",
        "task-a",
        batch="",
        model="model-a",
        orchestra=True,
        finished_at="2025-01-01T00:30:00Z",
        total_tokens=90,
        elapsed_seconds=9.0,
    )
    return tmp_path


def test_collect_results_filters_sorts_and_uses_task_metadata(reporting_data: Path) -> None:
    from bench.reporting.queries import collect_results, filter_results

    entries = collect_results(reporting_data / "results", tasks_dir=reporting_data / "tasks")

    assert [entry.run_id for entry in entries] == ["20250101T010103", "20250101T010101", "20250101T010102"]
    assert [entry.batch for entry in entries] == ["smoke", "smoke", "capability-easy"]
    assert [entry.model for entry in entries] == ["model-a", "model-a", "model-b"]
    assert [entry.orchestra for entry in entries] == [True, True, False]

    assert [entry.task_id for entry in filter_results(entries, task="task-a")] == ["task-a", "task-a"]
    assert [entry.batch for entry in filter_results(entries, suite="smoke")] == ["smoke", "smoke"]
    assert [entry.run_id for entry in filter_results(entries, model="model-b")] == ["20250101T010102"]
    assert [entry.run_id for entry in filter_results(entries, orchestra=True)] == ["20250101T010103", "20250101T010101"]


def test_reporting_formatters_render_dashboard_runs_detail_tokens_and_timing(reporting_data: Path) -> None:
    from bench.reporting.formatters import (
        format_dashboard,
        format_run_detail,
        format_runs,
        format_timing,
        format_tokens,
    )
    from bench.reporting.queries import collect_results

    entries = collect_results(reporting_data / "results", tasks_dir=reporting_data / "tasks")

    dashboard = format_dashboard(entries)
    runs = format_runs(entries)
    detail = format_run_detail(entries[0])
    tokens = format_tokens(entries)
    timing = format_timing(entries)

    assert "dashboard" in dashboard
    assert "smoke" in dashboard
    assert "runs: 3" in dashboard

    assert "20250101T010103" in runs
    assert "model-b" in runs

    assert "task-a" in detail
    assert "tokens" in detail
    assert "elapsed" in detail

    assert "total_tokens" in tokens
    assert "240" in tokens

    assert "timing" in timing
    assert "12.5" in timing


def test_collect_results_defaults_to_cwd_results_not_v1(tmp_path: Path, monkeypatch) -> None:
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-c", batch="smoke")
    _write_result(results_root, "20250101T010104", "task-c", batch="", model="model-c", orchestra=True)

    monkeypatch.chdir(tmp_path)

    entries = collect_results(tasks_dir=tasks_root)

    assert [entry.run_id for entry in entries] == ["20250101T010104"]
    assert entries[0].path == results_root / "20250101T010104-task-c" / "result.json"


def test_collect_results_ignores_missing_results(tmp_path: Path) -> None:
    from bench.reporting.queries import collect_results

    assert collect_results(tmp_path / "results") == []
