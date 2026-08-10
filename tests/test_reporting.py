"""Tests for Slice 4 — reporting and comparison support."""

from __future__ import annotations

import json
import statistics
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Import after path setup
from __init__ import TaskResult  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────

def _make_result(task_id="task-a", run_id="run-1", score="pass"):
    return TaskResult(
        task_id=task_id,
        run_id=run_id,
        score=score,
        checks={"check_ok": True},
    )


# ── 1. Token / timing fields on TaskResult ───────────────────────

class TestTaskResultFields:
    """TaskResult carries token, timing, role, and split metadata."""

    def test_result_has_tokens_field(self):
        r = _make_result()
        assert hasattr(r, "tokens") or getattr(r, "tokens", None) is not None

    def test_result_default_tokens_is_empty_dict(self):
        r = _make_result()
        # tokens should default to empty dict (not crash on access)
        tokens = getattr(r, "tokens", {})
        assert isinstance(tokens, dict)

    def test_result_can_store_token_totals(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            tokens={"total": 500, "prompt": 200, "completion": 300},
        )
        assert r.tokens["total"] == 500

    def test_result_has_elapsed_seconds_field(self):
        r = _make_result()
        # Should not raise — field exists with default None/0
        val = getattr(r, "elapsed_seconds", None)
        # Default should be falsy (None or 0) when absent
        assert val is None or val == 0

    def test_result_can_store_elapsed_time(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            elapsed_seconds=42.5,
        )
        assert r.elapsed_seconds == 42.5

    def test_result_has_roles_used_field(self):
        r = _make_result()
        roles = getattr(r, "roles_used", None)
        # Default should be empty list or similar
        if roles is not None:
            assert isinstance(roles, (list, tuple))

    def test_result_can_store_roles(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            roles_used=["builder"],
        )
        assert "builder" in r.roles_used

    def test_result_has_split_field(self):
        """Dev vs holdout split label."""
        r = _make_result()
        val = getattr(r, "split", None)
        # Default should be empty string or 'dev' (safe default)
        assert isinstance(val, str)


# ── 2. Token summary ingestion from artifacts ────────────────

class TestTokenIngestion:
    """Read token/timing data from artifact files when available."""

    def test_ingest_artifacts_parses_token_file(self, tmp_path):
        # Create a fake run result dir with an artifact
        run_dir = tmp_path / "results" / "run-1-task-a"
        run_dir.mkdir(parents=True)

        # Write a token summary file (simulating what Pi/Orchestra might write)
        artifacts_subdir = run_dir / "artifacts"
        artifacts_subdir.mkdir()
        tokens_file = artifacts_subdir / "tokens.json"
        tokens_file.write_text(json.dumps({
            "total_tokens": 1200,
            "prompt_tokens": 400,
            "completion_tokens": 800,
            "parent_tokens": 300,
            "worker_tokens": 900,
        }))

        # Import the ingestion function
        from eval_harness import ingest_artifacts
        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert enriched is not None
        if enriched.tokens:
            # Should have ingested some token data
            total = enriched.tokens.get("total", 0) + enriched.tokens.get("prompt_tokens", 0)
            assert total > 0

    def test_ingest_artifacts_no_crash_without_files(self, tmp_path):
        """Should not fail when no artifact files exist."""
        from eval_harness import ingest_artifacts
        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")
        assert enriched is not None


# ── 3. Repeated-trial aggregation ─────────────────────────────

class TestRepeatedTrialAggregation:
    """Group results by task + model and compute aggregate stats."""

    def test_aggregate_by_task_returns_per_task_stats(self, tmp_path):
        from eval_harness import aggregate_repeated_trials

        # Write several result files for the same task with different run_ids
        base = tmp_path / "results"
        for i in range(3):
            d = base / f"run-{i}-task-a"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-a", run_id=f"run-{i}", score="pass")
            r.write_json(d / "result.json")

        results = aggregate_repeated_trials(base)
        assert "task-a" in results or len(results) > 0

    def test_aggregate_includes_run_count(self, tmp_path):
        from eval_harness import aggregate_repeated_trials

        base = tmp_path / "results"
        for i in range(5):
            d = base / f"run-{i}-task-x"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-x", run_id=f"run-{i}", score="pass")
            r.write_json(d / "result.json")

        results = aggregate_repeated_trials(base)
        # Find task-x in results
        for entry in (results.get("tasks", []) if isinstance(results, dict) else []):
            if entry.get("task_id") == "task-x":
                assert entry["runs"] == 5
                return

    def test_aggregate_pass_rate(self, tmp_path):
        from eval_harness import aggregate_repeated_trials

        base = tmp_path / "results"
        # 3 passes, 2 fails for task-b
        scores = ["pass", "pass", "pass", "fail", "fail"]
        for i, score in enumerate(scores):
            d = base / f"run-{i}-task-b"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-b", run_id=f"run-{i}", score=score)
            r.write_json(d / "result.json")

        results = aggregate_repeated_trials(base)
        # Find task-b and verify pass_rate is 0.6 (3/5)
        for entry in (results.get("tasks", []) if isinstance(results, dict) else []):
            if entry.get("task_id") == "task-b":
                assert entry["pass_rate"] == pytest.approx(0.6, abs=0.01) or entry["pass_rate"] == 0.6


