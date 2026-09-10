"""Load and filter benchmark results for read-only reporting."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from bench.paths import RepoPaths
from bench.reporting.orchestra_metrics import extract_orchestra_metrics
from bench.reporting.scoring import score_report_entry
from bench.reporting.session_debug import classify_session
from bench.reporting.usage_metrics import extract_usage_metrics
from bench.result import TaskResult, load_result
from bench.tasks import TaskLoadError, load_task


@dataclass(frozen=True)
class ReportEntry:
    path: Path
    result: TaskResult
    batch: str
    model: str = ""
    orchestra: bool | None = None
    score_numeric: float | None = None
    score_display: str = ""
    category_scores: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    failure_reason: str = ""
    harness_status: str = ""
    harness_exit_code: int | None = None
    harness_error: str = ""
    evaluation_status: str = ""
    evaluation_score: str = ""
    evaluation_error: str = ""
    artifact_paths: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    orchestra_metrics: dict[str, Any] = field(default_factory=dict)

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


@dataclass(frozen=True)
class ComparisonSelection:
    selector: str
    label: str
    kind: str
    entries: tuple[ReportEntry, ...]


def _default_results_dir() -> Path:
    return RepoPaths(Path.cwd()).results_dir


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce_float(value: object) -> float | None:
    if not _is_numeric(value):
        try:
            value = float(value)  # type: ignore[assignment]
        except (TypeError, ValueError):
            return None
    return float(value)


def _series_stats(values: Sequence[object]) -> dict[str, Any]:
    numbers = [float(value) for value in values if _is_numeric(value)]
    if not numbers:
        return {"available": 0, "avg": None, "high": None, "low": None}
    return {
        "available": len(numbers),
        "avg": mean(numbers),
        "high": max(numbers),
        "low": min(numbers),
    }


def _count_summary(values: Sequence[object]) -> dict[str, Any]:
    available = 0
    true_count = 0
    for value in values:
        if value is None:
            continue
        available += 1
        if bool(value):
            true_count += 1
    return {"available": available, "true": true_count, "false": available - true_count}


def _numeric_from_mapping(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        coerced = _coerce_float(value)
        if coerced is not None:
            return coerced
    return None


def _first_defined(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _entry_category_value(entry: ReportEntry, category: str) -> float | None:
    value = entry.category_scores.get(category) if isinstance(entry.category_scores, dict) else None
    if isinstance(value, dict):
        return _numeric_from_mapping(value, "score_numeric", "score")
    return _coerce_float(value)


def canonical_functionality_checks(entry: ReportEntry) -> dict[str, bool] | None:
    """Return only the evaluator's canonical functionality checks."""
    details = entry.result.evaluation.details if isinstance(entry.result.evaluation.details, dict) else {}
    functionality = details.get("functionality") if isinstance(details.get("functionality"), dict) else {}
    checks = functionality.get("checks")
    if not isinstance(checks, dict) or not checks or not all(isinstance(name, str) and isinstance(value, bool) for name, value in checks.items()):
        return None
    return dict(checks)


def _entry_token_bucket(entry: ReportEntry, bucket: str) -> dict[str, Any]:
    tokens = entry.tokens if isinstance(entry.tokens, dict) else {}
    bucket_data = tokens.get(bucket) if isinstance(tokens, dict) else None
    return bucket_data if isinstance(bucket_data, dict) else {}


def _entry_token_value(entry: ReportEntry, bucket: str, *keys: str) -> float | None:
    bucket_data = _entry_token_bucket(entry, bucket)
    return _numeric_from_mapping(bucket_data, *keys)


def _entry_orchestra_mapping(entry: ReportEntry, *keys: str) -> dict[str, Any]:
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _entry_orchestra_value(entry: ReportEntry, *keys: str) -> float | None:
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    return _numeric_from_mapping(metrics, *keys)


