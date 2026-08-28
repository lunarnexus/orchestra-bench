"""Stable result schema and atomic JSON persistence for benchmark runs."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunMeta:
    run_id: str
    task_id: str
    batch: str = ""
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMeta":
        return cls(
            run_id=str(data.get("run_id") or ""),
            task_id=str(data.get("task_id") or ""),
            batch=str(data.get("batch") or ""),
            started_at=str(data.get("started_at") or ""),
            finished_at=str(data.get("finished_at") or ""),
        )


@dataclass
class HarnessResult:
    status: str = "not_run"  # not_run | ok | lifecycle_failed
    exit_code: int | None = None
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessResult":
        return cls(
            status=str(data.get("status") or "not_run"),
            exit_code=data.get("exit_code"),
            error=str(data.get("error") or ""),
            details=dict(data.get("details") or {}),
        )


@dataclass
class EvaluationResult:
    status: str = "not_run"  # not_run | ok | failed
    score: str = ""
    checks: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationResult":
        return cls(
            status=str(data.get("status") or "not_run"),
            score=str(data.get("score") or ""),
            checks=dict(data.get("checks") or {}),
            error=str(data.get("error") or ""),
            details=dict(data.get("details") or {}),
        )


@dataclass
class TaskResult:
    run_meta: RunMeta
    harness: HarnessResult = field(default_factory=HarnessResult)
    evaluation: EvaluationResult = field(default_factory=EvaluationResult)
    outcome: str = "not_run"  # not_run | pass | fail
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.run_meta.run_id

    @property
    def task_id(self) -> str:
        return self.run_meta.task_id

    @property
    def batch(self) -> str:
        return self.run_meta.batch

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskResult":
        if "run_meta" in data:
            run_meta = RunMeta.from_dict(dict(data.get("run_meta") or {}))
        else:
            run_meta = RunMeta.from_dict(data)

        return cls(
            run_meta=run_meta,
            harness=HarnessResult.from_dict(dict(data.get("harness") or {})),
            evaluation=EvaluationResult.from_dict(dict(data.get("evaluation") or {})),
            outcome=str(data.get("outcome") or data.get("score") or "not_run"),
            details=dict(data.get("details") or {}),
        )


def _json_text(result: TaskResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def _cleanup_temp_file(path: Path | None) -> None:
    if path is None:
        return
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json_atomic(path: Path | str, result: TaskResult) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(_json_text(result))
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(tmp_path, 0o644)  # container runs as root; host operators must read run outputs
        os.replace(tmp_path, dest)
        _fsync_directory(dest.parent)
        return dest
    except Exception:
        _cleanup_temp_file(tmp_path)
        raise


def load_result(path: Path | str) -> TaskResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("result JSON must be an object")
    return TaskResult.from_dict(data)

