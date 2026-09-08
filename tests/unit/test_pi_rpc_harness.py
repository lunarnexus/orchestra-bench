from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from bench.harnesses.base import HarnessArtifactPaths, HarnessRequest
from bench.paths import RunPaths
from bench.workspace import workspace_dir


class _FakeStdin:
    def __init__(self, process: "_FakeJsonlProcess") -> None:
        self.process = process
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeJsonlProcess:
    def __init__(
        self,
        *,
        chunks: list[str] | None = None,
        stderr_chunks: list[str] | None = None,
        exit_code: int = 0,
        wait_timeout: bool = False,
        event_log: list[str] | None = None,
    ) -> None:
        self.stdin = _FakeStdin(self)
        self.chunks = list(chunks or [])
        self.stderr_chunks = list(stderr_chunks or [])
        self.exit_code = exit_code
        self.wait_timeout = wait_timeout
        self.alive = True
        self.killed = False
        self.sent_commands: list[dict[str, object]] = []
        self.event_log = event_log

    def read_chunk(self, timeout: float | None = None) -> str | None:
        if self.chunks:
            chunk = self.chunks.pop(0)
            if self.event_log is not None:
                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                    self.event_log.append(f"read:raw:{chunk.strip()}")
                else:
                    self.event_log.append(f"read:{payload.get('type')}")
            return chunk
        if self.alive:
            return ""
        return None

    def read_stderr_chunk(self, timeout: float | None = None) -> str | None:
        if self.stderr_chunks:
            return self.stderr_chunks.pop(0)
        if self.alive:
            return ""
        return None

    def poll(self) -> int | None:
        return None if self.alive else self.exit_code

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_timeout and self.alive:
            raise subprocess.TimeoutExpired(cmd=["pi"], timeout=timeout)
        self.alive = False
        return self.exit_code

    def kill(self) -> None:
        self.killed = True
        self.alive = False
        self.exit_code = 137

    def on_send(self, command: dict[str, object]) -> None:
        self.sent_commands.append(command)
        if self.event_log is not None:
            message = str(command.get("message") or "")
            self.event_log.append(f"send:{command.get('type')}:{message}")


def _request(
    tmp_path: Path,
    *,
    timeout_seconds: float = 0.2,
    metadata: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
) -> HarnessRequest:
    run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
    return HarnessRequest(
        run_paths=run_paths,
        prompt="Build the thing.",
        timeout_seconds=timeout_seconds,
        env=dict(env or {}),
        artifacts=HarnessArtifactPaths.for_run_paths(run_paths),
        metadata=dict(metadata or {}),
    )


def test_verbose_send_prompt_prints_prompt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    process = _FakeJsonlProcess()
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    harness.start(_request(tmp_path, metadata={"stream_output": True}))

    harness.send_prompt("Line one\nLine two")

    output = capsys.readouterr().out
    assert output == "[bench:pi] prompt >>>\nLine one\nLine two\n[bench:pi] <<< prompt\n"
    assert {"type": "prompt", "message": "Line one\nLine two"} in process.sent_commands


def test_verbose_tool_events_show_input_and_output_previews(capsys: pytest.CaptureFixture[str]) -> None:
    from bench.harnesses import pi_rpc
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pi_rpc, "_VERBOSE_PREVIEW_LINES", 2)
    try:
        harness = PiRpcHarness(["pi"])
        harness._emit_verbose_event(
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "toolcall_end",
                    "toolCall": {"name": "orch_dispatch", "arguments": {"goal": "line1\nline2\nline3"}},
                },
            }
        )
        harness._emit_verbose_event(
            {
                "type": "tool_execution_end",
                "toolName": "orch_dispatch",
                "isError": False,
                "result": {"content": [{"text": "out1\nout2\nout3"}]},
            }
        )
    finally:
        monkeypatch.undo()

    output = capsys.readouterr().out
    assert "[bench:pi] tool ready: orch_dispatch\n" in output
    assert "line1\nline2\n[bench:pi] ... tool input truncated ...\n" in output
    assert "[bench:pi] tool done: orch_dispatch (ok)\n" in output
    assert "out1\nout2\n[bench:pi] ... tool output truncated ...\n" in output


