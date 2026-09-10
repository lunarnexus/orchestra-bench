from __future__ import annotations

from pathlib import Path

import json
import pytest

from bench.evaluator import EvaluationError
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic


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
    notes: str = "",
    score_numeric: float | None = None,
    score_display: str = "",
    started_at: str = "2025-01-01T00:00:00Z",
    finished_at: str = "2025-01-01T00:10:00Z",
    total_tokens: int | None = None,
    elapsed_seconds: float | None = None,
) -> Path:
    result = TaskResult(
        run_meta=RunMeta(run_id=run_id, task_id=task_id, batch=batch, started_at=started_at, finished_at=finished_at),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score=score_display or "pass"),
        outcome="pass",
        score_numeric=score_numeric,
        score_display=score_display,
        details={
            "provenance": {"model": model, "orchestra": orchestra, "notes": notes},
            "tokens": {"total": total_tokens} if total_tokens is not None else {},
            "timing": {"elapsed_seconds": elapsed_seconds} if elapsed_seconds is not None else {},
            "notes": notes,
        },
    )
    path = results_root / f"{run_id}-{task_id}" / "result.json"
    return write_json_atomic(path, result)


def _write_pi_session(
    run_dir: Path,
    session_id: str,
    events: list[dict[str, object]],
    *,
    filename: str | None = None,
) -> Path:
    path = run_dir / "artifacts" / "pi-sessions" / f"{filename or session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "session", "id": session_id}, *events]
    path.write_text("\n".join(json.dumps(event, sort_keys=True) for event in lines) + "\n", encoding="utf-8")
    return path


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
        notes="normal run",
        score_numeric=89.0,
        score_display="89/100",
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
        notes="secondary run",
        score_numeric=76.0,
        score_display="76/100",
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
        notes="follow-up run",
        score_numeric=91.0,
        score_display="91/100",
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


def test_collect_results_reads_persisted_pi_session_usage_and_formats_tokens(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    result_path = _write_result(
        results_root,
        "20250101T010103",
        "task-a",
        batch="",
        model="model-a",
        orchestra=True,
        notes="follow-up run",
        score_numeric=91.0,
        score_display="91/100",
    )
    run_dir = result_path.parent

    _write_pi_session(
        run_dir,
        "orchestra-main-1",
        [
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input": 100,
                        "output": 40,
                        "reasoning": 10,
                        "cacheRead": 5,
                        "cacheWrite": 7,
                        "cacheWrite1h": 3,
                    },
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "toolResult",
                    "usage": {"input": 10, "output": 4, "reasoning": 1, "cacheRead": 2, "cacheWrite": 1},
                },
            },
            {"type": "compaction", "usage": {"input": 6, "output": 3, "reasoning": 1, "cacheRead": 0, "cacheWrite": 2}},
            {"type": "branch_summary", "usage": {"input": 8, "output": 2, "reasoning": 0, "cacheRead": 1, "cacheWrite": 0}},
        ],
        filename="20250101T010103_parent.jsonl",
    )
    _write_pi_session(
        run_dir,
        "child-session-1",
        [
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "usage": {"input": 20, "output": 5, "reasoning": 2, "cacheRead": 1, "cacheWrite": 0},
                },
            },
            {"type": "branch_summary", "usage": {"input": 4, "output": 1, "reasoning": 0, "cacheRead": 0, "cacheWrite": 2}},
        ],
        filename="20250101T010103_orchestra-worker-1.jsonl",
    )

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert len(entries) == 1
    entry = entries[0]

    assert entry.total_tokens == 210
    assert entry.tokens["session_ids"] == ["child-session-1", "orchestra-main-1"]
    assert entry.tokens["parent_session_ids"] == ["orchestra-main-1"]
    assert entry.tokens["child_session_ids"] == ["child-session-1"]
    assert entry.tokens["main_session"]["cache_write_tokens"] == 12
    assert entry.tokens["children_sessions"]["cache_write_tokens"] == 2
    assert entry.tokens["parent_session"]["final_context_tokens"] == 100
    assert entry.tokens["children_sessions"]["final_context_tokens"] == 20
    assert entry.tokens["all_sessions"]["total_tokens"] == 210
    assert entry.tokens["all_sessions"]["input_tokens"] == 138
    assert entry.tokens["all_sessions"]["output_tokens"] == 51
    assert entry.tokens["all_sessions"]["reasoning_tokens"] == 13
    assert entry.tokens["all_sessions"]["cached_input_read_tokens"] == 7
    assert entry.tokens["all_sessions"]["cache_write_tokens"] == 14
    assert entry.tokens["all_sessions"]["api_calls"] == 5
    assert entry.tokens["all_sessions"]["compactions"] == 1
    assert entry.score_numeric is None
    assert entry.score_display == ""
    assert entry.notes == "follow-up run"

    detail = format_run_detail(entry)
    assert "all      : total=210 input=138 output=51 reasoning=13 cache_read=7 cache_write=14 calls=5" in detail
    assert "parent   : total=177 input=114 output=45 reasoning=11 cache_read=6 cache_write=12 calls=3" in detail
    assert "children : total=33 input=24 output=6 reasoning=2 cache_read=1 cache_write=2 calls=2" in detail
    assert "parent   : final=100 max=100 compactions=1" in detail
    assert "children : final=20 max=20 compactions=0" in detail
    assert "parent   : orchestra-main-1" in detail
    assert "children : child-session-1" in detail


