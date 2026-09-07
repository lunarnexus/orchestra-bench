from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from bench.result import (
    EvaluationResult,
    HarnessResult,
    ResultSchemaError,
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
            score="95/100",
            checks={"done": True},
            details={"grader": "evaluate/run.sh"},
        ),
        outcome="pass",
        score_numeric=95.0,
        score_display="95/100",
        task_meta={"task_id": task_id, "family": "smoke", "batch": "smoke", "scoring_type": "numeric"},
        category_scores={
            "functionality": {"score_numeric": 40.0, "score_display": "40/40"},
            "orchestration": {"score_numeric": 35.0, "score_display": "35/35"},
            "efficiency": {"score_numeric": 10.0, "score_display": "10/10"},
            "reliability": {"score_numeric": 10.0, "score_display": "10/15"},
        },
        tokens={"total": 1234, "parent": 234, "children": 1000},
        context={"parent": {"final": 123, "max": 456}, "children": {"final": 100, "max": 400}},
        orchestra={"dispatches": 2, "returns": 2},
        reliability={"evidence": "good"},
        details={"notes": "ready", "orchestra_metrics": {"dispatch": {"attempts": 2, "accepted": 2}}},
    )


def test_result_round_trip(tmp_path: Path) -> None:
    result = _result()
    path = tmp_path / "results" / "20250101T010203-task-one" / "result.json"

    written = write_json_atomic(path, result)
    loaded = load_result(written)

    assert written == path
    assert loaded == result
    assert asdict(loaded) == asdict(result)
    assert loaded.score_numeric == 95.0
    assert loaded.score_display == "95/100"
    assert loaded.category_scores["functionality"]["score_numeric"] == 40.0
    assert loaded.details["orchestra_metrics"] == {"dispatch": {"attempts": 2, "accepted": 2}}
    assert loaded.result == "pass"
    assert loaded.verdict == "pass"


def test_result_schema_defaults_are_structured_and_numeric(tmp_path: Path) -> None:
    result = TaskResult(run_meta=RunMeta(run_id="run-default", task_id="task-default"))

    assert result.schema_version == "v2"
    assert result.score_numeric is None
    assert result.score_display == ""
    assert result.task_meta == {}
    assert result.category_scores == {}
    assert result.tokens == {}
    assert result.context == {}
    assert result.orchestra == {}
    assert result.reliability == {}

    path = tmp_path / "result.json"
    written = write_json_atomic(path, result)
    loaded = load_result(written)

    assert loaded == result


def test_result_schema_rejects_non_numeric_score(tmp_path: Path) -> None:
    payload = _result().to_dict()
    payload["score_numeric"] = "pass"
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResultSchemaError, match="score_numeric"):
        load_result(path)


def test_result_schema_rejects_legacy_result_json(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "task_id": "task-one",
                "run_id": "20250101T010203",
                "score": "pass",
                "outcome": "pass",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResultSchemaError, match="schema_version"):
        load_result(path)


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
        outcome="error",
    )
    evaluator_failed = TaskResult(
        run_meta=RunMeta(run_id="run-2", task_id="task-2"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="failed", error="grader crashed"),
        outcome="error",
    )
    task_failed = TaskResult(
        run_meta=RunMeta(run_id="run-3", task_id="task-3"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="fail", checks={"check": False}),
        outcome="fail",
    )

    assert harness_failed.harness.status == "lifecycle_failed"
    assert harness_failed.evaluation.status == "not_run"
    assert harness_failed.outcome == "error"

    assert evaluator_failed.harness.status == "ok"
    assert evaluator_failed.evaluation.status == "failed"
    assert evaluator_failed.outcome == "error"

    assert task_failed.harness.status == "ok"
    assert task_failed.evaluation.status == "ok"
    assert task_failed.evaluation.score == "fail"
    assert task_failed.outcome == "fail"
