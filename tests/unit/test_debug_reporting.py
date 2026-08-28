from __future__ import annotations

import json
from pathlib import Path

from bench.paths import RunPaths
from bench.reporting.debug import build_debug_report, format_debug_report
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, write_json_atomic


def _write(path: Path, text: str = "ok\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_run_artifacts(run_paths: RunPaths) -> None:
    _write(run_paths.artifacts_dir / "harness" / "transcript.txt", "prompt: do the thing\n")
    _write(run_paths.artifacts_dir / "harness" / "events.jsonl", '{"type":"agent_settled"}\n')
    _write(run_paths.artifacts_dir / "harness" / "run.log", "harness log\n")
    _write_json(run_paths.artifacts_dir / "harness" / "summary.json", {"status": "ok", "exit_code": 0})
    _write(run_paths.artifacts_dir / "evaluator" / "stdout.txt", "grader stdout\n")
    _write(run_paths.artifacts_dir / "evaluator" / "stderr.txt", "")
    _write(run_paths.artifacts_dir / "evaluator" / "log.txt", "evaluator log\n")
    _write_json(run_paths.artifacts_dir / "evaluator" / "result.json", {"status": "ok", "score": "fail"})
    _write_json(
        run_paths.manifest_path,
        {
            "classification": "ok",
            "command": ["bash", "evaluate/run.sh"],
            "returncode": 0,
            "source": "result_json",
        },
    )
    _write(run_paths.pi_rpc_events_path, '{"type":"agent_settled"}\n')
    _write(
        run_paths.orchestra_debug_dir / "status.jsonl",
        '{"active_runs":1,"descendants_terminal":false,"session_report_available":true,"session_report_delivered":false,"state":"running"}\n',
    )


def test_build_debug_report_summarizes_artifacts_and_orchestration_snapshots(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_run_artifacts(run_paths)
    result = TaskResult(
        run_meta=RunMeta(
            run_id=run_paths.run_id,
            task_id=run_paths.task_id,
            batch="smoke",
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:10:00Z",
        ),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="fail"),
        outcome="fail",
        details={"provenance": {"model": "agent-x", "orchestra": True}},
    )
    write_json_atomic(run_paths.result_json, result)

    report = build_debug_report(run_paths)
    text = format_debug_report(report)

    assert report.classification == "task failure"
    assert report.trace_status == "present"
    assert "status: task failure" in text
    assert "trace_status: present" in text
    assert "harness transcript: present" in text
    assert "harness events: present" in text
    assert "harness run.log: present" in text
    assert "harness summary: present" in text
    assert "evaluator result: present" in text
    assert "rpc events: present" in text
    assert "orchestra-debug: present" in text
    assert "orchestration snapshots:" in text
    assert "active_runs=1" in text
    assert str(run_paths.result_json) in text


def test_build_debug_report_distinguishes_failure_types_and_missing_trace(tmp_path: Path) -> None:
    harness_failed_paths = RunPaths(tmp_path, "20250101T010204", "task-two")
    harness_failed_paths.run_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        harness_failed_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=harness_failed_paths.run_id, task_id=harness_failed_paths.task_id, batch="smoke"),
            harness=HarnessResult(status="lifecycle_failed", exit_code=137, error="pi exited"),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )
    harness_failed_paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    _write_json(harness_failed_paths.artifacts_dir / "harness" / "summary.json", {"status": "lifecycle_failed"})

    evaluator_failed_paths = RunPaths(tmp_path, "20250101T010205", "task-three")
    evaluator_failed_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        evaluator_failed_paths.artifacts_dir / "evaluator" / "manifest.json",
        {"classification": "timeout", "returncode": None, "source": "stdout"},
    )
    write_json_atomic(
        evaluator_failed_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=evaluator_failed_paths.run_id, task_id=evaluator_failed_paths.task_id, batch="smoke"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="failed", error="grader timed out"),
            outcome="not_run",
        ),
    )

    missing_trace_paths = RunPaths(tmp_path, "20250101T010206", "task-four")

    cases = [
        (harness_failed_paths, "harness lifecycle failure"),
        (evaluator_failed_paths, "evaluator failure"),
        (missing_trace_paths, "missing trace"),
    ]

    for run_paths, expected in cases:
        report = build_debug_report(run_paths)
        text = format_debug_report(report)
        assert report.classification == expected
        assert expected in text
        assert "result.json" in text
        assert "harness transcript" in text


def test_build_debug_report_uses_artifact_clues_when_result_json_is_missing_or_invalid(tmp_path: Path) -> None:
    harness_only_paths = RunPaths(tmp_path, "20250101T010207", "task-five")
    harness_only_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(harness_only_paths.artifacts_dir / "harness" / "summary.json", {"status": "lifecycle_failed", "exit_code": 137})
    _write(harness_only_paths.artifacts_dir / "harness" / "transcript.txt", "prompt: do the thing\n")

    evaluator_only_paths = RunPaths(tmp_path, "20250101T010208", "task-six")
    evaluator_only_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write(evaluator_only_paths.result_json, "{not-json}\n")
    _write_json(
        evaluator_only_paths.manifest_path,
        {"classification": "timeout", "returncode": None, "source": "stdout"},
    )
    _write(evaluator_only_paths.artifacts_dir / "evaluator" / "stdout.txt", "grader stdout\n")

    harness_report = build_debug_report(harness_only_paths)
    harness_text = format_debug_report(harness_report)
    assert harness_report.classification == "harness lifecycle failure"
    assert harness_report.result_present is False
    assert harness_report.result_error == "missing result.json"
    assert "harness summary: present" in harness_text
    assert "status: harness lifecycle failure" in harness_text
    assert "result: outcome=n/a harness=lifecycle_failed evaluation=n/a score=n/a" in harness_text

    evaluator_report = build_debug_report(evaluator_only_paths)
    evaluator_text = format_debug_report(evaluator_report)
    assert evaluator_report.classification == "evaluator failure"
    assert evaluator_report.result_present is False
    assert evaluator_report.result_error.startswith("JSONDecodeError:")
    assert "evaluator manifest: present" in evaluator_text
    assert "status: evaluator failure" in evaluator_text
    assert "evaluation=timeout" in evaluator_text