def test_verbose_stream_does_not_insert_blank_spacer_lines(capsys: pytest.CaptureFixture[str]) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    harness = PiRpcHarness(["pi"])
    harness._emit_verbose_event({"type": "agent_start"})
    harness._emit_verbose_event({"type": "turn_start"})
    harness._emit_verbose_event({"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "Thinking"}})
    harness._emit_verbose_event({"type": "tool_execution_start", "toolName": "bash"})
    harness._emit_verbose_event({"type": "tool_execution_end", "toolName": "bash", "isError": False})

    output = capsys.readouterr().out
    assert output == "[bench:pi] agent_start\n[bench:pi] turn_start\nThinking\n[bench:pi] tool exec: bash\n[bench:pi] tool done: bash (ok)\n"
    assert "\n\n" not in output


def test_start_uses_request_workdir_and_minimized_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("LEAK_SECRET", "top-secret")
    request = _request(tmp_path, env={"REQUEST_ONLY": "1"})
    captured: dict[str, object] = {}
    process = _FakeJsonlProcess()

    def factory(**kwargs):
        captured.update(kwargs)
        return process

    harness = PiRpcHarness(["pi"], process_factory=factory, env={"HARNESS_ONLY": "yes"})
    harness.start(request)

    assert captured["cwd"] == workspace_dir(request.run_paths)
    env = captured["env"]
    assert env["HARNESS_ONLY"] == "yes"
    assert env["REQUEST_ONLY"] == "1"
    assert "LEAK_SECRET" not in env


def test_reads_partial_malformed_and_multiple_jsonl_events(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    process = _FakeJsonlProcess(
        chunks=[
            '{"type":"agent_start","message":"boot"}\n{"type":"bad',
            ' json\n{"type":"agent_settled","message":"done"}\n',
        ],
    )
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path)

    harness.start(request)

    first = harness.read_event(timeout=0.0)
    second = harness.read_event(timeout=0.0)
    third = harness.read_event(timeout=0.0)

    assert first == {"type": "agent_start", "message": "boot", "data": {}, "timestamp": ""}
    assert second == {"type": "raw", "line": '{"type":"bad json'}
    assert third == {"type": "agent_settled", "message": "done", "data": {}, "timestamp": ""}
    assert request.artifacts.events_path.read_text(encoding="utf-8").splitlines() == [
        json.dumps(first, sort_keys=True),
        json.dumps(second, sort_keys=True),
        json.dumps(third, sort_keys=True),
    ]


def test_query_state_sends_get_state_and_returns_response(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append(
                '{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n'
            )
            process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path)
    harness.start(request)

    state = harness.query_state(timeout=0.1)

    assert state == {"sessionId": "sess-1"}
    assert process.sent_commands[-1]["type"] == "get_state"
    assert json.loads(request.artifacts.events_path.read_text(encoding="utf-8")) == {
        "command": "get_state",
        "data": {"sessionId": "sess-1"},
        "success": True,
        "type": "response",
    }


def test_stop_drains_remaining_output_after_exit(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    process = _FakeJsonlProcess(chunks=['{"type":"agent_start"}\n', '{"type":"agent_settled"}\n'], exit_code=0)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path)
    harness.start(request)

    assert harness.read_event(timeout=0.0)["type"] == "agent_start"
    process.alive = False

    assert harness.stop() == 0
    assert harness.agent_settled_seen is True
    assert [event["type"] for event in harness.events] == ["agent_start", "agent_settled"]


def test_run_captures_stderr_to_run_log_and_classifies_timeout_missing_settled_and_nonzero_exit(
    tmp_path: Path,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") != "prompt":
            return
        process.stderr_chunks.append("stderr line\n")
        process.chunks.append('{"type":"response","command":"prompt","success":true}\n')
        process.chunks.append('{"type":"agent_start","message":"boot"}\n')

    timeout_request = _request(tmp_path / "timeout", timeout_seconds=0.01)
    timeout_process = _FakeJsonlProcess(wait_timeout=True)
    timeout_process.on_send = lambda command: on_send(timeout_process, command)
    timeout_harness = PiRpcHarness(["pi"], process_factory=lambda **_: timeout_process)
    timeout_result = timeout_harness.run(timeout_request)

    missing_request = _request(tmp_path / "missing", timeout_seconds=0.1)
    missing_process = _FakeJsonlProcess(exit_code=0)
    missing_process.on_send = lambda command: on_send(missing_process, command)
    missing_process.alive = False
    missing_harness = PiRpcHarness(["pi"], process_factory=lambda **_: missing_process)
    missing_result = missing_harness.run(missing_request)

    nonzero_request = _request(tmp_path / "nonzero", timeout_seconds=0.1)
    nonzero_process = _FakeJsonlProcess(exit_code=3)

    def on_send_nonzero(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") != "prompt":
            return
        process.stderr_chunks.append("stderr line\n")
        process.chunks.append('{"type":"response","command":"prompt","success":true}\n')
        process.chunks.append('{"type":"agent_start","message":"boot"}\n')
        process.chunks.append('{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"All set."}]}}\n')
        process.chunks.append('{"type":"agent_settled","message":"done"}\n')
        process.alive = False

    nonzero_process.on_send = lambda command: on_send_nonzero(nonzero_process, command)
    nonzero_harness = PiRpcHarness(["pi"], process_factory=lambda **_: nonzero_process)
    nonzero_result = nonzero_harness.run(nonzero_request)

    assert timeout_result.status == "lifecycle_failed"
    assert timeout_result.error == "timeout waiting for agent_settled"
    assert missing_result.status == "lifecycle_failed"
    assert "agent_settled" in missing_result.error
    assert nonzero_result.status == "lifecycle_failed"
    assert nonzero_result.error == "process exited with exit 3"
    assert timeout_request.artifacts.log_path.read_text(encoding="utf-8") == "stderr line\n"
    assert nonzero_request.artifacts.log_path.read_text(encoding="utf-8") == "stderr line\n"


class _GatedJsonlProcess(_FakeJsonlProcess):
    """Fake process that only releases gated chunks after a monotonic offset."""

    def __init__(self, *, gates: list[tuple[float, list[str]]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._gates = [(time.monotonic() + offset, list(chunks)) for offset, chunks in gates]

    def read_chunk(self, timeout: float | None = None) -> str | None:
        if not self.chunks:
            now = time.monotonic()
            while self._gates and now >= self._gates[0][0]:
                _, gated = self._gates.pop(0)
                self.chunks.extend(gated)
        return super().read_chunk(timeout)


def _sent_prompt_messages(process: _FakeJsonlProcess) -> list[str]:
    messages: list[str] = []
    for raw in process.stdin.writes:
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("type") == "prompt":
            messages.append(str(payload.get("message") or ""))
    return messages


def test_run_sends_orch_on_before_task_prompt_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    event_log: list[str] = []

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        _FakeJsonlProcess.on_send(process, command)
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        if command.get("message") == "/orch on":
            process.chunks.extend(
                [
                    '{"type":"extension_ui_request","message":"Orchestra orchestrator skill refreshed for this session."}\n',
                    '{"type":"agent_settled","message":"orch on settled"}\n',
                ]
            )
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_end","message":"wrap"}\n',
                '{"type":"agent_settled","message":"task settled"}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
                json.dumps({"type": "tool_execution_end", "toolName": "orch_status", "result": {"content": [{"text": json.dumps({"active_runs": 1, "descendants_terminal": False, "session_report_available": True, "session_report_delivered": False})}]}}) + "\n",
                json.dumps({"type": "tool_execution_end", "toolName": "orch_status", "result": {"content": [{"text": json.dumps({"active_runs": 0, "descendants_terminal": True, "session_report_available": True, "session_report_delivered": True})}]}}) + "\n",
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess(event_log=event_log)
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "orch-on", timeout_seconds=0.5, metadata={"orch_on": True})

    result = harness.run(request)

    assert result.status == "ok"
    assert _sent_prompt_messages(process) == ["/orch on", "Build the thing."]
    assert event_log.index("read:agent_settled") < event_log.index("send:prompt:Build the thing.")


def test_run_fails_when_orch_on_activation_success_is_missing(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    request = _request(tmp_path / "orch-on-missing", timeout_seconds=0.01, metadata={"orch_on": True})
    process = _FakeJsonlProcess()
    process.alive = False
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.error == "/orch on activation did not arrive"
    assert result.details["last_settle_status"] == "missing_activation"
    assert _sent_prompt_messages(process) == ["/orch on"]


def test_run_fails_when_orch_on_activation_arrives_but_never_settles(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") == "prompt" and command.get("message") == "/orch on":
            process.chunks.append('{"type":"extension_ui_request","message":"Orchestra orchestrator skill refreshed for this session."}\n')
            process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "orch-on-missing-settle", timeout_seconds=0.5, metadata={"orch_on": True})

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.error == "/orch on activation did not settle"
    assert result.details["last_settle_status"] == "missing_settled"
    assert _sent_prompt_messages(process) == ["/orch on"]


def test_run_skips_orch_on_when_not_requested(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") == "prompt":
            process.chunks.append('{"type":"agent_settled","message":"task settled"}\n')
            process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "no-orch-on", timeout_seconds=0.5)

    result = harness.run(request)

    assert result.status == "ok"
    assert _sent_prompt_messages(process) == ["Build the thing."]


def test_run_without_dispatch_does_not_require_doneish_even_when_status_snapshot_exists(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_status","result":{"content":[{"text":"{\\"active_runs\\":0,\\"descendants_terminal\\":true}"}]}}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"All acceptance criteria are implemented and verified."}]}}\n',
                '{"type":"agent_settled","message":"idle"}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "no-dispatch-status", timeout_seconds=0.5, metadata={"orch_on": False})

    result = harness.run(request)

    assert result.status == "ok"
    assert result.details["last_settle_status"] == "settled"


def test_run_accepts_doneish_text_before_final_agent_settled(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
                '{"type":"agent_settled","message":"idle"}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "done-before-settle", timeout_seconds=0.5)

    result = harness.run(request)

    assert result.status == "ok"
    assert result.details["last_settle_status"] == "settled"


def test_run_without_orch_on_fails_closed_when_no_authoritative_status_after_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_end","message":"wrap"}\n',
                '{"type":"agent_settled","message":"idle"}\n',
                '{"type":"raw","line":"builder returned done"}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "no-orch-on-children", timeout_seconds=0.5, metadata={"orch_on": False})

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.details["last_settle_status"] == "authoritative_status_unavailable"
    assert "no authoritative orchestra status available after dispatch" in result.error
    assert _sent_prompt_messages(process) == ["Build the thing."]


def test_run_keeps_session_open_until_doneish_parent_and_children_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{}}\n')
            return
        if command.get("type") != "prompt":
            return
        if command.get("message") == "/orch on":
            process.chunks.append('{"type":"extension_ui_request","message":"Orchestra orchestrator skill refreshed for this session."}\n')
            process.chunks.append('{"type":"agent_settled","message":"orch on settled"}\n')
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_end","message":"wrap"}\n',
                '{"type":"agent_settled","message":"idle"}\n',
                json.dumps(
                    {
                        "type": "tool_execution_end",
                        "toolName": "orch_status",
                        "result": {
                            "content": [
                                {
                                    "text": json.dumps(
                                        {
                                            "active_runs": 1,
                                            "descendants_terminal": False,
                                            "session_report_available": True,
                                            "session_report_delivered": False,
                                        }
                                    )
                                }
                            ]
                        },
                    }
                )
                + "\n",
                '{"type":"raw","line":"completed subagent"}\n',
                json.dumps(
                    {
                        "type": "tool_execution_end",
                        "toolName": "orch_status",
                        "result": {
                            "content": [
                                {
                                    "text": json.dumps(
                                        {
                                            "active_runs": 0,
                                            "descendants_terminal": True,
                                            "session_report_available": True,
                                            "session_report_delivered": True,
                                        }
                                    )
                                }
                            ]
                        },
                    }
                )
                + "\n",
                '{"type":"agent_settled","message":"done"}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "success", timeout_seconds=0.5, metadata={"orch_on": True})

    result = harness.run(request)

    assert result.status == "ok"
    assert result.details["last_settle_status"] == "settled"
    assert process.killed is False
    assert harness.agent_settled_seen is True
    assert _sent_prompt_messages(process) == ["/orch on", "Build the thing."]


def test_status_provider_fails_closed_without_authoritative_status_after_dispatch(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    harness = PiRpcHarness(["pi"])
    harness._state["sessionId"] = "sess-1"
    harness.events = [
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
        {"type": "extension_ui_request", "message": "orchestra: builder run-123 returned done (1/1)"},
    ]

    snapshot = harness.status_provider("sess-1")

    assert snapshot["state"] == "status_unavailable"
    assert snapshot.get("descendants_terminal") is not True
    assert harness._children_cleared(snapshot) is False


def test_children_cleared_requires_terminal_descendants_or_delivered_report(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    harness = PiRpcHarness(["pi"])

    assert harness._children_cleared(None) is True
    assert harness._children_cleared({"active_runs": 0, "descendants_terminal": True}) is True
    assert harness._children_cleared({"active_runs": 0, "descendants_terminal": False, "session_report_delivered": True}) is True
    assert harness._children_cleared({"active_runs": 0, "descendants_terminal": False, "session_report_delivered": None}) is False
    assert harness._children_cleared({"active_runs": 1, "descendants_terminal": True}) is False


def test_status_provider_fallback_terminal_on_consolidated_return_prompt(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    harness = PiRpcHarness(["pi"])
    harness._state["sessionId"] = "sess-1"
    harness.events = [
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
        {"type": "extension_ui_request", "message": "orchestra: builder run-123 returned done (1/1)"},
        {"type": "agent_start", "message": "return integration turn"},
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: 1 subagents returned]"}]},
        },
    ]

    snapshot = harness.status_provider("sess-1")

    assert snapshot["state"] == "settled"
    assert snapshot.get("descendants_terminal") is True
    assert snapshot.get("session_report_delivered") is True
    assert harness._children_cleared(snapshot) is True


def test_parent_doneish_requires_explicit_bench_sentinel() -> None:
    from bench.harnesses.pi_rpc import _text_is_doneish

    assert _text_is_doneish("Implementation complete and ready for grading.") is False
    assert _text_is_doneish("BENCH_PARENT_DONE") is True
    assert _text_is_doneish("bench_parent_done") is True
    assert _text_is_doneish("Bench Parent Done") is True
    assert _text_is_doneish("bench-parent-done.") is True


def test_parent_doneish_before_later_dispatch_does_not_count_as_final_completion() -> None:
    from bench.harnesses.pi_rpc import _parent_doneish_seen

    events = [
        {"type": "agent_settled", "message": "first parent turn settled"},
        {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Builder completed; dispatching review."}]}},
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
    ]

    assert _parent_doneish_seen(events) is False


def test_status_provider_invalidates_consolidated_return_after_later_dispatch(tmp_path: Path) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    harness = PiRpcHarness(["pi"])
    harness._state["sessionId"] = "sess-1"
    harness.events = [
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: 1 subagents returned]"}]},
        },
        {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Dispatching final review."}]}},
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
    ]

    snapshot = harness.status_provider("sess-1")

    assert snapshot["state"] == "status_unavailable"
    assert snapshot.get("descendants_terminal") is False
    assert snapshot.get("session_report_delivered") is False
    assert "post_report_dispatches=1" in snapshot.get("raw_text", "")
    assert harness._children_cleared(snapshot) is False


def test_run_settles_via_consolidated_return_prompt_without_cli_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        consolidated = json.dumps(
            {
                "type": "message",
                "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: 1 subagents returned]"}]},
            }
        )
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_settled","message":"parent settled after dispatch"}\n',
                '{"type":"extension_ui_request","message":"orchestra: builder run-123 returned done (1/1)"}\n',
                '{"type":"agent_start","message":"return integration turn"}\n',
                consolidated + "\n",
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "consolidated", timeout_seconds=0.5, metadata={"orch_on": False})

    result = harness.run(request)

    assert result.status == "ok"
    assert result.details["last_settle_status"] == "settled"
    assert process.killed is False
    assert _sent_prompt_messages(process) == ["Build the thing."]


def test_run_quiet_window_catches_dispatch_after_apparent_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_AUTO_CHILD_WAIT_SECONDS", "0.5")
    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    monkeypatch.setenv("BENCH_ORCHESTRA_QUIET_SECONDS", "0.3")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"[orchestra: 1 subagents returned]"}]}}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
                '{"type":"agent_settled","message":"final settled"}\n',
            ]
        )

    process = _GatedJsonlProcess(
        gates=[
            (
                0.1,
                ['{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n'],
            ),
        ],
    )
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "quiet-catches-late-dispatch", timeout_seconds=1.0, metadata={"orch_on": False})

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.details["last_settle_status"] == "authoritative_status_unavailable"