def _comparison_selector_parts(selector: str) -> tuple[str, str]:
    text = str(selector or "").strip()
    if not text:
        raise ValueError("comparison selector requires a value")
    if ":" in text:
        field, value = text.split(":", 1)
        field = field.strip().lower()
        value = value.strip()
        if field in {"run", "suite", "task", "model", "result"} and value:
            return field, value
    return "run", text


def _match_run_entries(entries: Sequence[ReportEntry], value: str) -> list[ReportEntry]:
    needle = value.strip().lower()
    if not needle:
        return []
    exact: list[ReportEntry] = []
    prefix: list[ReportEntry] = []
    for entry in entries:
        full_ref = f"{entry.run_id}-{entry.task_id}".lower()
        run_id = entry.run_id.lower()
        if needle == full_ref or needle == run_id:
            exact.append(entry)
        elif full_ref.startswith(needle) or run_id.startswith(needle):
            prefix.append(entry)
    return exact or prefix


def _selector_label(kind: str, value: str, entries: Sequence[ReportEntry]) -> str:
    if kind == "run":
        first = entries[0] if entries else None
        if first is not None:
            full_ref = f"{first.run_id}-{first.task_id}"
            if value.strip() in {first.run_id, full_ref}:
                return f"run {full_ref}"
        return f"run {value}"
    return f"{kind}={value}"


def resolve_comparison_selection(entries: Sequence[ReportEntry], selector: str) -> ComparisonSelection:
    kind, value = _comparison_selector_parts(selector)
    rows = list(entries)
    if kind == "run":
        matches = _match_run_entries(rows, value)
    else:
        matches = filter_results(rows, **{kind: value})
    if not matches:
        raise ValueError(f"no results matched selector: {selector!r}")
    if kind == "run" and len(matches) != 1:
        raise ValueError(f"run selector is ambiguous: {selector!r}")
    ordered = tuple(sorted(matches, key=_entry_sort_key))
    return ComparisonSelection(
        selector=str(selector),
        label=_selector_label(kind, value, ordered),
        kind=kind if len(ordered) == 1 else "group",
        entries=ordered,
    )


def _comparison_mode(parent: ComparisonSelection, children: ComparisonSelection) -> str:
    parent_kind = "run" if len(parent.entries) == 1 else "group"
    children_kind = "run" if len(children.entries) == 1 else "group"
    return f"{parent_kind}-vs-{children_kind}"


