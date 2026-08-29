"""Load and filter benchmark results for read-only reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from bench.paths import RepoPaths
from bench.result import TaskResult, load_result
from bench.tasks import TaskLoadError, load_task


@dataclass(frozen=True)
class ReportEntry:
    path: Path
    result: TaskResult
    batch: str
    model: str = ""
    orchestra: bool | None = None
    tokens: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.result.run_id

    @property
    def task_id(self) -> str:
        return self.result.task_id

    @property
    def outcome(self) -> str:
        return self.result.outcome

    @property
    def started_at(self) -> str:
        return self.result.run_meta.started_at

    @property
    def finished_at(self) -> str:
        return self.result.run_meta.finished_at

    @property
    def total_tokens(self) -> int | float | None:
        value = self.tokens.get("total") if isinstance(self.tokens, dict) else None
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

    @property
    def elapsed_seconds(self) -> float | None:
        value = None
        if isinstance(self.timing, dict):
            value = self.timing.get("elapsed_seconds")
            if value is None:
                value = self.timing.get("elapsed")
        if value is None:
            value = _elapsed_from_timestamps(self.started_at, self.finished_at)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _default_results_dir() -> Path:
    return RepoPaths(Path.cwd()).results_dir


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_provenance(run_dir: Path) -> dict[str, Any]:
    bench_run = _read_json(run_dir / ".bench_run.json")
    provenance = bench_run.get("provenance") or bench_run.get("config") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    return provenance


def _extract_tokens(result: TaskResult, provenance: dict[str, Any]) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    for candidate in (
        details.get("tokens"),
        details.get("token_summary"),
        provenance.get("tokens"),
        details.get("usage"),
    ):
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _extract_timing(result: TaskResult) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    for candidate in (details.get("timing"), details.get("duration"), details.get("elapsed")):
        if isinstance(candidate, dict):
            return dict(candidate)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return {"elapsed_seconds": float(candidate)}
    timing: dict[str, Any] = {}
    elapsed = _elapsed_from_timestamps(result.run_meta.started_at, result.run_meta.finished_at)
    if elapsed is not None:
        timing["elapsed_seconds"] = elapsed
    return timing


def _extract_provenance(result: TaskResult, provenance: dict[str, Any]) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    merged: dict[str, Any] = {}
    for candidate in (
        provenance,
        details.get("provenance"),
        details.get("run_meta"),
    ):
        if isinstance(candidate, dict):
            merged.update(candidate)
    return merged


def _coerce_batch(result: TaskResult, provenance: dict[str, Any], tasks_dir: Path | None) -> str:
    if result.batch:
        return result.batch
    task_id = result.task_id
    if provenance.get("batch"):
        return str(provenance.get("batch") or "")
    if tasks_dir is not None:
        try:
            task = load_task(task_id, tasks_root=tasks_dir)
            return task.batch
        except (TaskLoadError, ValueError, FileNotFoundError, IsADirectoryError):
            return ""
    return ""


def _coerce_model(result: TaskResult, provenance: dict[str, Any]) -> str:
    if provenance.get("model"):
        return str(provenance.get("model") or "")
    details = result.details if isinstance(result.details, dict) else {}
    inner = details.get("provenance")
    if isinstance(inner, dict) and inner.get("model"):
        return str(inner.get("model") or "")
    return ""


def _coerce_orchestra(result: TaskResult, provenance: dict[str, Any]) -> bool | None:
    details = result.details if isinstance(result.details, dict) else {}
    for source in (provenance, details, details.get("provenance") if isinstance(details.get("provenance"), dict) else {}):
        if not isinstance(source, dict):
            continue
        value = source.get("orchestra")
        if isinstance(value, bool):
            return value
        if value in ("true", "True", 1, "1"):
            return True
        if value in ("false", "False", 0, "0"):
            return False
    return None


def _elapsed_from_timestamps(started_at: str, finished_at: str) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        start = _parse_iso8601(started_at)
        finish = _parse_iso8601(finished_at)
    except ValueError:
        return None
    return max(0.0, (finish - start).total_seconds())


def _parse_iso8601(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _entry_sort_key(entry: ReportEntry) -> tuple[Any, ...]:
    try:
        finished = _parse_iso8601(entry.finished_at) if entry.finished_at else datetime.min.replace(tzinfo=timezone.utc)
    except ValueError:
        finished = datetime.min.replace(tzinfo=timezone.utc)
    return (finished, entry.run_id, entry.task_id)


def collect_results(
    results_dir: Path | str | None = None,
    *,
    tasks_dir: Path | str | None = None,
) -> list[ReportEntry]:
    base = Path(results_dir) if results_dir is not None else _default_results_dir()
    if not base.is_dir():
        return []

    resolved_tasks_dir = Path(tasks_dir) if tasks_dir is not None else None
    entries: list[ReportEntry] = []
    for run_dir in sorted(base.iterdir()):
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        if not result_path.is_file():
            continue
        try:
            result = load_result(result_path)
        except Exception:
            continue
        provenance = _load_provenance(run_dir)
        batch = _coerce_batch(result, provenance, resolved_tasks_dir)
        entries.append(
            ReportEntry(
                path=result_path,
                result=result,
                batch=batch,
                model=_coerce_model(result, provenance),
                orchestra=_coerce_orchestra(result, provenance),
                tokens=_extract_tokens(result, provenance),
                timing=_extract_timing(result),
                provenance=_extract_provenance(result, provenance),
            )
        )
    return sort_results(entries)


def filter_results(
    entries: Iterable[ReportEntry],
    *,
    task: str | None = None,
    suite: str | None = None,
    model: str | None = None,
    orchestra: bool | None = None,
) -> list[ReportEntry]:
    filtered: list[ReportEntry] = []
    for entry in entries:
        if task is not None and entry.task_id != task:
            continue
        if suite is not None and entry.batch != suite:
            continue
        if model is not None and entry.model != model:
            continue
        if orchestra is not None and entry.orchestra is not orchestra:
            continue
        filtered.append(entry)
    return filtered


def _coerce_sort_value(value: Any) -> tuple[int, Any]:
    if value is None:
        return (1, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float, str)):
        return (0, value)
    return (0, str(value))


def _entry_value_for_sort(entry: ReportEntry, key: str) -> Any:
    if key == "finished_at":
        try:
            return _parse_iso8601(entry.finished_at) if entry.finished_at else datetime.min.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if key == "started_at":
        try:
            return _parse_iso8601(entry.started_at) if entry.started_at else datetime.min.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if key == "total_tokens":
        return entry.total_tokens
    if key == "elapsed_seconds":
        return entry.elapsed_seconds
    return getattr(entry, key, None)


def sort_results(
    entries: Sequence[ReportEntry],
    *,
    key: str = "finished_at",
    reverse: bool = True,
) -> list[ReportEntry]:
    return sorted(entries, key=lambda entry: (_coerce_sort_value(_entry_value_for_sort(entry, key)), entry.run_id, entry.task_id), reverse=reverse)


__all__ = [
    "ReportEntry",
    "collect_results",
    "filter_results",
    "sort_results",
]
