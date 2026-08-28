"""Tests for shared rubric helpers — Slice 4 mechanics only.

Covers weighted categories/checks, score_numeric calculation, pass/fail
threshold (default 0.70) with critical checks, flat checks preservation,
and result JSON shape compatible with TaskResult fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from rubric_helpers import evaluate_rubric


# ── Shared test rubric definition ────────────────────────────────

def _make_sample_rubric() -> dict:
    """Two-category rubric used across tests."""
    return {
        "role_result_quality": {
            "weight": 0.40,
            "checks": {
                "has_answer": {"weight": 0.20, "critical": True},
                "mentions_role": {"weight": 0.15},
                "includes_evidence": {"weight": 0.05},
            },
        },
        "process_quality": {
            "weight": 0.30,
            "checks": {
                "followed_scope": {"weight": 0.15},
                "no_unrelated_changes": {"weight": 0.15},
            },
        },
    }


def _make_full_pass_checks() -> dict:
    return {
        "has_answer": True,
        "mentions_role": True,
        "includes_evidence": True,
        "followed_scope": True,
        "no_unrelated_changes": True,
    }


# ── 1. Basic scoring math ────────────────────────────────────────

class TestScoreNumericCalculation:
    """score_numeric is the sum of earned points across all checks."""

    def test_full_pass_yields_correct_score(self):
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=_make_full_pass_checks(),
        )
        # 0.20 + 0.15 + 0.05 + 0.15 + 0.15 = 0.70
        assert result["score_numeric"] == pytest.approx(0.70)

    def test_all_fail_yields_zero(self):
        checks = {k: False for k in _make_full_pass_checks()}
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        assert result["score_numeric"] == pytest.approx(0.0)

    def test_partial_score(self):
        """Only has_answer (0.20) and followed_scope (0.15) pass."""
        checks = {
            "has_answer": True,
            "mentions_role": False,
            "includes_evidence": False,
            "followed_scope": True,
            "no_unrelated_changes": False,
        }
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        assert result["score_numeric"] == pytest.approx(0.35)

    def test_unknown_checks_ignored(self):
        """Checks not in the rubric definition are ignored for scoring."""
        checks = {**_make_full_pass_checks(), "extra_check": True}
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        assert result["score_numeric"] == pytest.approx(0.70)

    def test_missing_checks_treat_as_false(self):
        """Checks in the rubric but not provided are treated as failed."""
        checks = {"has_answer": True}
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        assert result["score_numeric"] == pytest.approx(0.20)


# ── 2. Rubric breakdown structure ───────────────────────────────

class TestRubricBreakdown:
    """Each category in rubric output has score, max, and checks detail."""

    def test_category_score_and_max(self):
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=_make_full_pass_checks(),
        )
        rubric = result["rubric"]
        assert rubric["role_result_quality"]["max"] == pytest.approx(0.40)
        # Earned: 0.20 + 0.15 + 0.05 = 0.40 (capped at weight)
        assert rubric["role_result_quality"]["score"] == pytest.approx(0.40)

    def test_category_partial_score(self):
        checks = {
            "has_answer": True,   # 0.20 / 0.40 max
            "mentions_role": False,
            "includes_evidence": False,
            "followed_scope": False,
            "no_unrelated_changes": False,
        }
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        cat = result["rubric"]["role_result_quality"]
        assert cat["max"] == pytest.approx(0.40)
        assert cat["score"] == pytest.approx(0.20)

    def test_category_checks_detail_preserved(self):
        """Per-check pass/fail is preserved in the rubric breakdown."""
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=_make_full_pass_checks(),
        )
        cat_checks = result["rubric"]["role_result_quality"]["checks"]
        assert cat_checks["has_answer"] is True
        assert cat_checks["mentions_role"] is True

    def test_rubric_has_all_categories(self):
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks={},
        )
        assert set(result["rubric"]) == {
            "role_result_quality",
            "process_quality",
        }


# ── 3. Pass/fail threshold ─────────────────────────────────────

class TestPassFailThreshold:
    """Top-level score is 'pass' when score_numeric >= threshold and no critical misses."""

    def test_pass_at_exact_threshold(self):
        """score_numeric == 0.70 should pass (default threshold)."""
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=_make_full_pass_checks(),
        )
        assert result["score"] == "pass"

    def test_fail_below_threshold(self):
        """Only has_answer passes → 0.20 < 0.70."""
        checks = {"has_answer": True}
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        assert result["score"] == "fail"

    def test_pass_above_threshold(self):
        """All pass → score > 0.70."""
        # Use a rubric where total weight is 1.0 so full pass = 1.0 >= 0.70
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {"good": {"weight": 1.0}},
            },
        }
        result = evaluate_rubric(rubric=rubric, checks={"good": True})
        assert result["score"] == "pass"

    def test_custom_threshold(self):
        """Custom threshold overrides default 0.70."""
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {"ok": {"weight": 1.0}},
            },
        }
        # Score = 1.0, threshold is 0.95 → pass
        result = evaluate_rubric(
            rubric=rubric, checks={"ok": True}, threshold=0.95
        )
        assert result["score"] == "pass"

        # Score = 0.3 (only partial), threshold 0.5 → fail
        rubric2 = {
            "quality": {
                "weight": 1.0,
                "checks": {"a": {"weight": 0.4}, "b": {"weight": 0.6}},
            },
        }
        result2 = evaluate_rubric(
            rubric=rubric2, checks={"a": True, "b": False}, threshold=0.5
        )
        assert result2["score"] == "fail"


# ── 4. Critical checks ─────────────────────────────────────────

class TestCriticalChecks:
    """A critical check failing forces score='fail' regardless of numeric."""

    def test_critical_fail_overrides_score(self):
        """has_answer is critical — fail it even with high other scores."""
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {
                    "has_output": {"weight": 0.5, "critical": True},
                    "is_good": {"weight": 0.5},
                },
            },
        }
        checks = {"has_output": False, "is_good": True}
        result = evaluate_rubric(rubric=rubric, checks=checks)
        assert result["score_numeric"] == pytest.approx(0.5)
        assert result["score"] == "fail"

    def test_critical_pass_at_threshold(self):
        """All critical pass and numeric >= threshold → pass."""
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {
                    "has_output": {"weight": 0.3, "critical": True},
                    "is_good": {"weight": 0.7},
                },
            },
        }
        result = evaluate_rubric(
            rubric=rubric, checks={"has_output": True, "is_good": True}
        )
        assert result["score"] == "pass"

    def test_no_critical_means_any_check_counts(self):
        """When no check is critical, only threshold matters."""
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {"a": {"weight": 0.5}, "b": {"weight": 0.5}},
            },
        }
        result = evaluate_rubric(rubric=rubric, checks={"a": True, "b": False})
        assert result["score"] == "fail"  # 0.5 < 0.70

    def test_critical_not_marked_by_default(self):
        """Checks without 'critical' key are not critical."""
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks={"has_answer": False},
        )
        # has_answer is critical in _make_sample_rubric
        assert result["score"] == "fail"


# ── 5. Flat checks preservation ────────────────────────────────

class TestFlatChecksPreservation:
    """Original flat checks dict is preserved in output for dashboards."""

    def test_checks_passthrough(self):
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=_make_full_pass_checks(),
        )
        assert "checks" in result
        assert result["checks"]["has_answer"] is True

    def test_extra_checks_preserved_in_flat_output(self):
        """Non-rubric checks still appear in flat output."""
        checks = {**_make_full_pass_checks(), "extra_info": "yes"}
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=checks,
        )
        assert result["checks"]["extra_info"] == "yes"


# ── 6. Result JSON shape compatible with TaskResult ────────────

class TestResultShape:
    """Output dict keys map cleanly to TaskResult fields."""

    def test_has_score_and_score_numeric(self):
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks={},
        )
        assert "score" in result
        assert "score_numeric" in result
        assert isinstance(result["score"], str)
        assert isinstance(result["score_numeric"], float)

    def test_has_rubric_dict(self):
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks={},
        )
        assert "rubric" in result
        assert isinstance(result["rubric"], dict)

    def test_score_numeric_clamped_to_one(self):
        """If check weights exceed category weight, score doesn't overflow."""
        rubric = {
            "quality": {
                "weight": 0.5,
                "checks": {
                    "a": {"weight": 0.3},
                    "b": {"weight": 0.3},
                },
            },
        }
        result = evaluate_rubric(rubric=rubric, checks={"a": True, "b": True})
        # Total check weights = 0.6 but category weight is 0.5
        assert result["score_numeric"] == pytest.approx(0.5)

    def test_score_numeric_rounded(self):
        """Score numeric is rounded to avoid floating point artifacts."""
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {"a": {"weight": 0.33}},
            },
        }
        result = evaluate_rubric(rubric=rubric, checks={"a": True})
        # Should not be something like 0.33000000000000002
        assert result["score_numeric"] == pytest.approx(0.33)

    def test_empty_rubric_yields_zero(self):
        rubric: dict = {}
        result = evaluate_rubric(rubric=rubric, checks={})
        assert result["score_numeric"] == pytest.approx(0.0)
        assert result["score"] == "fail"

    def test_result_is_json_serializable(self):
        """Output should serialize to JSON without errors."""
        result = evaluate_rubric(
            rubric=_make_sample_rubric(),
            checks=_make_full_pass_checks(),
        )
        text = json.dumps(result)
        assert len(text) > 0


