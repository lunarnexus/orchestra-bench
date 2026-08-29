"""Pi RPC harness with JSONL event framing and lifecycle classification."""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from bench.harnesses.base import BaseHarness, HarnessRequest, LifecycleEvent
from bench.harnesses.process import build_process_env
from bench.workspace import workspace_dir
from bench.result import HarnessResult


class JsonlEventFramer:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str, *, eof: bool = False) -> list[dict[str, Any]]:
        self._buffer += chunk
        events: list[dict[str, Any]] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            event = self._parse_line(line)
            if event is not None:
                events.append(event)
        if eof and self._buffer:
            event = self._parse_line(self._buffer)
            self._buffer = ""
            if event is not None:
                events.append(event)
        return events

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        line = line.rstrip("\r")
        if not line.strip():
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return {"type": "raw", "line": line}
        if not isinstance(event, dict):
            return {"type": "raw", "value": event}
        if "type" not in event:
            event["type"] = "raw"
        return event


@runtime_checkable
class _JsonlProcess(Protocol):
    stdin: Any

    def read_chunk(self, timeout: float | None = None) -> str | None: ...

    def read_stderr_chunk(self, timeout: float | None = None) -> str | None: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


@dataclass
class _SubprocessJsonlProcess:
    command: Sequence[str]
    cwd: str | Path | None = None
    env: Mapping[str, str] | None = None
    stderr_to_stdout: bool = False
    _proc: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _stderr_buffer: deque[str] = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        stderr = subprocess.STDOUT if self.stderr_to_stdout else subprocess.PIPE
        self._proc = subprocess.Popen(
            list(self.command),
            cwd=None if self.cwd is None else str(self.cwd),
            env=None if self.env is None else dict(self.env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
        )

    @property
    def stdin(self) -> Any:
        if self._proc is None:
            return None
        return self._proc.stdin

    def read_chunk(self, timeout: float | None = None) -> str | None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        stdout_fd = proc.stdout.fileno()
        stderr = proc.stderr
        stderr_fd = None if stderr is None else stderr.fileno()
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            fds = [stdout_fd]
            if stderr_fd is not None:
                fds.append(stderr_fd)
            wait = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select(fds, [], [], wait)
            except OSError:
                return None
            if not ready:
                return ""
            if stderr_fd is not None and stderr_fd in ready:
                chunk = os.read(stderr_fd, 65536)
                if chunk:
                    self._stderr_buffer.append(chunk.decode("utf-8", "replace"))
                else:
                    stderr_fd = None
            if stdout_fd in ready:
                chunk = os.read(stdout_fd, 65536)
                if not chunk:
                    return None
                return chunk.decode("utf-8", "replace")

    def read_stderr_chunk(self, timeout: float | None = None) -> str | None:
        if self._stderr_buffer:
            return self._stderr_buffer.popleft()
        proc = self._proc
        if proc is None or proc.stderr is None:
            return None
        fd = proc.stderr.fileno()
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            wait = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([fd], [], [], wait)
            except OSError:
                return None
            if not ready:
                return ""
            chunk = os.read(fd, 65536)
            if not chunk:
                return None
            return chunk.decode("utf-8", "replace")

    def poll(self) -> int | None:
        if self._proc is None:
            return None
        return self._proc.poll()

    def wait(self, timeout: float | None = None) -> int:
        if self._proc is None:
            return 0
        return self._proc.wait(timeout=timeout)

    def kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()


@dataclass
class PiRpcHarness(BaseHarness):
    command: Sequence[str]
    process_factory: Callable[..., _JsonlProcess] = _SubprocessJsonlProcess
    cwd: str | Path | None = None
    env: Mapping[str, str] | None = None
    events: list[dict[str, Any]] = field(default_factory=list, init=False)
    _process: _JsonlProcess | None = field(default=None, init=False, repr=False)
    _request: HarnessRequest | None = field(default=None, init=False, repr=False)
    _framer: JsonlEventFramer = field(default_factory=JsonlEventFramer, init=False, repr=False)
    _pending_events: deque[dict[str, Any]] = field(default_factory=deque, init=False, repr=False)
    _state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_settle_status: str = field(default="not_started", init=False, repr=False)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def agent_settled_seen(self) -> bool:
        return any(event.get("type") == "agent_settled" for event in self.events)

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    @property
    def last_settle_status(self) -> str:
        return self._last_settle_status

    def start(self, request: HarnessRequest) -> None:
        if self._process is not None:
            raise RuntimeError("Pi RPC harness already started")
        self._request = request
        self.events.clear()
        self._pending_events.clear()
        self._state.clear()
        self._framer = JsonlEventFramer()
        self._last_settle_status = "running"
        request.artifacts.events_path.parent.mkdir(parents=True, exist_ok=True)
        request.artifacts.summary_path.parent.mkdir(parents=True, exist_ok=True)
        request.artifacts.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        request.artifacts.log_path.parent.mkdir(parents=True, exist_ok=True)
        request.artifacts.events_path.write_text("", encoding="utf-8")
        request.artifacts.transcript_path.write_text("", encoding="utf-8")
        request.artifacts.log_path.write_text("", encoding="utf-8")
        env = build_process_env(configured_env=self.env, request_env=request.env)
        self._process = self.process_factory(command=list(self.command), cwd=workspace_dir(request.run_paths), env=env)

    def _require_started(self) -> tuple[HarnessRequest, _JsonlProcess]:
        if self._request is None or self._process is None:
            raise RuntimeError("Pi RPC harness not started")
        return self._request, self._process

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("type") == "raw":
            return event
        if "command" in event or "success" in event:
            return event
        if set(event).issubset({"type", "message", "data", "timestamp"}):
            return LifecycleEvent.from_value(event).to_dict()
        return event

    def _record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_event(event)
        self.events.append(normalized)
        request = self._request
        if request is not None:
            request.artifacts.events_path.parent.mkdir(parents=True, exist_ok=True)
            with request.artifacts.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(normalized, sort_keys=True) + "\n")
        if normalized.get("type") == "response" and normalized.get("command") == "get_state":
            self._state = dict(normalized.get("data") or {})
        return normalized

    def _record_stderr(self, text: str) -> None:
        request = self._request
        if request is None or text == "":
            return
        request.artifacts.log_path.parent.mkdir(parents=True, exist_ok=True)
        with request.artifacts.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")

    def _drain_stderr(self, timeout: float | None = 0.0) -> None:
        _, process = self._require_started()
        while True:
            chunk = process.read_stderr_chunk(timeout)
            if chunk in (None, ""):
                break
            self._record_stderr(chunk)

    def _next_event(self, timeout: float | None = None) -> dict[str, Any] | None:
        _, process = self._require_started()
        if self._pending_events:
            event = self._pending_events.popleft()
            self._drain_stderr()
            return self._record_event(event)
        chunk = process.read_chunk(timeout)
        self._drain_stderr()
        if chunk == "":
            return None
        if chunk is None:
            parsed = self._framer.feed("", eof=True)
        else:
            parsed = self._framer.feed(chunk)
        if not parsed:
            return None
        self._pending_events.extend(parsed)
        event = self._pending_events.popleft()
        return self._record_event(event)

    def read_event(self, timeout: float | None = 1.0) -> dict[str, Any] | None:
        return self._next_event(timeout)

    def send(self, command: dict[str, Any]) -> None:
        request, process = self._require_started()
        stdin = process.stdin
        if stdin is None:
            raise RuntimeError("Pi RPC process does not have stdin")
        payload = json.dumps(command, sort_keys=True).encode("utf-8") + b"\n"
        stdin.write(payload)
        stdin.flush()
        if hasattr(process, "sent_commands"):
            process.sent_commands.append(dict(command))  # type: ignore[attr-defined]
        if hasattr(process, "on_send"):
            process.on_send(dict(command))  # type: ignore[attr-defined]
        request.artifacts.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with request.artifacts.transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(command, sort_keys=True) + "\n")

    def send_prompt(self, prompt: str) -> None:
        self.send({"type": "prompt", "message": prompt})

    def query_state(self, timeout: float | None = None) -> dict[str, Any]:
        self.send({"type": "get_state"})
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return dict(self._state)
            event = self._next_event(timeout=remaining if deadline is not None else timeout)
            if event is None:
                if not self.running:
                    return dict(self._state)
                continue
            if event.get("type") == "response" and event.get("command") == "get_state":
                return dict(self._state)

    def wait_for_settled(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.agent_settled_seen:
                self._last_settle_status = "settled"
                return True
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0:
                self._last_settle_status = "timeout"
                return False
            event = self._next_event(timeout=remaining if deadline is not None else timeout)
            if event is None:
                process = self._process
                if process is not None and process.poll() is not None:
                    self._drain_remaining_output()
                    if self.agent_settled_seen:
                        self._last_settle_status = "settled"
                        return True
                    self._last_settle_status = "missing_settled"
                    return False
                continue
            if event.get("type") == "agent_settled":
                self._last_settle_status = "settled"
                return True

    def _drain_remaining_output(self) -> None:
        while True:
            event = self._next_event(timeout=0.0)
            if event is None:
                self._drain_stderr()
                break

    def stop(self, grace_seconds: float = 5.0) -> int | None:
        process = self._process
        if process is None:
            return None
        try:
            if process.poll() is None:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    process.wait(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            self._drain_remaining_output()
            self._drain_stderr()
            self._process = None
        return process.poll()

    def run(self, request: HarnessRequest) -> HarnessResult:
        self.start(request)
        self.write_transcript(request, f"prompt: {request.prompt}")
        self.send_prompt(request.prompt)
        if request.metadata.get("state_query"):
            self.query_state(timeout=request.timeout_seconds)
        settled = self.wait_for_settled(timeout=request.timeout_seconds)
        exit_code = self.stop()
        details = {
            "agent_settled_seen": self.agent_settled_seen,
            "command": list(self.command),
            "event_count": len(self.events),
            "exit_code": exit_code,
            "last_settle_status": self._last_settle_status,
            "state": dict(self._state),
        }
        if not settled or self._last_settle_status != "settled":
            if self._last_settle_status == "timeout":
                error = "timeout waiting for agent_settled"
            elif self.agent_settled_seen:
                error = f"process exited with exit {exit_code}"
            else:
                error = "missing agent_settled"
            result = self.build_result(status="lifecycle_failed", exit_code=exit_code, error=error, details=details)
        elif exit_code not in (None, 0):
            result = self.build_result(
                status="lifecycle_failed",
                exit_code=exit_code,
                error=f"process exited with exit {exit_code}",
                details=details,
            )
        else:
            result = self.build_result(status="ok", exit_code=exit_code, details=details)
        self.write_summary(request, result.details | {"status": result.status, "exit_code": result.exit_code, "error": result.error})
        return result