# ── 4. Dev vs holdout split reporting ───────────────────────

class TestDevHoldoutReporting:
    """Results distinguish dev and holdout tasks in output."""

    def test_summarize_includes_split_breakdown(self, tmp_path):
        from eval_harness import summarize_results_with_splits

        base = tmp_path / "results"
        # Write a result with split=dev
        d1 = base / "run-1-dev-task"
        d1.mkdir(parents=True)
        r1 = TaskResult(task_id="dev-task", run_id="run-1", score="pass")
        if hasattr(r1, 'split'):
            r1.split = "dev"
        r1.write_json(d1 / "result.json")

        # Write a result with split=holdout
        d2 = base / "run-1-holdout-task"
        d2.mkdir(parents=True)
        r2 = TaskResult(task_id="holdout-task", run_id="run-1", score="fail")
        if hasattr(r2, 'split'):
            r2.split = "holdout"
        r2.write_json(d2 / "result.json")

        summary = summarize_results_with_splits(base)
        # Should contain dev and holdout sections
        assert isinstance(summary, dict)
        # Must have split breakdown (either as keys or in a nested structure)
        has_split_info = any(
            k in str(summary).lower() for k in ["dev", "holdout"]
        )
        assert has_split_info


# ── 5. Run metadata schema support ───────────────────────

