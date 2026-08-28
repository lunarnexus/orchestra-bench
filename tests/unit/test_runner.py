from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bench.config import resolve_harness_for_role
from bench.orchestration import OrchestrationSettleResult
from bench.provenance import build_run_metadata, snapshot_catalog_runtime
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.runner import grade_run, prepare_run, run_and_grade, run_task
from bench.tasks import load_task


def _write_task(task_dir: Path, *, task_id: str = "alpha-run") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(
        "task_id: {task_id}\n"
        "description: Sample task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 10\n"
        "evaluator: evaluate/run.sh\n".format(task_id=task_id),
        encoding="utf-8",
    )
    (task_dir / "PRD.md").write_text("Product requirements.\n", encoding="utf-8")
    (task_dir / "Prompt.md").write_text("Do the thing.\n", encoding="utf-8")
    (task_dir / "fixture").mkdir()
    (task_dir / "evaluate").mkdir()
    (task_dir / "evaluate" / "run.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")


def _write_catalog(catalog_path: Path) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  fake:\n"
        "    harness: fake-harness\n"
        "    command:\n"
        "    - fake\n"
        "    - '{prompt}'\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: fake\n"
        "    model: fake-model\n"
        "    agent: fake-agent\n"
        "    profile: default\n"
        "    env:\n"
        "      HARNESS_ENV: catalog\n"
        "    skills:\n"
        "    - builder\n",
        encoding="utf-8",
    )


