"""Pi RPC harness with JSONL event framing and lifecycle classification."""

from __future__ import annotations

import ast
import json
import os
import re
import select
import subprocess
import sys
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


_PARENT_DONE_SENTINEL_RE = re.compile(r"\bBENCH[ _-]?PARENT[ _-]?DONE\b", re.IGNORECASE)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "text":
            continue
        text = str(item.get("text") or "")
        if text:
            parts.append(text)
    return "\n".join(parts)


def _assistant_message_from_event(event: dict[str, Any]) -> dict[str, Any]:
    message = event.get("message")
    if isinstance(message, dict):
        return message
    if isinstance(message, str) and message.startswith("{"):
        try:
            parsed = ast.literal_eval(message)
        except (ValueError, SyntaxError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _assistant_text_from_events(events: Sequence[dict[str, Any]]) -> str:
    final_text = ""
    streamed: list[str] = []
    for event in events:
        event_type = str(event.get("type") or "")
        if event_type in {"message", "message_end"}:
            message = _assistant_message_from_event(event)
            if not message:
                continue
            if str(message.get("role") or "").lower() != "assistant":
                continue
            text = _message_text(message)
            if text:
                final_text = text
        elif event_type == "message_update":
            update = event.get("assistantMessageEvent")
            if not isinstance(update, dict):
                continue
            update_type = str(update.get("type") or "")
            if update_type in {"text_delta", "thinking_delta"}:
                delta = str(update.get("delta") or "")
                if delta:
                    streamed.append(delta)
    if final_text:
        return final_text
    return "".join(streamed)


def _text_is_doneish(text: str) -> bool:
    return bool(_PARENT_DONE_SENTINEL_RE.search(str(text or "")))


def _parent_doneish_seen(events: Sequence[dict[str, Any]]) -> bool:
    return _text_is_doneish(_assistant_text_from_events(events[len(events) // 2 :]))


def _orchestra_dispatch_seen(events: Sequence[dict[str, Any]]) -> bool:
    return any(event.get("type") == "tool_execution_end" and event.get("toolName") == "orch_dispatch" and not event.get("isError") for event in events)


# Fallback completion contract: Orchestra injects this consolidated parent
# user prompt listing all returned children/auto-verifiers, then starts a new
# parent turn. Without CLI status it is the evidence that descendants are
# terminal and the session report has been delivered.
_CONSOLIDATED_RETURN_PATTERN = re.compile(r"\[orchestra:\s*\d+\s+subagents?\s+returned\]", re.IGNORECASE)
_DIRECT_RETURN_PHRASES = (
    "completed subagent",
    "subagent completed",
    "orchestra returned",
    "returned done",
)

_ORCH_ON_ACTIVATION_PATTERNS = (
    re.compile(r"Orchestra orchestrator skill refreshed for this session\.", re.IGNORECASE),
    re.compile(r"Orchestra orchestrator skill (?:refreshed|loaded|activated)\b", re.IGNORECASE),
)


def _event_text_fragments(event: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    message = event.get("message")
    if isinstance(message, str) and message.strip():
        fragments.append(message)
    elif isinstance(message, dict):
        text = _message_text(message)
        if text:
            fragments.append(text)
    line = event.get("line")
    if isinstance(line, str) and line.strip():
        fragments.append(line)
    text = event.get("text")
    if isinstance(text, str) and text.strip():
        fragments.append(text)
    raw_text = event.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        fragments.append(raw_text)
    result = event.get("result")
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_text = item.get("text")
                if isinstance(item_text, str) and item_text.strip():
                    fragments.append(item_text)
    assistant_message = _assistant_message_from_event(event)
    if assistant_message:
        assistant_text = _message_text(assistant_message)
        if assistant_text:
            fragments.append(assistant_text)
    return fragments


def _consolidated_report_delivered(snapshot: dict[str, Any] | None, children_cleared: bool) -> bool:
    """Whether the consolidated session report has been delivered to the parent."""
    if not isinstance(snapshot, dict):
        return False
    # Fallback completion contract: the consolidated "[orchestra: N subagents
    # returned]" prompt was observed in the event stream.
    if str(snapshot.get("raw_text") or "").endswith("fallback_contract"):
        return True
    # Authoritative status reporting a delivered session report for cleared children.
    return children_cleared and snapshot.get("session_report_delivered") is True


def _orch_on_activation_seen(events: Sequence[dict[str, Any]]) -> bool:
    for event in events:
        for text in _event_text_fragments(event):
            if any(pattern.search(text) for pattern in _ORCH_ON_ACTIVATION_PATTERNS):
                return True
    return False


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
    def session_id(self) -> str:
        return str(self._state.get("sessionId") or self._state.get("session_id") or "")

    def _status_from_orchestra_cli(self, session_id: str) -> dict[str, Any] | None:
        request = self._request
        if request is None or not session_id:
            return None
        run_id = request.run_paths.run_id
        config_path = Path(f"/workspace/.pi/home/{run_id}/.pi/agent/orchestra/config.yaml")
        catalog_path = Path(f"/workspace/.pi/home/{run_id}/.pi/agent/orchestra/agent-catalog.yaml")
        if not config_path.is_file() or not catalog_path.is_file():
            return None
        try:
            completed = subprocess.run(
                [
                    "python3",
                    "-m",
                    "orchestra",
                    "--config",
                    str(config_path),
                    "--agent-catalog",
                    str(catalog_path),
                    "status",
                    "--session-id",
                    session_id if session_id.startswith("pi:") else f"pi:{session_id}",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=workspace_dir(request.run_paths),
            )
        except Exception:
            return None
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"raw_text": completed.stdout}
        active_runs = payload.get("active_runs")
        active_count = active_runs.get("count") if isinstance(active_runs, dict) else active_runs
        descendants_terminal = payload.get("descendants_terminal")
        return {
            "state": "settled" if active_count == 0 or descendants_terminal is True else "running",
            "parsed": True,
            "active_runs": active_count,
            "descendants_terminal": descendants_terminal,
            "session_report_available": payload.get("session_report_available"),
            "session_report_delivered": payload.get("session_report_delivered"),
            "raw_text": completed.stdout.strip(),
        }

    def _orchestra_status_snapshot(self) -> dict[str, Any] | None:
        # Authoritative CLI status is returned as-is: direct-return
        # notifications must never override authoritative active descendants.
        cli_snapshot = self._status_from_orchestra_cli(self.session_id)
        if cli_snapshot is not None:
            return cli_snapshot
        for event in reversed(self.events):
            if event.get("type") != "tool_execution_end" or event.get("toolName") != "orch_status":
                continue
            result = event.get("result")
            if not isinstance(result, dict):
                continue
            content = result.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    return {"raw_text": text}
                active_runs = payload.get("active_runs")
                active_count = active_runs.get("count") if isinstance(active_runs, dict) else active_runs
                descendants_terminal = payload.get("descendants_terminal")
                if active_count == 0 or descendants_terminal is True:
                    state = "settled"
                else:
                    state = "running"
                return {
                    "state": state,
                    "parsed": True,
                    "active_runs": active_count,
                    "descendants_terminal": descendants_terminal,
                    "session_report_available": payload.get("session_report_available"),
                    "session_report_delivered": payload.get("session_report_delivered"),
                    "raw_text": text,
                }
        dispatches = 0
        direct_returns = 0
        dispatches_after_consolidated = 0
        direct_returns_after_consolidated = 0
        consolidated_return_seen = False
        for event in self.events:
            if event.get("type") == "tool_execution_end" and event.get("toolName") == "orch_dispatch" and not event.get("isError"):
                dispatches += 1
                if consolidated_return_seen:
                    dispatches_after_consolidated += 1
            fragments = _event_text_fragments(event)
            if any(_CONSOLIDATED_RETURN_PATTERN.search(text) for text in fragments):
                consolidated_return_seen = True
                dispatches_after_consolidated = 0
                direct_returns_after_consolidated = 0
                continue
            direct_return_count = sum(1 for phrase in _DIRECT_RETURN_PHRASES if any(phrase in text.lower() for text in fragments))
            direct_returns += direct_return_count
            if consolidated_return_seen:
                direct_returns_after_consolidated += direct_return_count
        if not dispatches:
            return None
        # The consolidated parent prompt is the fallback completion contract,
        # but only for the current dispatch epoch. A later successful dispatch
        # makes older consolidated-report evidence stale until another report arrives.
        if consolidated_return_seen and dispatches_after_consolidated == 0:
            return {
                "state": "settled",
                "parsed": False,
                "active_runs": 0,
                "descendants_terminal": True,
                "session_report_available": True,
                "session_report_delivered": True,
                "post_report_dispatches": 0,
                "raw_text": f"dispatches={dispatches} direct_returns={direct_returns} consolidated_return=1 fallback_contract",
            }
        # A dispatched run never settles from direct-return inference alone:
        # without authoritative status or a current consolidated report we fail closed.
        return {
            "state": "status_unavailable",
            "parsed": False,
            "active_runs": None,
            "descendants_terminal": False,
            "session_report_available": direct_returns > 0 or consolidated_return_seen,
            "session_report_delivered": False,
            "post_report_dispatches": dispatches_after_consolidated,
            "raw_text": (
                f"dispatches={dispatches} direct_returns={direct_returns} "
                f"consolidated_return={1 if consolidated_return_seen else 0} "
                f"post_report_dispatches={dispatches_after_consolidated} authoritative_status_unavailable"
            ),
        }

    def status_provider(self, session_id: str) -> dict[str, Any]:
        snapshot = self._orchestra_status_snapshot()
        if snapshot is not None:
            return snapshot
        state = dict(self._state)
        if session_id and not state.get("sessionId"):
            state["sessionId"] = session_id
        return state

    @property
    def last_settle_status(self) -> str:
        return self._last_settle_status

    def _parent_done_grace_seconds(self) -> float:
        configured = os.environ.get("BENCH_PARENT_DONE_GRACE_SECONDS", "10")
        try:
            return max(0.0, float(configured))
        except ValueError:
            return 10.0

    def _parent_finalize_window_seconds(self) -> float:
        # Separate budget for the parent's final model turn after the consolidated
        # session report is delivered; sized to permit a normal final turn.
        configured = os.environ.get("BENCH_PARENT_FINALIZE_WINDOW_SECONDS", "300")
        try:
            return max(0.0, float(configured))
        except ValueError:
            return 300.0

    def _orchestra_quiet_seconds(self) -> float:
        # Settle observation window after apparent completion. This catches late
        # post-return dispatches without counting the quiet wait as model work.
        configured = os.environ.get("BENCH_ORCHESTRA_QUIET_SECONDS", "45")
        try:
            return max(0.0, float(configured))
        except ValueError:
            return 45.0

    def _remaining_timeout(self, deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    def _children_cleared(self, snapshot: dict[str, Any] | None) -> bool:
        if snapshot is None:
            return True
        active_runs = snapshot.get("active_runs")
        if isinstance(active_runs, (int, float)):
            active_clear = active_runs == 0
        else:
            active_clear = snapshot.get("state") == "settled" or snapshot.get("descendants_terminal") is True
        if not active_clear:
            return False
        # A dispatched run only clears when descendants are terminal or the
        # session report has been delivered per the available contract.
        if snapshot.get("descendants_terminal") is True:
            return True
        return snapshot.get("session_report_delivered") is True

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
            if request.metadata.get("stream_output"):
                self._emit_verbose_event(normalized)
        if normalized.get("type") == "response" and normalized.get("command") == "get_state":
            self._state = dict(normalized.get("data") or {})
        return normalized

    def _emit_verbose_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "message_update":
            update = event.get("assistantMessageEvent")
            if not isinstance(update, dict):
                return
            update_type = str(update.get("type") or "")
            if update_type in {"text_delta", "thinking_delta"}:
                delta = str(update.get("delta") or "")
                if delta:
                    sys.stdout.write(delta)
                    sys.stdout.flush()
            elif update_type == "toolcall_start":
                print(f"\n[bench:pi] tool start: {update.get('toolName') or 'unknown'}", flush=True)
            elif update_type == "toolcall_end":
                tool = update.get("toolCall")
                name = tool.get("name") if isinstance(tool, dict) else "unknown"
                print(f"\n[bench:pi] tool ready: {name}", flush=True)
            return
        if event_type == "tool_execution_start":
            print(f"\n[bench:pi] tool exec: {event.get('toolName') or 'unknown'}", flush=True)
        elif event_type == "tool_execution_end":
            marker = "error" if event.get("isError") else "ok"
            print(f"\n[bench:pi] tool done: {event.get('toolName') or 'unknown'} ({marker})", flush=True)
        elif event_type in {"agent_start", "agent_settled", "agent_end", "turn_start", "turn_end"}:
            print(f"\n[bench:pi] {event_type}", flush=True)

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

    def wait_for_settled(self, timeout: float | None = None, *, start_index: int = 0) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if any(event.get("type") == "agent_settled" for event in self.events[start_index:]):
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
                    if any(event.get("type") == "agent_settled" for event in self.events[start_index:]):
                        self._last_settle_status = "settled"
                        return True
                    self._last_settle_status = "missing_settled"
                    return False
                continue
            if event.get("type") == "agent_settled":
                self._last_settle_status = "settled"
                return True

    def wait_for_orch_on_activation(self, timeout: float | None = None, *, start_index: int = 0) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        activation_seen = False
        while True:
            events = self.events[start_index:]
            if not activation_seen and _orch_on_activation_seen(events):
                activation_seen = True
            if activation_seen and any(event.get("type") == "agent_settled" for event in events):
                self._last_settle_status = "settled"
                return True
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0:
                self._last_settle_status = "missing_settled" if activation_seen else "timeout"
                return False
            event = self._next_event(timeout=remaining if deadline is not None else timeout)
            if event is None:
                process = self._process
                if process is not None and process.poll() is not None:
                    self._drain_remaining_output()
                    events = self.events[start_index:]
                    if not activation_seen and _orch_on_activation_seen(events):
                        activation_seen = True
                    if activation_seen and any(event.get("type") == "agent_settled" for event in events):
                        self._last_settle_status = "settled"
                        return True
                    self._last_settle_status = "missing_settled" if activation_seen else "missing_activation"
                    return False
                continue
            if not activation_seen and _orch_on_activation_seen(self.events[start_index:]):
                activation_seen = True

    def _drain_remaining_output(self) -> None:
        while True:
            event = self._next_event(timeout=0.0)
            if event is None:
                self._drain_stderr()
                break

    def _child_wait_seconds(self, timeout: float | None) -> float:
        configured = os.environ.get("BENCH_AUTO_CHILD_WAIT_SECONDS", "300")
        try:
            child_wait = max(0.0, float(configured))
        except ValueError:
            child_wait = 60.0
        grace_seconds = self._parent_done_grace_seconds()
        if timeout is not None:
            child_wait = min(child_wait, max(0.0, float(timeout)))
        return max(child_wait, grace_seconds)

    def _emit_waiting_for_children(self, snapshot: dict[str, Any] | None) -> None:
        request = self._request
        if request is None:
            return
        active = "unknown"
        if isinstance(snapshot, dict) and snapshot.get("active_runs") is not None:
            active = str(snapshot.get("active_runs"))
        print(f"[bench] waiting for children: active={active}", flush=True)

    def wait_for_orchestra_children(self, timeout: float | None = None) -> bool:
        grace_seconds = self._parent_done_grace_seconds()
        finalize_seconds = self._parent_finalize_window_seconds()
        quiet_seconds = self._orchestra_quiet_seconds()
        deadline = time.monotonic() + self._child_wait_seconds(timeout)
        grace_until = None
        quiet_until = None
        finalize_granted = False
        handled_post_report_dispatches = 0
        last_wait_announcement = 0.0
        while True:
            doneish_seen = _parent_doneish_seen(self.events)
            snapshot = self._orchestra_status_snapshot()
            status_unavailable = isinstance(snapshot, dict) and snapshot.get("state") == "status_unavailable"
            children_cleared = self._children_cleared(snapshot)
            children_active = (snapshot is not None and not children_cleared) or status_unavailable
            post_report_dispatches = 0
            if isinstance(snapshot, dict) and isinstance(snapshot.get("post_report_dispatches"), (int, float)):
                post_report_dispatches = int(snapshot["post_report_dispatches"])
            if post_report_dispatches > handled_post_report_dispatches:
                # A new dispatch after a consolidated report starts a new child-wait
                # epoch; the older parent-finalization window no longer applies.
                handled_post_report_dispatches = post_report_dispatches
                finalize_granted = False
                quiet_until = None
                deadline = time.monotonic() + self._child_wait_seconds(timeout)
            if _consolidated_report_delivered(snapshot, children_cleared) and not finalize_granted:
                # The consolidated session report opens a fresh parent turn; grant it a
                # separate finalization window instead of an exhausted child deadline.
                # Granted once so duplicate report events never re-extend the deadline.
                finalize_granted = True
                if finalize_seconds > 0:
                    window_end = time.monotonic() + finalize_seconds
                    if deadline is None or window_end > deadline:
                        deadline = window_end
            if not (doneish_seen and children_cleared):
                quiet_until = None
            if doneish_seen:
                if grace_until is None and grace_seconds > 0:
                    grace_until = time.monotonic() + grace_seconds
                if grace_until is not None:
                    remaining_grace = max(0.0, grace_until - time.monotonic())
                    if remaining_grace > 0:
                        remaining = self._remaining_timeout(deadline)
                        if remaining == 0:
                            if status_unavailable:
                                self._last_settle_status = "authoritative_status_unavailable"
                            elif children_active:
                                self._last_settle_status = "children_active_timeout"
                            else:
                                self._last_settle_status = "children_active_after_parent_done"
                            return False
                        wait_time = min(remaining_grace, remaining if remaining is not None else remaining_grace)
                        event = self._next_event(timeout=wait_time)
                        if event is None and self._process is not None and self._process.poll() is not None:
                            self._drain_remaining_output()
                        continue
                    grace_until = None
                if children_cleared:
                    if quiet_seconds <= 0 or (self._process is not None and self._process.poll() is not None):
                        self._last_settle_status = "settled"
                        return True
                    if quiet_until is None:
                        quiet_until = time.monotonic() + quiet_seconds
                    quiet_remaining = max(0.0, quiet_until - time.monotonic())
                    if quiet_remaining == 0:
                        self._last_settle_status = "settled"
                        return True
                    event = self._next_event(timeout=min(5.0, quiet_remaining))
                    if event is None:
                        if self._process is not None and self._process.poll() is not None:
                            self._last_settle_status = "settled"
                            return True
                        continue
                    quiet_until = None
                    continue
                self._last_settle_status = "authoritative_status_unavailable" if status_unavailable else "children_active_after_parent_done"
            elif children_active:
                self._last_settle_status = "authoritative_status_unavailable" if status_unavailable else "children_active_after_parent_exit"
                now = time.monotonic()
                if now - last_wait_announcement >= 30.0:
                    self._emit_waiting_for_children(snapshot)
                    last_wait_announcement = now
            else:
                self._last_settle_status = "parent_not_done"
                # With the consolidated report delivered, wait out the finalization
                # window for the parent's done-ish turn instead of failing early;
                # expiry below then fails closed as parent_not_done.
                if snapshot is not None and children_cleared and not finalize_granted:
                    return False

            remaining = self._remaining_timeout(deadline)
            if remaining == 0:
                if status_unavailable:
                    self._last_settle_status = "authoritative_status_unavailable"
                elif children_active:
                    self._last_settle_status = "children_active_timeout"
                return False

            event = self._next_event(timeout=min(5.0, remaining) if remaining is not None else 5.0)
            if event is None:
                if self._process is not None and self._process.poll() is not None:
                    if status_unavailable:
                        self._last_settle_status = "authoritative_status_unavailable"
                    elif children_active:
                        self._last_settle_status = "children_active_timeout"
                    else:
                        self._last_settle_status = "parent_not_done"
                    return False
                continue

            if event.get("type") in {"agent_settled", "agent_end"}:
                doneish_seen = _parent_doneish_seen(self.events)
                if doneish_seen and grace_seconds > 0:
                    grace_until = time.monotonic() + grace_seconds
                continue

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
        deadline = None if request.timeout_seconds is None else time.monotonic() + max(0.0, request.timeout_seconds)
        orch_on_requested = bool(request.metadata.get("orch_on"))
        if orch_on_requested:
            orch_on_start = len(self.events)
            self.write_transcript(request, "prompt: /orch on")
            self.send_prompt("/orch on")
            if not self.wait_for_orch_on_activation(timeout=self._remaining_timeout(deadline), start_index=orch_on_start):
                exit_code = self.stop()
                details = {
                    "agent_settled_seen": self.agent_settled_seen,
                    "command": list(self.command),
                    "event_count": len(self.events),
                    "exit_code": exit_code,
                    "last_settle_status": self._last_settle_status,
                    "orch_on": orch_on_requested,
                    "state": dict(self._state),
                }
                orch_on_error_map = {
                    "timeout": "/orch on activation timed out",
                    "missing_activation": "/orch on activation did not arrive",
                    "missing_settled": "/orch on activation did not settle",
                }
                result = self.build_result(
                    status="lifecycle_failed",
                    exit_code=exit_code,
                    error=orch_on_error_map.get(self._last_settle_status, "/orch on did not settle"),
                    details=details,
                )
                self.write_summary(request, result.details | {"status": result.status, "exit_code": result.exit_code, "error": result.error})
                return result
        self.write_transcript(request, f"prompt: {request.prompt}")
        task_start = len(self.events)
        self.send_prompt(request.prompt)
        try:
            self.query_state(timeout=self._remaining_timeout(deadline))
        except Exception:
            pass
        settled = self.wait_for_settled(timeout=self._remaining_timeout(deadline), start_index=task_start)
        if settled and (orch_on_requested or _orchestra_dispatch_seen(self.events[task_start:])):
            settled = self.wait_for_orchestra_children()
        exit_code = self.stop()
        reported_exit_code = 0 if settled and self._last_settle_status == "settled" and exit_code == -9 else exit_code
        details = {
            "agent_settled_seen": self.agent_settled_seen,
            "command": list(self.command),
            "event_count": len(self.events),
            "exit_code": reported_exit_code,
            "shutdown_exit_code": exit_code,
            "last_settle_status": self._last_settle_status,
            "state": dict(self._state),
        }
        if not settled or self._last_settle_status != "settled":
            error_map = {
                "timeout": "timeout waiting for agent_settled",
                "missing_activation": "/orch on activation did not arrive",
                "missing_settled": "missing agent_settled",
                "parent_not_done": "parent did not emit BENCH_PARENT_DONE before the completion timeout",
                "children_active_after_parent_done": "children still active after parent done-ish",
                "children_active_after_parent_exit": "children still active after parent exit",
                "children_active_timeout": "children still active after parent wait timeout",
                "authoritative_status_unavailable": "no authoritative orchestra status available after dispatch; refusing to grade",
            }
            error = error_map.get(self._last_settle_status, f"settle gate failed ({self._last_settle_status})")
            result = self.build_result(status="lifecycle_failed", exit_code=reported_exit_code, error=error, details=details)
        elif reported_exit_code not in (None, 0):
            result = self.build_result(
                status="lifecycle_failed",
                exit_code=reported_exit_code,
                error=f"process exited with exit {reported_exit_code}",
                details=details,
            )
        else:
            result = self.build_result(status="ok", exit_code=reported_exit_code, details=details)
        self.write_summary(request, result.details | {"status": result.status, "exit_code": result.exit_code, "error": result.error})
        return result
