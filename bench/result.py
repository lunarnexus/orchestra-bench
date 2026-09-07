"""Stable result schema and atomic JSON persistence for benchmark runs."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .ownership import normalize_run_ownership

SCHEMA_VERSION = "v2"


class ResultSchemaError(ValueError):
    """Raised when a result JSON document is missing or violates the V2 schema."""


def _mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ResultSchemaError(f"{field_name} must be a JSON object")
    return dict(value)


def _optional_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _mapping(value, field_name=field_name)


def _coerce_score_numeric(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ResultSchemaError("score_numeric must be a number or null")
    if isinstance(value, (int, float)):
        return float(value)
    raise ResultSchemaError("score_numeric must be a number or null")


@dataclass
class RunMeta:
    run_id: str
    task_id: str
    batch: str = ""
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMeta":
        payload = _mapping(data, field_name="run_meta")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            task_id=str(payload.get("task_id") or ""),
            batch=str(payload.get("batch") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
        )


@dataclass
class HarnessResult:
    status: str = "not_run"  # not_run | ok | lifecycle_failed
    exit_code: int | None = None
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessResult":
        payload = _mapping(data, field_name="harness")
        return cls(
            status=str(payload.get("status") or "not_run"),
            exit_code=payload.get("exit_code"),
            error=str(payload.get("error") or ""),
            details=_optional_mapping(payload.get("details"), field_name="harness.details"),
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
        payload = _mapping(data, field_name="evaluation")
        return cls(
            status=str(payload.get("status") or "not_run"),
            score=str(payload.get("score") or ""),
            checks=_optional_mapping(payload.get("checks"), field_name="evaluation.checks"),
            error=str(payload.get("error") or ""),
            details=_optional_mapping(payload.get("details"), field_name="evaluation.details"),
        )


@dataclass
class TaskResult:
    run_meta: RunMeta
    schema_version: str = SCHEMA_VERSION
    harness: HarnessResult = field(default_factory=HarnessResult)
    evaluation: EvaluationResult = field(default_factory=EvaluationResult)
    outcome: str = "not_run"  # not_run | pass | fail | error
    score_numeric: float | None = None
    score_display: str = ""
    task_meta: dict[str, Any] = field(default_factory=dict)
    category_scores: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    orchestra: dict[str, Any] = field(default_factory=dict)
    reliability: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = str(self.schema_version or "")
        if self.schema_version != SCHEMA_VERSION:
            raise ResultSchemaError(f"unsupported result schema version: {self.schema_version!r}")
        self.outcome = str(self.outcome or "not_run")
        self.score_display = str(self.score_display or "")
        self.score_numeric = _coerce_score_numeric(self.score_numeric)
        self.task_meta = _optional_mapping(self.task_meta, field_name="task_meta")
        self.category_scores = _optional_mapping(self.category_scores, field_name="category_scores")
        self.tokens = _optional_mapping(self.tokens, field_name="tokens")
        self.context = _optional_mapping(self.context, field_name="context")
        self.orchestra = _optional_mapping(self.orchestra, field_name="orchestra")
        self.reliability = _optional_mapping(self.reliability, field_name="reliability")
        self.details = _optional_mapping(self.details, field_name="details")

    @property
    def run_id(self) -> str:
        return self.run_meta.run_id

    @property
    def task_id(self) -> str:
        return self.run_meta.task_id

    @property
    def batch(self) -> str:
        return self.run_meta.batch

    @property
    def result(self) -> str:
        return self.outcome

    @property
    def verdict(self) -> str:
        return self.outcome

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskResult":
        payload = _mapping(data, field_name="result JSON")
        try:
            schema_version = str(payload["schema_version"] or "")
            run_meta_payload = payload["run_meta"]
            harness_payload = payload["harness"]
            evaluation_payload = payload["evaluation"]
            score_numeric_payload = payload["score_numeric"]
            score_display_payload = payload["score_display"]
            task_meta_payload = payload["task_meta"]
            category_scores_payload = payload["category_scores"]
            tokens_payload = payload["tokens"]
            context_payload = payload["context"]
            orchestra_payload = payload["orchestra"]
            reliability_payload = payload["reliability"]
            details_payload = payload["details"]
            outcome_payload = payload["outcome"]
        except KeyError as exc:
            raise ResultSchemaError(f"result JSON missing required field: {exc.args[0]}") from exc

        if schema_version != SCHEMA_VERSION:
            raise ResultSchemaError(f"unsupported result schema version: {schema_version!r}")

        return cls(
            run_meta=RunMeta.from_dict(run_meta_payload),
            schema_version=schema_version,
            harness=HarnessResult.from_dict(harness_payload),
            evaluation=EvaluationResult.from_dict(evaluation_payload),
            outcome=str(outcome_payload or "not_run"),
            score_numeric=_coerce_score_numeric(score_numeric_payload),
            score_display=str(score_display_payload or ""),
            task_meta=_optional_mapping(task_meta_payload, field_name="task_meta"),
            category_scores=_optional_mapping(category_scores_payload, field_name="category_scores"),
            tokens=_optional_mapping(tokens_payload, field_name="tokens"),
            context=_optional_mapping(context_payload, field_name="context"),
            orchestra=_optional_mapping(orchestra_payload, field_name="orchestra"),
            reliability=_optional_mapping(reliability_payload, field_name="reliability"),
            details=_optional_mapping(details_payload, field_name="details"),
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
        normalize_run_ownership(dest.parent)
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
