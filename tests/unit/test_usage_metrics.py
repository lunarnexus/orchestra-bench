from __future__ import annotations

import json
from pathlib import Path

from bench.reporting.usage_metrics import extract_usage_metrics


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _session(path: Path, session_id: str, *events: dict[str, object]) -> None:
    _write_jsonl(path, [{"type": "session", "id": session_id}, *events])


def _usage(input_tokens: int, output_tokens: int, total_tokens: int) -> dict[str, object]:
    return {"input": input_tokens, "output": output_tokens, "totalTokens": total_tokens}


def test_harness_only_usage_populates_parent_and_all_context_from_input(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "artifacts" / "harness" / "events.jsonl",
        [
            {"type": "message_update", "usage": _usage(100, 10, 110)},
            {"type": "message_update", "usage": _usage(100, 10, 110)},
            {"type": "message_end"},
            {"type": "message_update", "usage": _usage(150, 20, 170)},
            {"type": "message_update", "usage": _usage(150, 20, 170)},
            {"type": "agent_end"},
            {"command": "get_state", "data": {"sessionId": "parent-harness-1"}},
        ],
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["total"] == 280
    assert metrics["session_ids"] == ["parent-harness-1"]
    assert metrics["parent_session_ids"] == ["parent-harness-1"]
    assert metrics["all_sessions"]["total_tokens"] == 280
    assert metrics["parent_session"]["total_tokens"] == 280
    assert metrics["all_sessions"]["api_calls"] == 2
    assert metrics["parent_session"]["final_context_tokens"] == 150
    assert metrics["parent_session"]["max_context_tokens"] == 150
    assert metrics["all_sessions"]["final_context_tokens"] == 150
    assert metrics["all_sessions"]["max_context_tokens"] == 150
    assert metrics["child_session_ids"] == []
    assert metrics["children_sessions"] is None
    assert metrics["all_sessions"]["total_tokens"] == 280
    assert metrics["unavailable_reasons"]["children"] == "no child activity observed in harness events"
    assert "all" not in metrics["unavailable_reasons"]


def test_parent_and_child_pi_sessions_have_separate_buckets_and_ids(tmp_path: Path) -> None:
    sessions = tmp_path / "artifacts" / "pi-sessions"
    _session(
        sessions / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"usage": _usage(100, 20, 120)}},
    )
    _session(
        sessions / "orchestra-worker-child.jsonl",
        "child-1",
        {"type": "message_end", "message": {"usage": _usage(30, 5, 35)}},
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["total"] == 155
    assert metrics["session_ids"] == ["child-1", "parent-1"]
    assert metrics["parent_session_ids"] == ["parent-1"]
    assert metrics["child_session_ids"] == ["child-1"]
    assert metrics["parent_session"]["total_tokens"] == 120
    assert metrics["children_sessions"]["total_tokens"] == 35
    assert metrics["all_sessions"]["total_tokens"] == 155
    assert metrics["sources"] == {"parent": "pi_session", "children": "pi_sessions"}
    assert metrics["unavailable_reasons"] == {}


def test_child_activity_without_readable_child_sessions_does_not_label_parent_as_all(tmp_path: Path) -> None:
    _session(
        tmp_path / "artifacts" / "pi-sessions" / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"usage": _usage(100, 20, 120)}},
    )
    _write_jsonl(
        tmp_path / "artifacts" / "harness" / "events.jsonl",
        [
            {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
            {"command": "get_state", "data": {"sessionId": "parent-1"}},
        ],
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["all_sessions"] is None
    assert metrics["total"] is None
    assert metrics["child_session_ids"] == []
    assert metrics["children_sessions"] is None
    assert metrics["parent_session"]["total_tokens"] == 120
    assert "children" in metrics["unavailable_reasons"]
    assert "all" in metrics["unavailable_reasons"]


def test_failed_child_dispatch_is_not_observed_activity(tmp_path: Path) -> None:
    _session(
        tmp_path / "artifacts" / "pi-sessions" / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"usage": _usage(100, 20, 120)}},
    )
    _write_jsonl(
        tmp_path / "artifacts" / "harness" / "events.jsonl",
        [{"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": True}],
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["all_sessions"] is not None
    assert metrics["total"] == 120
    assert metrics["unavailable_reasons"]["children"] == "no child activity observed in harness events"
    assert "all" not in metrics["unavailable_reasons"]


def test_parent_only_session_without_harness_events_records_evidence_basis(tmp_path: Path) -> None:
    _session(
        tmp_path / "artifacts" / "pi-sessions" / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"usage": _usage(100, 20, 120)}},
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["total"] == 120
    assert metrics["all_sessions"]["total_tokens"] == 120
    assert metrics["unavailable_reasons"] == {
        "children": "no child session files or harness events available"
    }