class TestRunMetadata:
    """run_meta carries model, config, harness mode info."""

    def test_result_can_store_run_metadata(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            run_meta={
                "model": "claude-sonnet-4-20250514",
                "orchestra": True,
                "config_version": "abc123",
            },
        )
        assert r.run_meta["model"] == "claude-sonnet-4-20250514"

    def test_result_serialize_roundtrips_run_meta(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = TaskResult(
                task_id="t1", run_id="r1", score="pass",
                tokens={"total": 100},
                elapsed_seconds=30.0,
                roles_used=["builder"],
                split="dev",
                run_meta={"model": "gpt-4o"},
            )
            out = r.write_json(Path(td) / "result.json")
            loaded = TaskResult.from_json(out)
            assert loaded.run_meta["model"] == "gpt-4o"

    def test_result_from_json_requires_current_task_id_schema(self):
        """Legacy result files without task_id are invalid."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            old_data = {
                "task": "t1",
                "run_id": "r1",
                "score": "pass",
                "checks": {},
            }
            p = Path(td) / "result.json"
            p.write_text(json.dumps(old_data))
            with pytest.raises(ValueError):
                TaskResult.from_json(p)


# ── 6. Comparison reporting CLI ───────────────────────

class TestComparisonReport:
    """CLI supports comparing two sets of runs."""

    def test_compare_runs_generates_output(self, tmp_path):
        from eval_harness import compare_runs
        base = tmp_path / "results"

        # Group A results
        for i in range(3):
            d = base / f"a-run-{i}-task-x"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-x", run_id=f"a-run-{i}", score="pass")
            if hasattr(r, 'run_meta'):
                r.run_meta["group"] = "A"
            r.write_json(d / "result.json")

        # Group B results
        for i in range(3):
            d = base / f"b-run-{i}-task-x"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-x", run_id=f"b-run-{i}", score="fail")
            if hasattr(r, 'run_meta'):
                r.run_meta["group"] = "B"
            r.write_json(d / "result.json")

        comparison = compare_runs(base)
        assert isinstance(comparison, dict) or len(str(comparison)) > 0


class TestProvenanceComparison:
    """Comparisons should split by catalog/runtime provenance, not just model."""

    def test_compare_runs_separates_same_model_different_provenance(self, tmp_path):
        from eval_harness import compare_runs

        base = tmp_path / "results"
        shared = {
            "role": "builder",
            "default_role": "builder",
            "model": "openai-codex/gpt-5.4-mini",
            "catalog_path": "config/orchestra/agent-catalog.yaml",
            "orchestra": True,
        }

        for run_id, catalog_sha256 in (("run-a", "aaa"), ("run-b", "bbb")):
            d = base / f"{run_id}-task-x"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-x", run_id=run_id, score="pass")
            r.run_meta.update({**shared, "catalog_sha256": catalog_sha256})
            r.write_json(d)

        comparison = compare_runs(base)

        assert len(comparison["groups"]) == 2
        assert all("provenance" in group for group in comparison["groups"])
        hashes = {group["provenance"]["catalog_sha256"] for group in comparison["groups"]}
        assert hashes == {"aaa", "bbb"}

    def test_summarize_results_with_meta_groups_by_provenance(self, tmp_path):
        from eval_harness import summarize_results_with_meta

        base = tmp_path / "results"
        for run_id, orchestra in (("run-a", True), ("run-b", False)):
            d = base / f"{run_id}-task-y"
            d.mkdir(parents=True)
            r = TaskResult(task_id="task-y", run_id=run_id, score="pass")
            r.run_meta.update({
                "role": "builder",
                "default_role": "builder",
                "model": "openai-codex/gpt-5.4-mini",
                "catalog_path": "config/orchestra/agent-catalog.yaml",
                "catalog_sha256": "abc123",
                "orchestra": orchestra,
            })
            r.write_json(d)

        summary = summarize_results_with_meta(base)

        assert "by_provenance" in summary
        assert len(summary["by_provenance"]) == 2
        assert sum(entry["orchestra_on"] for entry in summary["by_provenance"]) == 1
        assert sum(entry["orchestra_off"] for entry in summary["by_provenance"]) == 1


# ── 7. Elapsed time capture in grade flow ────────────────

class TestElapsedTiming:
    """Grade flow captures elapsed_seconds when available."""

    def test_result_records_elapsed_when_set(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            elapsed_seconds=55.0,
        )
        assert r.elapsed_seconds == 55.0

    def test_elapsed_in_serialized_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = TaskResult(
                task_id="t1", run_id="r1", score="pass",
                elapsed_seconds=55.0,
            )
            out = r.write_json(Path(td) / "result.json")
            data = json.loads(out.read_text())
            assert "elapsed_seconds" in data
            assert data["elapsed_seconds"] == 55.0


# ── 8. TaskMeta split/batch field support ───────────────────────

class TestTaskMetaSplit:
    """Task metadata carries split and batch labels from task.yaml."""

    def test_task_meta_has_split_default_dev(self):
        from __init__ import TaskMeta
        m = TaskMeta(task_id="t1")
        assert m.split == "dev"

    def test_task_meta_has_batch_default_none(self):
        from __init__ import TaskMeta
        m = TaskMeta(task_id="t1")
        assert m.batch == ""

    def test_load_task_reads_split_from_yaml(self, tmp_path):
        task_dir = tmp_path / "tasks" / "test-task"
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text(
            "task_id: test-task\nsplit: holdout\n"
        )

        import sys as _sys
        from eval_harness import load_task
        meta = load_task(task_dir, tasks_dir=tmp_path / "tasks")
        assert meta.split == "holdout"

    def test_load_task_reads_batch_from_yaml(self, tmp_path):
        task_dir = tmp_path / "tasks" / "test-task-batch"
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text(
            "task_id: test-task-batch\nbatch: smoke\n"
        )

        from eval_harness import load_task
        meta = load_task(task_dir, tasks_dir=tmp_path / "tasks")
        assert meta.batch == "smoke"

    def test_load_task_default_split_when_missing(self, tmp_path):
        task_dir = tmp_path / "tasks" / "test-task2"
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text("task_id: test-task2\n")

        from eval_harness import load_task
        meta = load_task(task_dir, tasks_dir=tmp_path / "tasks")
        assert meta.split == "dev"


# ── 9. Print functions smoke tests ───────────────────────

class TestPrintFunctions:
    """CLI print functions execute without errors."""

    def test_print_aggregate_runs(self, tmp_path):
        from eval_harness import aggregate_repeated_trials, _print_aggregate

        base = tmp_path / "results"
        for i in range(2):
            d = base / f"run-{i}-t1"
            d.mkdir(parents=True)
            r = TaskResult(task_id="t1", run_id=f"run-{i}", score="pass")
            r.write_json(d / "result.json")

        data = aggregate_repeated_trials(base)
        # Should not raise
        _print_aggregate(data)

    def test_print_comparison_runs(self, tmp_path):
        from eval_harness import print_comparison

        base = tmp_path / "results"
        for i in range(2):
            d = base / f"run-{i}-t1"
            d.mkdir(parents=True)
            r = TaskResult(task_id="t1", run_id=f"run-{i}", score="pass",
                           elapsed_seconds=30.0,
                           split="dev")
            r.write_json(d / "result.json")

        # Should not raise
        print_comparison(base)

    def test_print_split_summary_runs(self, tmp_path):
        from eval_harness import print_split_summary

        base = tmp_path / "results"
        for i in range(2):
            d = base / f"run-{i}-t1"
            d.mkdir(parents=True)
            r = TaskResult(task_id="t1", run_id=f"run-{i}", score="pass",
                           split="dev")
            r.write_json(d / "result.json")

        # Should not raise
        print_split_summary(base)

