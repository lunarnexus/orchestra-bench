"""Human-readable reporting views for benchmark results."""

from __future__ import annotations

from statistics import mean
from typing import Iterable

from .queries import ReportEntry


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _fmt_number(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _lines(*items: object) -> str:
    return "\n".join(str(item) for item in items if str(item) != "") + "\n"


def _as_list(entries: Iterable[ReportEntry]) -> list[ReportEntry]:
    return list(entries)


def format_dashboard(entries: Iterable[ReportEntry]) -> str:
    rows = _as_list(entries)
    total = len(rows)
    passed = sum(1 for row in rows if row.outcome == "pass")
    failed = total - passed
    batches: dict[str, list[ReportEntry]] = {}
    for row in rows:
        batches.setdefault(row.batch or "unlabeled", []).append(row)

    body = ["dashboard", f"runs: {total}", f"passed: {passed}", f"failed: {failed}"]
    if batches:
        body.append("batches:")
        for batch, batch_rows in sorted(batches.items()):
            batch_passed = sum(1 for row in batch_rows if row.outcome == "pass")
            body.append(f"- {batch}: {batch_passed}/{len(batch_rows)} pass")
    return _lines(*body)


def format_runs(entries: Iterable[ReportEntry]) -> str:
    rows = _as_list(entries)
    body = ["runs", "run_id task_id batch outcome model orchestra elapsed total_tokens"]
    for row in rows:
        body.append(
            " ".join(
                [
                    row.run_id,
                    row.task_id,
                    row.batch or "unlabeled",
                    row.outcome,
                    row.model or "n/a",
                    _fmt_bool(row.orchestra),
                    _fmt_number(row.elapsed_seconds),
                    _fmt_number(row.total_tokens),
                ]
            )
        )
    return _lines(*body)


def format_run_detail(entry: ReportEntry) -> str:
    body = [
        "run",
        f"run_id: {entry.run_id}",
        f"task_id: {entry.task_id}",
        f"batch: {entry.batch or 'unlabeled'}",
        f"outcome: {entry.outcome}",
        f"model: {entry.model or 'n/a'}",
        f"orchestra: {_fmt_bool(entry.orchestra)}",
        f"started_at: {entry.started_at or 'n/a'}",
        f"finished_at: {entry.finished_at or 'n/a'}",
        f"elapsed_seconds: {_fmt_number(entry.elapsed_seconds)}",
        f"total_tokens: {_fmt_number(entry.total_tokens)}",
    ]
    if entry.provenance:
        body.append(f"provenance: {entry.provenance}")
    if entry.tokens:
        body.append(f"tokens: {entry.tokens}")
    if entry.timing:
        body.append(f"timing: {entry.timing}")
    return _lines(*body)


def format_tokens(entries: Iterable[ReportEntry]) -> str:
    rows = [row for row in entries if row.total_tokens is not None]
    totals = [float(row.total_tokens or 0) for row in rows]
    total = sum(totals)
    body = ["tokens", f"runs: {len(rows)}", f"total_tokens: {_fmt_number(total)}"]
    if rows:
        body.append(f"min_total_tokens: {_fmt_number(min(totals))}")
        body.append(f"max_total_tokens: {_fmt_number(max(totals))}")
        body.append(f"avg_total_tokens: {_fmt_number(mean(totals))}")
    return _lines(*body)


def format_timing(entries: Iterable[ReportEntry]) -> str:
    rows = [row for row in entries if row.elapsed_seconds is not None]
    values = [row.elapsed_seconds for row in rows if row.elapsed_seconds is not None]
    body = ["timing", f"runs: {len(rows)}"]
    for row in rows:
        body.append(f"- {row.run_id} {row.task_id}: {_fmt_number(row.elapsed_seconds)}s")
    if values:
        body.append(f"elapsed_seconds: {_fmt_number(sum(values))}")
        body.append(f"min_elapsed_seconds: {_fmt_number(min(values))}")
        body.append(f"max_elapsed_seconds: {_fmt_number(max(values))}")
        body.append(f"avg_elapsed_seconds: {_fmt_number(mean(values))}")
    return _lines(*body)


__all__ = [
    "format_dashboard",
    "format_runs",
    "format_run_detail",
    "format_tokens",
    "format_timing",
]
