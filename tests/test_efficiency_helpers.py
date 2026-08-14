"""Tests for Slice 2 — historical efficiency helpers."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from __init__ import TaskResult  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────


def _write_result(base: Path, task_id: str, run_id: str, score: str = "pass",
                  tokens: dict | None = None, elapsed: float | None = None):
    """Write a TaskResult JSON file to *base* and return the result."""
    # write_json(path) treats `path` as the output directory,
    # so we pass the run_dir directly (not path / "result.json").
    d = base / f"{run_id}-{task_id}"
    r = TaskResult(
        task_id=task_id,
        run_id=run_id,
        score=score,
        tokens=tokens or {},
        elapsed_seconds=elapsed,
    )
    r.write_json(d)
    return r


def _build_history(base: Path, task_id: str):
    """Write 3 historical results for *task_id* (no current run)."""
    _write_result(base, task_id, "hist-1", tokens={"total": 800}, elapsed=25.0)
    _write_result(base, task_id, "hist-2", tokens={"total": 1200}, elapsed=40.0)
    _write_result(base, task_id, "hist-3", score="fail", tokens={"total": 2000}, elapsed=80.0)


# ── 1. Insufficient history (no prior runs) ────────────────────


class TestInsufficientHistory:
    """No prior comparable runs → insufficient-history."""

    def test_no_prior_runs(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        current = _write_result(base, "task-a", "current-1", tokens={"total": 500}, elapsed=20.0)
        result = compare_efficiency(current, base)

        assert result["tokens"]["position"] == "insufficient-history"
        assert result["elapsed"]["position"] == "insufficient-history"

    def test_one_prior_run_is_enough(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "hist-1", tokens={"total": 900}, elapsed=35.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total": 700}, elapsed=28.0)
        result = compare_efficiency(current, base)

        assert result["tokens"]["position"] != "insufficient-history"
        assert result["elapsed"]["position"] != "insufficient-history"

    def test_two_prior_runs_is_enough(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 600}, elapsed=30.0)
        _write_result(base, "task-a", "h2", tokens={"total": 800}, elapsed=45.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total": 700}, elapsed=37.0)
        result = compare_efficiency(current, base)

        assert result["tokens"]["position"] != "insufficient-history"
        assert result["elapsed"]["position"] != "insufficient-history"


# ── 2. Current run excluded from history stats ────────────────


class TestCurrentRunExcluded:
    """The current run should not contaminate its own historical comparison."""

    def test_current_not_in_history(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-x", "h1", tokens={"total": 500}, elapsed=20.0)
        _write_result(base, "task-x", "h2", tokens={"total": 600}, elapsed=25.0)
        current = _write_result(base, "task-x", "current-1", tokens={"total": 9000}, elapsed=500.0)
        result = compare_efficiency(current, base)

        # History min should be from h1/h2, not the extreme current value
        assert result["tokens"]["min"] == 500
        assert result["tokens"]["max"] == 600
        assert result["elapsed"]["min"] == 20.0


# ── 3. Token stats: min / median / max / current / position ────────


class TestTokenStats:
    """Verify token comparison fields are computed correctly."""

    def test_token_min_median_max(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _build_history(base, "task-a")
        current = _write_result(base, "task-a", "current-1", tokens={"total": 950}, elapsed=35.0)
        result = compare_efficiency(current, base)

        assert result["tokens"]["min"] == 800
        assert result["tokens"]["max"] == 2000
        assert result["tokens"]["median"] == 1200
        assert result["tokens"]["current"] == 950

    def test_token_position_normal(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _build_history(base, "task-a")
        current = _write_result(base, "task-a", "current-1", tokens={"total": 1200}, elapsed=35.0)
        result = compare_efficiency(current, base)

        # Median is 1200 → exactly normal range
        assert result["tokens"]["position"] == "normal"

    def test_token_position_low(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _build_history(base, "task-a")
        current = _write_result(base, "task-a", "current-1", tokens={"total": 850}, elapsed=35.0)
        result = compare_efficiency(current, base)

        # Between min (800) and median (1200), closer to min → low
        assert result["tokens"]["position"] == "low"

    def test_token_position_high(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _build_history(base, "task-a")
        current = _write_result(base, "task-a", "current-1", tokens={"total": 1700}, elapsed=35.0)
        result = compare_efficiency(current, base)

        # Between median (1200) and max (2000), closer to max → high
        assert result["tokens"]["position"] == "high"


# ── 4. Elapsed stats: min / median / max / current / position ────


class TestElapsedStats:
    """Verify elapsed-time comparison fields are computed correctly."""

    def test_elapsed_min_median_max(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _build_history(base, "task-a")
        current = _write_result(base, "task-a", "current-1", tokens={"total": 950}, elapsed=32.0)
        result = compare_efficiency(current, base)

        assert result["elapsed"]["min"] == 25.0
        assert result["elapsed"]["max"] == 80.0
        assert result["elapsed"]["median"] == 40.0
        assert result["elapsed"]["current"] == 32.0


# ── 5. Pass-only history ────────────────────────────────────────


class TestPassOnlyHistory:
    """When any pass history exists, include a pass-only comparison view."""

    def test_pass_only_present_when_enough(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        # 2 passes + 1 fail → pass-only has 2 runs (enough)
        _write_result(base, "task-a", "h1", score="pass", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2", score="pass", tokens={"total": 900}, elapsed=30.0)
        _write_result(base, "task-a", "h3", score="fail", tokens={"total": 2000}, elapsed=80.0)
        current = _write_result(base, "task-a", "current-1", score="pass", tokens={"total": 850}, elapsed=27.0)

        result = compare_efficiency(current, base)
        assert "pass_only" in result

    def test_pass_only_not_present_when_none(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", score="fail", tokens={"total": 2000}, elapsed=80.0)
        current = _write_result(base, "task-a", "current-1", score="pass", tokens={"total": 850}, elapsed=27.0)

        result = compare_efficiency(current, base)
        assert "pass_only" not in result


# ── 6. Missing data handling ────────────────────────────────────


class TestMissingData:
    """Handle missing token or elapsed data gracefully."""

    def test_no_tokens_in_current(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2", tokens={"total": 1200}, elapsed=40.0)
        current = _write_result(base, "task-a", "current-1")  # no tokens
        result = compare_efficiency(current, base)

        assert result["tokens"]["current"] is None or result["tokens"]["current"] == 0
        assert result["elapsed"]["current"] is None

    def test_no_elapsed_in_current(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2", tokens={"total": 1200}, elapsed=40.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total": 900})  # no elapsed
        result = compare_efficiency(current, base)

        assert result["elapsed"]["current"] is None

    def test_different_task_id_not_included(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-other", "h1", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-other", "h2", tokens={"total": 900}, elapsed=30.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total": 850}, elapsed=27.0)

        result = compare_efficiency(current, base)
        assert result["tokens"]["position"] == "insufficient-history"


# ── 7. Result enrichment integration ────────────────────────


class TestResultEnrichment:
    """compare_efficiency can optionally write back to the result."""

    def test_enrich_result_field(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2", tokens={"total": 1200}, elapsed=40.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total": 900}, elapsed=35.0)

        result = compare_efficiency(current, base)
        # The returned dict can be stored in result.efficiency
        assert isinstance(result, dict)
        assert "tokens" in result
        assert "elapsed" in result


# ── 8. Edge cases ────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary conditions and edge scenarios."""

    def test_all_same_history_values(self, tmp_path):
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 1000}, elapsed=30.0)
        _write_result(base, "task-a", "h2", tokens={"total": 1000}, elapsed=30.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total": 1000}, elapsed=30.0)

        result = compare_efficiency(current, base)
        assert result["tokens"]["min"] == 1000
        assert result["tokens"]["max"] == 1000
        assert result["tokens"]["position"] == "normal"

    def test_history_runs_no_tokens(self, tmp_path):
        """Two prior runs with no token data → insufficient-history for all-runs tokens."""
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1")  # no tokens
        _write_result(base, "task-a", "h2")  # no tokens
        current = _write_result(base, "task-a", "current-1", tokens={"total": 500}, elapsed=20.0)

        result = compare_efficiency(current, base)
        assert result["tokens"]["position"] == "insufficient-history"
        # count should be 0 (no prior runs with real token data)
        assert result["tokens"]["count"] == 0

    def test_history_mixed_token_data(self, tmp_path):
        """One prior run with tokens is enough for comparison."""
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2")  # no tokens
        current = _write_result(base, "task-a", "current-1", tokens={"total": 500}, elapsed=20.0)

        result = compare_efficiency(current, base)
        assert result["tokens"]["position"] == "new-low"
        assert result["tokens"]["count"] == 1

    def test_history_two_with_tokens_one_without(self, tmp_path):
        """Two prior runs with tokens + one without → enough for stats."""
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2", tokens={"total": 1200}, elapsed=40.0)
        _write_result(base, "task-a", "h3")  # no tokens
        current = _write_result(base, "task-a", "current-1", tokens={"total": 950}, elapsed=35.0)

        result = compare_efficiency(current, base)
        assert result["tokens"]["position"] != "insufficient-history"
        # Only h1 and h2 count (h3 has no token data)
        assert result["tokens"]["count"] == 2
        assert result["tokens"]["min"] == 800
        assert result["tokens"]["max"] == 1200

    def test_total_tokens_key_fallback(self, tmp_path):
        """Prefer 'total' key, fall back to 'total_tokens' in history."""
        from eval_harness import compare_efficiency
        base = tmp_path / "results"
        _write_result(base, "task-a", "h1", tokens={"total_tokens": 800}, elapsed=25.0)
        _write_result(base, "task-a", "h2", tokens={"total_tokens": 1200}, elapsed=40.0)
        current = _write_result(base, "task-a", "current-1", tokens={"total_tokens": 950}, elapsed=35.0)

        result = compare_efficiency(current, base)
        assert result["tokens"]["min"] == 800
        assert result["tokens"]["max"] == 1200