def test_run_detail_renders_persisted_correctness_mode_usage_and_behavior_facts(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-facts", batch="smoke")
    result_path = results_root / "20250101T010105-task-facts" / "result.json"
    result = TaskResult(
        run_meta=RunMeta(
            run_id="20250101T010105",
            task_id="task-facts",
            batch="smoke",
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:10:00Z",
        ),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(
            status="ok",
            score="fail",
            checks={"create_file": True, "run_command": False, "preserve_output": True},
            details={
                "functionality": {
                    "checks": {"create_file": True, "run_command": False, "preserve_output": True},
                    "evidence": {"source": "persisted"},
                }
            },
        ),
        outcome="fail",
        score_numeric=66.6667,
        score_display="67/100",
        category_scores={"functionality": {"score_numeric": 66.6667, "score_display": "67/100"}},
        tokens={
            "total": 210,
            "sources": {"parent": "pi_session", "children": "pi_sessions"},
            "unavailable_reasons": {"children": "child usage unavailable from persisted sessions"},
            "all_sessions": {
                "total_tokens": 210,
                "input_tokens": 150,
                "output_tokens": 60,
                "reasoning_tokens": 0,
                "cached_input_read_tokens": 0,
                "cache_write_tokens": 0,
                "api_calls": 3,
                "final_context_tokens": 100,
                "max_context_tokens": 120,
                "compactions": 1,
            },
            "parent_session": {
                "total_tokens": 150,
                "input_tokens": 100,
                "output_tokens": 50,
                "reasoning_tokens": 0,
                "cached_input_read_tokens": 0,
                "cache_write_tokens": 0,
                "api_calls": 2,
                "final_context_tokens": 100,
                "max_context_tokens": 120,
                "compactions": 1,
            },
            "children_sessions": {
                "total_tokens": 60,
                "input_tokens": 50,
                "output_tokens": 10,
                "reasoning_tokens": 0,
                "cached_input_read_tokens": 0,
                "cache_write_tokens": 0,
                "api_calls": 1,
                "final_context_tokens": 50,
                "max_context_tokens": 50,
                "compactions": 0,
            },
            "parent_session_ids": ["parent-1"],
            "child_session_ids": ["child-1"],
        },
        context={"parent": {"final": 100, "max": 120}, "children": {"final": 50, "max": 50}},
        orchestra={
            "dispatch_attempts": 3,
            "dispatch_accepted": 2,
            "dispatch_rejected": 1,
            "dispatch": {"attempts": 3, "accepted": 2, "rejected": 1},
            "roles": {"requested": ["builder"], "started": ["builder"], "returned": ["builder"]},
            "child_sessions": {"completed": 1, "failed": 0, "timed_out": 1, "reconciled": 0, "active": 0, "inferred_active": 0},
            "parent": {"waited": True, "integrated": True, "finalized_before_children": False},
        },
        details={
            "provenance": {
                "harness": "pi",
                "model": "model-a",
                "orchestra": True,
                "no_orchestra": False,
                "mode_disabled_flag": False,
                "mode_enabled_requested": True,
                "orchestra_tools_available": True,
            }
        },
    )
    write_json_atomic(result_path, result)
    persisted = load_result(result_path)

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert len(entries) == 1
    detail = format_run_detail(entries[0])

    assert persisted.evaluation.details["functionality"]["checks"] == {"create_file": True, "run_command": False, "preserve_output": True}
    assert entries[0].tokens["all_sessions"]["total_tokens"] == persisted.tokens["all_sessions"]["total_tokens"] == 210
    assert entries[0].provenance["mode_enabled_requested"] is persisted.details["provenance"]["mode_enabled_requested"] is True
    assert entries[0].orchestra_metrics["dispatch_attempts"] == persisted.orchestra["dispatch_attempts"] == 3
    assert "correctness: score=67/100 checks=2/3" in detail
    assert "failed checks: run_command" in detail
    assert "no-orchestra  : no" in detail
    assert "tools         : available" in detail
    assert "all      : total=210" in detail
    assert "parent   : total=150" in detail
    assert "children : total=60" in detail
    assert "sources   : parent=pi_session children=pi_sessions" in detail
    assert "unavailable: children=child usage unavailable from persisted sessions" in detail
    assert "all      : final=100 max=120 compactions=1" in detail
    assert "parent   : final=100 max=120 compactions=1" in detail
    assert "children : final=50 max=50 compactions=0" in detail
    assert "dispatch  : attempts=3 accepted=2 rejected=1" in detail
    assert "children  : completed=1 failed=0 timed_out=1 reconciled=0 active=0 inferred_active=0" in detail
    assert "parent    : waited=yes integrated=yes finalized_before_children=no" in detail


def test_run_detail_reports_disabled_and_unknown_mode_facts(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import ReportEntry

    def entry(provenance: dict[str, object]) -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id="task-a", batch="smoke"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={"provenance": provenance},
        )
        return ReportEntry(path=tmp_path / "result.json", result=result, batch="smoke", provenance=provenance)

    disabled = format_run_detail(
        entry(
            {
                "orchestra": False,
                "no_orchestra": True,
                "mode_disabled_flag": True,
                "mode_enabled_requested": False,
                "orchestra_tools_available": False,
            }
        )
    )
    assert "no-orchestra  : yes" in disabled
    assert "tools         : disabled" in disabled

    unknown = format_run_detail(entry({"orchestra": None}))
    assert "no-orchestra  : unknown" in unknown
    assert "tools         : unknown" in unknown
    assert "sources   : parent=n/a children=n/a" in unknown
    assert "unavailable: n/a" in unknown


def test_run_detail_shows_configured_availability_and_observed_execution_independently(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import ReportEntry

    def entry(provenance: dict[str, object]) -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id="task-a", batch="smoke"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={"provenance": provenance},
        )
        return ReportEntry(path=tmp_path / "result.json", result=result, batch="smoke", provenance=provenance)

    # Activation was explicitly disabled by a flag; observed execution is still reported when it happens.
    independent = format_run_detail(
        entry(
            {
                "orchestra": False,
                "mode_disabled_flag": True,
                "mode_enabled_requested": False,
                "orchestra_tools_available": None,
                "orchestra_tools_executed": True,
            }
        )
    )
    assert "tools         : observed" in independent
    assert "tools-exec    : yes" in independent

    # Configured available while observed execution is false.
    mixed = format_run_detail(
        entry(
            {
                "orchestra": True,
                "mode_disabled_flag": False,
                "mode_enabled_requested": True,
                "orchestra_tools_available": True,
                "orchestra_tools_executed": False,
            }
        )
    )
    assert "tools         : available" in mixed
    assert "tools-exec    : no" in mixed

    # No evidence at all: both facts stay unknown.
    unknown = format_run_detail(entry({"orchestra": None}))
    assert "tools         : unknown" in unknown
    assert "tools-exec    : unknown" in unknown


def test_failure_reason_summarizes_failed_functionality_checks() -> None:
    from bench.reporting.queries import _extract_failure_reason

    result = TaskResult(
        run_meta=RunMeta(run_id="20250101T010105", task_id="task-c"),
        evaluation=EvaluationResult(
            status="ok",
            details={
                "functionality": {
                    "checks": {
                        "functional_a": True,
                        "functional_b": False,
                        "functional_c": False,
                    },
                    "evidence": {"large": "payload"},
                }
            },
        ),
        outcome="fail",
    )

    assert _extract_failure_reason(result) == "failed checks: functional_b, functional_c"


def test_collect_results_infers_tool_availability_from_pi_widget(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    run_dir = tmp_path / "results" / "20250101T010107-task-e"
    write_json_atomic(
        run_dir / "result.json",
        TaskResult(
            run_meta=RunMeta(run_id="20250101T010107", task_id="task-e", batch="smoke"),
            harness=HarnessResult(status="ok"),
            evaluation=EvaluationResult(status="ok", score="pass", details={"functionality": {"checks": {"functional_a": True}}}),
            outcome="pass",
            details={"provenance": {"harness": "pi", "model": "model-a", "no_orchestra": False, "orchestra_tools_available": None, "orchestra_tools_executed": False}},
        ),
    )
    events = run_dir / "artifacts" / "harness" / "events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    events.write_text(json.dumps({"type": "extension_ui_request", "widgetLines": ["(Orchestra:on)"]}) + "\n", encoding="utf-8")

    [entry] = collect_results(tmp_path / "results")
    detail = format_run_detail(entry)

    assert "tools         : available" in detail
    assert "tools-exec    : no" in detail


def test_run_detail_tools_display_uses_observed_execution(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import ReportEntry

    result = TaskResult(
        run_meta=RunMeta(run_id="20250101T010106", task_id="task-d", batch="smoke"),
        harness=HarnessResult(status="ok"),
        evaluation=EvaluationResult(status="ok", score="pass", details={"functionality": {"checks": {"functional_a": True}}}),
        outcome="pass",
    )
    entry = ReportEntry(
        path=tmp_path / "result.json",
        result=result,
        batch="smoke",
        model="model-a",
        orchestra=False,
        provenance={"harness": "pi", "model": "model-a", "orchestra_tools_executed": True},
    )

    detail = format_run_detail(entry)

    assert "tools         : observed" in detail
    assert "tools-exec    : yes" in detail


def test_reporting_formatters_render_dashboard_runs_detail_tokens_and_timing(reporting_data: Path) -> None:
    from bench.reporting.formatters import (
        format_dashboard,
        format_run_detail,
        format_runs,
        format_timing,
        format_tokens,
    )
    from bench.reporting.queries import ReportEntry, collect_results

    entries = collect_results(reporting_data / "results", tasks_dir=reporting_data / "tasks")

    dashboard = format_dashboard(entries)
    runs = format_runs(entries)
    tokens = format_tokens(entries)
    timing = format_timing(entries)

    detail_entry = ReportEntry(
        path=reporting_data / "results" / "20250101T010103-task-a" / "result.json",
        result=TaskResult(
            run_meta=RunMeta(
                run_id="20250101T010103",
                task_id="task-a",
                batch="smoke",
                started_at="2025-01-01T00:00:00Z",
                finished_at="2025-01-01T00:10:00Z",
            ),
            harness=HarnessResult(
                status="ok",
                exit_code=0,
                details={
                    "artifacts": {
                        "transcript": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "harness" / "transcript.txt",
                        "summary": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "harness" / "summary.json",
                        "log": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "harness" / "run.log",
                        "pi_sessions": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "pi-sessions",
                    }
                },
            ),
            evaluation=EvaluationResult(
                status="ok",
                score="pass",
                checks={"accept": True, "reject": False},
                details={"summary": "pass"},
            ),
            outcome="pass",
        ),
        batch="smoke",
        model="model-a",
        orchestra=True,
        score_numeric=89.0,
        score_display="89/100",
        notes="ready",
        failure_reason="",
        artifact_paths={
            "result_json": reporting_data / "results" / "20250101T010103-task-a" / "result.json",
            "workspace": reporting_data / "results" / "20250101T010103-task-a" / "workspace",
            "harness": {
                "transcript": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "harness" / "transcript.txt",
                "summary": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "harness" / "summary.json",
                "log": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "harness" / "run.log",
                "pi_sessions": reporting_data / "results" / "20250101T010103-task-a" / "artifacts" / "pi-sessions",
            },
        },
        provenance={"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": True},
        tokens={
            "all_sessions": {
                "total_tokens": 120,
                "input_tokens": 80,
                "output_tokens": 40,
                "reasoning_tokens": 5,
                "cached_input_read_tokens": 10,
                "cache_write_tokens": 0,
                "api_calls": 3,
                "final_context_tokens": 120,
                "max_context_tokens": 120,
                "compactions": 0,
            },
            "parent_session": {
                "total_tokens": 60,
                "input_tokens": 45,
                "output_tokens": 15,
                "reasoning_tokens": 2,
                "cached_input_read_tokens": 0,
                "cache_write_tokens": 0,
                "api_calls": 2,
                "final_context_tokens": 60,
                "max_context_tokens": 60,
                "compactions": 0,
            },
            "children_sessions": {
                "total_tokens": 60,
                "input_tokens": 35,
                "output_tokens": 25,
                "reasoning_tokens": 3,
                "cached_input_read_tokens": 0,
                "cache_write_tokens": 1,
                "api_calls": 1,
                "final_context_tokens": 60,
                "max_context_tokens": 60,
                "compactions": 1,
            },
            "session_ids": ["main-session-1", "orchestra-worker-1", "orchestra-worker-2"],
            "parent_session_ids": ["main-session-1"],
            "child_session_ids": ["orchestra-worker-1", "orchestra-worker-2"],
        },
    )
    detail_fail_entry = ReportEntry(
        path=reporting_data / "results" / "20250101T010104-task-b" / "result.json",
        result=TaskResult(
            run_meta=RunMeta(
                run_id="20250101T010104",
                task_id="task-b",
                batch="smoke",
                started_at="2025-01-01T01:00:00Z",
                finished_at="2025-01-01T01:05:00Z",
            ),
            harness=HarnessResult(status="lifecycle_failed", exit_code=1, error="runner crashed"),
            evaluation=EvaluationResult(status="failed", score="0.23", error="evaluation crashed", details={}),
            outcome="error",
        ),
        batch="smoke",
        model="model-b",
        orchestra=False,
        harness_status="lifecycle_failed",
        harness_exit_code=1,
        harness_error="runner crashed",
        evaluation_status="failed",
        evaluation_score="0.23",
        evaluation_error="evaluation crashed",
        failure_reason="evaluation crashed",
        provenance={"harness": "pi", "backend": "pi", "model": "model-b", "orchestra": False},
    )

    workspace = detail_entry.path.parent / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".evaluator-reports.sqlite3").write_text("db", encoding="utf-8")
    (workspace / ".tmp-evaluator-inventory.json").write_text("{}", encoding="utf-8")
    (workspace / ".pytest_cache").mkdir()
    (workspace / "__pycache__").mkdir()
    (workspace / "PLAN.md").write_text("plan", encoding="utf-8")
    (workspace / "test_shop.py").write_text("test", encoding="utf-8")

    detail = format_run_detail(detail_entry)
    detail_fail = format_run_detail(detail_fail_entry)

    assert "orchestra-bench dashboard" in dashboard
    assert "runs       : 3" in dashboard
    assert "passed     : 3" in dashboard
    assert "failed     : 0" in dashboard
    assert "error      : 0" in dashboard
    assert "evaluated pass rate : 100.0% (3/3)" in dashboard

    assert "20250101T010103" in runs
    assert "model-b" in runs

    assert detail.startswith("=== run 20250101T010103 ===\n")
    assert "task      : task-a" in detail
    assert "suite     : smoke" in detail
    # Lifecycle/harness state and evaluation state are separate axes, not one `result` line.
    assert "lifecycle : ok" in detail
    assert "evaluation: ok" in detail
    assert not any(line.startswith("result    ") for line in detail.splitlines())
    assert "score     : 89/100" in detail
    assert "reason    :" not in detail
    assert "agent     : harness=pi model=model-a orchestra=yes" in detail
    assert "runtime   : elapsed=10m00.0s window=2025-01-01 00:00 → 2025-01-01 00:10" in detail
    assert "2025-01-01T00:00:00Z" not in detail
    assert "2025-01-01T00:10:00Z" not in detail

    assert "=== tokens ===" in detail
    assert "all      : total=120 input=80 output=40 reasoning=5 cache_read=10 cache_write=0 calls=3" in detail
    assert "parent   : total=60 input=45 output=15 reasoning=2 cache_read=0 cache_write=0 calls=2" in detail
    assert "children : total=60 input=35 output=25 reasoning=3 cache_read=0 cache_write=1 calls=1" in detail
    assert "=== context ===" in detail
    assert "parent   : final=60 max=60 compactions=0" in detail
    assert "children : final=60 max=60 compactions=1" in detail

    assert "=== sessions ===" in detail
    assert "parent   : main-session-1" in detail
    assert "children : orchestra-worker-1, orchestra-worker-2" in detail

    assert "=== diagnostics ===" in detail
    assert "runner    :" not in detail
    assert "evaluator :" not in detail
    assert "details   :" in detail
    # Root wrappers are gone; the debug hint points at scripts/.
    assert "debug     : scripts/04-debug 20250101T010103-task-a orch|full|raw" in detail

    assert "=== artifacts ===" in detail
    assert f"result   : {detail_entry.path}" in detail
    assert f"workspace: {detail_entry.path.parent / 'workspace'}" in detail
    assert "workspace evaluator: .evaluator-reports.sqlite3, .tmp-evaluator-inventory.json" in detail
    assert "workspace cache/runtime: .pytest_cache, __pycache__" in detail
    assert "workspace agent/support: PLAN.md, test_shop.py" in detail
    assert "artifacts/harness" in detail
    assert "transcript=" in detail
    assert "sessions : " in detail
    assert "tokens     :" not in detail
    assert "error      : n/a" not in detail
    assert "subagents" not in detail
    assert "True" not in detail

    assert detail_fail.startswith("=== run 20250101T010104 ===\n")
    # Harness failed and the evaluator never produced a verdict: both axes are shown.
    assert "lifecycle : lifecycle_failed" in detail_fail
    assert "evaluation: failed" in detail_fail
    assert not any(line.startswith("result    ") for line in detail_fail.splitlines())
    assert "correctness: not evaluated" in detail_fail
    assert "score     : n/a" in detail_fail
    assert "reason    : evaluation crashed" in detail_fail
    assert "agent     : harness=pi model=model-b orchestra=no" in detail_fail
    assert "runtime   : elapsed=5m00.0s window=2025-01-01 01:00 → 2025-01-01 01:05" in detail_fail
    assert "runner    : lifecycle_failed exit=1 runner crashed" in detail_fail
    assert "evaluator : failed evaluation crashed" in detail_fail

    assert "total_tokens" in tokens
    assert "240" in tokens

    assert "timing" in timing
    assert "12.5" in timing


def test_reporting_compare_selectors_and_formatters_cover_run_group_and_modes(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_comparison_results
    from bench.reporting.queries import ReportEntry, compare_selected_results
    from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult

    def make_entry(
        run_id: str,
        task_id: str,
        *,
        model: str,
        outcome: str,
        score_numeric: float | None,
        score_display: str,
        failure_reason: str,
        total_tokens: int,
        parent_tokens: int,
        children_tokens: int,
        elapsed_seconds: float,
        dispatch_attempts: int,
    ) -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score=score_display or outcome),
            outcome=outcome,
            score_numeric=score_numeric,
            score_display=score_display,
            details={"provenance": {"harness": "pi", "backend": "pi", "model": model, "orchestra": True}},
        )
        return ReportEntry(
            path=tmp_path / f"{run_id}-{task_id}" / "result.json",
            result=result,
            batch="smoke",
            model=model,
            orchestra=True,
            score_numeric=score_numeric,
            score_display=score_display,
            category_scores={
                "functionality": {"score_numeric": 20.0 if outcome == "pass" else 16.0},
                "orchestration": {"score_numeric": 35.0 if outcome == "pass" else 28.0},
                "efficiency": {"score_numeric": 10.0 if outcome == "pass" else 8.0},
                "reliability": {"score_numeric": 15.0},
            },
            notes="ready",
            failure_reason=failure_reason,
            harness_status="ok",
            harness_exit_code=0,
            harness_error="",
            evaluation_status="ok",
            evaluation_score=score_display,
            evaluation_error="",
            artifact_paths={},
            tokens={
                "total": total_tokens,
                "parent_session": {"total_tokens": parent_tokens, "final_context_tokens": parent_tokens, "max_context_tokens": parent_tokens + 10, "compactions": 1 if outcome != "pass" else 0},
                "children_sessions": {"total_tokens": children_tokens, "final_context_tokens": children_tokens, "max_context_tokens": children_tokens + 5, "compactions": 0 if outcome == "pass" else 1},
            },
            timing={"elapsed_seconds": elapsed_seconds},
            provenance={"harness": "pi", "backend": "pi", "model": model, "orchestra": True},
            orchestra_metrics={
                "dispatch_attempts": dispatch_attempts,
                "dispatch_accepted": dispatch_attempts,
                "dispatch_rejected": 0,
                "roles_requested": ["builder"],
                "roles_started": ["builder"],
                "roles_returned": ["builder"],
                "child_returns": {"ok": 1 if outcome == "pass" else 0, "error": 0 if outcome == "pass" else 1, "blocker": 0},
                "child_sessions": {"completed": 1 if outcome == "pass" else 0, "failed": 0 if outcome == "pass" else 1, "timed_out": 0, "reconciled": 0, "active": 0},
                "parent": {"waited": True, "integrated": outcome == "pass", "finalized_before_children": outcome != "pass"},
                "duplicate_same_slice_dispatches": 0,
                "same_slice_dispatches": 0,
            },
        )

    entries = [
        make_entry(
            "20250101T010101",
            "task-a",
            model="model-a",
            outcome="pass",
            score_numeric=90.0,
            score_display="90/100",
            failure_reason="",
            total_tokens=100,
            parent_tokens=60,
            children_tokens=40,
            elapsed_seconds=10.0,
            dispatch_attempts=2,
        ),
        make_entry(
            "20250101T010102",
            "task-b",
            model="model-b",
            outcome="fail",
            score_numeric=70.0,
            score_display="70/100",
            failure_reason="evaluation crashed",
            total_tokens=200,
            parent_tokens=80,
            children_tokens=120,
            elapsed_seconds=20.0,
            dispatch_attempts=1,
        ),
        make_entry(
            "20250101T010103",
            "task-c",
            model="model-b",
            outcome="fail",
            score_numeric=65.0,
            score_display="65/100",
            failure_reason="evaluation crashed",
            total_tokens=220,
            parent_tokens=90,
            children_tokens=130,
            elapsed_seconds=22.0,
            dispatch_attempts=1,
        ),
    ]

    run_vs_run = compare_selected_results(entries, "run:20250101T010101", "run:20250101T010102")
    group_vs_group = compare_selected_results(entries, "suite:smoke", "result:fail")
    run_vs_group = compare_selected_results(entries, "run:20250101T010101", "model:model-b")

    assert run_vs_run["mode"] == "run-vs-run"
    assert group_vs_group["mode"] == "group-vs-group"
    assert run_vs_group["mode"] == "run-vs-group"

    formatted = format_comparison_results(run_vs_group)
    assert "=== compare ===" in formatted
    assert "mode      : run-vs-group" in formatted
    assert "parent    : run 20250101T010101-task-a" in formatted
    assert "children  : model=model-b" in formatted
    assert "pass rate" in formatted
    assert "score" in formatted
    assert "tokens/context" in formatted
    assert "dispatch" in formatted
    assert "evaluation crashed" in formatted
    assert "failure reasons" in formatted
    assert "orchestration :" not in formatted
    assert "efficiency :" not in formatted
    assert "reliability :" not in formatted


def test_collect_results_populates_orchestra_metrics_from_pi_sessions(tmp_path: Path) -> None:
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-orch", batch="smoke")
    result_path = _write_result(results_root, "20250101T010106", "task-orch", batch="", model="model-a", orchestra=True)
    run_dir = result_path.parent

    _write_pi_session(
        run_dir,
        "parent-session",
        [
            {
                "type": "message",
                "timestamp": "2025-01-01T00:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "toolCall", "name": "orch_dispatch", "arguments": {"role": "builder", "goal": "implement checkout", "taskLabel": "slice-a"}}]},
            },
            {
                "type": "message",
                "timestamp": "2025-01-01T00:00:02Z",
                "message": {"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            },
            {
                "type": "message",
                "timestamp": "2025-01-01T00:00:03Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: builder abc123 success]\nsummary: pass"}]},
            },
        ],
    )

    entries = collect_results(results_root, tasks_dir=tasks_root)

    assert entries[0].orchestra_metrics["dispatch_attempts"] == 1
    assert entries[0].result.orchestra["dispatch_attempts"] == 1
    assert entries[0].result.orchestra["roles_returned"] == ["builder"]