def test_duplicate_session_ids_are_counted_once(tmp_path: Path) -> None:
    sessions = tmp_path / "artifacts" / "pi-sessions"
    for name in ("parent.jsonl", "parent-copy.jsonl"):
        _session(
            sessions / name,
            "parent-1",
            {"type": "message_end", "message": {"usage": _usage(100, 20, 120)}},
        )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["session_ids"] == ["parent-1"]
    assert metrics["total"] == 120
    assert metrics["all_sessions"]["api_calls"] == 1


def test_parent_pi_session_takes_precedence_over_duplicate_harness_parent(tmp_path: Path) -> None:
    _session(
        tmp_path / "artifacts" / "pi-sessions" / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"usage": _usage(100, 20, 120)}},
    )
    _write_jsonl(
        tmp_path / "artifacts" / "harness" / "events.jsonl",
        [
            {"type": "message_update", "usage": _usage(900, 100, 1000)},
            {"type": "agent_end"},
            {"command": "get_state", "data": {"sessionId": "parent-1"}},
        ],
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["total"] == 120
    assert metrics["parent_session"]["total_tokens"] == 120
    assert metrics["all_sessions"]["total_tokens"] == 120
    assert metrics["sources"]["parent"] == "pi_session"


def test_explicit_compaction_event_increments_compaction_count(tmp_path: Path) -> None:
    _session(
        tmp_path / "artifacts" / "pi-sessions" / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"usage": _usage(100, 10, 110)}},
        {"type": "compaction", "usage": _usage(80, 5, 85)},
        {"type": "message_end", "message": {"usage": _usage(120, 20, 140)}},
    )

    metrics = extract_usage_metrics(tmp_path)

    assert metrics["total"] == 335
    assert metrics["parent_session"]["compactions"] == 1
    assert metrics["all_sessions"]["compactions"] == 1
    assert metrics["parent_session"]["final_context_tokens"] == 120
    assert metrics["parent_session"]["max_context_tokens"] == 120


def test_semantic_usage_boundaries_ignore_tool_results_and_preserve_assistant_context(tmp_path: Path) -> None:
    _session(
        tmp_path / "artifacts" / "pi-sessions" / "parent.jsonl",
        "parent-1",
        {"type": "message_end", "message": {"role": "assistant", "usage": _usage(100, 10, 110)}},
        {"type": "message_end", "message": {"role": "toolResult", "usage": _usage(900, 90, 990)}},
        {"type": "compaction", "usage": _usage(80, 5, 85)},
        {"type": "branch_summary", "usage": _usage(70, 4, 74)},
    )

    metrics = extract_usage_metrics(tmp_path)
    bucket = metrics["parent_session"]

    assert bucket["total_tokens"] == 269
    assert bucket["input_tokens"] == 250
    assert bucket["output_tokens"] == 19
    assert bucket["api_calls"] == 3
    assert bucket["compactions"] == 1
    assert bucket["final_context_tokens"] == 100
    assert bucket["max_context_tokens"] == 100