def test_run_grants_parent_finalize_window_when_consolidated_report_arrives_near_child_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    # Child deadline expires at ~0.35s; the consolidated report arrives first and the
    # parent's final model turn only completes after the child deadline would have expired.
    monkeypatch.setenv("BENCH_AUTO_CHILD_WAIT_SECONDS", "0.35")
    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    monkeypatch.setenv("BENCH_ORCHESTRA_QUIET_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_settled","message":"parent settled after dispatch"}\n',
            ]
        )

    consolidated = json.dumps(
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: 2 subagents returned]"}]},
        }
    )
    process = _GatedJsonlProcess(
        gates=[
            (
                0.1,
                [
                    consolidated + "\n",
                    '{"type":"agent_start","message":"return integration turn"}\n',
                ],
            ),
            # Final parent turn lands after the exhausted child deadline.
            (
                0.6,
                [
                    '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
                    '{"type":"agent_settled","message":"final settled"}\n',
                ],
            ),
        ]
    )
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "finalize-window", timeout_seconds=5.0, metadata={"orch_on": False})

    result = harness.run(request)

    assert result.status == "ok"
    assert result.details["last_settle_status"] == "settled"
    assert process.killed is False
    # No synthetic prompt: only the original task prompt was sent.
    assert _sent_prompt_messages(process) == ["Build the thing."]


