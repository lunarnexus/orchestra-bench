from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, write_json_atomic


def _write_task_result(results_root: Path, run_id: str, task_id: str, *, orchestra: bool = True) -> Path:
    result = TaskResult(
        run_meta=RunMeta(run_id=run_id, task_id=task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass"),
        outcome="pass",
        details={"provenance": {"orchestra": orchestra}},
    )
    return write_json_atomic(results_root / f"{run_id}-{task_id}" / "result.json", result)


def _session_event(ts: str, *, event_type: str = "message", **payload: object) -> dict[str, object]:
    event: dict[str, object] = {"type": event_type, "timestamp": ts}
    event.update(payload)
    return event


def _write_session(run_dir: Path, filename: str, session_id: str, events: list[dict[str, object]]) -> Path:
    path = run_dir / "artifacts" / "pi-sessions" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "session", "id": session_id, "timestamp": events[0]["timestamp"] if events else "2025-01-01T00:00:00Z"}, *events]
    path.write_text("\n".join(json.dumps(line, sort_keys=True) for line in lines) + "\n", encoding="utf-8")
    return path


def _dispatch_call(role: str, goal: str, task_label: str) -> dict[str, object]:
    return {
        "type": "toolCall",
        "name": "orch_dispatch",
        "arguments": {"role": role, "goal": goal, "taskLabel": task_label},
    }


def _dispatch_result(text: str) -> dict[str, object]:
    return {
        "role": "toolResult",
        "toolName": "orch_dispatch",
        "content": [{"type": "text", "text": text}],
    }


def _summary_text(role: str, session_id: str, status: str, *, extra: str = "") -> str:
    suffix = f"\n{extra}" if extra else ""
    return f"[orchestra: {role} {session_id} {status}]\nsummary: {status}{suffix}"


def test_happy_path_extracts_dispatch_roles_and_parent_signals(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010101", "task-a")
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "user", "content": [{"type": "text", "text": "I've sent the request and I'm waiting for a response before proceeding further."}]},
            ),
            _session_event(
                "2025-01-01T00:00:04Z",
                message={"role": "user", "content": [{"type": "text", "text": "[orchestra: builder abc123 success]\nsummary: pass"}]},
            ),
            _session_event(
                "2025-01-01T00:00:05Z",
                message={"role": "assistant", "content": [{"type": "text", "text": "advance the plan using this subagent return"}]},
            ),
            _session_event(
                "2025-01-01T00:00:06Z",
                message={"role": "assistant", "content": [{"type": "text", "text": "Final summary: done."}]},
            ),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 1
    assert metrics["dispatch_rejected"] == 0
    assert metrics["roles_requested"] == ["builder"]
    assert metrics["roles_started"] == ["builder"]
    assert metrics["roles_returned"] == ["builder"]
    assert metrics["child_returns"] == {"ok": 1, "error": 0, "blocker": 0}
    assert metrics["child_sessions"] == {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}
    assert metrics["parent"]["waited"] is True
    assert metrics["parent"]["integrated"] is True
    assert metrics["parent"]["finalized_before_children"] is False
    assert metrics["dispatch"]["attempts"] == 1
    assert metrics["roles"]["requested"] == ["builder"]


def test_rejected_dispatch_counts_reasons_and_does_not_start_child(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010102", "task-b")
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "dispatch was not accepted: model concurrency limit exceeded"}]},
            ),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 0
    assert metrics["dispatch_rejected"] == 1
    assert metrics["dispatch_rejection_reasons"] == {"dispatch was not accepted": 1}
    assert metrics["roles_requested"] == ["builder"]
    assert metrics["roles_started"] == []
    assert metrics["roles_returned"] == []
    assert metrics["child_sessions"] == {"completed": 0, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}