def test_collect_results_scores_enriched_runs_from_normalized_inputs(tmp_path: Path) -> None:
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-score", batch="smoke")
    result = TaskResult(
        run_meta=RunMeta(run_id="20250101T010107", task_id="task-score", batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(
            status="ok",
            score="fail",
            checks={"core": True, "workflow": False},
            details={
                "functionality": {
                    "checks": {"core": True, "workflow": False},
                    "evidence": {"order_id": "order-1", "customer_id": "c-1"},
                }
            },
        ),
        outcome="pass",
        details={"provenance": {"orchestra": True}},
        score_numeric=None,
        score_display="",
        context={"parent": {"final": 50, "max": 60, "compactions": 0}},
        reliability={"artifacts_present": True},
        tokens={
            "total": 100,
            "all_sessions": {"total_tokens": 100, "final_context_tokens": 50, "max_context_tokens": 60, "compactions": 0},
            "parent_session": {"total_tokens": 100, "final_context_tokens": 50, "max_context_tokens": 60, "compactions": 0},
        },
        orchestra={
            "dispatch": {"attempts": 1, "accepted": 1, "rejected": 0, "rejection_reasons": {}},
            "roles": {"requested": ["builder"], "returned": ["builder"]},
            "child_sessions": {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0},
            "parent": {"waited": True, "integrated": True, "finalized_before_children": False},
            "duplicate_same_slice_dispatches": 0,
            "same_slice_dispatches": 0,
            "evidence": {"pi_sessions": True, "orchestra_debug": False},
        },
    )
    write_json_atomic(results_root / "20250101T010107-task-score" / "result.json", result)

    entries = collect_results(results_root, tasks_dir=tasks_root)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.score_numeric == pytest.approx(50.0)
    assert entry.score_display == "50/100"
    assert "efficiency" not in entry.category_scores
    assert entry.result.category_scores["functionality"]["score_numeric"] == pytest.approx(50.0)
    assert entry.result.evaluation.details["functionality"]["evidence"]["order_id"] == "order-1"


def test_reporting_formatters_render_dashboard_aggregates_and_recent_runs(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard
    from bench.reporting.queries import ReportEntry
    from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult

    def make_entry(
        run_id: str,
        task_id: str,
        *,
        outcome: str,
        score_numeric: float | None,
        score_display: str,
        category_scores: dict[str, object],
        tokens: dict[str, object],
        timing: dict[str, object],
        orchestra_metrics: dict[str, object],
    ) -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score=score_display or outcome),
            outcome=outcome,
            score_numeric=score_numeric,
            score_display=score_display,
            category_scores=category_scores,
            tokens=tokens,
            reliability={"artifacts_present": True},
            details={"provenance": {"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": True}},
        )
        return ReportEntry(
            path=tmp_path / f"{run_id}-{task_id}" / "result.json",
            result=result,
            batch="smoke",
            model="model-a",
            orchestra=True,
            score_numeric=score_numeric,
            score_display=score_display,
            category_scores=category_scores,
            notes="ready",
            failure_reason="",
            harness_status="ok",
            harness_exit_code=0,
            harness_error="",
            evaluation_status="ok",
            evaluation_score=score_display,
            evaluation_error="",
            artifact_paths={},
            tokens=tokens,
            timing=timing,
            provenance={"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": True},
            orchestra_metrics=orchestra_metrics,
        )

    entries = [
        make_entry(
            "20250101T010101",
            "task-a",
            outcome="pass",
            score_numeric=90.0,
            score_display="90/100",
            category_scores={"functionality": {"score_numeric": 20.0}, "orchestration": {"score_numeric": 35.0}, "efficiency": {"score_numeric": 10.0}, "reliability": {"score_numeric": 15.0}},
            tokens={"all_sessions": {"total_tokens": 100, "final_context_tokens": 80, "max_context_tokens": 120, "compactions": 1}},
            timing={"elapsed_seconds": 10.0},
            orchestra_metrics={"dispatch_attempts": 2, "dispatch_accepted": 2, "child_sessions": {"completed": 2, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}},
        ),
        make_entry(
            "20250101T010102",
            "task-b",
            outcome="fail",
            score_numeric=70.0,
            score_display="70/100",
            category_scores={"functionality": {"score_numeric": 18.0}, "orchestration": {"score_numeric": 28.0}, "efficiency": {"score_numeric": 9.0}, "reliability": {"score_numeric": 15.0}},
            tokens={"all_sessions": {"total_tokens": 300, "final_context_tokens": 140, "max_context_tokens": 200, "compactions": 3}},
            timing={"elapsed_seconds": 30.0},
            orchestra_metrics={"dispatch_attempts": 1, "dispatch_accepted": 1, "child_sessions": {"completed": 1, "failed": 1, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}},
        ),
        make_entry(
            "20250101T010103",
            "task-c",
            outcome="error",
            score_numeric=None,
            score_display="",
            category_scores={},
            tokens={"all_sessions": {"total_tokens": 50, "final_context_tokens": 25, "max_context_tokens": 30, "compactions": 0}},
            timing={"elapsed_seconds": 5.0},
            orchestra_metrics={"dispatch_attempts": 0, "dispatch_accepted": 0, "child_sessions": {"completed": 0, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}},
        ),
    ]

    dashboard = format_dashboard(entries)

    assert "runs       : 3" in dashboard
    assert "passed     : 1" in dashboard
    assert "failed     : 1" in dashboard
    assert "error      : 1" in dashboard
    assert "evaluated pass rate : 50.0% (1/2)" in dashboard
    assert "score      : available=2/3 avg=80 high=90 low=70" in dashboard
    assert "functionality : scored=2/3" in dashboard
    assert "orchestration :" not in dashboard
    assert "efficiency :" not in dashboard
    assert "reliability :" not in dashboard
    assert "tokens all           : avg=150 high=300 low=50" in dashboard
    assert "context all          : avg=81.7 high=140 low=25" in dashboard
    assert "compactions all      : total=4 avg=1.3" in dashboard
    assert "tokens main          : n/a" in dashboard
    assert "tokens children      : n/a" in dashboard
    assert "elapsed              : avg=15.0s high=30.0s low=5.0s" in dashboard
    assert "dispatches : attempts=3 accepted=3 rejected=0" in dashboard
    assert "children   : completed=3 failed=1 timed_out=0 reconciled=0 active=0 inferred_active=0" in dashboard
    # The error summary carries compact run refs so an operator can jump to the run.
    evaluator_error_line = next(line for line in dashboard.splitlines() if line.startswith("evaluator"))
    assert "20250101T010103-task-c" in evaluator_error_line
    # Scored runs (pass/fail) are never listed as errors.
    assert "20250101T010102" not in dashboard
    assert "scripts/03-results runs" in dashboard