def _summarize_selection(entries: Sequence[ReportEntry]) -> dict[str, Any]:
    rows = list(entries)
    passed = sum(1 for row in rows if row.outcome == "pass")
    failed = sum(1 for row in rows if row.outcome == "fail")
    errored = sum(1 for row in rows if row.outcome == "error")
    scored = passed + failed

    score_values = [float(row.score_numeric) for row in rows if _is_numeric(row.score_numeric)]
    category_names = ("functionality",)
    categories = {
        category: _series_stats([
            value
            for value in (_entry_category_value(row, category) for row in rows)
            if value is not None
        ])
        for category in category_names
    }

    tokens = {
        "total": _series_stats([
            value
            for value in (row.total_tokens for row in rows)
            if value is not None
        ]),
        "parent_total": _series_stats([
            _first_defined(_entry_token_value(row, "parent_session", "total_tokens"), _entry_token_value(row, "main_session", "total_tokens"))
            for row in rows
            if _first_defined(_entry_token_value(row, "parent_session", "total_tokens"), _entry_token_value(row, "main_session", "total_tokens")) is not None
        ]),
        "children_total": _series_stats([
            _first_defined(_entry_token_value(row, "children_sessions", "total_tokens"), _entry_token_value(row, "subagent_sessions", "total_tokens"))
            for row in rows
            if _first_defined(_entry_token_value(row, "children_sessions", "total_tokens"), _entry_token_value(row, "subagent_sessions", "total_tokens")) is not None
        ]),
        "parent_final_context": _series_stats([
            _first_defined(_entry_token_value(row, "parent_session", "final_context_tokens"), _entry_token_value(row, "main_session", "final_context_tokens"))
            for row in rows
            if _first_defined(_entry_token_value(row, "parent_session", "final_context_tokens"), _entry_token_value(row, "main_session", "final_context_tokens")) is not None
        ]),
        "children_final_context": _series_stats([
            _first_defined(_entry_token_value(row, "children_sessions", "final_context_tokens"), _entry_token_value(row, "subagent_sessions", "final_context_tokens"))
            for row in rows
            if _first_defined(_entry_token_value(row, "children_sessions", "final_context_tokens"), _entry_token_value(row, "subagent_sessions", "final_context_tokens")) is not None
        ]),
        "parent_max_context": _series_stats([
            _first_defined(_entry_token_value(row, "parent_session", "max_context_tokens"), _entry_token_value(row, "main_session", "max_context_tokens"))
            for row in rows
            if _first_defined(_entry_token_value(row, "parent_session", "max_context_tokens"), _entry_token_value(row, "main_session", "max_context_tokens")) is not None
        ]),
        "children_max_context": _series_stats([
            _first_defined(_entry_token_value(row, "children_sessions", "max_context_tokens"), _entry_token_value(row, "subagent_sessions", "max_context_tokens"))
            for row in rows
            if _first_defined(_entry_token_value(row, "children_sessions", "max_context_tokens"), _entry_token_value(row, "subagent_sessions", "max_context_tokens")) is not None
        ]),
        "parent_compactions": _series_stats([
            _first_defined(_entry_token_bucket(row, "parent_session").get("compactions"), _entry_token_bucket(row, "main_session").get("compactions"))
            for row in rows
            if _first_defined(_entry_token_bucket(row, "parent_session").get("compactions"), _entry_token_bucket(row, "main_session").get("compactions")) is not None
        ]),
        "children_compactions": _series_stats([
            _first_defined(_entry_token_bucket(row, "children_sessions").get("compactions"), _entry_token_bucket(row, "subagent_sessions").get("compactions"))
            for row in rows
            if _first_defined(_entry_token_bucket(row, "children_sessions").get("compactions"), _entry_token_bucket(row, "subagent_sessions").get("compactions")) is not None
        ]),
    }

    orchestra = {
        "dispatch_attempts": _series_stats([value for value in (_entry_orchestra_value(row, "dispatch_attempts") for row in rows) if value is not None]),
        "dispatch_accepted": _series_stats([value for value in (_entry_orchestra_value(row, "dispatch_accepted") for row in rows) if value is not None]),
        "dispatch_rejected": _series_stats([value for value in (_entry_orchestra_value(row, "dispatch_rejected") for row in rows) if value is not None]),
        "roles_requested": _series_stats([
            len(row.orchestra_metrics.get("roles_requested") or [])
            for row in rows
            if isinstance(row.orchestra_metrics, dict) and isinstance(row.orchestra_metrics.get("roles_requested"), list)
        ]),
        "roles_started": _series_stats([
            len(row.orchestra_metrics.get("roles_started") or [])
            for row in rows
            if isinstance(row.orchestra_metrics, dict) and isinstance(row.orchestra_metrics.get("roles_started"), list)
        ]),
        "roles_returned": _series_stats([
            len(row.orchestra_metrics.get("roles_returned") or [])
            for row in rows
            if isinstance(row.orchestra_metrics, dict) and isinstance(row.orchestra_metrics.get("roles_returned"), list)
        ]),
        "duplicate_same_slice_dispatches": _series_stats([value for value in (_entry_orchestra_value(row, "duplicate_same_slice_dispatches", "same_slice_dispatches") for row in rows) if value is not None]),
        "same_slice_dispatches": _series_stats([value for value in (_entry_orchestra_value(row, "same_slice_dispatches", "duplicate_same_slice_dispatches") for row in rows) if value is not None]),
        "child_returns": {
            "ok": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_returns")), "ok") for row in rows) if value is not None]),
            "error": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_returns")), "error") for row in rows) if value is not None]),
            "blocker": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_returns")), "blocker") for row in rows) if value is not None]),
        },
        "child_sessions": {
            "completed": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_sessions")), "completed") for row in rows) if value is not None]),
            "failed": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_sessions")), "failed") for row in rows) if value is not None]),
            "timed_out": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_sessions")), "timed_out") for row in rows) if value is not None]),
            "reconciled": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_sessions")), "reconciled") for row in rows) if value is not None]),
            "active": _series_stats([value for value in (_numeric_from_mapping((_entry_orchestra_mapping(row, "child_sessions")), "active") for row in rows) if value is not None]),
        },
        "parent": {
            "waited": _count_summary([_entry_orchestra_mapping(row, "parent").get("waited") for row in rows]),
            "integrated": _count_summary([_entry_orchestra_mapping(row, "parent").get("integrated") for row in rows]),
            "finalized_before_children": _count_summary([_entry_orchestra_mapping(row, "parent").get("finalized_before_children") for row in rows]),
        },
    }

    failure_reasons = Counter(
        str(row.failure_reason).strip()
        for row in rows
        if row.outcome != "pass" and str(row.failure_reason).strip()
    )

    return {
        "runs": len(rows),
        "passed": passed,
        "failed": failed,
        "error": errored,
        "scored": scored,
        "pass_rate": (passed / scored) if scored else None,
        "score": _series_stats(score_values),
        "categories": categories,
        "tokens": tokens,
        "elapsed": _series_stats([row.elapsed_seconds for row in rows if row.elapsed_seconds is not None]),
        "orchestra": orchestra,
        "failure_reasons": [{"reason": reason, "count": count} for reason, count in failure_reasons.most_common()],
    }


