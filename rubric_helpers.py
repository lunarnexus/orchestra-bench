"""Shared rubric helpers for role-focused benchmark scoring.

Centralize scoring mechanics (not policy). Task/role-specific rubrics stay
flexible and local to each evaluator via the ``rubric`` dict passed in.

Key functions:
- ``evaluate_rubric()`` — compute score_numeric, pass/fail threshold, category
  breakdown, and flat checks preservation from a task-local rubric definition.
"""

from __future__ import annotations


# Default pass/fail threshold for role-focused tasks.
DEFAULT_THRESHOLD = 0.70


def evaluate_rubric(
    rubric: dict[str, object],
    checks: dict[str, object],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, object]:
    """Evaluate a task-local rubric against flat check results.

    Args:
        rubric: Category-level rubric definition::

            {
                "category_name": {
                    "weight": 0.40,
                    "checks": {
                        "check_id": {"weight": 0.20, "critical": True},
                    },
                },
            }

        checks: Flat dict of check results (name -> truthy/falsy).
        threshold: Numeric score required for ``score == "pass"``.

    Returns:
        A dict with keys compatible with TaskResult fields::

            {
                "score": "pass" | "fail",
                "score_numeric": 0.85,
                "rubric": {"category_name": {"score": ..., "max": ..., "checks": {...}}, ...},
                "checks": {"check_id": True, ...},  # original flat checks preserved
            }

    Critical checks:
        If any check marked ``"critical": True`` fails (is falsy or missing),
        the result is forced to ``"fail"`` regardless of numeric score.

    Weight normalization:
        - When a check has no explicit ``weight``, its share defaults to an
          equal split of the category weight across all checks in that category.
        - If total declared check weights exceed the category weight, they are
          normalized proportionally so earned points never overflow the budget.
    """

    # ── Build per-category scoring state ────────────────────────────

    rubric_breakdown: dict[str, object] = {}
    score_numeric = 0.0
    any_critical_miss = False

    for cat_name, cat_def in (rubric or {}).items():
        cat_weight = float(cat_def.get("weight", 0))
        cat_checks_def: dict[str, object] = cat_def.get("checks") or {}
        num_checks = len(cat_checks_def) if cat_checks_def else 1

        # Compute effective weight per check
        raw_weights: dict[str, float] = {}
        for chk_name, chk_def in cat_checks_def.items():
            w = float((chk_def or {}).get("weight", 0))
            if w <= 0 and num_checks > 0:
                # Equal split of category weight when no explicit weight
                w = cat_weight / num_checks
            raw_weights[chk_name] = w

        total_raw = sum(raw_weights.values())

        # Normalize if weights exceed category budget
        effective_weights: dict[str, float]
        if total_raw > 0 and total_raw > cat_weight + 1e-9:
            scale = cat_weight / total_raw
            effective_weights = {k: v * scale for k, v in raw_weights.items()}
        else:
            effective_weights = dict(raw_weights)

        # Score each check within this category
        cat_score = 0.0
        cat_check_results: dict[str, object] = {}

        for chk_name in cat_checks_def:
            chk_def = cat_checks_def[chk_name] or {}
            raw_value = checks.get(chk_name)
            if isinstance(raw_value, bool):
                check_value = 1.0 if raw_value else 0.0
            elif isinstance(raw_value, (int, float)):
                check_value = max(0.0, min(1.0, float(raw_value)))
            else:
                check_value = 1.0 if bool(raw_value) else 0.0
            passed = check_value >= 1.0 - 1e-9
            is_critical = bool((chk_def or {}).get("critical", False))

            if not passed and is_critical:
                any_critical_miss = True

            earned = effective_weights.get(chk_name, 0.0) * check_value
            cat_score += earned
            cat_check_results[chk_name] = raw_value if isinstance(raw_value, (bool, int, float)) else passed

        # Clamp category score to its weight (safety against float drift)
        cat_score = min(cat_score, cat_weight + 1e-9)
        cat_score = round(cat_score, 6)

        rubric_breakdown[cat_name] = {
            "score": cat_score,
            "max": cat_weight,
            "checks": cat_check_results,
        }

        score_numeric += cat_score

    # Round final score to avoid floating-point noise (e.g. 0.33000000002)
    score_numeric = round(score_numeric, 6)

    # ── Determine pass/fail ────────────────────────────────────────

    if any_critical_miss:
        score: str = "fail"
    elif score_numeric >= threshold - 1e-9:
        score = "pass"
    else:
        score = "fail"

    # For empty rubric with no checks, ensure fail
    if not rubric and score == "pass":
        score = "fail"

    return {
        "score": score,
        "score_numeric": score_numeric,
        "rubric": rubric_breakdown,
        "checks": dict(checks),
    }