def test_run_grants_parent_finalize_window_when_cli_status_misses_delivered_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_AUTO_CHILD_WAIT_SECONDS", "0.35")
    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    monkeypatch.setenv("BENCH_PARENT_FINALIZE_WINDOW_SECONDS", "1.0")
    monkeypatch.setenv("BENCH_ORCHESTRA_QUIET_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_settled","message":"parent settled after dispatch"}\n',
            ]
        )

    consolidated = json.dumps(
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: 2 subagents returned]"}]},
        }
    )
    process = _GatedJsonlProcess(
        gates=[
            (0.1, [consolidated + "\n", '{"type":"agent_start","message":"return integration turn"}\n']),
            (
                0.6,
                [
                    '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
                    '{"type":"agent_settled","message":"final settled"}\n',
                ],
            ),
        ]
    )
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    monkeypatch.setattr(
        harness,
        "_status_from_orchestra_cli",
        lambda session_id: {
            "state": "settled",
            "parsed": True,
            "active_runs": 0,
            "descendants_terminal": True,
            "session_report_available": False,
            "session_report_delivered": False,
            "raw_text": '{"active_runs":{"count":0},"descendants_terminal":true,"session_report_delivered":false}',
        },
    )
    request = _request(tmp_path / "cli-report-mismatch", timeout_seconds=5.0, metadata={"orch_on": False})

    result = harness.run(request)

    assert result.status == "ok"
    assert result.details["last_settle_status"] == "settled"