def compare_selected_results(entries: Iterable[ReportEntry], parent_selector: str, children_selector: str) -> dict[str, Any]:
    rows = list(entries)
    parent = resolve_comparison_selection(rows, parent_selector)
    children = resolve_comparison_selection(rows, children_selector)
    return {
        "mode": _comparison_mode(parent, children),
        "parent": {"selector": parent.selector, "label": parent.label, "kind": parent.kind, **_summarize_selection(parent.entries)},
        "children": {"selector": children.selector, "label": children.label, "kind": children.kind, **_summarize_selection(children.entries)},
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_bench_run(run_dir: Path) -> dict[str, Any]:
    return _read_json(run_dir / ".bench_run.json")


def _load_provenance(run_dir: Path) -> dict[str, Any]:
    bench_run = _load_bench_run(run_dir)
    provenance = bench_run.get("provenance") or bench_run.get("config") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    return provenance


def _fill_run_meta_from_bench_run(result: TaskResult, bench_run: dict[str, Any]) -> None:
    run_meta = bench_run.get("run_meta") if isinstance(bench_run, dict) else {}
    if not isinstance(run_meta, dict):
        run_meta = {}
    if not result.run_meta.started_at:
        result.run_meta.started_at = str(run_meta.get("started_at") or bench_run.get("started_at") or "")
    if not result.run_meta.finished_at:
        result.run_meta.finished_at = str(run_meta.get("finished_at") or bench_run.get("finished_at") or "")


def _empty_token_bucket() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "api_calls": 0,
        "final_context_tokens": None,
        "max_context_tokens": None,
        "compactions": 0,
    }


def _read_pi_session_events(path: Path) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return tuple(events)


def _session_id_from_events(events: Iterable[dict[str, Any]], fallback: str) -> str:
    for event in events:
        if event.get("type") == "session" and event.get("id"):
            return str(event.get("id") or "")
    return fallback


def _session_usage(event: dict[str, Any]) -> dict[str, Any] | None:
    message = event.get("message")
    if isinstance(message, dict) and message.get("role") in {"assistant", "toolResult"}:
        usage = message.get("usage")
        if isinstance(usage, dict):
            return usage
    if event.get("type") in {"compaction", "branch_summary"}:
        usage = event.get("usage")
        if isinstance(usage, dict):
            return usage
    return None


