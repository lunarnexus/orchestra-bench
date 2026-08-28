"""Minimal Pi RPC client over JSONL stdin/stdout.

Drives any command that speaks the Pi RPC protocol (normally
`docker exec -i ... pi --mode rpc`). Records every stdout line as an event,
optionally appending them to a JSONL artifact file.

Stdout is read with raw os.read + select and split on LF manually: buffered
readline() reads ahead into userspace buffers, which breaks select-based
timeouts (see Pi docs/rpc.md framing notes).
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class PiRpcRunner:
    command: list[str]
    workdir: str | None = None
    event_log_path: Path | str | None = None
    event_callback: Callable[[dict], None] | None = None
    events: list[dict] = field(default_factory=list)

    _proc: subprocess.Popen | None = field(default=None, repr=False, compare=False)
    _log_file: object = field(default=None, repr=False, compare=False)
    _buf: str = ""

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def agent_settled_seen(self) -> bool:
        return any(event.get("type") == "agent_settled" for event in self.events)

    def start(self) -> None:
        if self.running:
            raise RuntimeError("runner already started")
        if self.event_log_path is not None:
            Path(self.event_log_path).parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(Path(self.event_log_path), "a", encoding="utf-8")
        self._proc = subprocess.Popen(
            self.command,
            cwd=self.workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,  # binary; we decode manually
            stderr=None,  # inherit so operator sees Pi noise live
        )

    def send(self, command: dict) -> None:
        if not self.running or self._proc is None or self._proc.stdin is None:
            raise RuntimeError("runner not running")
        self._proc.stdin.write(json.dumps(command).encode() + b"\n")
        self._proc.stdin.flush()

    def read_line(self, timeout: float | None = 1.0) -> dict | None:
        """Read one stdout line as a JSON event. Returns None on EOF or no data."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        fd = proc.stdout.fileno()

        while "\n" not in self._buf and (self.running or self._buf):
            try:
                ready, _, _ = select.select([fd], [], [], timeout)
            except OSError:
                break  # fd closed/EOF
            if not ready:
                break
            chunk = os.read(fd, 65536)
            if not chunk:  # EOF
                break
            self._buf += chunk.decode("utf-8", "replace")

        if "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
        elif proc.poll() is not None and self._buf.strip():
            # EOF with a final unterminated line.
            line, self._buf = self._buf, ""
        else:
            return None

        line = line.rstrip("\r")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"type": "raw", "line": line}
        if not isinstance(event, dict):
            event = {"type": "raw", "value": event}
        self.events.append(event)
        log_file = self._log_file
        if log_file is not None:
            log_file.write(json.dumps(event, default=str) + "\n")
            log_file.flush()
        if self.event_callback is not None:
            self.event_callback(event)
        return event

    def wait_for_settled(self, timeout: float | None = None, poll_timeout: float = 1.0) -> bool:
        """Consume events until agent_settled is seen or the total timeout elapses."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return False
            event = self.read_line(timeout=poll_timeout if remaining is None else min(poll_timeout, remaining))
            if event is not None and event.get("type") == "agent_settled":
                return True
            # Process exited without settling (or settled already in buffer).
            if not self.running:
                return any(e.get("type") == "agent_settled" for e in self.events)

    def _drain_remaining_output(self) -> None:
        """Consume any remaining stdout lines after process exit.

        This improves capture of final agent_settled/response lines that may have
        been written before exit but not yet read by the caller.
        """
        while True:
            event = self.read_line(timeout=0.0)
            if event is None:
                break

    def stop(self, grace_seconds: float = 5.0) -> int | None:
        """Close the session cleanly; kill after grace period. Returns exit code."""
        proc = self._proc
        if proc is None:
            return None
        try:
            if proc.poll() is None:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        finally:
            self._drain_remaining_output()
            log_file = self._log_file
            if log_file is not None:
                log_file.close()
                self._log_file = None
            self._proc = None
        return proc.returncode
