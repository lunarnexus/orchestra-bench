from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import pytest

from bench.result import (
    EvaluationResult,
    HarnessResult,
    RunMeta,
    TaskResult,
    load_result,
    write_json_atomic,
)


def _result(run_id: str = "20250101T010203", task_id: str = "task-one") -> TaskResult:
    return TaskResult(
        run_meta=RunMeta(run_id=run_id, task_id=task_id, batch="smoke", started_at="2025-01-01T01:02:03Z"),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "pi-rpc"}),
        evaluation=EvaluationResult(
            status="ok",
            score="pass",
            checks={"done": True},
            details={"grader": "evaluate/run.sh"},
        ),
        outcome="pass",
        details={"notes": "ready"},
    )


def test_result_round_trip(tmp_path: Path) -> None:
    result = _result()
    path = tmp_path / "results" / "20250101T010203-task-one" / "result.json"

    written = write_json_atomic(path, result)
    loaded = load_result(written)

    assert written == path
    assert loaded == result
    assert asdict(loaded) == asdict(result)


def test_atomic_write_preserves_existing_result_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "result.json"
    original = _result(task_id="task-old")
    replacement = _result(task_id="task-new")

    write_json_atomic(path, original)

    def boom(src: os.PathLike[str] | str, dst: os.PathLike[str] | str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        write_json_atomic(path, replacement)

    assert load_result(path) == original


def test_result_schema_distinguishes_harness_failure_evaluator_failure_and_task_outcome() -> None:
    harness_failed = TaskResult(
        run_meta=RunMeta(run_id="run-1", task_id="task-1"),
        harness=HarnessResult(status="lifecycle_failed", exit_code=137, error="pi exited"),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    evaluator_failed = TaskResult(
        run_meta=RunMeta(run_id="run-2", task_id="task-2"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="failed", error="grader crashed"),
        outcome="not_run",
    )
    task_failed = TaskResult(
        run_meta=RunMeta(run_id="run-3", task_id="task-3"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="fail", checks={"check": False}),
        outcome="fail",
    )

    assert harness_failed.harness.status == "lifecycle_failed"
    assert harness_failed.evaluation.status == "not_run"
    assert harness_failed.outcome == "not_run"

    assert evaluator_failed.harness.status == "ok"
    assert evaluator_failed.evaluation.status == "failed"
    assert evaluator_failed.outcome == "not_run"

    assert task_failed.harness.status == "ok"
    assert task_failed.evaluation.status == "ok"
    assert task_failed.evaluation.score == "fail"
    assert task_failed.outcome == "fail"


def test_write_json_atomic_keeps_run_outputs_readable_by_operators(tmp_path: Path) -> None:
    """Run results are written on shared mounts by the container (root); host operators must read them."""
    path = tmp_path / "results" / "20250101T010203-task-one" / "result.json"

    write_json_atomic(path, _result())

    assert path.stat().st_mode & 0o777 == 0o644