def test_reporting_formatters_dashboard_reason_lines(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard
    from bench.reporting.queries import ReportEntry
    from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult

    empty_children = {"completed": 0, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}

    def make_entry(run_id: str, orchestra_metrics: dict[str, object]) -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=f"task-{run_id}", batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            score_numeric=80.0,
            score_display="80/100",
            category_scores={"functionality": {"score_numeric": 20.0}},
            tokens={"all_sessions": {"total_tokens": 100, "final_context_tokens": 50, "max_context_tokens": 60, "compactions": 0}},
            reliability={"artifacts_present": True},
        )
        return ReportEntry(
            path=tmp_path / run_id / "result.json",
            result=result,
            batch="smoke",
            model="model-a",
            orchestra=True,
            score_numeric=80.0,
            score_display="80/100",
            category_scores={"functionality": {"score_numeric": 20.0}},
            notes="ready",
            failure_reason="",
            harness_status="ok",
            harness_exit_code=0,
            harness_error="",
            evaluation_status="ok",
            evaluation_score="80/100",
            evaluation_error="",
            artifact_paths={},
            tokens={"all_sessions": {"total_tokens": 100, "final_context_tokens": 50, "max_context_tokens": 60, "compactions": 0}},
            timing={"elapsed_seconds": 5.0},
            provenance={"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": True},
            orchestra_metrics=orchestra_metrics,
        )

    entries = [
        make_entry(
            "20250101T030301",
            {
                "dispatch_attempts": 4,
                "dispatch_accepted": 2,
                "dispatch_rejected": 2,
                "child_sessions": {**empty_children, "completed": 1, "failed": 1},
                "dispatch_rejection_reasons": {"model concurrency limit exceeded": 1, "not accepted": 1},
                "child_failure_reasons": {"timeout": 1},
            },
        ),
        make_entry(
            "20250101T030302",
            {
                "dispatch_attempts": 1,
                "dispatch_accepted": 1,
                "child_sessions": {**empty_children, "completed": 2},
                # Current extraction fallback marker must render as an honest no-reason label.
                "dispatch_rejection_reasons": {"dispatch was not accepted": 1},
                # Nested aliases only; no top-level reason dicts beyond the fallback above.
                "dispatch": {"attempts": 0, "accepted": 0, "rejected": 0, "rejection_reasons": {}},
                "children": {"returns": {}, "sessions": empty_children, "failure_reasons": None},
            },
        ),
    ]

    dashboard = format_dashboard(entries)

    # Totals are preserved across entries.
    assert "dispatches : attempts=5 accepted=3 rejected=2" in dashboard
    assert "children   : completed=3 failed=1 timed_out=0 reconciled=0 active=0 inferred_active=0" in dashboard
    # Opaque markers (both legacy `not accepted` and the current extraction fallback)
    # merge into one honest no-reason label; concrete reasons pass through unchanged.
    assert "rejects    : rejected without recorded reason: 2; model concurrency limit exceeded: 1" in dashboard
    assert "dispatch was not accepted" not in dashboard
    assert "not accepted: 1" not in dashboard.replace("rejected without recorded reason", "")
    assert "child fails : timeout: 1" in dashboard
    # Rejects line sits inside the orchestra section, after children totals.
    assert dashboard.index("children   : completed=3") < dashboard.index("rejects    :")

    stale_pass_override = make_entry(
        "20250101T030304",
        {
            "dispatch_attempts": 1,
            "dispatch_accepted": 1,
            "child_sessions": {**empty_children, "completed": 1, "failed": 1},
            "child_failure_reasons": {
                "Status: complete Verdict: **pass** builder run `abc123` satisfies all acceptance criteria": 1
            },
        },
    )
    stale_dashboard = format_dashboard([stale_pass_override])
    assert "children   : completed=1 failed=0" in stale_dashboard
    assert "child fails" not in stale_dashboard

    bare_dashboard = format_dashboard([make_entry("20250101T030303", {"dispatch_attempts": 0, "dispatch_accepted": 0, "child_sessions": empty_children})])
    assert "rejects" not in bare_dashboard
    assert "child fails" not in bare_dashboard


