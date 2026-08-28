"""Backend-neutral harness request, lifecycle event, and artifact helpers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from bench.paths import RunPaths
from bench.result import HarnessResult


@dataclass(frozen=True)
class HarnessArtifactPaths:
    root: Path
    transcript_path: Path
    events_path: Path
    summary_path: Path
    log_path: Path

    @classmethod
    def for_run_paths(cls, run_paths: RunPaths) -> "HarnessArtifactPaths":
        root = run_paths.artifacts_dir / "harness"
        return cls(
            root=root,
            transcript_path=root / "transcript.txt",
            events_path=root / "events.jsonl",
            summary_path=root / "summary.json",
            log_path=root / "run.log",
        )


@dataclass(frozen=True)
class LifecycleEvent:
    type: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LifecycleEvent":
        return cls(
            type=str(data.get("type") or ""),
            message=str(data.get("message") or ""),
            data=dict(data.get("data") or {}),
            timestamp=str(data.get("timestamp") or ""),
        )

    @classmethod
    def from_value(cls, value: "LifecycleEvent | dict[str, Any]") -> "LifecycleEvent":
        if isinstance(value, cls):
            return value
        return cls.from_dict(value)


@dataclass(frozen=True)
class HarnessRequest:
    run_paths: RunPaths
    prompt: str
    model: str = ""
    agent: str = ""
    profile: str = ""
    timeout_seconds: float | None = None
    env: dict[str, str] = field(default_factory=dict)
    artifacts: HarnessArtifactPaths | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.artifacts is None:
            object.__setattr__(self, "artifacts", HarnessArtifactPaths.for_run_paths(self.run_paths))


@runtime_checkable
class Harness(Protocol):
    def run(self, request: HarnessRequest) -> HarnessResult:
        ...


class BaseHarness(ABC):
    @abstractmethod
    def run(self, request: HarnessRequest) -> HarnessResult:
        raise NotImplementedError

    def write_transcript(self, request: HarnessRequest, text: str) -> Path:
        path = request.artifacts.transcript_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
        return path

    def write_event(self, request: HarnessRequest, event: LifecycleEvent | dict[str, Any]) -> Path:
        path = request.artifacts.events_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = LifecycleEvent.from_value(event).to_dict()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return path

    def write_log(self, request: HarnessRequest, text: str) -> Path:
        path = request.artifacts.log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
        return path

    def write_summary(self, request: HarnessRequest, summary: dict[str, Any]) -> Path:
        path = request.artifacts.summary_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def build_result(
        self,
        *,
        status: str = "not_run",
        exit_code: int | None = None,
        error: str = "",
        details: dict[str, Any] | None = None,
    ) -> HarnessResult:
        return HarnessResult(status=status, exit_code=exit_code, error=error, details=dict(details or {}))