def _usage_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _usage_total_tokens(usage: dict[str, Any]) -> int:
    total_tokens = usage.get("totalTokens")
    if isinstance(total_tokens, (int, float)) and not isinstance(total_tokens, bool):
        return int(total_tokens)
    input_tokens = _usage_int(usage.get("input"))
    output_tokens = _usage_int(usage.get("output"))
    cache_read_tokens = _usage_int(usage.get("cacheRead"))
    cache_write_tokens = _usage_int(usage.get("cacheWrite")) + _usage_int(usage.get("cacheWrite1h"))
    return input_tokens + output_tokens + cache_read_tokens + cache_write_tokens


def _add_usage(target: dict[str, Any], usage: dict[str, Any]) -> int:
    input_tokens = _usage_int(usage.get("input"))
    output_tokens = _usage_int(usage.get("output"))
    reasoning_tokens = _usage_int(usage.get("reasoning"))
    cache_read_tokens = _usage_int(usage.get("cacheRead"))
    cache_write_tokens = _usage_int(usage.get("cacheWrite")) + _usage_int(usage.get("cacheWrite1h"))
    total_tokens = _usage_total_tokens(usage)
    target["input_tokens"] += input_tokens
    target["output_tokens"] += output_tokens
    target["reasoning_tokens"] += reasoning_tokens
    target["cached_input_read_tokens"] += cache_read_tokens
    target["cache_write_tokens"] += cache_write_tokens
    target["total_tokens"] += total_tokens
    target["api_calls"] += 1
    return total_tokens


def _update_context_metrics(target: dict[str, Any], *, context_total: int) -> None:
    target["final_context_tokens"] = context_total
    current_max = target["max_context_tokens"]
    target["max_context_tokens"] = context_total if current_max is None else max(current_max, context_total)


def _extract_tokens_from_pi_sessions(run_dir: Path) -> dict[str, Any]:
    sessions_dir = run_dir / "artifacts" / "pi-sessions"
    if not sessions_dir.is_dir():
        return {}

    all_sessions = _empty_token_bucket()
    parent_sessions = _empty_token_bucket()
    child_sessions = _empty_token_bucket()
    parent_session_ids: list[str] = []
    child_session_ids: list[str] = []
    session_ids: list[str] = []

    seen_parent = False
    seen_child = False

    for path in sorted(sessions_dir.rglob("*.jsonl")):
        events = _read_pi_session_events(path)
        if not events:
            continue
        session_id = _session_id_from_events(events, path.stem)
        if session_id and session_id not in session_ids:
            session_ids.append(session_id)
        kind = classify_session(path, session_id=session_id)
        if kind == "worker":
            seen_child = True
            if session_id and session_id not in child_session_ids:
                child_session_ids.append(session_id)
            bucket = child_sessions
        else:
            seen_parent = True
            if session_id and session_id not in parent_session_ids:
                parent_session_ids.append(session_id)
            bucket = parent_sessions

        for event in events:
            usage = _session_usage(event)
            if not isinstance(usage, dict):
                continue
            total_tokens = _add_usage(bucket, usage)
            _add_usage(all_sessions, usage)
            _update_context_metrics(bucket, context_total=total_tokens)
            _update_context_metrics(all_sessions, context_total=total_tokens)
            if event.get("type") == "compaction":
                bucket["compactions"] += 1
                all_sessions["compactions"] += 1

    if not session_ids:
        return {}

    payload: dict[str, Any] = {
        "total": all_sessions["total_tokens"],
        "session_ids": session_ids,
        "parent_session_ids": parent_session_ids,
        "child_session_ids": child_session_ids,
        "subagent_session_ids": child_session_ids,
        "all_sessions": all_sessions,
        "parent_session": parent_sessions if seen_parent else None,
        "children_sessions": child_sessions if seen_child else None,
        "main_session": parent_sessions if seen_parent else None,
        "subagent_sessions": child_sessions if seen_child else None,
    }
    return payload