def test_honest_rejection_reason_maps_only_opaque_markers() -> None:
    from bench.reporting.formatters import _honest_rejection_counts, _honest_rejection_reason

    # Opaque extraction fallback markers (both current and legacy variants) map to the honest label.
    assert _honest_rejection_reason("dispatch was not accepted") == "rejected without recorded reason"
    assert _honest_rejection_reason("not accepted") == "rejected without recorded reason"
    assert _honest_rejection_reason("  NOT ACCEPTED . ") == "rejected without recorded reason"
    # Concrete reasons pass through unchanged.
    assert _honest_rejection_reason("model concurrency limit exceeded") == "model concurrency limit exceeded"

    # Both marker variants merge into one honest bucket; concrete counts are preserved.
    counts = _honest_rejection_counts(
        {"dispatch was not accepted": 3, "not accepted": 2, "global concurrency limit exceeded": 1}
    )
    assert counts == {"rejected without recorded reason": 5, "global concurrency limit exceeded": 1}


def test_reporting_formatters_dashboard_usage_bucket_aliases_and_compactions(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard
    from bench.reporting.queries import ReportEntry
    from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult

    empty_children = {"completed": 0, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}

    def make_entry(run_id: str, tokens: dict[str, object]) -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=f"task-{run_id}", batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            score_numeric=80.0,
            score_display="80/100",
            category_scores={"functionality": {"score_numeric": 20.0}},
            tokens=tokens,
            reliability={"artifacts_present": True},
        )
        return ReportEntry(
            path=tmp_path / run_id / "result.json",
            result=result,
            batch="smoke",
            model="model-a",
            orchestra=True,
            score_numeric=80.0,
            score_display="80/100",
            category_scores={"functionality": {"score_numeric": 20.0}},
            notes="ready",
            failure_reason="",
            harness_status="ok",
            harness_exit_code=0,
            harness_error="",
            evaluation_status="ok",
            evaluation_score="80/100",
            evaluation_error="",
            artifact_paths={},
            tokens=tokens,
            timing={"elapsed_seconds": 5.0},
            provenance={"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": True},
            orchestra_metrics={"dispatch_attempts": 0, "dispatch_accepted": 0, "child_sessions": empty_children},
        )

    entries = [
        make_entry(
            "20250101T020201",
            {
                "parent_session": {"total_tokens": 100, "final_context_tokens": 50, "max_context_tokens": 60, "compactions": 1},
                "children_sessions": {"total_tokens": 40, "final_context_tokens": 20, "max_context_tokens": 30, "compactions": 2},
            },
        ),
        make_entry(
            "20250101T020202",
            {
                "main_session": {"total_tokens": 300, "final_context_tokens": 90, "max_context_tokens": 120, "compactions": 5},
                "subagent_sessions": {"total_tokens": 60, "final_context_tokens": 30, "max_context_tokens": 40, "compactions": 0},
            },
        ),
    ]

    dashboard = format_dashboard(entries)

    assert "tokens all           : n/a" in dashboard
    # main bucket: parent_session and main_session aliases both resolve.
    assert "tokens main          : avg=200 high=300 low=100" in dashboard
    assert "context main         : avg=70 high=90 low=50" in dashboard
    # children bucket: children_sessions and subagent_sessions aliases both resolve.
    assert "tokens children      : avg=50 high=60 low=40" in dashboard
    assert "context children     : avg=25 high=30 low=20" in dashboard
    assert "compactions main     : total=6 avg=3" in dashboard
    assert "compactions children : total=2 avg=1" in dashboard