def test_run_fails_parent_not_done_when_no_doneish_by_finalize_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_AUTO_CHILD_WAIT_SECONDS", "0.4")
    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")
    monkeypatch.setenv("BENCH_PARENT_FINALIZE_WINDOW_SECONDS", "0.15")

    consolidated = json.dumps(
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "[orchestra: 2 subagents returned]"}]},
        }
    )

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_settled","message":"parent settled after dispatch"}\n',
            ]
        )

    process = _GatedJsonlProcess(gates=[(0.1, [consolidated + "\n", '{"type":"agent_start","message":"return integration turn"}\n'])])
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "finalize-timeout", timeout_seconds=5.0, metadata={"orch_on": False})

    result = harness.run(request)

    # Children are terminal via the consolidated report; only the parent final turn is missing.
    assert result.status == "lifecycle_failed"
    assert result.details["last_settle_status"] == "parent_not_done"
    assert result.error == "parent did not emit BENCH_PARENT_DONE before the completion timeout"
    assert _sent_prompt_messages(process) == ["Build the thing."]


def test_child_wait_default_follows_orchestra_config_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness
    import bench.harnesses.pi_rpc as pi_rpc

    harness = PiRpcHarness(["pi"])
    harness._request = _request(tmp_path / "wait-config")

    monkeypatch.delenv("BENCH_AUTO_CHILD_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("BENCH_PARENT_FINALIZE_WINDOW_SECONDS", raising=False)
    monkeypatch.setattr(pi_rpc.Path, "is_file", lambda self: str(self).endswith("config.yaml"))
    monkeypatch.setattr(pi_rpc.Path, "read_text", lambda self, encoding=None: "default_timeout: 1800\nsoft_timeout: 1500\n")

    assert harness._child_wait_seconds(None) == 1920.0
    assert harness._parent_finalize_window_seconds() == 1920.0


def test_orchestra_status_cli_uses_supported_status_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness
    import bench.harnesses.pi_rpc as pi_rpc

    harness = PiRpcHarness(["pi"])
    harness._request = _request(tmp_path / "status-args")
    harness._state["sessionId"] = "sess-1"
    captured: dict[str, object] = {}

    monkeypatch.setattr(pi_rpc.Path, "is_dir", lambda self: str(self).endswith("/.pi/agent/orchestra"))

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout='{"active_runs":{"count":0},"descendants_terminal":true}', stderr="")

    monkeypatch.setattr(pi_rpc.subprocess, "run", fake_run)

    snapshot = harness._status_from_orchestra_cli("sess-1")

    command = captured["command"]
    assert "--agent-catalog" not in command
    assert command[:4] == ["python3", "-m", "orchestra", "--config"]
    assert command[4].endswith("/.pi/agent/orchestra")
    assert not command[4].endswith("config.yaml")
    assert command[-3:] == ["--session-id", "pi:sess-1", "--json"]
    assert snapshot is not None
    assert snapshot["state"] == "settled"


