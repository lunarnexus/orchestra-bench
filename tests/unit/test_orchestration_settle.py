from __future__ import annotations

from bench.orchestration import (
    coerce_status_snapshot,
    parse_active_runs,
    parse_status_text,
    wait_for_orchestration_settle,
)


class _Harness:
    def __init__(self, *, settled: bool = True, status: str = "settled") -> None:
        self._settled = settled
        self._status = status
        self.calls: list[float | None] = []

    def wait_for_settled(self, timeout: float | None = None) -> bool:
        self.calls.append(timeout)
        return self._settled

    @property
    def last_settle_status(self) -> str:
        return self._status


class _SequenceProvider:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.calls: list[str] = []

    def __call__(self, session_id: str) -> object:
        self.calls.append(session_id)
        index = min(len(self.calls) - 1, len(self.outputs) - 1)
        return self.outputs[index]



def test_parse_active_runs_and_status_text() -> None:
    text = "active_runs: 2 / 5\ndescendants_terminal: no\nsession_report_delivered: yes\n"

    assert parse_active_runs(text) == 2
    snapshot = parse_status_text(text, session_id="sess-1")
    assert snapshot.session_id == "sess-1"
    assert snapshot.active_runs == 2
    assert snapshot.descendants_terminal is False
    assert snapshot.session_report_delivered is True
    assert snapshot.state == "running"
    assert snapshot.parsed is True



def test_coerce_status_snapshot_preserves_raw_text_and_structured_state() -> None:
    snapshot = coerce_status_snapshot(
        "sess-2",
        {"state": "timeout", "raw_text": "timed out", "active_runs": 1, "descendants_terminal": False},
    )

    assert snapshot.session_id == "sess-2"
    assert snapshot.state == "timeout"
    assert snapshot.raw_text == "timed out"
    assert snapshot.active_runs == 1



def test_active_worker_blocks_grading() -> None:
    provider = _SequenceProvider(["active_runs: 1 / 4\ndescendants_terminal: no\n"])

    result = wait_for_orchestration_settle("sess-3", provider, timeout_seconds=0.0)

    assert result.safe_to_grade is False
    assert result.reason == "timeout"
    assert result.snapshots[0].raw_text.startswith("active_runs: 1")
    assert result.snapshots[0].active_runs == 1
    assert provider.calls == ["sess-3"]



def test_terminal_worker_permits_grading() -> None:
    provider = _SequenceProvider(["active_runs: 0 / 4\ndescendants_terminal: yes\n"])

    result = wait_for_orchestration_settle("sess-4", provider, timeout_seconds=1.0)

    assert result.safe_to_grade is True
    assert result.reason == "settled"
    assert result.snapshots[-1].state == "settled"
    assert result.snapshots[-1].active_runs == 0



def test_timeout_returns_unsafe_and_preserves_last_snapshot() -> None:
    provider = _SequenceProvider(["active_runs: 3 / 4\ndescendants_terminal: no\n"])

    result = wait_for_orchestration_settle("sess-5", provider, timeout_seconds=0.0)

    assert result.safe_to_grade is False
    assert result.reason == "timeout"
    assert result.snapshots[-1].active_runs == 3
    assert result.snapshots[-1].raw_text.startswith("active_runs: 3")



def test_missing_and_unparseable_status_are_distinct_failures() -> None:
    missing = wait_for_orchestration_settle("sess-6", lambda _session_id: None, timeout_seconds=1.0)
    unparseable = wait_for_orchestration_settle("sess-7", lambda _session_id: "nonsense", timeout_seconds=1.0)

    assert missing.safe_to_grade is False
    assert missing.reason == "missing_status"
    assert missing.snapshots[-1].state == "missing"

    assert unparseable.safe_to_grade is False
    assert unparseable.reason == "unparseable_status"
    assert unparseable.snapshots[-1].state == "unparseable"



def test_parent_settled_but_child_running_blocks_grading() -> None:
    provider = _SequenceProvider(["active_runs: 1 / 2\ndescendants_terminal: no\n"])

    result = wait_for_orchestration_settle("sess-8", provider, timeout_seconds=0.0)

    assert result.safe_to_grade is False
    assert result.reason == "timeout"
    assert result.snapshots[-1].active_runs == 1
    assert result.snapshots[-1].state == "running"
