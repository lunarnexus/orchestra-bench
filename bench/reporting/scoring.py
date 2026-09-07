"""Correctness-only scoring for normalized benchmark results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol, Sequence

from bench.result import TaskResult


class _ScoreSource(Protocol):
    result: TaskResult
    tokens: dict[str, Any]
    orchestra_metrics: dict[str, Any]
    orchestra: bool | None
    total_tokens: int | float | None
    elapsed_seconds: float | None


@dataclass(frozen=True)
class ScoreResult:
    score_numeric: float | None
    score_display: str
    category_scores: dict[str, dict[str, Any]]
    available: bool
    reason: str = ""


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_score_display(score: float | None) -> str:
    if score is None:
        return ""
    rounded = Decimal(str(score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(rounded)}/100"


def _unscored(reason: str) -> ScoreResult:
    return ScoreResult(
        score_numeric=None,
        score_display="",
        category_scores={},
        available=False,
        reason=reason,
    )


def _functionality_checks(result: TaskResult) -> dict[str, bool] | str:
    details = _mapping(result.evaluation.details)
    functionality = _mapping(details.get("functionality"))
    raw_checks = functionality.get("checks")
    if not isinstance(raw_checks, dict) or not raw_checks:
        return "missing functionality checks"
    checks: dict[str, bool] = {}
    for name, value in raw_checks.items():
        if not isinstance(name, str) or not name:
            return "invalid functionality check name"
        if not isinstance(value, bool):
            return "non-boolean functionality check"
        checks[name] = value
    return checks


def _expected_verdict(checks: dict[str, bool]) -> str:
    return "pass" if all(checks.values()) else "fail"


def _score_result(result: TaskResult) -> ScoreResult:
    if result.harness.status != "ok" or result.evaluation.status != "ok" or result.outcome not in {"pass", "fail"}:
        return _unscored("score unavailable")

    checks_or_reason = _functionality_checks(result)
    if isinstance(checks_or_reason, str):
        return _unscored(checks_or_reason)
    checks = checks_or_reason

    expected = _expected_verdict(checks)
    actual = str(result.evaluation.score or "").strip().lower()
    if actual != expected:
        return _unscored("contradictory evaluator verdict")

    passed = sum(1 for value in checks.values() if value)
    total = len(checks)
    score_numeric = round((passed / total) * 100.0, 4)
    factor = round(passed / total, 4)
    return ScoreResult(
        score_numeric=score_numeric,
        score_display=_format_score_display(score_numeric),
        category_scores={
            "functionality": {
                "available": True,
                "factor": factor,
                "score_numeric": score_numeric,
                "score_display": _format_score_display(score_numeric),
                "inputs": {
                    "checks": dict(checks),
                    "passed": passed,
                    "total": total,
                    "source": "details.functionality.checks",
                },
            }
        },
        available=True,
    )


def score_task_result(result: TaskResult, *, history: Sequence[TaskResult] = ()) -> ScoreResult:
    """Compute correctness from canonical functionality checks.

    History is accepted for API compatibility but never changes correctness.
    """
    return _score_result(result)


def score_report_entry(entry: _ScoreSource, *, history: Sequence[_ScoreSource] = ()) -> ScoreResult:
    """Compute correctness for a report row.

    Diagnostics on the entry are intentionally ignored by the correctness score.
    """
    return _score_result(entry.result)


__all__ = ["ScoreResult", "score_report_entry", "score_task_result"]
