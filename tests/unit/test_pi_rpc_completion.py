"""Completion and overall-budget regressions for Pi RPC."""

import json
import time

import pytest

from bench.harnesses.pi_rpc import PiRpcHarness, _event_runtime_error, _parent_doneish_seen
from test_pi_rpc_harness import _FakeJsonlProcess, _GatedJsonlProcess, _request


def test_thinking_is_not_a_completion_message():
    events = [{"type": "message_update", "assistantMessageEvent": {
        "type": "thinking_delta", "delta": "I must eventually say BENCH_PARENT_DONE",
    }}]
    assert not _parent_doneish_seen(events)


def test_length_error_survives_empty_agent_end():
    events = [
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "length"}},
        {"type": "agent_end"},
    ]
    assert "output limit" in _event_runtime_error(events)
    events.append({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}})
    assert not _event_runtime_error(events)


def test_snapshot_poll_cannot_finish_after_overall_deadline(tmp_path, monkeypatch):
    harness = PiRpcHarness(["pi"])
    harness._request = _request(tmp_path)
    harness._task_deadline = time.monotonic() + 0.02
    harness.events.append(json.loads(DONE))
    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    monkeypatch.setenv("BENCH_ORCHESTRA_QUIET_SECONDS", "0")

    def slow_snapshot():
        time.sleep(0.04)
        return {"active_runs": 0, "descendants_terminal": True}

    monkeypatch.setattr(harness, "_orchestra_status_snapshot", slow_snapshot)
    assert not harness.wait_for_orchestra_children()


def test_reasoning_limit_is_not_successful_settlement(tmp_path):
    process = _FakeJsonlProcess()

    def on_send(command):
        if command.get("type") == "get_state":
            process.chunks.append(json.dumps({"type": "response", "command": "get_state", "success": True, "data": {}}) + "\n")
        elif command.get("type") == "prompt":
            process.chunks.extend(json.dumps(e) + "\n" for e in [
                {"type": "message_end", "message": {"role": "assistant", "stopReason": "length", "content": []}},
                {"type": "agent_end"},
                {"type": "agent_settled"},
            ])
            process.alive = False

    process.on_send = on_send
    result = PiRpcHarness(["pi"], process_factory=lambda **_: process).run(_request(tmp_path))
    assert result.status == "lifecycle_failed"
    assert "output limit" in result.error


def run_delayed_parent(tmp_path, monkeypatch, *, budget, gates, phase_budget):
    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    monkeypatch.setenv("BENCH_ORCHESTRA_QUIET_SECONDS", "0")
    process = _GatedJsonlProcess(gates=gates)

    def on_send(command):
        if command.get("type") == "get_state":
            process.chunks.append(json.dumps({"type": "response", "command": "get_state", "success": True, "data": {}}) + "\n")
        elif command.get("type") == "prompt":
            process.chunks.extend([
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_settled"}\n',
            ])

    process.on_send = on_send
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    monkeypatch.setattr(harness, "_child_wait_seconds", lambda timeout: phase_budget)
    monkeypatch.setattr(harness, "_parent_finalize_window_seconds", lambda: phase_budget)
    started = time.monotonic()
    result = harness.run(_request(tmp_path, timeout_seconds=budget))
    return result, time.monotonic() - started


REPORT = json.dumps({"type": "message", "message": {"role": "user", "content": [
    {"type": "text", "text": "[orchestra: 1 subagents returned]"},
]}}) + "\n"
DONE = json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
    {"type": "text", "text": "BENCH_PARENT_DONE"},
]}}) + "\n"
DISPATCH = '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n'


def test_child_floor_cannot_end_task_before_overall_budget(tmp_path, monkeypatch):
    result, _ = run_delayed_parent(tmp_path, monkeypatch, budget=0.5,
                                   gates=[(0.12, [REPORT, DONE])], phase_budget=0.02)
    assert result.status == "ok"


@pytest.mark.parametrize("gates", [
    [(0.02, [REPORT]), (0.3, [DONE])],
    [(0.02, [REPORT]), (0.04, [DISPATCH]), (0.06, [REPORT]), (0.3, [DONE])],
])
def test_finalize_or_new_dispatch_cannot_extend_overall_budget(tmp_path, monkeypatch, gates):
    result, elapsed = run_delayed_parent(tmp_path, monkeypatch, budget=0.1,
                                         gates=gates, phase_budget=1.0)
    assert result.status == "lifecycle_failed"
    assert elapsed < 0.25
