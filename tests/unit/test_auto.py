from __future__ import annotations

from bench.auto import CompletionPolicy, wait_until_safe_to_grade


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



def test_no_orchestra_settles_on_harness_terminal_state() -> None:
    harness = _Harness()

    result = wait_until_safe_to_grade(harness, policy=CompletionPolicy(orchestra_enabled=False))

    assert result.safe_to_grade is True
    assert result.reason == "harness_terminal"
    assert harness.calls == [None]
    assert result.snapshots == ()



def test_orchestra_requires_status_provider_when_enabled() -> None:
    harness = _Harness()

    result = wait_until_safe_to_grade(harness, policy=CompletionPolicy(orchestra_enabled=True))

    assert result.safe_to_grade is False
    assert result.reason == "missing_status_provider"
    assert harness.calls == [None]



def test_terminal_worker_permits_grading() -> None:
    harness = _Harness()

    result = wait_until_safe_to_grade(
        harness,
        session_id="sess-1",
        status_provider=lambda session_id: "active_runs: 0 / 3\ndescendants_terminal: yes\n",
        policy=CompletionPolicy(orchestra_enabled=True),
    )

    assert result.safe_to_grade is True
    assert result.reason == "settled"
    assert result.snapshots[0].session_id == "sess-1"
    assert result.snapshots[0].active_runs == 0