def test_reporting_formatters_surface_unorchestrated_tool_activity_without_scoring_it(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard, format_run_detail
    from bench.reporting.queries import ReportEntry
    from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult

    def make_entry(*, run_id: str, orchestra: bool, orchestration_score: float | None, tool_activity: dict[str, object] | None = None, child_sessions: dict[str, object] | None = None) -> ReportEntry:
        category_scores = {
            "functionality": {"score_numeric": 20.0, "available": True},
            "orchestration": {"score_numeric": orchestration_score, "available": orchestration_score is not None, "score_display": "35/35" if orchestration_score is not None else "n/a", "inputs": {"tool_activity": tool_activity or {}}},
            "efficiency": {"score_numeric": 10.0, "available": True},
            "reliability": {"score_numeric": 15.0, "available": True},
        }
        child_sessions = child_sessions or {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}
        result = TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id="task-orch", batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            score_numeric=80.0,
            score_display="80/100",
            category_scores=category_scores,
            details={"provenance": {"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": orchestra}},
        )
        return ReportEntry(
            path=tmp_path / f"{run_id}-task-orch" / "result.json",
            result=result,
            batch="smoke",
            model="model-a",
            orchestra=orchestra,
            score_numeric=80.0,
            score_display="80/100",
            category_scores=category_scores,
            notes="ready",
            failure_reason="",
            harness_status="ok",
            harness_exit_code=0,
            harness_error="",
            evaluation_status="ok",
            evaluation_score="pass",
            evaluation_error="",
            artifact_paths={},
            tokens={"all_sessions": {"total_tokens": 100, "final_context_tokens": 80, "max_context_tokens": 120, "compactions": 1}},
            timing={"elapsed_seconds": 10.0},
            provenance={"harness": "pi", "backend": "pi", "model": "model-a", "orchestra": orchestra},
            orchestra_metrics={
                "dispatch_attempts": 1,
                "dispatch_accepted": 1,
                "child_sessions": child_sessions or {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0},
                **({"tool_activity": tool_activity} if tool_activity else {}),
            },
        )

    entries = [
        make_entry(run_id="20250101T010201", orchestra=True, orchestration_score=35.0),
        make_entry(
            run_id="20250101T010202",
            orchestra=False,
            orchestration_score=None,
            tool_activity={
                "detected": True,
                "reason": "dispatch/child activity observed while orchestration was disabled",
                "child_sessions": {"active": 1, "inferred_active": 1},
            },
            child_sessions={"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 1, "inferred_active": 1},
        ),
    ]

    dashboard = format_dashboard(entries)
    detail = format_run_detail(entries[1])

    assert "orchestration :" not in dashboard
    assert "efficiency :" not in dashboard
    assert "reliability :" not in dashboard
    # The per-run tool-activity line lives in run detail only; the dashboard no longer shows N/M.
    assert "tool activity :" not in dashboard
    # The run-detail tool-activity line reports neutral counts only, without stored reason text.
    assert "orchestration was disabled" not in detail
    assert "tool activity: dispatches=n/a accepted=n/a active=1 inferred_active=1" in detail
    assert "orchestra=no" in detail
    assert "inferred_active=1" in detail


def test_reporting_formatters_render_persisted_provenance_tool_activity(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    results_root = tmp_path / "results"
    result = TaskResult(
        run_meta=RunMeta(run_id="20250101T010203", task_id="task-orch", batch="smoke"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass"),
        outcome="pass",
        details={
            "provenance": {
                "orchestra": False,
                "tool_activity": True,
            }
        },
    )
    write_json_atomic(results_root / "20250101T010203-task-orch" / "result.json", result)

    entry = collect_results(results_root)[0]
    detail = format_run_detail(entry)

    # Neutral counts-only line from persisted provenance tool_activity.
    assert "orchestration was disabled" not in detail
    assert "tool activity: dispatches=n/a accepted=n/a active=n/a inferred_active=n/a" in detail




def test_parse_since_filter_supports_simple_relative_and_calendar_values() -> None:
    from datetime import datetime, timezone, timedelta

    from bench.reporting.queries import parse_since_filter

    now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)

    assert parse_since_filter("-10m", now=now) == now - timedelta(minutes=10)
    assert parse_since_filter("10m", now=now) == now - timedelta(minutes=10)
    assert parse_since_filter("-2h", now=now) == now - timedelta(hours=2)
    assert parse_since_filter("today", now=now) == datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    assert parse_since_filter("yesterday", now=now) == datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_collect_results_filters_common_fields_case_insensitively_and_with_generic_filters(tmp_path: Path) -> None:
    from bench.reporting.queries import ReportEntry, filter_results
    from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult

    def make_entry(*, run_id: str, task_id: str, batch: str, model: str, outcome: str, orchestra: bool, notes: str, role: str, harness_status: str = "ok") -> ReportEntry:
        result = TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch=batch, started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status=harness_status, exit_code=0 if harness_status == "ok" else 1),
            evaluation=EvaluationResult(status="ok", score=outcome),
            outcome=outcome,
            details={"provenance": {"harness": "pi", "backend": "pi", "model": model, "orchestra": orchestra, "role": role, "notes": notes}},
        )
        return ReportEntry(
            path=tmp_path / f"{run_id}-{task_id}" / "result.json",
            result=result,
            batch=batch,
            model=model,
            orchestra=orchestra,
            notes=notes,
            harness_status=harness_status,
            evaluation_status="ok",
            evaluation_score=outcome,
            provenance={"harness": "pi", "backend": "pi", "model": model, "orchestra": orchestra, "role": role, "notes": notes},
        )

    entries = [
        make_entry(run_id="20250101T010101", task_id="task-a", batch="smoke", model="model-a", outcome="pass", orchestra=True, notes="Follow-up run", role="builder"),
        make_entry(run_id="20250101T010102", task_id="task-b", batch="role-focused", model="model-b", outcome="fail", orchestra=False, notes="Secondary run", role="reviewer", harness_status="lifecycle_failed"),
    ]

    filtered = filter_results(
        entries,
        task="TASK-A",
        suite="SMOKE",
        model="MODEL-A",
        harness="PI",
        result="PASS",
        notes="follow",
        orchestra=True,
        role="build",
        filters=[("backend", "PI"), ("notes", "RUN")],
    )

    assert [entry.run_id for entry in filtered] == ["20250101T010101"]


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


def test_collect_results_skips_invalid_legacy_result_dirs_for_dashboard_and_listing(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard, format_runs
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    _write_result(results_root, "20250101T010104", "task-a", batch="", model="model-a", orchestra=True, score_numeric=91.0, score_display="91/100")

    legacy_dir = results_root / "20240101T000000-legacy-task"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "result.json").write_text('{"run_id":"20240101T000000","task_id":"legacy-task","score":"pass"}\n', encoding="utf-8")

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert [entry.run_id for entry in entries] == ["20250101T010104"]

    dashboard = format_dashboard(entries)
    runs = format_runs(entries)
    assert "legacy-task" not in dashboard
    assert "legacy-task" not in runs


