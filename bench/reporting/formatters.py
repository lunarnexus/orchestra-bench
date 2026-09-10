"""Human-readable reporting views for benchmark results."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .queries import ReportEntry, canonical_functionality_checks


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


_HUMAN_NUMBER_UNITS = ((10**12, "T"), (10**9, "B"), (10**6, "M"), (10**3, "K"))


def human_number(value: int | float | bool | None) -> str:
    """Format a numeric value for compact human-readable reporting.

    Small numbers render plainly; large ones use K/M/B/T suffixes with one
    decimal (e.g. 572129.3 -> "572.1K", 2132494 -> "2.1M"). None renders as
    "n/a" and booleans render verbatim, matching existing formatter output.
    """
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    magnitude = abs(number)
    if magnitude < 1000:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    for scale, suffix in _HUMAN_NUMBER_UNITS:
        if magnitude >= scale:
            text = f"{number / scale:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return str(value)


def _fmt_number(value: int | float | bool | None) -> str:
    """Backward-compatible numeric formatter backed by :func:`human_number`."""
    return human_number(value)


def _fmt_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 60:
        return f"{value:.1f}s"
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes)}m{seconds:04.1f}s"


def _fmt_timestamp(value: str | None) -> str:
    if not value:
        return "n/a"
    text = str(value).strip()
    if not text:
        return "n/a"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _meaningful_reason(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized not in {"", "n/a", "na", "ok", "pass", "passed", "success", "succeeded", "done"}


def _should_show_score(outcome: str, score: str) -> bool:
    normalized = score.strip().lower()
    return bool(normalized) and normalized not in {"n/a", "na"} and normalized != outcome.strip().lower()


def _score_display(outcome: str, score: str) -> str:
    normalized = score.strip()
    if normalized:
        return normalized
    return outcome or "n/a"


def _agent_display(entry: ReportEntry) -> str:
    provenance = entry.provenance if isinstance(entry.provenance, dict) else {}
    if not provenance:
        details = entry.result.details if isinstance(entry.result.details, dict) else {}
        fallback = details.get("provenance")
        if isinstance(fallback, dict):
            provenance = fallback
    parts: list[str] = []
    harness = str(provenance.get("harness") or provenance.get("backend") or "").strip()
    backend = str(provenance.get("backend") or "").strip()
    if harness:
        parts.append(f"harness={harness}")
    if backend and backend != harness:
        parts.append(f"backend={backend}")
    parts.append(f"model={entry.model or provenance.get('model') or 'n/a'}")
    parts.append(f"orchestra={_fmt_bool(entry.orchestra)}")
    return " ".join(parts)


def _status(row: ReportEntry) -> str:
    # A lifecycle-incomplete run must never render as PASS/FAIL, even if an
    # inconsistent result.json claims a product outcome.
    if row.harness_status and str(row.harness_status).strip().lower() not in ("", "ok"):
        return row.harness_status
    if row.outcome == "pass":
        return "PASS"
    if row.outcome == "fail":
        return "FAIL"
    if row.harness_status and row.harness_status != "ok":
        return row.harness_status
    return row.outcome or "n/a"


def _entry_harness_failed(entry: ReportEntry) -> bool:
    status = str(entry.harness_status or "").strip().lower()
    return bool(status) and status != "ok"


def _entry_is_scored(entry: ReportEntry) -> bool:
    """True when the run completed its lifecycle and produced an evaluator verdict.

    Lifecycle-incomplete runs (harness failed / crashed / timed out) and runs
    whose evaluation errored or never ran are not scored, regardless of any
    score fields that may be present on a partial result.
    """
    if _entry_harness_failed(entry):
        return False
    if entry.outcome not in ("pass", "fail"):
        return False
    status = str(entry.evaluation_status or "").strip().lower()
    if status in {"failed", "error"} and entry.score_numeric is None:
        return False
    return True


def _lifecycle_error_reason(entry: ReportEntry) -> str:
    status = str(entry.harness_status or "").strip() or "failed"
    reason = _summarize_multiline(entry.harness_error)
    if not _meaningful_reason(reason):
        reason = f"harness {status}"
    if entry.harness_exit_code not in (None, 0) and "exit=" not in reason:
        reason = f"{reason} exit={entry.harness_exit_code}"
    return reason


def _evaluator_error_reason(entry: ReportEntry) -> str:
    status = str(entry.evaluation_status or "").strip().lower()
    reason = _summarize_multiline(entry.evaluation_error)
    if _meaningful_reason(reason):
        return reason
    if status and status != "ok":
        return f"evaluation {status}"
    return str(entry.outcome) or "not evaluated"


def _short_model(model: str) -> str:
    if not model:
        return "n/a"
    return model.replace("lmstudio/", "")


def _lines(*items: object) -> str:
    return "\n".join(str(item) for item in items if str(item) != "") + "\n"


def _workspace_note_buckets(workspace: Path) -> dict[str, list[str]]:
    """Classify common post-run workspace extras for operator inspection.

    This is intentionally heuristic and display-only: task outputs remain the
    evaluator's source of truth. The goal is to separate obvious evaluator files
    and runtime caches from agent-created support artifacts when reading a run.
    """
    buckets = {
        "evaluator": [],
        "cache/runtime": [],
        "agent/support": [],
    }
    if not workspace.is_dir():
        return buckets
    for path in sorted(workspace.iterdir(), key=lambda item: item.name):
        name = path.name
        if name.startswith(".evaluator-") or name.startswith(".tmp-evaluator-"):
            buckets["evaluator"].append(name)
        elif name in {"__pycache__", ".pytest_cache"} or name.endswith(".sqlite3"):
            buckets["cache/runtime"].append(name)
        elif name in {"PLAN.md", "RESEARCH.md"} or name.startswith("test_") or name.endswith("_test.py"):
            buckets["agent/support"].append(name)
    return buckets


def _workspace_note_lines(workspace: Path) -> list[str]:
    buckets = _workspace_note_buckets(workspace)
    lines: list[str] = []
    for label, names in buckets.items():
        if names:
            lines.append(f"workspace {label}: {', '.join(names[:8])}" + (f", +{len(names) - 8} more" if len(names) > 8 else ""))
    return lines


def _as_list(entries: Iterable[ReportEntry]) -> list[ReportEntry]:
    return list(entries)


_LABEL_WIDTH = 11


def _fmt_decimal(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.1f}"


def _summary_stats(
    values: list[float],
    *,
    total: int | None = None,
    include_available: bool = False,
    availability_label: str = "available",
    formatter=_fmt_decimal,
) -> str:
    if not values:
        if include_available and total is not None:
            return f"{availability_label}=0/{total} avg=n/a high=n/a low=n/a"
        return "n/a"
    pieces: list[str] = []
    if include_available and total is not None:
        pieces.append(f"{availability_label}={len(values)}/{total}")
    pieces.append(f"avg={formatter(mean(values))}")
    pieces.append(f"high={formatter(max(values))}")
    pieces.append(f"low={formatter(min(values))}")
    return " ".join(pieces)


def _entry_score_value(entry: ReportEntry) -> float | None:
    if isinstance(entry.score_numeric, (int, float)) and not isinstance(entry.score_numeric, bool):
        return float(entry.score_numeric)
    return None


def _entry_category_value(entry: ReportEntry, category: str) -> float | None:
    value = entry.category_scores.get(category) if isinstance(entry.category_scores, dict) else None
    if isinstance(value, dict):
        candidate = value.get("score_numeric")
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
        candidate = value.get("score")
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _entry_token_value(entry: ReportEntry, bucket: str, key: str = "total_tokens") -> float | None:
    tokens = entry.tokens if isinstance(entry.tokens, dict) else {}
    bucket_data = tokens.get(bucket) if isinstance(tokens, dict) else None
    if not isinstance(bucket_data, dict):
        return None
    value = bucket_data.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _entry_total_tokens(entry: ReportEntry) -> float | None:
    if entry.total_tokens is not None:
        return float(entry.total_tokens)
    for bucket in ("all_sessions", "parent_session", "main_session"):
        value = _entry_token_value(entry, bucket, "total_tokens")
        if value is not None:
            return value
    return None


def _entry_context_bucket(entry: ReportEntry, bucket: str) -> dict[str, Any]:
    tokens = entry.tokens if isinstance(entry.tokens, dict) else {}
    aliases = {
        "parent": ("parent_session", "main_session"),
        "main": ("parent_session", "main_session"),
        "children": ("children_sessions", "subagent_sessions"),
        "all": ("all_sessions",),
    }
    for name in aliases.get(bucket, (bucket,)):
        value = tokens.get(name)
        if isinstance(value, dict) and value:
            return value
    context = entry.context if isinstance(entry.context, dict) else {}
    if not context and isinstance(entry.result.context, dict):
        context = entry.result.context
    value = context.get(bucket)
    return value if isinstance(value, dict) else {}


def _entry_usage_value(entry: ReportEntry, bucket: str, key: str) -> float | None:
    data = _entry_context_bucket(entry, bucket)
    value = data.get(key) if isinstance(data, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _compaction_stats(values: list[float]) -> str:
    if not values:
        return "n/a"
    total = sum(values)
    avg = round(mean(values), 1)
    return f"total={human_number(total)} avg={human_number(avg)}"


def _fmt_usage_value(value: float) -> str:
    """Round per-bucket stats to one decimal before compacting large numbers."""
    return _fmt_number(round(float(value), 1))


def _usage_lines(rows: list[tuple[str, str]]) -> list[str]:
    width = max([_LABEL_WIDTH] + [len(label) + 1 for label, _ in rows]) if rows else _LABEL_WIDTH
    return [f"{label:<{width}}: {value}" for label, value in rows]


def _child_failure_reason_is_pass_override(reason: object) -> bool:
    text = str(reason or "").strip().lower()
    return "verdict:" in text and "pass" in text and ("status: complete" in text or "status: done" in text)


def _entry_child_failure_pass_override(entry: ReportEntry) -> bool:
    reasons = _entry_orchestra_reasons(entry, "child_failure_reasons", "children", "failure_reasons")
    return bool(reasons) and all(_child_failure_reason_is_pass_override(reason) for reason in reasons)


def _entry_orchestra_value(entry: ReportEntry, key: str) -> Any:
    if key == "failed" and _entry_child_failure_pass_override(entry):
        return 0
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    value = metrics.get(key)
    if value is not None:
        return value
    dispatch = metrics.get("dispatch") if isinstance(metrics.get("dispatch"), dict) else {}
    if key in {"dispatch_attempts", "dispatch_accepted", "dispatch_rejected"}:
        return dispatch.get(key.removeprefix("dispatch_"))
    children = metrics.get("child_sessions") if isinstance(metrics.get("child_sessions"), dict) else {}
    if key in {"completed", "failed", "timed_out", "reconciled", "active", "inferred_active"}:
        return children.get(key)
    return None


def _entry_orchestra_mapping(entry: ReportEntry, key: str) -> dict[str, Any]:
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    value = metrics.get(key)
    return value if isinstance(value, dict) else {}


def _entry_orchestra_reasons(entry: ReportEntry, top_key: str, nested_container: str, nested_key: str) -> dict[str, Any]:
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    value = metrics.get(top_key)
    if not isinstance(value, dict):
        container = metrics.get(nested_container)
        if isinstance(container, dict):
            value = container.get(nested_key)
    return value if isinstance(value, dict) else {}


def _reason_counts(rows: list[ReportEntry], top_key: str, nested_container: str, nested_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reasons = _entry_orchestra_reasons(row, top_key, nested_container, nested_key)
        if top_key == "child_failure_reasons" and reasons and all(_child_failure_reason_is_pass_override(reason) for reason in reasons):
            continue
        for reason, count in reasons.items():
            try:
                value = int(count)
            except (TypeError, ValueError):
                continue
            counts[str(reason)] = counts.get(str(reason), 0) + value
    return counts


def _reason_line(label: str, counts: dict[str, int]) -> str:
    ordered = "; ".join(f"{reason}: {count}" for reason, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return _format_label(label, ordered)


_NO_REJECTION_REASON_LABEL = "rejected without recorded reason"
_OPAQUE_REJECTION_MARKERS = {"dispatch was not accepted", "not accepted"}


def _honest_rejection_reason(reason: object) -> str:
    """Render a stored rejection reason with honest wording.

    Extraction falls back to the bare `dispatch was not accepted` marker when an
    orch_dispatch result carried no concrete detail; surface that as an explicit
    no-reason label instead of opaque phrasing. Concrete reasons pass through unchanged.
    """
    text = str(reason or "").strip()
    if text.rstrip(".").strip().lower() in _OPAQUE_REJECTION_MARKERS:
        return _NO_REJECTION_REASON_LABEL
    return text


def _honest_rejection_counts(counts: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for reason, count in counts.items():
        label = _honest_rejection_reason(reason)
        merged[label] = merged.get(label, 0) + count
    return merged


def _fmt_list(value: object) -> str:
    if not isinstance(value, list):
        return "n/a"
    return ", ".join(str(item) for item in value if str(item).strip()) or "none"


def _fmt_explicit_flag(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return "unknown"


def _fmt_tools_availability(provenance: dict[str, Any]) -> str:
    if provenance.get("no_orchestra") is True or provenance.get("orchestra_tools_available") is False:
        return "disabled"
    if provenance.get("orchestra_tools_available") is True:
        return "available"
    if provenance.get("orchestra_tools_executed") is True:
        return "observed"
    return "unknown"


def _entry_dispatch_value(entry: ReportEntry, key: str) -> float:
    if key == "failed" and _entry_child_failure_pass_override(entry):
        return 0.0
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    value = metrics.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    dispatch = metrics.get("dispatch") if isinstance(metrics.get("dispatch"), dict) else {}
    if isinstance(dispatch, dict):
        nested = dispatch.get(key)
        if isinstance(nested, (int, float)) and not isinstance(nested, bool):
            return float(nested)
    children = metrics.get("child_sessions") if isinstance(metrics.get("child_sessions"), dict) else {}
    if key in {"completed", "failed", "timed_out", "reconciled", "active", "inferred_active"} and isinstance(children, dict):
        nested = children.get(key)
        if isinstance(nested, (int, float)) and not isinstance(nested, bool):
            return float(nested)
    return 0.0


def _entry_tool_activity(entry: ReportEntry) -> dict[str, Any] | None:
    metrics = entry.orchestra_metrics if isinstance(entry.orchestra_metrics, dict) else {}
    activity = metrics.get("tool_activity") or metrics.get("contamination")
    if isinstance(activity, dict) and activity.get("detected"):
        return activity
    if activity is True:
        return {"detected": True}
    orchestration = entry.category_scores.get("orchestration") if isinstance(entry.category_scores, dict) else {}
    inputs = orchestration.get("inputs") if isinstance(orchestration, dict) else {}
    activity = inputs.get("tool_activity") or inputs.get("contamination") if isinstance(inputs, dict) else None
    if isinstance(activity, dict) and activity.get("detected"):
        return activity
    if activity is True:
        return {"detected": True}
    provenance = entry.provenance if isinstance(entry.provenance, dict) else {}
    if not provenance:
        details = entry.result.details if isinstance(entry.result.details, dict) else {}
        fallback = details.get("provenance")
        if isinstance(fallback, dict):
            provenance = fallback
    activity = provenance.get("tool_activity")
    if isinstance(activity, dict) and activity.get("detected"):
        return activity
    if activity is True:
        return {"detected": True}
    return None


def _format_label(label: str, value: str) -> str:
    width = max(_LABEL_WIDTH, len(label) + 1)
    return f"{label:<{width}}: {value}"


def format_dashboard(entries: Iterable[ReportEntry]) -> str:
    rows = _as_list(entries)
    total = len(rows)
    scored_rows = [row for row in rows if _entry_is_scored(row)]
    evaluated = len(scored_rows)
    not_evaluated = total - evaluated
    passed = sum(1 for row in scored_rows if row.outcome == "pass")
    failed = sum(1 for row in scored_rows if row.outcome == "fail")
    errored = sum(1 for row in rows if row.outcome == "error" or not _entry_is_scored(row))
    scored_total = passed + failed
    by_suite: dict[str, list[ReportEntry]] = defaultdict(list)
    for row in rows:
        by_suite[row.batch or "unlabeled"].append(row)

    score_values = [_entry_score_value(row) for row in rows]
    score_values = [value for value in score_values if value is not None]
    category_names = ("functionality",)
    usage_buckets = ("all", "main", "children")
    token_values_by_bucket = {
        bucket: [value for value in (_entry_usage_value(row, bucket, "total_tokens") for row in rows) if value is not None]
        for bucket in usage_buckets
    }
    context_values_by_bucket = {
        bucket: [value for value in (_entry_usage_value(row, bucket, "final_context_tokens") for row in rows) if value is not None]
        for bucket in usage_buckets
    }
    compaction_values_by_bucket = {
        bucket: [value for value in (_entry_usage_value(row, bucket, "compactions") for row in rows) if value is not None]
        for bucket in usage_buckets
    }
    elapsed_values = [row.elapsed_seconds for row in rows if row.elapsed_seconds is not None]
    dispatch_attempts = sum(_entry_dispatch_value(row, "dispatch_attempts") for row in rows)
    dispatch_accepted = sum(_entry_dispatch_value(row, "dispatch_accepted") for row in rows)
    dispatch_rejected = sum(_entry_dispatch_value(row, "dispatch_rejected") for row in rows)
    child_completed = sum(_entry_dispatch_value(row, "completed") for row in rows)
    child_failed = sum(_entry_dispatch_value(row, "failed") for row in rows)
    child_timed_out = sum(_entry_dispatch_value(row, "timed_out") for row in rows)
    child_reconciled = sum(_entry_dispatch_value(row, "reconciled") for row in rows)
    child_active = sum(_entry_dispatch_value(row, "active") for row in rows)
    child_inferred_active = sum(_entry_dispatch_value(row, "inferred_active") for row in rows)

    task_counts: dict[str, int] = {}
    for row in rows:
        tid = str(row.task_id or "").strip()
        if tid:
            task_counts[tid] = task_counts.get(tid, 0) + 1
    duplicate_tasks = {tid: count for tid, count in task_counts.items() if count > 1}

    lifecycle_reasons: dict[str, int] = {}
    evaluator_reasons: dict[str, int] = {}
    lifecycle_refs: dict[str, list[str]] = {}
    evaluator_refs: dict[str, list[str]] = {}
    for row in rows:
        if _entry_is_scored(row):
            continue
        ref = f"{row.run_id}-{row.task_id}"
        if _entry_harness_failed(row):
            bucket, reason, refs = lifecycle_reasons, _lifecycle_error_reason(row), lifecycle_refs
        else:
            bucket, reason, refs = evaluator_reasons, _evaluator_error_reason(row), evaluator_refs
        bucket[reason] = bucket.get(reason, 0) + 1
        refs.setdefault(reason, []).append(ref)
    errors_lines: list[str] = []
    if not lifecycle_reasons and not evaluator_reasons:
        errors_lines.append("no lifecycle or evaluator errors")
    else:
        def _counted(counts: dict[str, int], refs: dict[str, list[str]]) -> str:
            parts = []
            for reason, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
                listed = refs.get(reason, [])[:5]
                extra = len(refs.get(reason, ())) - len(listed)
                ref_text = " ".join(listed) + (f" (+{extra} more)" if extra > 0 else "")
                parts.append(f"{reason}: {count} [{ref_text}]")
            return "; ".join(parts)
        if lifecycle_reasons:
            errors_lines.append(_format_label("lifecycle", _counted(lifecycle_reasons, lifecycle_refs)))
        if evaluator_reasons:
            errors_lines.append(_format_label("evaluator", _counted(evaluator_reasons, evaluator_refs)))

    reject_reasons = _reason_counts(rows, "dispatch_rejection_reasons", "dispatch", "rejection_reasons")
    child_fail_reasons = _reason_counts(rows, "child_failure_reasons", "children", "failure_reasons")
    reason_lines: list[str] = []
    if reject_reasons:
        reason_lines.append(_reason_line("rejects", _honest_rejection_counts(reject_reasons)))
    if child_fail_reasons:
        reason_lines.append(_reason_line("child fails", child_fail_reasons))

    usage_rows: list[tuple[str, str]] = []
    for bucket in ("all", "main", "children"):
        usage_rows.append((f"tokens {bucket}", _summary_stats(token_values_by_bucket[bucket], formatter=_fmt_usage_value)))
    for bucket in ("all", "main", "children"):
        usage_rows.append((f"context {bucket}", _summary_stats(context_values_by_bucket[bucket], formatter=_fmt_usage_value)))
    for bucket in ("all", "main", "children"):
        usage_rows.append((f"compactions {bucket}", _compaction_stats(compaction_values_by_bucket[bucket])))
    usage_rows.append(("elapsed", _summary_stats([float(value) for value in elapsed_values], formatter=_fmt_seconds)))

    body = [
        "=== orchestra-bench dashboard ===",
        _format_label("runs", str(total)),
        _format_label("passed", str(passed)),
        _format_label("failed", str(failed)),
        _format_label("error", str(errored)),
    ]
    if duplicate_tasks:
        dup_text = ", ".join(
            f"{tid} x{count}" for tid, count in sorted(duplicate_tasks.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        body.append(_format_label("duplicates", f"warning: {len(duplicate_tasks)} task id(s) selected more than once (retries): {dup_text}"))
    body.extend([
        _format_label("evaluated", f"{evaluated}/{total}"),
        _format_label("not evaluated", str(not_evaluated)),
        _format_label(
            "evaluated pass rate",
            f"{(passed / scored_total) * 100:.1f}% ({passed}/{scored_total}) over {evaluated} evaluated runs" if scored_total else "n/a (no evaluated runs)",
        ),
        "",
        "=== scores ===",
        _format_label("score", _summary_stats(score_values, total=total, include_available=True)),
    ])
    for category in category_names:
        category_values = [value for value in (_entry_category_value(row, category) for row in rows) if value is not None]
        body.append(_format_label(category, _summary_stats(category_values, total=total, include_available=True, availability_label="scored")))

    body.extend(
        [
            "",
            "=== usage ===",
            *_usage_lines(usage_rows),
            "",
            "=== orchestra ===",
            _format_label("dispatches", f"attempts={_fmt_decimal(dispatch_attempts)} accepted={_fmt_decimal(dispatch_accepted)} rejected={_fmt_decimal(dispatch_rejected)}"),
            _format_label("children", f"completed={_fmt_decimal(child_completed)} failed={_fmt_decimal(child_failed)} timed_out={_fmt_decimal(child_timed_out)} reconciled={_fmt_decimal(child_reconciled)} active={_fmt_decimal(child_active)} inferred_active={_fmt_decimal(child_inferred_active)}"),
            *reason_lines,
            "",
            "=== errors ===",
            *errors_lines,
            "",
            "tip: scripts/03-results runs | scripts/03-results run <ref> | scripts/04-debug <ref> orch|full|raw",
        ]
    )
    return _lines(*body)


def format_runs(entries: Iterable[ReportEntry]) -> str:
    rows = _as_list(entries)
    body = ["=== recent runs ==="]
    if not rows:
        body.append("no runs found")
        return _lines(*body)
    for row in rows:
        run_ref = f"{row.run_id}-{row.task_id}"
        notes = str(row.notes or "").replace("\n", " ").strip()
        body.append(
            f"{_status(row):<16} {run_ref:<54} "
            f"suite={row.batch or 'unlabeled':<10} time={_fmt_seconds(row.elapsed_seconds):<8} "
            f"model={_short_model(row.model)} notes={notes or 'n/a'}"
        )
    return _lines(*body)


def _summarize_multiline(value: object) -> str:
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    if not lines:
        return "n/a"
    for line in reversed(lines):
        if "Error" in line or "Exception" in line or "Traceback" not in line:
            return line
    return lines[-1]


def format_run_detail(entry: ReportEntry) -> str:
    artifacts = entry.artifact_paths if isinstance(entry.artifact_paths, dict) else {}
    run_ref = f"{entry.run_id}-{entry.task_id}"
    outcome = entry.outcome or "n/a"
    score = (
        entry.score_display
        or (f"{int(entry.score_numeric)}/100" if isinstance(entry.score_numeric, (int, float)) and float(entry.score_numeric).is_integer() else (f"{entry.score_numeric:g}/100" if isinstance(entry.score_numeric, (int, float)) else ""))
        or "n/a"
    )
    reason = _summarize_multiline(entry.failure_reason)
    checks = canonical_functionality_checks(entry)
    if checks is None:
        check_summary = "n/a"
        failed_checks = "n/a"
    else:
        passed_checks = sum(1 for value in checks.values() if value)
        check_summary = f"{passed_checks}/{len(checks)}"
        failed_checks = ", ".join(sorted(name for name, value in checks.items() if not value)) or "none"
    provenance = entry.provenance if isinstance(entry.provenance, dict) else {}
    if not provenance:
        details = entry.result.details if isinstance(entry.result.details, dict) else {}
        fallback = details.get("provenance")
        if isinstance(fallback, dict):
            provenance = fallback
    # Correctness/evaluation state and lifecycle/harness state are separate axes;
    # a run can be harness-failed while still carrying an evaluator verdict (or vice versa).
    # Prefer the flattened entry fields; fall back to the persisted result so a
    # manually-built ReportEntry still renders its recorded states.
    lifecycle_state = str(entry.harness_status or "").strip() or str(getattr(entry.result, "harness", None) and entry.result.harness.status or "").strip()
    if not lifecycle_state:
        lifecycle_state = "ok" if entry.outcome in ("pass", "fail") else "n/a"
    evaluation_state = str(entry.evaluation_status or "").strip() or str(getattr(entry.result, "evaluation", None) and entry.result.evaluation.status or "").strip()
    if not evaluation_state:
        evaluation_state = "not_run" if (entry.score_numeric is None and not entry.score_display) else "unknown"
    scored = _entry_is_scored(entry)
    body = [
        f"=== run {entry.run_id} ===",
        f"task      : {entry.task_id}",
        f"suite     : {entry.batch or 'unlabeled'}",
        f"lifecycle : {lifecycle_state}",
        f"evaluation: {evaluation_state}",
        f"score     : {score}",
    ]
    if outcome != "pass" and _meaningful_reason(reason):
        body.append(f"reason    : {reason}")
    if scored:
        correctness_line = f"score={score} checks={check_summary}"
    else:
        # Evaluator never produced a usable verdict (not run or failed); the
        # score/checks fields on a partial result.json are not trustworthy.
        correctness_line = "not evaluated"
    body.extend([
        "",
        "=== correctness ===",
        f"correctness: {correctness_line}",
        f"failed checks: {failed_checks}",
        "",
        "=== mode ===",
        f"no-orchestra  : {_fmt_explicit_flag(provenance.get('no_orchestra'))}",
        f"tools         : {_fmt_tools_availability(provenance)}",
        f"tools-exec    : {_fmt_explicit_flag(provenance.get('orchestra_tools_executed'))}",
        f"agent     : {_agent_display(entry)}",
        f"runtime   : elapsed={_fmt_seconds(entry.elapsed_seconds)}"
        + (
            f" window={_fmt_timestamp(entry.started_at)} → {_fmt_timestamp(entry.finished_at)}"
            if entry.started_at or entry.finished_at
            else ""
        ),
    ])

    tokens = entry.tokens if isinstance(entry.tokens, dict) else {}

    def append_bucket(label: str, data: object) -> None:
        metrics = data if isinstance(data, dict) else {}
        body.append(
            " ".join(
                [
                    f"{label:<9}: total={_fmt_number(metrics.get('total_tokens'))}",
                    f"input={_fmt_number(metrics.get('input_tokens'))}",
                    f"output={_fmt_number(metrics.get('output_tokens'))}",
                    f"reasoning={_fmt_number(metrics.get('reasoning_tokens'))}",
                    f"cache_read={_fmt_number(metrics.get('cached_input_read_tokens'))}",
                    f"cache_write={_fmt_number(metrics.get('cache_write_tokens'))}",
                    f"calls={_fmt_number(metrics.get('api_calls'))}",
                ]
            )
        )

    def append_context(label: str, data: object) -> None:
        metrics = data if isinstance(data, dict) else {}
        final = metrics.get("final_context_tokens")
        if final is None:
            final = metrics.get("final")
        maximum = metrics.get("max_context_tokens")
        if maximum is None:
            maximum = metrics.get("max")
        body.append(
            f"{label:<9}: final={_fmt_number(final)} "
            f"max={_fmt_number(maximum)} "
            f"compactions={_fmt_number(metrics.get('compactions'))}"
        )

    def session_values(values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        return [str(value) for value in values if str(value)]

    parent_bucket = _entry_context_bucket(entry, "parent")
    child_bucket = _entry_context_bucket(entry, "children")
    all_bucket = _entry_context_bucket(entry, "all")
    parent_ids = session_values(tokens.get("parent_session_ids"))
    child_ids = session_values(tokens.get("child_session_ids") or tokens.get("subagent_session_ids"))

    body.extend(["", "=== tokens ==="])
    append_bucket("all", all_bucket)
    append_bucket("parent", parent_bucket)
    append_bucket("children", child_bucket)
    sources = tokens.get("sources") if isinstance(tokens.get("sources"), dict) else {}
    body.append(
        f"sources   : parent={sources.get('parent') or 'n/a'} children={sources.get('children') or 'n/a'}"
    )
    unavailable = tokens.get("unavailable_reasons") if isinstance(tokens.get("unavailable_reasons"), dict) else {}
    reason_text = ", ".join(
        f"{key}={value}" for key, value in sorted(unavailable.items()) if str(value).strip()
    ) or "n/a"
    body.append(f"unavailable: {reason_text}")

    body.extend(["", "=== context ==="])
    append_context("all", all_bucket)
    append_context("parent", parent_bucket)
    append_context("children", child_bucket)

    if parent_ids or child_ids:
        body.extend(["", "=== sessions ==="])
        body.append(f"parent   : {', '.join(parent_ids) if parent_ids else 'n/a'}")
        body.append(f"children : {', '.join(child_ids) if child_ids else 'n/a'}")

    parent = _entry_orchestra_mapping(entry, "parent")
    roles = _entry_orchestra_mapping(entry, "roles")
    body.extend([
        "",
        "=== orchestration behavior ===",
        "dispatch  : "
        f"attempts={_fmt_number(_entry_orchestra_value(entry, 'dispatch_attempts'))} "
        f"accepted={_fmt_number(_entry_orchestra_value(entry, 'dispatch_accepted'))} "
        f"rejected={_fmt_number(_entry_orchestra_value(entry, 'dispatch_rejected'))}",
        "children  : "
        f"completed={_fmt_number(_entry_orchestra_value(entry, 'completed'))} "
        f"failed={_fmt_number(_entry_orchestra_value(entry, 'failed'))} "
        f"timed_out={_fmt_number(_entry_orchestra_value(entry, 'timed_out'))} "
        f"reconciled={_fmt_number(_entry_orchestra_value(entry, 'reconciled'))} "
        f"active={_fmt_number(_entry_orchestra_value(entry, 'active'))} "
        f"inferred_active={_fmt_number(_entry_orchestra_value(entry, 'inferred_active'))}",
        "parent    : "
        f"waited={_fmt_explicit_flag(parent.get('waited'))} "
        f"integrated={_fmt_explicit_flag(parent.get('integrated'))} "
        f"finalized_before_children={_fmt_explicit_flag(parent.get('finalized_before_children'))}",
        "roles     : "
        f"requested={_fmt_list(roles.get('requested'))} "
        f"started={_fmt_list(roles.get('started'))} "
        f"returned={_fmt_list(roles.get('returned'))}",
    ])

    body.extend(["", "=== diagnostics ==="])
    if outcome != "pass":
        runner_bits = []
        if entry.harness_status and entry.harness_status != "ok":
            runner_bits.append(entry.harness_status)
        if entry.harness_exit_code not in (None, 0):
            runner_bits.append(f"exit={_fmt_number(entry.harness_exit_code)}")
        harness_error = _summarize_multiline(entry.harness_error)
        if _meaningful_reason(harness_error):
            runner_bits.append(harness_error)
        if runner_bits:
            body.append(f"runner    : {' '.join(runner_bits)}")

        evaluator_bits = []
        if entry.evaluation_status and entry.evaluation_status != "ok":
            evaluator_bits.append(entry.evaluation_status)
        if _should_show_score(outcome, score):
            evaluator_bits.append(f"score={score}")
        evaluation_error = _summarize_multiline(entry.evaluation_error)
        if _meaningful_reason(evaluation_error):
            evaluator_bits.append(evaluation_error)
        if evaluator_bits:
            body.append(f"evaluator : {' '.join(evaluator_bits)}")
    if checks:
        passed = sum(1 for value in checks.values() if bool(value))
        failed = len(checks) - passed
        body.append(f"checks    : pass={passed} fail={failed}")
        for key, value in sorted(checks.items()):
            marker = "ok" if bool(value) else "fail"
            body.append(f"  {marker:<4} {key}")
    tool_activity = _entry_tool_activity(entry)
    if tool_activity is not None:
        child_sessions = tool_activity.get("child_sessions") if isinstance(tool_activity.get("child_sessions"), dict) else {}
        # Neutral, counts-only line: stored reason texts may assert legacy mode state
        # (e.g. "orchestration was disabled" or references to an enable command) that is
        # ambiguous under the current mode model, so only observed counts are surfaced.
        body.append(
            "tool activity: "
            f"dispatches={_fmt_number(tool_activity.get('dispatch_attempts'))} "
            f"accepted={_fmt_number(tool_activity.get('dispatch_accepted'))} "
            f"active={_fmt_number(child_sessions.get('active'))} "
            f"inferred_active={_fmt_number(child_sessions.get('inferred_active'))}"
        )
    evaluator_stdout = artifacts.get("evaluator")
    if isinstance(evaluator_stdout, dict):
        evaluator_stdout = evaluator_stdout.get("stdout") or evaluator_stdout.get("result") or evaluator_stdout.get("log")
    if not evaluator_stdout:
        evaluator_stdout = artifacts.get("evaluator_stdout") or (entry.path.parent / "artifacts" / "evaluator" / "stdout.txt")
    body.append(f"details   : {evaluator_stdout}")
    body.append(f"debug     : scripts/04-debug {run_ref} orch|full|raw")

    body.extend(["", "=== artifacts ==="])
    body.append(f"result   : {artifacts.get('result_json') or entry.path}")
    workspace_path = Path(str(artifacts.get('workspace') or (entry.path.parent / 'workspace')))
    body.append(f"workspace: {workspace_path}")
    body.extend(_workspace_note_lines(workspace_path))
    harness_artifacts = artifacts.get("harness")
    harness_path = entry.path.parent / "artifacts" / "harness"
    if isinstance(harness_artifacts, dict):
        parts = [f"{harness_path}"]
        for key in ("transcript", "summary", "log"):
            value = harness_artifacts.get(key)
            if value:
                parts.append(f"{key}={value}")
        body.append(f"harness  : {' '.join(parts)}")
    else:
        body.append(f"harness  : {harness_path}")

    sessions_candidates: list[Path] = []
    for value in ([harness_artifacts.get("pi_sessions")] if isinstance(harness_artifacts, dict) else []) + [artifacts.get("sessions")]:
        if str(value or "").strip():
            path = Path(str(value))
            if not any(path is candidate or path == candidate for candidate in sessions_candidates):
                sessions_candidates.append(path)
    default_sessions = entry.path.parent / "artifacts" / "pi-sessions"
    if default_sessions != (sessions_candidates[0] if sessions_candidates else None):
        sessions_candidates.append(default_sessions)
    present_sessions = next((candidate for candidate in sessions_candidates if candidate.exists()), None)
    if present_sessions is not None:
        body.append(f"sessions : {present_sessions}")
    else:
        sessions_ref = sessions_candidates[0]
        harness_values: list[Any] = list(harness_artifacts.values()) if isinstance(harness_artifacts, dict) else [harness_path]
        present_harness = sorted({str(Path(value)) for value in harness_values if str(value or "").strip() and Path(str(value)).exists()})
        fallback = f" [fallback: harness {' '.join(present_harness)}]" if present_harness else ""
        body.append(f"sessions : missing (expected {sessions_ref}){fallback}")
    return _lines(*body)


def format_tokens(entries: Iterable[ReportEntry]) -> str:
    rows = [row for row in entries if row.total_tokens is not None]
    totals = [float(row.total_tokens or 0) for row in rows]
    total = sum(totals)
    body = ["=== token usage ===", f"runs: {len(rows)}", f"total_tokens: {_fmt_number(total)}"]
    if rows:
        body.append(f"min_total_tokens: {_fmt_number(min(totals))}")
        body.append(f"max_total_tokens: {_fmt_number(max(totals))}")
        body.append(f"avg_total_tokens: {_fmt_number(mean(totals))}")
    return _lines(*body)


def format_timing(entries: Iterable[ReportEntry]) -> str:
    rows = [row for row in entries if row.elapsed_seconds is not None]
    values = [row.elapsed_seconds for row in rows if row.elapsed_seconds is not None]
    body = ["=== timing ===", f"runs: {len(rows)}"]
    for row in rows:
        body.append(f"{row.run_id:<18} {row.task_id:<34} {_fmt_seconds(row.elapsed_seconds)}")
    if values:
        body.append("")
        body.append(f"total: {_fmt_seconds(sum(values))}")
        body.append(f"min  : {_fmt_seconds(min(values))}")
        body.append(f"max  : {_fmt_seconds(max(values))}")
        body.append(f"avg  : {_fmt_seconds(mean(values))}")
    return _lines(*body)


def _stat_value(summary: dict[str, Any] | None, key: str = "avg") -> float | None:
    if not isinstance(summary, dict):
        return None
    value = summary.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _format_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _format_delta(value: float | None, *, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if float(value).is_integer():
        return f"{value:+.0f}{suffix}"
    return f"{value:+.1f}{suffix}"


def _format_ratio(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return "n/a"
    available = summary.get("available")
    true_count = summary.get("true")
    if not isinstance(available, int) or available <= 0 or not isinstance(true_count, int):
        return "n/a"
    return f"{true_count}/{available}"


def _format_metric_line(label: str, parent: str, children: str, delta: str) -> str:
    return f"{label:<20}: parent={parent} children={children} delta={delta}"


def _format_stat_line(label: str, parent: dict[str, Any] | None, children: dict[str, Any] | None, *, suffix: str = "") -> str:
    parent_value = _stat_value(parent)
    children_value = _stat_value(children)
    delta = None if parent_value is None or children_value is None else children_value - parent_value
    parent_text = _format_number(parent_value) + suffix if parent_value is not None else "n/a"
    children_text = _format_number(children_value) + suffix if children_value is not None else "n/a"
    return _format_metric_line(label, parent_text, children_text, _format_delta(delta, suffix=suffix))


def _format_result_counts(parent: dict[str, Any], children: dict[str, Any]) -> str:
    return _format_metric_line(
        "results",
        f"pass={_format_number(parent.get('passed'))} fail={_format_number(parent.get('failed'))} error={_format_number(parent.get('error'))}",
        f"pass={_format_number(children.get('passed'))} fail={_format_number(children.get('failed'))} error={_format_number(children.get('error'))}",
        f"pass={_format_delta(float(children.get('passed', 0)) - float(parent.get('passed', 0)))} "
        f"fail={_format_delta(float(children.get('failed', 0)) - float(parent.get('failed', 0)))} "
        f"error={_format_delta(float(children.get('error', 0)) - float(parent.get('error', 0)))}",
    )


def _format_pass_rate(parent: dict[str, Any], children: dict[str, Any]) -> str:
    parent_rate = _stat_value(parent, "pass_rate")
    children_rate = _stat_value(children, "pass_rate")
    delta = None if parent_rate is None or children_rate is None else (children_rate - parent_rate) * 100.0
    parent_text = "n/a"
    children_text = "n/a"
    if parent_rate is not None:
        parent_text = f"{parent_rate * 100:.1f}% ({_format_number(parent.get('passed'))}/{_format_number(parent.get('scored'))})"
    if children_rate is not None:
        children_text = f"{children_rate * 100:.1f}% ({_format_number(children.get('passed'))}/{_format_number(children.get('scored'))})"
    return _format_metric_line("pass rate", parent_text, children_text, _format_delta(delta, suffix="pp"))


def _format_count_ratio_line(label: str, parent: dict[str, Any] | None, children: dict[str, Any] | None) -> str:
    parent_text = _format_ratio(parent)
    children_text = _format_ratio(children)
    delta = None
    if isinstance(parent, dict) and isinstance(children, dict):
        parent_true = parent.get("true")
        children_true = children.get("true")
        if isinstance(parent_true, int) and isinstance(children_true, int):
            delta = float(children_true - parent_true)
    return _format_metric_line(label, parent_text, children_text, _format_delta(delta))


def _reason_key(item: dict[str, Any]) -> tuple[int, str]:
    count = item.get("count")
    return (-(count if isinstance(count, int) else 0), str(item.get("reason") or ""))


def format_comparison_results(summary: dict[str, Any]) -> str:
    parent = summary.get("parent") if isinstance(summary.get("parent"), dict) else {}
    children = summary.get("children") if isinstance(summary.get("children"), dict) else {}
    mode = str(summary.get("mode") or "n/a")
    body = [
        "=== compare ===",
        f"mode      : {mode}",
        f"parent    : {parent.get('label') or parent.get('selector') or 'n/a'} ({_format_number(parent.get('runs'))} runs)",
        f"children  : {children.get('label') or children.get('selector') or 'n/a'} ({_format_number(children.get('runs'))} runs)",
        "",
        "=== results ===",
        _format_metric_line("runs", _format_number(parent.get('runs')), _format_number(children.get('runs')), _format_delta(float(children.get('runs', 0)) - float(parent.get('runs', 0)))),
        _format_result_counts(parent, children),
        _format_pass_rate(parent, children),
        "",
        "=== scores ===",
        _format_stat_line("score", parent.get("score") if isinstance(parent.get("score"), dict) else None, children.get("score") if isinstance(children.get("score"), dict) else None),
    ]
    for category in ("functionality",):
        body.append(
            _format_stat_line(
                category,
                parent.get("categories", {}).get(category) if isinstance(parent.get("categories"), dict) else None,
                children.get("categories", {}).get(category) if isinstance(children.get("categories"), dict) else None,
            )
        )
    body.extend([
        "",
        "=== tokens/context ===",
        _format_stat_line("tokens", parent.get("tokens", {}).get("total") if isinstance(parent.get("tokens"), dict) else None, children.get("tokens", {}).get("total") if isinstance(children.get("tokens"), dict) else None),
        _format_stat_line("parent tokens", parent.get("tokens", {}).get("parent_total") if isinstance(parent.get("tokens"), dict) else None, children.get("tokens", {}).get("parent_total") if isinstance(children.get("tokens"), dict) else None),
        _format_stat_line("children tokens", parent.get("tokens", {}).get("children_total") if isinstance(parent.get("tokens"), dict) else None, children.get("tokens", {}).get("children_total") if isinstance(children.get("tokens"), dict) else None),
        _format_stat_line("context final", parent.get("tokens", {}).get("parent_final_context") if isinstance(parent.get("tokens"), dict) else None, children.get("tokens", {}).get("parent_final_context") if isinstance(children.get("tokens"), dict) else None),
        _format_stat_line("context max", parent.get("tokens", {}).get("parent_max_context") if isinstance(parent.get("tokens"), dict) else None, children.get("tokens", {}).get("parent_max_context") if isinstance(children.get("tokens"), dict) else None),
        _format_stat_line("compactions", parent.get("tokens", {}).get("parent_compactions") if isinstance(parent.get("tokens"), dict) else None, children.get("tokens", {}).get("parent_compactions") if isinstance(children.get("tokens"), dict) else None),
        _format_stat_line("elapsed", parent.get("elapsed") if isinstance(parent.get("elapsed"), dict) else None, children.get("elapsed") if isinstance(children.get("elapsed"), dict) else None, suffix="s"),
        "",
        "=== orchestra ===",
        _format_stat_line("dispatch", parent.get("orchestra", {}).get("dispatch_attempts") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("dispatch_attempts") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("accepted", parent.get("orchestra", {}).get("dispatch_accepted") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("dispatch_accepted") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("rejected", parent.get("orchestra", {}).get("dispatch_rejected") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("dispatch_rejected") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("roles requested", parent.get("orchestra", {}).get("roles_requested") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("roles_requested") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("roles started", parent.get("orchestra", {}).get("roles_started") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("roles_started") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("roles returned", parent.get("orchestra", {}).get("roles_returned") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("roles_returned") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child ok", parent.get("orchestra", {}).get("child_returns", {}).get("ok") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_returns", {}).get("ok") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child error", parent.get("orchestra", {}).get("child_returns", {}).get("error") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_returns", {}).get("error") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child blocker", parent.get("orchestra", {}).get("child_returns", {}).get("blocker") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_returns", {}).get("blocker") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child completed", parent.get("orchestra", {}).get("child_sessions", {}).get("completed") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_sessions", {}).get("completed") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child failed", parent.get("orchestra", {}).get("child_sessions", {}).get("failed") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_sessions", {}).get("failed") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child timed out", parent.get("orchestra", {}).get("child_sessions", {}).get("timed_out") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_sessions", {}).get("timed_out") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child reconciled", parent.get("orchestra", {}).get("child_sessions", {}).get("reconciled") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_sessions", {}).get("reconciled") if isinstance(children.get("orchestra"), dict) else None),
        _format_stat_line("child active", parent.get("orchestra", {}).get("child_sessions", {}).get("active") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("child_sessions", {}).get("active") if isinstance(children.get("orchestra"), dict) else None),
        _format_count_ratio_line("parent waited", parent.get("orchestra", {}).get("parent", {}).get("waited") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("parent", {}).get("waited") if isinstance(children.get("orchestra"), dict) else None),
        _format_count_ratio_line("parent integrated", parent.get("orchestra", {}).get("parent", {}).get("integrated") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("parent", {}).get("integrated") if isinstance(children.get("orchestra"), dict) else None),
        _format_count_ratio_line("finalized early", parent.get("orchestra", {}).get("parent", {}).get("finalized_before_children") if isinstance(parent.get("orchestra"), dict) else None, children.get("orchestra", {}).get("parent", {}).get("finalized_before_children") if isinstance(children.get("orchestra"), dict) else None),
    ])

    reasons: dict[str, tuple[int, int]] = {}
    parent_reasons = {str(item.get("reason") or ""): int(item.get("count") or 0) for item in parent.get("failure_reasons", []) if isinstance(item, dict) and str(item.get("reason") or "")}
    children_reasons = {str(item.get("reason") or ""): int(item.get("count") or 0) for item in children.get("failure_reasons", []) if isinstance(item, dict) and str(item.get("reason") or "")}
    for reason in sorted(set(parent_reasons) | set(children_reasons)):
        reasons[reason] = (parent_reasons.get(reason, 0), children_reasons.get(reason, 0))
    if reasons:
        body.extend(["", "=== failure reasons ==="])
        for reason, (parent_count, child_count) in sorted(reasons.items(), key=lambda item: (-max(item[1]), item[0]))[:5]:
            body.append(
                _format_metric_line(
                    reason,
                    _format_number(float(parent_count)),
                    _format_number(float(child_count)),
                    _format_delta(float(child_count - parent_count)),
                )
            )
    return _lines(*body)


__all__ = [
    "format_dashboard",
    "format_runs",
    "format_run_detail",
    "format_tokens",
    "format_timing",
    "format_comparison_results",
]