# ── 7. Edge cases and robustness ───────────────────────────────

class TestEdgeCases:
    """Single check, single category, missing weight defaults."""

    def test_single_check_rubric(self):
        rubric = {
            "output": {"weight": 1.0, "checks": {"present": {"weight": 1.0}}},
        }
        result = evaluate_rubric(rubric=rubric, checks={"present": True})
        assert result["score_numeric"] == pytest.approx(1.0)
        assert result["score"] == "pass"

    def test_weight_default_to_equal_split(self):
        """When a check has no explicit weight, split category weight equally."""
        rubric = {
            "quality": {
                "weight": 0.6,
                "checks": {"a": {}, "b": {}, "c": {}},
            },
        }
        result = evaluate_rubric(rubric=rubric, checks={"a": True, "b": False, "c": True})
        # Each check gets 0.6 / 3 = 0.2; two pass → 0.4
        assert result["score_numeric"] == pytest.approx(0.4)

    def test_weight_normalization_within_category(self):
        """Check weights that sum to more than category weight are normalized."""
        rubric = {
            "quality": {
                "weight": 1.0,
                "checks": {
                    "a": {"weight": 3},   # 50% of total check weight
                    "b": {"weight": 2},   # 33%
                    "c": {"weight": 1},   # 17%
                },
            },
        }
        result = evaluate_rubric(
            rubric=rubric, checks={"a": True, "b": True, "c": False}
        )
        # Total check weights = 6; a=3/6*1.0=0.5, b=2/6*1.0≈0.33 → ≈0.83
        assert result["score_numeric"] == pytest.approx(5 / 6, abs=0.001)


# ── Import for pytest ───────────────────────────────────────────

import pytest  # noqa: E402 (ensure all above code runs before import side effects)
