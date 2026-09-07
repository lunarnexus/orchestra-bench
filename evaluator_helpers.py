"""Shared evaluator output helpers for V2 task graders."""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Mapping
from typing import Any


class EvaluatorContractError(ValueError):
    pass


def _validate_checks(checks: Mapping[str, object]) -> dict[str, bool]:
    if not checks:
        raise EvaluatorContractError("functionality checks must be non-empty")
    out: dict[str, bool] = {}
    for name, value in checks.items():
        if not isinstance(name, str) or not name:
            raise EvaluatorContractError("functionality check names must be non-empty strings")
        if not isinstance(value, bool):
            raise EvaluatorContractError(f"functionality check {name!r} must be boolean")
        out[name] = value
    return out


def emit_result(checks: Mapping[str, object], *, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    canonical = _validate_checks(checks)
    score = "pass" if all(canonical.values()) else "fail"
    result = {
        "score": score,
        "checks": dict(canonical),
        "details": {
            "functionality": {
                "checks": dict(canonical),
                "evidence": dict(evidence or {}),
            }
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def run_evaluator(initial_checks: Mapping[str, bool], evaluate: Callable[[dict[str, bool]], Mapping[str, Any] | None]) -> int:
    checks = _validate_checks(initial_checks)
    evidence: dict[str, Any] = {}
    try:
        returned = evaluate(checks)
        if isinstance(returned, Mapping):
            evidence.update(dict(returned))
    except Exception as exc:  # candidate/evaluator workflow failure becomes evidence plus failed checks
        evidence["exception"] = repr(exc)
        evidence["traceback"] = traceback.format_exc()
    result = emit_result(checks, evidence=evidence)
    return 0 if result["score"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit("evaluator_helpers is imported by task evaluators")
