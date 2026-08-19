"""Tests for bench.orchestration_gate with fake status output."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from bench.orchestration_gate import parse_active_runs, wait_for_settled  # noqa: E402


STATUS_ACTIVE = """session_id: abc123
active_runs: 2/3
global_active_runs: 2/8
model_active_runs:
- lmstudio/qwen/qwen3.8-27b: 2/1
"""

STATUS_IDLE = """session_id: abc123
active_runs: 0/3
global_active_runs: 0/8
status: no active runs
"""


def test_parse_active_runs():
    assert parse_active_runs(STATUS_ACTIVE) == 2
    assert parse_active_runs(STATUS_IDLE) == 0
    assert parse_active_runs("garbage") is None


def _seq_query(values):
    it = iter(values)

    def query():
        return next(it, STATUS_IDLE)

    return query


def test_waits_while_workers_active():
    calls = {"n": 0}

    def query():
        calls["n"] += 1
        return STATUS_ACTIVE if calls["n"] < 3 else STATUS_IDLE

    assert wait_for_settled(query, timeout=5.0, poll_interval=0.05) is True
    assert calls["n"] == 3


def test_timeout_returns_false():
    import time

    started = time.monotonic()
    result = wait_for_settled(lambda: STATUS_ACTIVE, timeout=0.2, poll_interval=0.05)
    assert result is False
    assert time.monotonic() - started < 2.0


def test_query_failure_keeps_polling_then_succeeds():
    state = {"n": 0}

    def query():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("docker hiccup")
        return STATUS_IDLE

    assert wait_for_settled(query, timeout=5.0, poll_interval=0.05) is True
