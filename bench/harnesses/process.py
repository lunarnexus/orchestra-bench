"""Reusable transcript helpers for line-oriented harness processes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from bench.harnesses.base import HarnessArtifactPaths, LifecycleEvent
from bench.result import HarnessResult

_ALLOWED_AMBIENT_ENV = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
)


def build_process_env(
    configured_env: Mapping[str, object] | None = None,
    request_env: Mapping[str, object] | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _ALLOWED_AMBIENT_ENV:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    for source in (configured_env, request_env):
        if source is None:
            continue
        for key, value in source.items():
            env[str(key)] = str(value)
    return env


@dataclass
class ProcessTranscript:
    artifacts: HarnessArtifactPaths
    command: Sequence[str] = ()
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    events: list[LifecycleEvent] = field(default_factory=list)

    def record_stdout(self, text: str) -> Path:
        self.stdout.append(text)
        path = self.artifacts.transcript_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
        return path

    def record_stderr(self, text: str) -> Path:
        self.stderr.append(text)
        path = self.artifacts.log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
        return path

    def record_event(self, event: LifecycleEvent | dict[str, Any]) -> Path:
        normalized = LifecycleEvent.from_value(event)
        self.events.append(normalized)
        path = self.artifacts.events_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized.to_dict(), sort_keys=True) + "\n")
        return path

    def write_summary(
        self,
        *,
        status: str,
        exit_code: int | None,
        error: str = "",
        details: dict[str, Any] | None = None,
    ) -> Path:
        summary = {
            "command": list(self.command),
            "details": dict(details or {}),
            "error": error,
            "exit_code": exit_code,
            "status": status,
        }
        path = self.artifacts.summary_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def finish(
        self,
        *,
        status: str = "ok",
        exit_code: int | None = None,
        error: str = "",
        details: dict[str, Any] | None = None,
    ) -> HarnessResult:
        self.write_summary(status=status, exit_code=exit_code, error=error, details=details)
        return HarnessResult(status=status, exit_code=exit_code, error=error, details=dict(details or {}))