def _extract_tokens(result: TaskResult, provenance: dict[str, Any], run_dir: Path | None = None) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    for candidate in (
        result.tokens,
        details.get("tokens"),
        details.get("token_summary"),
        provenance.get("tokens"),
        details.get("usage"),
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    if run_dir is not None:
        return extract_usage_metrics(run_dir)
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


def _orchestra_tools_available_from_events(run_dir: Path) -> bool | None:
    events_path = run_dir / "artifacts" / "harness" / "events.jsonl"
    if not events_path.is_file():
        return None
    try:
        lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if "Orchestra:on" in line or "orchestra_tools\": \"on" in line or "orchestra_tools': 'on" in line:
            return True
        if "Orchestra:off" in line or "orchestra_tools\": \"off" in line or "orchestra_tools': 'off" in line:
            return False
    return None


def _extract_provenance(result: TaskResult, provenance: dict[str, Any], run_dir: Path | None = None) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    merged: dict[str, Any] = {}
    for candidate in (
        provenance,
        details.get("provenance"),
        details.get("run_meta"),
    ):
        if isinstance(candidate, dict):
            merged.update(candidate)
    if merged.get("no_orchestra") is True:
        merged["orchestra_tools_available"] = False
    elif merged.get("orchestra_tools_available") is None and run_dir is not None:
        observed = _orchestra_tools_available_from_events(run_dir)
        if observed is not None:
            merged["orchestra_tools_available"] = observed
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


_NUMERIC_DISPLAY_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*/\s*100\s*$")


def _score_display(result: TaskResult) -> str:
    if result.score_display:
        normalized = result.score_display.strip()
        if _NUMERIC_DISPLAY_RE.match(normalized):
            return normalized
    if result.score_numeric is not None:
        numeric = result.score_numeric
        if float(numeric).is_integer():
            return f"{int(numeric)}/100"
        return f"{numeric:g}/100"
    return ""


def _extract_notes(result: TaskResult, provenance: dict[str, Any]) -> str:
    details = result.details if isinstance(result.details, dict) else {}
    candidates: list[dict[str, Any]] = [provenance, details]
    inner = details.get("provenance")
    if isinstance(inner, dict):
        candidates.append(inner)
    for source in candidates:
        value = source.get("notes")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _summarize_reason(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("summary", "error", "value", "message"):
            candidate = value.get(key)
            if candidate is None:
                continue
            text = str(candidate).strip()
            if text:
                return text
        for candidate in value.values():
            text = str(candidate).strip()
            if text:
                return text
        return ""
    text = str(value).strip()
    return text


def _extract_failure_reason(result: TaskResult) -> str:
    details = getattr(result.evaluation, "details", None)
    if isinstance(details, dict):
        functionality = details.get("functionality")
        if isinstance(functionality, dict):
            checks = functionality.get("checks")
            if isinstance(checks, dict):
                failed = sorted(name for name, value in checks.items() if isinstance(name, str) and value is False)
                if failed:
                    return "failed checks: " + ", ".join(failed)
    candidates: list[Any] = []
    candidates.append(getattr(result.evaluation, "error", None))
    candidates.append(getattr(result.harness, "error", None))
    candidates.append(details)
    for candidate in candidates:
        text = _summarize_reason(candidate)
        if text:
            return text
    return ""


def _extract_artifact_paths(result: TaskResult, run_dir: Path) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    artifacts = details.get("artifacts")
    payload: dict[str, Any] = dict(artifacts) if isinstance(artifacts, dict) else {}
    payload.setdefault("result_json", str(run_dir / "result.json"))
    payload.setdefault("workspace", str(run_dir / "workspace"))
    payload.setdefault("harness", str(run_dir / "artifacts" / "harness"))
    payload.setdefault("evaluator", str(run_dir / "artifacts" / "evaluator"))
    payload.setdefault("sessions", str(run_dir / "artifacts" / "pi-sessions"))
    return payload


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


def _extract_orchestra(result: TaskResult, run_dir: Path) -> dict[str, Any]:
    details = result.details if isinstance(result.details, dict) else {}
    candidate = details.get("orchestra") or result.orchestra
    if isinstance(candidate, dict) and candidate:
        return dict(candidate)
    return extract_orchestra_metrics(run_dir)


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
    entries_by_task: dict[str, list[ReportEntry]] = defaultdict(list)
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
        bench_run = _load_bench_run(run_dir)
        _fill_run_meta_from_bench_run(result, bench_run)
        provenance = _load_provenance(run_dir)
        batch = _coerce_batch(result, provenance, resolved_tasks_dir)
        orchestra_metrics = _extract_orchestra(result, run_dir)
        if orchestra_metrics:
            result.orchestra = dict(orchestra_metrics)
        entry = ReportEntry(
            path=result_path,
            result=result,
            batch=batch,
            model=_coerce_model(result, provenance),
            orchestra=_coerce_orchestra(result, provenance),
            score_numeric=result.score_numeric,
            score_display=_score_display(result),
            category_scores=dict(result.category_scores),
            notes=_extract_notes(result, provenance),
            failure_reason=_extract_failure_reason(result),
            harness_status=result.harness.status,
            harness_exit_code=int(result.harness.exit_code) if isinstance(result.harness.exit_code, (int, float)) and not isinstance(result.harness.exit_code, bool) else None,
            harness_error=result.harness.error,
            evaluation_status=result.evaluation.status,
            evaluation_score=result.evaluation.score,
            evaluation_error=result.evaluation.error,
            artifact_paths=_extract_artifact_paths(result, run_dir),
            tokens=_extract_tokens(result, provenance, run_dir),
            context=dict(result.context),
            timing=_extract_timing(result),
            provenance=_extract_provenance(result, provenance, run_dir),
            orchestra_metrics=orchestra_metrics,
        )
        entries_by_task[entry.task_id].append(entry)

    scored_entries: list[ReportEntry] = []
    for task_entries in entries_by_task.values():
        history: list[ReportEntry] = []
        for entry in sorted(task_entries, key=_entry_sort_key):
            scored = score_report_entry(entry, history=history)
            entry.result.score_numeric = scored.score_numeric
            entry.result.score_display = scored.score_display
            entry.result.category_scores = dict(scored.category_scores)
            scored_entry = replace(
                entry,
                score_numeric=scored.score_numeric,
                score_display=scored.score_display,
                category_scores=dict(scored.category_scores),
            )
            history.append(scored_entry)
            scored_entries.append(scored_entry)

    return sort_results(scored_entries)


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return text


def _flatten_text_values(value: object) -> list[str]:
    values: list[str] = []
    if value is None:
        return values
    if isinstance(value, bool):
        values.append("yes" if value else "no")
        values.append("true" if value else "false")
        return values
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        values.append(str(value))
        return values
    if isinstance(value, str):
        text = value.strip()
        if text:
            values.append(text)
        return values
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_flatten_text_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        for item in value:
            values.extend(_flatten_text_values(item))
    return values


def _collect_matching_field_values(data: object, field: str) -> list[str]:
    field_name = field.strip().lower()
    if not field_name:
        return []
    values: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).strip().lower() == field_name:
                values.extend(_flatten_text_values(value))
            values.extend(_collect_matching_field_values(value, field_name))
    elif isinstance(data, (list, tuple, set)):
        for value in data:
            values.extend(_collect_matching_field_values(value, field_name))
    return values


def _candidate_field_values(entry: ReportEntry, field: str) -> list[str]:
    field_name = field.strip().lower()
    if field_name == "task":
        return [entry.task_id]
    if field_name == "suite":
        return [entry.batch]
    if field_name == "model":
        return [entry.model, str(entry.provenance.get("model") or "")]
    if field_name == "harness":
        values = [entry.harness_status, str(entry.provenance.get("harness") or ""), str(entry.provenance.get("backend") or "")]
        details = entry.result.harness.details if isinstance(entry.result.harness.details, dict) else {}
        values.extend(_collect_matching_field_values(details, "harness"))
        values.extend(_collect_matching_field_values(details, "backend"))
        return values
    if field_name == "result":
        return [entry.outcome, entry.result.evaluation.score, entry.result.harness.status]
    if field_name == "notes":
        return [entry.notes, entry.failure_reason]
    if field_name == "orchestra":
        values = ["yes" if entry.orchestra else "no" if entry.orchestra is False else ""]
        values.extend(_flatten_text_values(entry.provenance.get("orchestra")))
        return values
    if field_name == "role":
        values = [str(entry.provenance.get("role") or ""), str(entry.provenance.get("default_role") or "")]
        values.extend(_collect_matching_field_values(entry.result.task_meta, "role"))
        values.extend(_collect_matching_field_values(entry.result.task_meta, "default_role"))
        values.extend(_collect_matching_field_values(entry.orchestra_metrics, "role"))
        return values
    values: list[str] = []
    for source in (entry.provenance, entry.result.task_meta, entry.result.details, entry.tokens, entry.category_scores, entry.orchestra_metrics):
        values.extend(_collect_matching_field_values(source, field_name))
    return values


def _matches_field(entry: ReportEntry, field: str, expected: str) -> bool:
    needle = _normalize_text(expected)
    if not needle:
        return True
    if field.strip().lower() == "orchestra":
        if needle in {"yes", "true", "1"}:
            return entry.orchestra is True
        if needle in {"no", "false", "0"}:
            return entry.orchestra is False
    candidates = {_normalize_text(value) for value in _candidate_field_values(entry, field) if _normalize_text(value)}
    return any(needle in candidate for candidate in candidates)


def parse_since_filter(value: str, *, now: datetime | None = None) -> datetime:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("since filter requires a value")
    current = now or datetime.now(timezone.utc)
    if text == "today":
        return current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if text == "yesterday":
        return current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    if text[0] in {"+", "-"}:
        text = text[1:]
    if len(text) < 2 or not text[:-1].isdigit():
        raise ValueError(f"unsupported since filter: {value!r}")
    amount = int(text[:-1])
    unit = text[-1]
    delta: timedelta
    if unit == "m":
        delta = timedelta(minutes=amount)
    elif unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    elif unit == "s":
        delta = timedelta(seconds=amount)
    else:
        raise ValueError(f"unsupported since filter: {value!r}")
    return current - delta


def _coerce_since(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_since_filter(text)
    except ValueError:
        try:
            return _parse_iso8601(text)
        except ValueError:
            raise


def _entry_finished_at(entry: ReportEntry) -> datetime | None:
    if not entry.finished_at:
        return None
    try:
        return _parse_iso8601(entry.finished_at)
    except ValueError:
        return None


def filter_results(
    entries: Iterable[ReportEntry],
    *,
    task: str | None = None,
    suite: str | None = None,
    model: str | None = None,
    harness: str | None = None,
    result: str | None = None,
    notes: str | None = None,
    since: datetime | str | None = None,
    orchestra: bool | None = None,
    role: str | None = None,
    filters: Sequence[tuple[str, str]] | None = None,
) -> list[ReportEntry]:
    filtered: list[ReportEntry] = []
    cutoff = _coerce_since(since)
    generic_filters = list(filters or [])
    for entry in entries:
        if task is not None and not _matches_field(entry, "task", task):
            continue
        if suite is not None and not _matches_field(entry, "suite", suite):
            continue
        if model is not None and not _matches_field(entry, "model", model):
            continue
        if harness is not None and not _matches_field(entry, "harness", harness):
            continue
        if result is not None and not _matches_field(entry, "result", result):
            continue
        if notes is not None and not _matches_field(entry, "notes", notes):
            continue
        if orchestra is not None and entry.orchestra is not orchestra:
            continue
        if role is not None and not _matches_field(entry, "role", role):
            continue
        if cutoff is not None:
            finished_at = _entry_finished_at(entry)
            if finished_at is None or finished_at < cutoff:
                continue
        matched = True
        for field, expected in generic_filters:
            if not _matches_field(entry, field, expected):
                matched = False
                break
        if not matched:
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
    "ComparisonSelection",
    "ReportEntry",
    "canonical_functionality_checks",
    "collect_results",
    "compare_selected_results",
    "filter_results",
    "resolve_comparison_selection",
    "sort_results",
]