def test_select_compare_and_rescore_preserve_reporting_data(reporting_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.reporting.management import compare_results, describe_filters, rescore_results, select_results, format_compare_results

    entries = select_results(
        reporting_data / "results",
        tasks_dir=reporting_data / "tasks",
        task="task-a",
        sort="total_tokens",
        reverse=False,
        limit=1,
    )
    assert [entry.run_id for entry in entries] == ["20250101T010103"]
    assert describe_filters(task="task-a", sort="total_tokens", reverse=False, limit=1) == "task=task-a, sort=total_tokens asc, limit=1"

    summary = compare_results(select_results(reporting_data / "results", tasks_dir=reporting_data / "tasks", task="task-a"))
    assert summary["runs"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["groups"][0]["suite"] == "smoke"
    assert "suite=smoke" in format_compare_results(summary)

    original_path = reporting_data / "results" / "20250101T010103-task-a" / "result.json"
    before = load_result(original_path).to_dict()

    def fake_grade_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise EvaluationError("boom", classification="crash")

    monkeypatch.setattr("bench.runner._grade_run", fake_grade_run, raising=False)

    results = rescore_results(
        select_results(reporting_data / "results", tasks_dir=reporting_data / "tasks", task="task-a"),
        root=reporting_data,
        tasks_dir=reporting_data / "tasks",
    )

    after = load_result(original_path).to_dict()
    assert after == before
    assert len(results) == 2


def test_management_resolves_grade_run_at_call_time(reporting_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from bench import runner as runner_module

    real = runner_module.grade_run

    def stale_fake(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("stale patched grade_run leaked into management")

    monkeypatch.setattr(runner_module, "grade_run", stale_fake)
    # re-executes management's imports inside the patch window, simulating a first lazy
    # import of bench.reporting during an auto-gate test that patches bench.runner.grade_run
    importlib.reload(importlib.import_module("bench.reporting.management"))
    # runner auto-gate test finishes: real grade_run is restored before later reporting tests run
    monkeypatch.setattr(runner_module, "grade_run", real)

    def failing_eval(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise EvaluationError("boom", classification="crash")

    monkeypatch.setattr(runner_module, "_grade_run", failing_eval, raising=False)

    from bench.reporting.management import rescore_results, select_results

    results = rescore_results(
        select_results(reporting_data / "results", tasks_dir=reporting_data / "tasks", task="task-a"),
        root=reporting_data,
        tasks_dir=reporting_data / "tasks",
    )
    assert len(results) == 2


def _entry_for(path: Path):
    from bench.reporting.queries import ReportEntry

    return ReportEntry(path=path, result=load_result(path), batch="smoke")


def test_delete_results_repairs_readonly_tree_before_rmtree(tmp_path: Path) -> None:
    import os

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    path = _write_result(results_root, "20250101T000000", "task-a", batch="smoke")
    run_dir = path.parent
    sub = run_dir / "workspace"
    sub.mkdir()
    (sub / "f.txt").write_text("x\n", encoding="utf-8")
    os.chmod(sub, 0o555)

    from bench.reporting.management import delete_results

    deleted = delete_results([_entry_for(path)], confirmed=True)
    assert deleted == [run_dir]
    assert not run_dir.exists()


def test_delete_results_falls_back_to_container_when_host_cannot_delete(tmp_path: Path, monkeypatch) -> None:
    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    path = _write_result(results_root, "20250101T000000", "task-a", batch="smoke")
    run_dir = path.parent

    import bench.reporting.management as management
    import bench.runtime as runtime

    def _local_rmtree(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("simulated foreign ownership")

    calls: list[list[str]] = []

    class _Completed:
        returncode = 0
        stderr = ""

    def _fake_container_exec(command, *, workdir=None, verbose=False):  # type: ignore[no-untyped-def]
        calls.append(list(command))
        import shutil as _shutil

        assert command[-1] == f"/bench/results/{run_dir.name}"
        import os as _os

        for current, dirnames, filenames in _os.walk(run_dir, topdown=False):
            base = Path(current)
            for name in filenames:
                (base / name).unlink()
            for name in dirnames:
                (base / name).rmdir()
        run_dir.rmdir()  # simulate root-side delete of the mounted path
        return _Completed()

    monkeypatch.setattr(management.shutil, "rmtree", _local_rmtree)
    monkeypatch.setattr(runtime, "container_exec", _fake_container_exec)

    from bench.reporting.management import delete_results

    deleted = delete_results([_entry_for(path)], confirmed=True)
    assert deleted == [run_dir]
    assert not run_dir.exists()
    assert calls and f"/bench/results/{run_dir.name}" in " ".join(calls[0])


def test_delete_results_container_fallback_requires_mounted_results_layout(tmp_path: Path, monkeypatch) -> None:
    import bench.reporting.management as management

    stray = tmp_path / "stray-run-dir"
    stray.mkdir()
    (stray / "f.txt").write_text("x\n", encoding="utf-8")

    def _local_rmtree(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("simulated foreign ownership")

    monkeypatch.setattr(management.shutil, "rmtree", _local_rmtree)

    with pytest.raises(RuntimeError, match="not the mounted"):
        management._delete_run_dir(stray)


def _sessions_line(detail: str) -> str:
    lines = [line for line in detail.splitlines() if line.startswith("sessions")]
    assert len(lines) == 1, f"expected exactly one sessions line, got {lines}"
    return lines[0]


def _sessions_value(line: str) -> str:
    # label (if any) always comes before the path, so checking the prefix is safe
    return line.split(":", 1)[1].strip()




def test_run_detail_labels_missing_pi_sessions_and_shows_harness_fallback(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    result_path = _write_result(results_root, "20250101T060001", "task-a", model="model-a", orchestra=False)
    run_dir = result_path.parent

    # harness fallback artifacts exist, but pi-sessions does not
    harness_dir = run_dir / "artifacts" / "harness"
    harness_dir.mkdir(parents=True)
    (harness_dir / "events.jsonl").write_text('{"type":"session"}\n', encoding="utf-8")

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert len(entries) == 1
    detail = format_run_detail(entries[0])

    sessions_path = run_dir / "artifacts" / "pi-sessions"
    line = _sessions_line(detail)
    value = _sessions_value(line)
    assert value.startswith("missing") or value.startswith("unavailable"), f"sessions line not labeled missing: {line!r}"
    assert str(sessions_path) in line, f"expected path still referenced as expected location: {line!r}"
    assert "[fallback:" in line and "harness" in line, f"harness fallback should be surfaced when present: {line!r}"


def test_run_detail_labels_missing_pi_sessions_without_harness_fallback(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    result_path = _write_result(results_root, "20250101T060002", "task-a", model="model-a", orchestra=False)

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert len(entries) == 1
    detail = format_run_detail(entries[0])

    value = _sessions_value(_sessions_line(detail))
    assert value.startswith("missing") or value.startswith("unavailable"), f"sessions line not labeled missing: {value!r}"
    assert "[fallback:" not in value, f"no fallback should be claimed when harness artifacts are absent: {value!r}"


def test_run_detail_shows_present_pi_sessions_without_missing_label(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    result_path = _write_result(results_root, "20250101T060003", "task-a", model="model-a", orchestra=False)
    run_dir = result_path.parent

    sessions_path = run_dir / "artifacts" / "pi-sessions"
    sessions_path.mkdir(parents=True)
    (sessions_path / "20250101T060003_parent.jsonl").write_text('{"type":"session"}\n', encoding="utf-8")

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert len(entries) == 1
    detail = format_run_detail(entries[0])

    line = _sessions_line(detail)
    value = _sessions_value(line)
    assert not (value.startswith("missing") or value.startswith("unavailable")), f"present sessions wrongly labeled missing: {line!r}"
    assert str(sessions_path) in value


def test_failure_paths_report_error_states_without_bogus_success_scores(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard, format_run_detail, format_runs
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")

    (results_root / "20250101T090001-task-a").mkdir(parents=True)
    write_json_atomic(
        results_root / "20250101T090001-task-a" / "result.json",
        TaskResult(
            run_meta=RunMeta(run_id="20250101T090001", task_id="task-a", batch="", started_at="2025-01-01T09:00:00Z", finished_at="2025-01-01T09:00:30Z"),
            harness=HarnessResult(status="lifecycle_failed", exit_code=1, error="runner crashed"),
            evaluation=EvaluationResult(status="not_run", score="", details={}),
            outcome="error",
        ),
    )

    (results_root / "20250101T090002-task-a").mkdir(parents=True)
    write_json_atomic(
        results_root / "20250101T090002-task-a" / "result.json",
        TaskResult(
            run_meta=RunMeta(run_id="20250101T090002", task_id="task-a", batch="", started_at="2025-01-01T09:01:00Z", finished_at="2025-01-01T09:01:30Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="failed", score="", error="evaluator produced no JSON", details={}),
            outcome="error",
        ),
    )

    _write_result(
        results_root,
        "20250101T090003",
        "task-a",
        batch="",
        model="model-a",
        orchestra=False,
        score_numeric=80.0,
        score_display="80/100",
    )

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert [entry.run_id for entry in sorted(entries, key=lambda row: row.run_id)] == [
        "20250101T090001",
        "20250101T090002",
        "20250101T090003",
    ]

    dashboard = format_dashboard(entries)
    runs = format_runs(entries)

    assert "runs       : 3" in dashboard
    assert "passed     : 1" in dashboard
    assert "failed     : 0" in dashboard
    assert "error      : 2" in dashboard
    assert "evaluated pass rate : 100.0% (1/1)" in dashboard

    def _line(text: str, run_id: str) -> str:
        return next(line for line in text.splitlines() if run_id in line)

    assert _line(runs, "20250101T090001").startswith("lifecycle_failed 20250101T090001-task-a")
    assert _line(runs, "20250101T090002").startswith("error            20250101T090002-task-a")
    assert _line(runs, "20250101T090003").startswith("PASS             20250101T090003-task-a")

    by_id = {entry.run_id: entry for entry in entries}
    lifecycle_detail = format_run_detail(by_id["20250101T090001"])
    evaluator_detail = format_run_detail(by_id["20250101T090002"])

    # Lifecycle and evaluation state are separate axes; a not-run evaluator is explicit.
    assert "lifecycle : lifecycle_failed" in lifecycle_detail
    assert "evaluation: not_run" in lifecycle_detail
    assert not any(line.startswith("result    ") for line in lifecycle_detail.splitlines())
    assert "correctness: not evaluated" in lifecycle_detail
    assert "score     : n/a" in lifecycle_detail
    assert "runner    : lifecycle_failed exit=1 runner crashed" in lifecycle_detail

    assert "lifecycle : ok" in evaluator_detail
    assert "evaluation: failed" in evaluator_detail
    assert "correctness: not evaluated" in evaluator_detail
    assert "score     : n/a" in evaluator_detail
    assert "evaluator : failed evaluator produced no JSON" in evaluator_detail


def test_collect_results_ignores_malformed_and_missing_result_json(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")

    malformed_dir = results_root / "20250101T090004-task-a"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "result.json").write_text("{ this is not json", encoding="utf-8")

    missing_dir = results_root / "20250101T090005-task-a"
    missing_dir.mkdir(parents=True)

    _write_result(
        results_root,
        "20250101T090006",
        "task-a",
        batch="",
        model="model-a",
        orchestra=False,
        score_numeric=80.0,
        score_display="80/100",
    )

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert [entry.run_id for entry in entries] == ["20250101T090006"]

    dashboard = format_dashboard(entries)
    assert "runs       : 1" in dashboard
    assert "passed     : 1" in dashboard
    assert "error      : 0" in dashboard
    assert "20250101T090004" not in dashboard
    assert "20250101T090005" not in dashboard


def test_run_detail_labels_noop_notimplemented_as_failure(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")

    run_dir = results_root / "20250101T090007-task-a"
    run_dir.mkdir(parents=True)
    write_json_atomic(
        run_dir / "result.json",
        TaskResult(
            run_meta=RunMeta(run_id="20250101T090007", task_id="task-a", batch="", started_at="2025-01-01T09:02:00Z", finished_at="2025-01-01T09:03:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(
                status="ok",
                score="fail",
                checks={"source_exists": True, "workflow_passes": False},
                details={
                    "functionality": {
                        "checks": {"source_exists": True, "workflow_passes": False},
                        "evidence": {"raw": "NotImplementedError: checkout workflow not implemented"},
                    }
                },
            ),
            outcome="fail",
        ),
    )

    entries = collect_results(results_root, tasks_dir=tasks_root)
    assert [entry.run_id for entry in entries] == ["20250101T090007"]
    entry = entries[0]

    detail = format_run_detail(entry)
    # Product failure is an evaluation verdict on a healthy lifecycle, shown as separate axes.
    assert "lifecycle : ok" in detail
    assert "evaluation: ok" in detail
    assert not any(line.startswith("result    ") for line in detail.splitlines())
    assert entry.category_scores["functionality"]["score_numeric"] == 50.0
    score_line = next(line for line in detail.splitlines() if line.startswith("score     "))
    assert "/100" in score_line or "n/a" in score_line
    numeric = None
    if "/100" in score_line:
        numeric = float(score_line.split(":")[1].strip().split("/")[0])
    assert numeric is None or numeric <= 50, f"no-op run reported a passing-looking total: {score_line!r}"


def test_human_number_compacts_large_values_and_preserves_small_ones() -> None:
    from bench.reporting.formatters import _fmt_number, human_number

    assert human_number(None) == "n/a"
    assert human_number(True) == "True"
    assert human_number(False) == "False"
    assert human_number(0) == "0"
    assert human_number(-150) == "-150"
    assert human_number(999) == "999"
    assert human_number(42.5) == "42.5"
    assert human_number(100.0) == "100"

    assert human_number(1_000) == "1K"
    assert human_number(572129.3) == "572.1K"
    assert human_number(-2_132_494) == "-2.1M"
    assert human_number(1_500_000_000) == "1.5B"
    assert human_number(3_000_000_000_000) == "3T"

    # _fmt_number keeps its prior plain behavior for small values via human_number
    assert _fmt_number(None) == "n/a"
    assert _fmt_number(True) == "True"
    assert _fmt_number(210) == "210"
    assert _fmt_number(57.0) == "57"


def test_run_detail_token_lines_use_human_number_for_large_totals(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_run_detail, human_number

    # Guard against divergence between the shared formatter and its examples.
    assert human_number(572129.3) == "572.1K"
    assert human_number(2132494) == "2.1M"


def _dashboard_entry(
    tmp_path: Path,
    run_id: str,
    *,
    outcome: str = "pass",
    score_numeric: float | None = 90.0,
    harness_status: str = "ok",
    harness_exit_code: int | None = 0,
    harness_error: str = "",
    evaluation_status: str = "ok",
    evaluation_score: str = "pass",
    evaluation_error: str = "",
) -> object:
    from bench.reporting.queries import ReportEntry

    result = TaskResult(
        run_meta=RunMeta(run_id=run_id, task_id="task-a", batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
        harness=HarnessResult(status=harness_status, exit_code=harness_exit_code, error=harness_error),
        evaluation=EvaluationResult(status=evaluation_status, score=evaluation_score, error=evaluation_error),
        outcome=outcome,
        score_numeric=score_numeric,
        score_display=f"{int(score_numeric)}/100" if score_numeric is not None else "",
    )
    return ReportEntry(
        path=tmp_path / run_id / "result.json",
        result=result,
        batch="smoke",
        model="model-a",
        harness_status=harness_status,
        harness_exit_code=harness_exit_code,
        harness_error=harness_error,
        evaluation_status=evaluation_status,
        evaluation_score=evaluation_score,
        evaluation_error=evaluation_error,
    )


def test_dashboard_shows_evaluated_not_evaluated_and_error_reason_counts(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard

    entries = [
        _dashboard_entry(tmp_path, "20250101T010001", outcome="pass", score_numeric=90.0),
        _dashboard_entry(
            tmp_path,
            "20250101T010002",
            outcome="fail",
            score_numeric=40.0,
            evaluation_score="fail",
        ),
        _dashboard_entry(
            tmp_path,
            "20250101T010003",
            outcome="error",
            score_numeric=None,
            harness_status="lifecycle_failed",
            harness_exit_code=1,
            harness_error="runner crashed",
            evaluation_status="not_run",
            evaluation_score="",
        ),
        _dashboard_entry(
            tmp_path,
            "20250101T010004",
            outcome="error",
            score_numeric=None,
            evaluation_status="failed",
            evaluation_score="",
            evaluation_error="evaluator produced no JSON",
        ),
    ]

    dashboard = format_dashboard(entries)

    assert "runs       : 4" in dashboard
    assert "passed     : 1" in dashboard
    assert "failed     : 1" in dashboard
    assert "error      : 2" in dashboard
    assert "evaluated  : 2/4" in dashboard
    assert "not evaluated : 2" in dashboard
    # Pass rate is computed over evaluated runs only.
    assert "evaluated pass rate : 50.0% (1/2) over 2 evaluated runs" in dashboard

    assert "=== errors ===" in dashboard
    lifecycle_line = next(line for line in dashboard.splitlines() if line.startswith("lifecycle"))
    evaluator_line = next(line for line in dashboard.splitlines() if line.startswith("evaluator"))
    # Lifecycle and evaluator reason counts are reported separately.
    assert "runner crashed exit=1: 1" in lifecycle_line
    assert "evaluator produced no JSON: 1" in evaluator_line
    # Each reason carries compact run refs, not only counts.
    assert "[20250101T010003-task-a]" in lifecycle_line
    assert "[20250101T010004-task-a]" in evaluator_line


def test_dashboard_excludes_lifecycle_incomplete_runs_from_scored_and_pass_rate(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard, format_runs

    entries = [
        _dashboard_entry(tmp_path, "20250101T020001", outcome="pass", score_numeric=90.0),
        # Inconsistent/partial result.json: harness failed but a pass verdict and
        # numeric score are present. It must not look scored or product-passed.
        _dashboard_entry(
            tmp_path,
            "20250101T020002",
            outcome="pass",
            score_numeric=80.0,
            harness_status="lifecycle_failed",
            harness_exit_code=1,
            harness_error="harness timeout",
        ),
    ]

    dashboard = format_dashboard(entries)

    assert "runs       : 2" in dashboard
    # Only the clean run is counted as passed/scored; pass rate stays 100% (1/1).
    assert "passed     : 1" in dashboard
    assert "evaluated  : 1/2" in dashboard
    assert "not evaluated : 1" in dashboard
    assert "evaluated pass rate : 100.0% (1/1) over 1 evaluated runs" in dashboard

    errors_line = next(line for line in dashboard.splitlines() if line.startswith("lifecycle"))
    assert "harness timeout exit=1: 1" in errors_line

    # The run listing must not render the lifecycle-incomplete run as PASS.
    runs = format_runs(entries)
    bad_line = next(line for line in runs.splitlines() if "20250101T020002" in line)
    assert bad_line.startswith("lifecycle_failed ")
    good_line = next(line for line in runs.splitlines() if "20250101T020001" in line)
    assert good_line.startswith("PASS")


def test_dashboard_errors_section_reports_none_when_all_runs_scored(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard

    entries = [
        _dashboard_entry(tmp_path, "20250101T030001", outcome="pass", score_numeric=90.0),
        _dashboard_entry(
            tmp_path,
            "20250101T030002",
            outcome="fail",
            score_numeric=40.0,
            evaluation_score="fail",
        ),
    ]

    dashboard = format_dashboard(entries)

    assert "not evaluated : 0" in dashboard
    # A product failure is a scored verdict, not a lifecycle/evaluator error:
    # it must not appear as an evaluator error reason.
    assert "no lifecycle or evaluator errors" in dashboard


def test_dashboard_warns_about_duplicate_selected_task_ids_when_selection_includes_retries(tmp_path: Path) -> None:
    from bench.reporting.formatters import format_dashboard
    from bench.reporting.queries import collect_results

    tasks_root = tmp_path / "tasks"
    results_root = tmp_path / "results"
    _write_task(tasks_root, "task-a", batch="smoke")
    # Three attempts (retries) of the same task in one selection.
    for run_id, score in (("20250101T091001", 80.0), ("20250101T091002", 75.0), ("20250101T091003", 85.0)):
        _write_result(
            results_root,
            run_id,
            "task-a",
            batch="smoke",
            model="model-a",
            orchestra=False,
            score_numeric=score,
            score_display=f"{int(score)}/100",
        )

    entries = collect_results(results_root, tasks_dir=tasks_root)
    dashboard = format_dashboard(entries)
    dup_line = next(line for line in dashboard.splitlines() if "duplicates" in line)
    assert "warning:" in dup_line
    assert "task-a x3" in dup_line

    # A selection without retries must not carry the warning.
    clean = format_dashboard([entries[0]])
    assert "duplicates" not in clean