def test_orchestra_status_preserves_authoritative_cli_despite_direct_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    harness = PiRpcHarness(["pi"])
    harness._state["sessionId"] = "sess-1"
    monkeypatch.setattr(
        harness,
        "_status_from_orchestra_cli",
        lambda session_id: {
            "state": "running",
            "parsed": True,
            "active_runs": 1,
            "descendants_terminal": False,
            "raw_text": '{"active_runs":1}',
        },
    )
    harness.events = [
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": False},
        {"type": "extension_ui_request", "message": "builder returned done (1/1)"},
        {"type": "agent_settled", "message": "parent settled"},
    ]

    snapshot = harness._orchestra_status_snapshot()

    assert snapshot is not None
    assert snapshot["active_runs"] == 1
    assert snapshot["descendants_terminal"] is False
    assert snapshot["state"] == "running"


def test_run_does_not_settle_when_cli_status_shows_active_descendant_after_direct_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{"sessionId":"sess-1"}}\n')
            return
        if command.get("type") != "prompt":
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_settled","message":"idle"}\n',
                '{"type":"raw","line":"builder returned done"}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"BENCH_PARENT_DONE"}]}}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    monkeypatch.setattr(
        harness,
        "_status_from_orchestra_cli",
        lambda session_id: {
            "state": "running",
            "parsed": True,
            "active_runs": 1,
            "descendants_terminal": False,
            "session_report_available": True,
            "session_report_delivered": False,
            "raw_text": '{"active_runs":1}',
        },
    )
    request = _request(tmp_path / "cli-active", timeout_seconds=0.5)

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.details["last_settle_status"] == "children_active_timeout"
    assert result.error == "children still active after parent wait timeout"
    assert _sent_prompt_messages(process) == ["Build the thing."]