class _SuccessHarness:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def run(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        assert request.metadata["run_meta"]["started_at"]
        assert request.metadata["provenance"]["model"] == "fake-model"
        assert request.metadata["bench_run"]["started_at"] == request.metadata["run_meta"]["started_at"]
        assert request.artifacts.summary_path.parent.name == "harness"
        assert request.env["HARNESS_ENV"] == "catalog"
        assert request.model == "fake-model"
        assert request.agent == "fake-agent"
        assert request.profile == "default"
        assert request.artifacts.transcript_path.parent.is_dir()
        request.artifacts.transcript_path.write_text("prompt seen\n", encoding="utf-8")
        return HarnessResult(status="ok", exit_code=0, details={"steps": 1})


class _FailingHarness:
    def run(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


class _AutoHarness:
    def run(self, request):  # type: ignore[no-untyped-def]
        return HarnessResult(status="ok", exit_code=0, details={"steps": 1})


def test_run_and_grade_auto_waits_before_grading_and_preserves_gate_details(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    order: list[str] = []

    def fake_wait_until_safe_to_grade(harness, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        order.append("gate")
        assert session_id == ""
        assert status_provider is None
        assert policy is not None and policy.orchestra_enabled is False
        return OrchestrationSettleResult(
            safe_to_grade=True,
            reason="harness_terminal",
            harness_status="settled",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        order.append("grade")
        result = load_result(run_paths.result_json)
        assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True
        assert result.details["provenance"]["auto_gate"]["reason"] == "harness_terminal"
        assert result.details["provenance"]["auto_gate"]["harness_status"] == "settled"
        return result

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _AutoHarness(), prepared=prepared, auto=True, orchestra=False)

    assert order == ["gate", "grade"]
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True


def test_run_and_grade_infers_auto_gate_from_prepared_provenance(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        auto=True,
        orchestra=False,
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    order: list[str] = []

    def fake_wait_until_safe_to_grade(harness, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        order.append("gate")
        assert session_id == ""
        assert status_provider is None
        assert policy is not None and policy.orchestra_enabled is False
        return OrchestrationSettleResult(
            safe_to_grade=True,
            reason="harness_terminal",
            harness_status="settled",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        order.append("grade")
        result = load_result(run_paths.result_json)
        assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True
        assert result.details["provenance"]["auto_gate"]["reason"] == "harness_terminal"
        return result

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _AutoHarness(), prepared=prepared)

    assert order == ["gate", "grade"]
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True


def test_run_and_grade_skips_grading_when_gate_is_not_safe(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        auto=True,
        orchestra=False,
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)

    def fake_wait_until_safe_to_grade(harness, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        return OrchestrationSettleResult(
            safe_to_grade=False,
            reason="timeout",
            harness_status="waiting",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        raise AssertionError("grade_run should not run when the gate is unsafe")

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _AutoHarness(), prepared=prepared)

    assert result.evaluation.status == "not_run"
    assert result.outcome == "not_run"
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is False
    assert result.details["provenance"]["auto_gate"]["reason"] == "timeout"


def test_run_and_grade_success_writes_bench_run_summary_and_final_result(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    assert prepared.run_paths.bench_run_json.is_file()
    bench_run = json.loads(prepared.run_paths.bench_run_json.read_text(encoding="utf-8"))
    assert bench_run["task"]["task_id"] == task.task_id
    assert bench_run["provenance"]["model"] == "fake-model"
    assert bench_run["started_at"]

    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "pass", "checks": {"done": True}}),
            stderr="",
        ),
    )

    assert result.harness == HarnessResult(status="ok", exit_code=0, details={"steps": 1})
    assert result.evaluation == EvaluationResult(status="ok", score="pass", checks={"done": True}, error="", details={})
    assert result.outcome == "pass"
    assert result.run_meta.run_id == "20250101T010203"
    assert result.run_meta.started_at
    assert result.run_meta.finished_at
    assert load_result(prepared.run_paths.result_json) == result
    assert json.loads(prepared.run_paths.result_json.read_text(encoding="utf-8"))["run_meta"]["finished_at"]
    assert json.loads(prepared.run_paths.artifacts_dir.joinpath("harness", "summary.json").read_text(encoding="utf-8"))["status"] == "ok"


def test_run_task_records_harness_failure_without_overwriting_prior_result(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    original = TaskResult(
        run_meta=RunMeta(run_id="20250101T010203", task_id=task.task_id, batch=task.batch, started_at="2025-01-01T01:02:03Z", finished_at="2025-01-01T01:02:04Z"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass", checks={"prior": True}),
        outcome="pass",
    )
    run_paths = tmp_path / "results" / "20250101T010203-alpha-run" / "result.json"
    write_json_atomic(run_paths, original)
    original_text = run_paths.read_text(encoding="utf-8")

    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    result = run_task(task, _FailingHarness(), prepared=prepared)

    assert result.harness.status == "lifecycle_failed"
    assert result.evaluation.status == "not_run"
    assert result.outcome == "not_run"
    assert result.harness.error == "harness crashed: boom"
    assert prepared.run_paths.result_json.read_text(encoding="utf-8") == original_text
    assert load_result(prepared.run_paths.result_json) == original


def test_grade_run_preserves_prior_result_and_returns_evaluator_failure_when_no_json(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    original = TaskResult(
        run_meta=RunMeta(run_id="20250101T010203", task_id=task.task_id, batch=task.batch, started_at="2025-01-01T01:02:03Z", finished_at="2025-01-01T01:02:04Z"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass", checks={"prior": True}),
        outcome="pass",
    )
    run_paths = tmp_path / "results" / "20250101T010203-alpha-run" / "result.json"
    write_json_atomic(run_paths, original)
    original_text = run_paths.read_text(encoding="utf-8")

    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="", stderr="boom\n"),
    )

    assert result.harness.status == "ok"
    assert result.evaluation.status == "failed"
    assert "no JSON" in result.evaluation.error
    assert result.outcome == "not_run"
    assert prepared.run_paths.result_json.read_text(encoding="utf-8") == original_text
    assert load_result(prepared.run_paths.result_json) == original


def test_prepare_run_writes_operator_readable_bench_run(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)

    assert prepared.run_paths.bench_run_json.stat().st_mode & 0o777 == 0o644