def test_child_failure_and_blocker_are_tracked(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010103", "task-c")
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            ),
            _session_event("2025-01-01T00:00:03Z", message={"role": "user", "content": [{"type": "text", "text": "[orchestra: builder abc123 failed]\nsummary: failed"}]}),
            _session_event("2025-01-01T00:00:04Z", message={"role": "user", "content": [{"type": "text", "text": "[orchestra: reviewer def456 blocker]\nsummary: blocked"}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["child_returns"] == {"ok": 0, "error": 1, "blocker": 1}
    assert metrics["child_sessions"] == {"completed": 0, "failed": 1, "timed_out": 0, "reconciled": 1, "active": 0, "inferred_active": 0}
    assert metrics["roles_returned"] == ["builder", "reviewer"]


def test_child_still_active_reports_active_child(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010104", "task-d")
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "user", "content": [{"type": "text", "text": "I'm waiting for the child to finish."}]},
            ),
        ],
    )
    _write_session(
        run_dir,
        "orchestra-worker-1.jsonl",
        "orchestra-worker-1",
        [
            _session_event("2025-01-01T00:00:02Z", message={"role": "assistant", "content": [{"type": "text", "text": "working"}]}),
            _session_event("2025-01-01T00:00:03Z", message={"role": "assistant", "content": [{"type": "text", "text": "still working"}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 1
    assert metrics["roles_started"] == ["builder"]
    assert metrics["roles_returned"] == []
    assert metrics["child_returns"] == {"ok": 0, "error": 0, "blocker": 0}
    assert metrics["child_sessions"] == {"completed": 0, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 1, "inferred_active": 1}
    assert metrics["parent"]["waited"] is True
    assert metrics["parent"]["finalized_before_children"] is None


def test_returned_children_reconcile_active_children_to_zero(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010104", "task-d")
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "user", "content": [{"type": "text", "text": "I'm waiting for the child to finish."}]},
            ),
            _session_event(
                "2025-01-01T00:00:04Z",
                message={"role": "user", "content": [{"type": "text", "text": "[orchestra: builder abc123 success]\nsummary: pass"}]},
            ),
            _session_event(
                "2025-01-01T00:00:05Z",
                message={"role": "assistant", "content": [{"type": "text", "text": "advance the plan using this subagent return"}]},
            ),
            _session_event(
                "2025-01-01T00:00:06Z",
                message={"role": "assistant", "content": [{"type": "text", "text": "Final summary: done."}]},
            ),
        ],
    )
    _write_session(
        run_dir,
        "orchestra-worker-1.jsonl",
        "orchestra-worker-1",
        [
            _session_event("2025-01-01T00:00:02Z", message={"role": "assistant", "content": [{"type": "text", "text": "working"}]}),
            _session_event("2025-01-01T00:00:03Z", message={"role": "assistant", "content": [{"type": "text", "text": "still working"}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 1
    assert metrics["roles_started"] == ["builder"]
    assert metrics["roles_returned"] == ["builder"]
    assert metrics["child_returns"] == {"ok": 1, "error": 0, "blocker": 0}
    assert metrics["child_sessions"] == {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}
    assert metrics["parent"]["waited"] is True
    assert metrics["parent"]["finalized_before_children"] is False


def test_duplicate_same_slice_dispatch_is_counted(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010105", "task-e")
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:04Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder def456"}]},
            ),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 2
    assert metrics["dispatch_accepted"] == 2
    assert metrics["duplicate_same_slice_dispatches"] == 1
    assert metrics["same_slice_dispatches"] == 1
    assert metrics["roles_requested"] == ["builder"]


def test_non_orchestra_dispatch_activity_is_reported_without_orch_on(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010106", "task-f", orchestra=False)
    run_dir = result_path.parent

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            ),
        ],
    )
    _write_session(
        run_dir,
        "orchestra-worker-1.jsonl",
        "orchestra-worker-1",
        [
            _session_event("2025-01-01T00:00:02Z", message={"role": "assistant", "content": [{"type": "text", "text": "working"}]}),
            _session_event("2025-01-01T00:00:03Z", message={"role": "assistant", "content": [{"type": "text", "text": "still working"}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["tool_activity_without_orch_on"]["detected"] is True
    assert "without /orch on" in metrics["tool_activity_without_orch_on"]["reason"]
    assert metrics["tool_activity_without_orch_on"]["dispatch_attempts"] == 1
    assert metrics["tool_activity_without_orch_on"]["child_sessions"]["active"] == 1
    assert metrics["tool_activity_without_orch_on"]["child_sessions"]["inferred_active"] == 1


def test_aggregate_return_message_counts_each_subagent_return(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010107", "task-g")
    run_dir = result_path.parent

    aggregate_return = (
        "[orchestra: 2 subagents returned]\n"
        "\n"
        "[orchestra: builder abc123 success]\n"
        "summary: Status: complete Verdict: pass\n"
        "tokens: input=10 output=5 reasoning=0 cache_read=0 cache_write=0 cost_usd=0.0\n"
        "next: advance the plan using this subagent return; do not repeat its work\n"
        "\n"
        "[orchestra: verifier def456 success]\n"
        "summary: All checks complete.\n"
        "tokens: input=20 output=8 reasoning=1 cache_read=0 cache_write=0 cost_usd=0.0\n"
    )

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a"), _dispatch_call("verifier", "verify slice-a", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: verifier def456\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event("2025-01-01T00:00:04Z", message={"role": "user", "content": [{"type": "text", "text": aggregate_return}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["roles_requested"] == ["builder", "verifier"]
    assert metrics["roles_started"] == ["builder", "verifier"]
    assert metrics["roles_returned"] == ["builder", "verifier"]
    assert metrics["child_returns"] == {"ok": 2, "error": 0, "blocker": 0}
    assert metrics["child_sessions"] == {"completed": 2, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}


def test_duplicate_aggregate_return_messages_do_not_double_count(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010108", "task-h")
    run_dir = result_path.parent

    aggregate_return = (
        "[orchestra: 2 subagents returned]\n"
        "\n"
        "[orchestra: builder abc123 success]\n"
        "summary: pass\n"
        "\n"
        "[orchestra: verifier def456 success]\n"
        "summary: done\n"
    )

    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event("2025-01-01T00:00:04Z", message={"role": "user", "content": [{"type": "text", "text": aggregate_return}]}),
            _session_event("2025-01-01T00:00:04Z", event_type="message_end", message={"role": "user", "content": [{"type": "text", "text": aggregate_return}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["roles_returned"] == ["builder", "verifier"]
    assert metrics["child_returns"] == {"ok": 2, "error": 0, "blocker": 0}
    assert metrics["child_sessions"]["completed"] == 2


def test_copied_child_sessions_deduplicate_terminal_evidence_by_identity(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T011001", "task-dup-terminal")
    run_dir = result_path.parent

    builder_return = "[orchestra: builder abc123 success]\nsummary: pass\n"
    verifier_return = "[orchestra: verifier def456 success]\nsummary: done\n"

    # Parent pi-session records both dispatches and the aggregate return delivered to it.
    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a"), _dispatch_call("verifier", "verify slice-a", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: verifier def456\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event("2025-01-01T00:00:09Z", message={"role": "user", "content": [{"type": "text", "text": builder_return + verifier_return}]}),
        ],
    )
    # Copied child sessions, each containing duplicated terminal return evidence for both children.
    _write_session(
        run_dir,
        "orchestra-worker-abc123.jsonl",
        "orchestra-worker-abc123",
        [
            _session_event("2025-01-01T00:00:04Z", message={"role": "assistant", "content": [{"type": "text", "text": builder_return}]}),
            _session_event("2025-01-01T00:00:09Z", message={"role": "user", "content": [{"type": "text", "text": builder_return + verifier_return}]}),
        ],
    )
    _write_session(
        run_dir,
        "orchestra-worker-def456.jsonl",
        "orchestra-worker-def456",
        [
            _session_event("2025-01-01T00:00:08Z", message={"role": "assistant", "content": [{"type": "text", "text": verifier_return}]}),
            _session_event("2025-01-01T00:00:09Z", message={"role": "user", "content": [{"type": "text", "text": builder_return + verifier_return}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 2
    assert metrics["dispatch_accepted"] == 2
    # Direct builder and auto-dependent verifier are distinct child records/roles.
    assert metrics["roles_returned"] == ["builder", "verifier"]
    assert metrics["child_returns"] == {"ok": 2, "error": 0, "blocker": 0}
    # Each child run is counted once by stable identity; terminal states are mutually exclusive.
    assert metrics["child_sessions"] == {"completed": 2, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0, "inferred_active": 0}


def test_truncated_child_session_is_active_without_completed(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T011002", "task-truncated")
    run_dir = result_path.parent

    # Both children dispatched and accepted; only the builder return was delivered to the parent.
    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a"), _dispatch_call("verifier", "verify slice-a", "slice-a")]},
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event(
                "2025-01-01T00:00:03Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: verifier def456\nsubagent will auto-return when finished. Do not poll while waiting."}]},
            ),
            _session_event("2025-01-01T00:00:09Z", message={"role": "user", "content": [{"type": "text", "text": "[orchestra: builder abc123 success]\nsummary: pass\n"}]}),
        ],
    )
    # Both child session files exist, but neither contains terminal return evidence (truncated copies).
    _write_session(
        run_dir,
        "orchestra-worker-abc123.jsonl",
        "orchestra-worker-abc123",
        [_session_event("2025-01-01T00:00:04Z", message={"role": "assistant", "content": [{"type": "text", "text": "working on slice-a"}]}),
    ])
    _write_session(
        run_dir,
        "orchestra-worker-def456.jsonl",
        "orchestra-worker-def456",
        [_session_event("2025-01-01T00:00:08Z", message={"role": "assistant", "content": [{"type": "text", "text": "verifying slice-a"}]}),
    ])

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 2
    assert metrics["dispatch_accepted"] == 2
    assert metrics["roles_returned"] == ["builder"]
    # One terminal child, one still-active: never both active and completed for the same identity.
    assert metrics["child_sessions"] == {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 1, "inferred_active": 1}


def _harness_dispatch_events(*, tool_call_id: str | None = "call-1") -> list[dict[str, object]]:
    start: dict[str, object] = {
        "type": "tool_execution_start",
        "timestamp": "2025-01-01T00:00:01Z",
        "toolName": "orch_dispatch",
        "arguments": {"role": "builder", "goal": "implement checkout", "taskLabel": "slice-a"},
    }
    end: dict[str, object] = {
        "type": "tool_execution_end",
        "timestamp": "2025-01-01T00:00:02Z",
        "toolName": "orch_dispatch",
        "result": {"content": [{"type": "text", "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting."}]},
    }
    if tool_call_id is not None:
        start["toolCallId"] = tool_call_id
        end["toolCallId"] = tool_call_id
    return [start, end]


def _write_harness_events(run_dir: Path, events: list[dict[str, object]]) -> Path:
    path = run_dir / "artifacts" / "harness" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def test_harness_only_lifecycle_failure_counts_one_accepted_attempt(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010901", "task-harness-only")
    run_dir = result_path.parent

    events = [*_harness_dispatch_events(), {"type": "error", "timestamp": "2025-01-01T00:00:05Z", "message": "pi exited unexpectedly"}]
    _write_harness_events(run_dir, events)

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["evidence"]["harness_events"] is True
    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 1
    assert metrics["dispatch_rejected"] == 0
    assert metrics["roles_requested"] == ["builder"]
    # The accepted child never returned because the harness died.
    assert metrics["child_sessions"]["inferred_active"] == 1


def test_parent_copy_and_harness_events_deduplicate_by_tool_call_id(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010902", "task-dedup-id")
    run_dir = result_path.parent

    # Copied parent pi-session: same dispatch recorded via assistant toolCall + toolResult.
    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event(
                "2025-01-01T00:00:01Z",
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "orch_dispatch",
                            "id": "call-1",
                            "arguments": {"role": "builder", "goal": "implement checkout", "taskLabel": "slice-a"},
                        }
                    ],
                },
            ),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "toolCallId": "call-1", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            ),
        ],
    )
    # Harness events: same underlying dispatch, same tool call id.
    _write_harness_events(run_dir, _harness_dispatch_events(tool_call_id="call-1"))

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 1
    assert metrics["roles_requested"] == ["builder"]
    assert metrics["roles_started"] == ["builder"]


def test_cross_source_keyless_dispatch_counts_once_and_worker_session_is_descendant(tmp_path: Path) -> None:
    from bench.reporting.orchestra_metrics import extract_orchestra_metrics

    results_root = tmp_path / "results"
    result_path = _write_task_result(results_root, "20250101T010903", "task-dedup-key")
    run_dir = result_path.parent

    # Parent copy without tool call ids: role/goal/task is the stable fallback key.
    _write_session(
        run_dir,
        "parent.jsonl",
        "parent-session",
        [
            _session_event("2025-01-01T00:00:01Z", message={"role": "assistant", "content": [_dispatch_call("builder", "implement checkout", "slice-a")]}),
            _session_event(
                "2025-01-01T00:00:02Z",
                message={"role": "toolResult", "toolName": "orch_dispatch", "content": [{"type": "text", "text": "orchestra dispatched: builder abc123"}]},
            ),
        ],
    )
    # Harness events for the same dispatch, also without tool call ids.
    _write_harness_events(run_dir, _harness_dispatch_events(tool_call_id=None))
    # Copied auto-dependent verifier session: a descendant child, not another parent attempt.
    _write_session(
        run_dir,
        "orchestra-worker-deadbeef.jsonl",
        "orchestra-worker-deadbeef",
        [
            _session_event("2025-01-01T00:00:03Z", message={"role": "assistant", "content": [{"type": "text", "text": "verifying slice-a"}]}),
        ],
    )

    metrics = extract_orchestra_metrics(run_dir)

    assert metrics["dispatch_attempts"] == 1
    assert metrics["dispatch_accepted"] == 1
    assert metrics["roles_requested"] == ["builder"]
    assert metrics["roles_started"] == ["builder"]