def test_run_times_out_when_children_stay_active_after_parent_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{}}\n')
            return
        if command.get("type") != "prompt":
            return
        if command.get("message") == "/orch on":
            process.chunks.append('{"type":"extension_ui_request","message":"Orchestra orchestrator skill refreshed for this session."}\n')
            process.chunks.append('{"type":"agent_settled","message":"orch on settled"}\n')
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"tool_execution_end","toolName":"orch_dispatch","isError":false}\n',
                '{"type":"agent_end","message":"wrap"}\n',
                '{"type":"agent_settled","message":"idle"}\n',
                json.dumps(
                    {
                        "type": "tool_execution_end",
                        "toolName": "orch_status",
                        "result": {
                            "content": [
                                {
                                    "text": json.dumps(
                                        {
                                            "active_runs": 1,
                                            "descendants_terminal": False,
                                            "session_report_available": True,
                                            "session_report_delivered": False,
                                        }
                                    )
                                }
                            ]
                        },
                    }
                )
                + "\n",
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "timeout", timeout_seconds=0.01, metadata={"orch_on": True})

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.details["last_settle_status"] == "children_active_timeout"
    assert result.error == "children still active after parent wait timeout"


def test_run_fails_closed_when_parent_settles_without_doneish_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.harnesses.pi_rpc import PiRpcHarness

    monkeypatch.setenv("BENCH_PARENT_DONE_GRACE_SECONDS", "0")

    def on_send(process: _FakeJsonlProcess, command: dict[str, object]) -> None:
        if command.get("type") == "get_state":
            process.chunks.append('{"type":"response","command":"get_state","success":true,"data":{}}\n')
            return
        if command.get("type") != "prompt":
            return
        if command.get("message") == "/orch on":
            process.chunks.append('{"type":"extension_ui_request","message":"Orchestra orchestrator skill refreshed for this session."}\n')
            process.chunks.append('{"type":"agent_settled","message":"orch on settled"}\n')
            return
        process.chunks.extend(
            [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start","message":"boot"}\n',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"Still working."}]}}\n',
                '{"type":"agent_settled","message":"idle"}\n',
            ]
        )
        process.alive = False

    process = _FakeJsonlProcess()
    process.on_send = lambda command: on_send(process, command)
    harness = PiRpcHarness(["pi"], process_factory=lambda **_: process)
    request = _request(tmp_path / "fail", timeout_seconds=0.5, metadata={"orch_on": True})

    result = harness.run(request)

    assert result.status == "lifecycle_failed"
    assert result.details["last_settle_status"] == "parent_not_done"
    assert "BENCH_PARENT_DONE" in result.error

