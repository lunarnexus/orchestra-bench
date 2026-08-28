from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.harnesses.base import HarnessArtifactPaths, HarnessRequest
from bench.paths import RunPaths


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
    ) -> None:
        self.stdin = _FakeStdin(self)
        self.chunks = list(chunks or [])
        self.stderr_chunks = list(stderr_chunks or [])
        self.exit_code = exit_code
        self.wait_timeout = wait_timeout
        self.alive = True
        self.killed = False
        self.sent_commands: list[dict[str, object]] = []

    def read_chunk(self, timeout: float | None = None) -> str | None:
        if self.chunks:
            return self.chunks.pop(0)
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

    assert captured["cwd"] == request.run_paths.container_workdir
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
        process.chunks.append('{"type":"agent_settled","message":"done"}\n')
        process.alive = False

    nonzero_process.on_send = lambda command: on_send_nonzero(nonzero_process, command)
    nonzero_harness = PiRpcHarness(["pi"], process_factory=lambda **_: nonzero_process)
    nonzero_result = nonzero_harness.run(nonzero_request)

    assert timeout_result.status == "lifecycle_failed"
    assert "timeout" in timeout_result.error.lower()
    assert missing_result.status == "lifecycle_failed"
    assert "agent_settled" in missing_result.error
    assert nonzero_result.status == "lifecycle_failed"
    assert "exit 3" in nonzero_result.error.lower()
    assert timeout_request.artifacts.log_path.read_text(encoding="utf-8") == "stderr line\n"
    assert nonzero_request.artifacts.log_path.read_text(encoding="utf-8") == "stderr line\n"

