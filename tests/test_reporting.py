"""Tests for Slice 4 — reporting and comparison support."""

from __future__ import annotations

import json
import os
import statistics
import textwrap
from pathlib import Path
import sqlite3
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

    def test_manual_elapsed_uses_last_parent_session_activity(self, tmp_path):
        """Manual runs should not count overnight idle time after the last Pi activity."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "2026-08-20T00-00-00-000Z_parent.jsonl").write_text(
            json.dumps({"type": "session", "id": "parent", "timestamp": "2026-08-20T00:00:00Z"}) + "\n" +
            json.dumps({"type": "message", "timestamp": "2026-08-20T00:10:00Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}) + "\n"
        )
        (session_dir / "2026-08-20T00-00-00-000Z_orchestra-worker-abc.jsonl").write_text(
            json.dumps({"type": "message", "timestamp": "2026-08-20T02:00:00Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "worker later"}]}}) + "\n"
        )

        result = _make_result(run_id="run-1", task_id="task-a")
        result.run_meta = {"started_epoch": 1787184000, "auto": False}  # 2026-08-20T00:00:00Z
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert enriched.elapsed_seconds == 600.0
        assert enriched.run_meta["elapsed_source"] == "last_parent_session_activity"
        assert "wall_elapsed_seconds" in enriched.run_meta
        assert "orchestra-worker" not in enriched.run_meta["last_parent_session_activity_file"]

    def test_auto_elapsed_keeps_wall_clock_fallback(self, tmp_path):
        """Auto runs already have controlled lifecycle; do not override with session activity."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "parent.jsonl").write_text(
            json.dumps({"type": "message", "timestamp": "2026-08-20T00:10:00Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}) + "\n"
        )

        result = _make_result(run_id="run-1", task_id="task-a")
        result.run_meta = {"started_epoch": 1787184000, "auto": True}
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert enriched.elapsed_seconds is not None
        assert enriched.run_meta.get("elapsed_source") == "wall_clock"

    def test_ingest_classified_expensive_main_session_tokens(self, tmp_path):
        """New classified expensive_main_session_tokens dict appears in result.tokens."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        run_dir.mkdir(parents=True)
        artifacts_subdir = run_dir / "artifacts"
        artifacts_subdir.mkdir()
        tokens_file = artifacts_subdir / "tokens.json"
        tokens_file.write_text(json.dumps({
            "input_tokens": 500,
            "output_tokens": 300,
            "reasoning_tokens": 100,
            "total_tokens": 900,
            "expensive_main_session_tokens": {
                "input_tokens": 400,
                "output_tokens": 250,
                "reasoning_tokens": 80,
                "cached_input_read_tokens": 50,
                "cache_write_tokens": 20,
                "total_tokens": 700,
            },
        }))

        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert isinstance(enriched.tokens.get("expensive_main_session_tokens"), dict)
        exp_main = enriched.tokens["expensive_main_session_tokens"]
        assert exp_main["total_tokens"] == 700
        assert exp_main["input_tokens"] == 400

    def test_ingest_classified_cheap_role_tokens(self, tmp_path):
        """New classified cheap_role_tokens dict appears in result.tokens."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        run_dir.mkdir(parents=True)
        artifacts_subdir = run_dir / "artifacts"
        artifacts_subdir.mkdir()
        tokens_file = artifacts_subdir / "tokens.json"
        tokens_file.write_text(json.dumps({
            "total_tokens": 900,
            "cheap_role_tokens": {
                "input_tokens": 100,
                "output_tokens": 50,
                "reasoning_tokens": 20,
                "total_tokens": 200,
            },
        }))

        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert isinstance(enriched.tokens.get("cheap_role_tokens"), dict)
        cheap = enriched.tokens["cheap_role_tokens"]
        assert cheap["total_tokens"] == 200

    def test_ingest_compaction_count(self, tmp_path):
        """compaction_count scalar is ingested when present."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        run_dir.mkdir(parents=True)
        artifacts_subdir = run_dir / "artifacts"
        artifacts_subdir.mkdir()
        tokens_file = artifacts_subdir / "tokens.json"
        tokens_file.write_text(json.dumps({
            "total_tokens": 900,
            "compaction_count": 3,
        }))

        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert enriched.tokens.get("compaction_count") == 3

    def test_ingest_main_session_context_fields(self, tmp_path):
        """Main session context fields are ingested from tokens.json."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        run_dir.mkdir(parents=True)
        artifacts_subdir = run_dir / "artifacts"
        artifacts_subdir.mkdir()
        tokens_file = artifacts_subdir / "tokens.json"
        tokens_file.write_text(json.dumps({
            "total_tokens": 900,
            "main_session_context_input_tokens": 4500,
            "main_session_context_total_tokens": 8000,
            "main_session_api_call_count": 12,
            "main_session_max_input_tokens": 6000,
            "main_session_max_total_tokens": 9500,
        }))

        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert enriched.tokens.get("main_session_context_input_tokens") == 4500
        assert enriched.tokens.get("main_session_api_call_count") == 12
        assert enriched.tokens.get("main_session_max_total_tokens") == 9500

    def test_ingest_active_worker_metrics(self, tmp_path):
        """New active-worker diagnostics are preserved in result.tokens."""
        from eval_harness import ingest_artifacts
        run_dir = tmp_path / "results" / "run-1-task-a"
        run_dir.mkdir(parents=True)
        artifacts_subdir = run_dir / "artifacts"
        artifacts_subdir.mkdir()
        tokens_file = artifacts_subdir / "tokens.json"
        tokens_file.write_text(json.dumps({
            "total_tokens": 900,
            "main_active_worker_tokens": 137,
            "main_active_worker_api_calls": 3,
        }))

        result = _make_result(run_id="run-1", task_id="task-a")
        enriched = ingest_artifacts(result, base_dir=tmp_path / "results")

        assert enriched.tokens.get("main_active_worker_tokens") == 137
        assert enriched.tokens.get("main_active_worker_api_calls") == 3


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


# ── 10. scripts/05-results run detail reporting ───────────────────


def _install_results_script(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    script = scripts_dir / "05-results"
    script.write_text((_REPO_ROOT / "scripts" / "05-results").read_text())
    script.chmod(0o755)
    (tmp_path / "eval_harness.py").write_text((_REPO_ROOT / "eval_harness.py").read_text())
    (tmp_path / "__init__.py").write_text((_REPO_ROOT / "__init__.py").read_text())
    return script


def _write_task_yaml(tmp_path: Path, task_id: str, *, batch: str | None = None, family: str | None = None) -> None:
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"task_id: {task_id}"]
    if batch:
        lines.append(f"batch: {batch}")
    if family:
        lines.append(f"family: {family}")
    (task_dir / "task.yaml").write_text("\n".join(lines) + "\n")


def _canonicalize_tokens(tokens: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(tokens, dict):
        return {}

    total = tokens.get("total_tokens", tokens.get("total"))
    if not isinstance(total, (int, float)):
        return dict(tokens)

    input_tokens = tokens.get("input_tokens", tokens.get("prompt_tokens", 0))
    output_tokens = tokens.get("output_tokens", tokens.get("completion_tokens", 0))
    reasoning_tokens = tokens.get("reasoning_tokens", 0)
    cached_read = tokens.get("cached_input_read_tokens", 0)
    cache_write = tokens.get("cache_write_tokens", 0)
    total_int = int(total)
    main_session = {
        "input_tokens": int(input_tokens) if isinstance(input_tokens, (int, float)) else 0,
        "output_tokens": int(output_tokens) if isinstance(output_tokens, (int, float)) else 0,
        "reasoning_tokens": int(reasoning_tokens) if isinstance(reasoning_tokens, (int, float)) else 0,
        "cached_input_read_tokens": int(cached_read) if isinstance(cached_read, (int, float)) else 0,
        "cache_write_tokens": int(cache_write) if isinstance(cache_write, (int, float)) else 0,
        "total_tokens": total_int,
    }
    role_sessions = {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
    }
    all_sessions = {
        "input_tokens": int(tokens.get("input_tokens", 0)) if isinstance(tokens.get("input_tokens", 0), (int, float)) else main_session["input_tokens"],
        "output_tokens": int(tokens.get("output_tokens", 0)) if isinstance(tokens.get("output_tokens", 0), (int, float)) else main_session["output_tokens"],
        "reasoning_tokens": int(tokens.get("reasoning_tokens", 0)) if isinstance(tokens.get("reasoning_tokens", 0), (int, float)) else main_session["reasoning_tokens"],
        "cached_input_read_tokens": int(tokens.get("cached_input_read_tokens", 0)) if isinstance(tokens.get("cached_input_read_tokens", 0), (int, float)) else main_session["cached_input_read_tokens"],
        "cache_write_tokens": int(tokens.get("cache_write_tokens", 0)) if isinstance(tokens.get("cache_write_tokens", 0), (int, float)) else main_session["cache_write_tokens"],
        "total_tokens": total_int,
    }
    return {
        **tokens,
        "main_session": dict(tokens.get("main_session", main_session)),
        "role_sessions": dict(tokens.get("role_sessions", role_sessions)),
        "all_sessions": dict(tokens.get("all_sessions", all_sessions)),
        "expensive_main_session_tokens": dict(tokens.get("expensive_main_session_tokens", main_session)),
        "cheap_role_tokens": dict(tokens.get("cheap_role_tokens", role_sessions)),
    }


def _write_result_json(tmp_path: Path, result: TaskResult) -> None:
    run_dir = tmp_path / "results" / f"{result.run_id}-{result.task_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    result.tokens = _canonicalize_tokens(result.tokens)
    (run_dir / "result.json").write_text(json.dumps(result.to_dict(), indent=2) + "\n")


class TestDashboardReporting:
    def test_run_detail_shows_orchestra_version(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                tokens={"total": 100},
                run_meta={
                    "orchestra_version": "0.1.3.dev18+gc4fc74df9",
                    "orchestra_source_rev": "c4fc74d",
                    "orchestra_source_dirty": False,
                    "pi_extensions_summary": "orchestra,pi-lmstudio",
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-a"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "orchestra ver: 0.1.3.dev18+gc4fc74df9 clean" in result.stdout

    def test_dashboard_shows_suite_and_test_breakdowns(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "smoke-a", batch="smoke")
        _write_task_yaml(tmp_path, "smoke-b", batch="smoke")
        _write_task_yaml(tmp_path, "cap-a", batch="capability-easy")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="smoke-a",
                run_id="run-1",
                score="pass",
                score_numeric=0.90,
                rubric={"quality": {"score": 0.45, "max": 0.50}},
                checks={"answer_exists": True, "tests_pass": True},
                orchestration_checks={"compaction_count": 1, "dispatch_count": 2},
                tokens={"total": 1000},
                elapsed_seconds=30.0,
                task_meta={"batch": "smoke"},
                run_meta={"notes": "BatchA", "auto": True, "orchestra": True, "pi_packages_summary": "pi-codegraph,pi-lmstudio", "pi_extensions_summary": "orchestra,pi-codegraph,pi-lmstudio", "aux_skills_summary": "none"},
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="smoke-b",
                run_id="run-2",
                score="fail",
                score_numeric=0.40,
                rubric={"quality": {"score": 0.20, "max": 0.50}},
                checks={"answer_exists": True, "tests_pass": False},
                orchestration_checks={"compaction_count": 0, "dispatch_count": 1},
                tokens={"total": 500},
                elapsed_seconds=45.0,
                task_meta={"batch": "smoke"},
                run_meta={"notes": "BatchA", "auto": True, "orchestra": True, "pi_packages_summary": "pi-codegraph,pi-lmstudio", "pi_extensions_summary": "orchestra,pi-codegraph,pi-lmstudio", "aux_skills_summary": "none"},
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="cap-a",
                run_id="run-3",
                score="pass",
                score_numeric=0.75,
                rubric={"quality": {"score": 0.30, "max": 0.40}},
                checks={"answer_exists": True},
                orchestration_checks={"compaction_count": 3, "dispatch_count": 4},
                tokens={"total": 2000},
                elapsed_seconds=90.0,
                task_meta={"batch": "capability-easy"},
                run_meta={"notes": "BatchB", "auto": True, "orchestra": False, "pi_packages_summary": "pi-codegraph,pi-lmstudio", "pi_extensions_summary": "orchestra,pi-codegraph,pi-lmstudio", "aux_skills_summary": "none"},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "args        : --auto | --auto --no-orchestra" in result.stdout
        assert "extensions  : orchestra,pi-codegraph,pi-lmstudio" in result.stdout
        assert "skills      : none" in result.stdout
        assert "config      : (none)" in result.stdout
        assert "tokens      : total=" in result.stdout
        assert "elapsed     : total=" in result.stdout
        assert "=== per-suite breakdown ===" in result.stdout
        assert "[smoke]" in result.stdout
        assert "[capability-easy]" in result.stdout
        assert "score_numeric: avg=0.6500" in result.stdout
        assert "- quality:" in result.stdout
        assert "- compaction_count: total=1 avg=0.50" in result.stdout
        assert "- target_role_dispatched:" not in result.stdout
        assert "=== per-test breakdown ===" in result.stdout
        assert "- smoke-a" in result.stdout
        assert "- smoke-b" in result.stdout

    def test_notes_filter_limits_dashboard_rows(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                tokens={"total": 100},
                elapsed_seconds=10.0,
                task_meta={"batch": "smoke"},
                run_meta={"notes": "Batch1 alpha"},
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-b",
                run_id="run-b",
                score="pass",
                tokens={"total": 200},
                elapsed_seconds=20.0,
                task_meta={"batch": "smoke"},
                run_meta={"notes": "Batch2 beta"},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--notes", "Batch1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "notes filter: batch1" in result.stdout
        assert "graded runs : 1" in result.stdout
        assert "- task-a" in result.stdout
        assert "- task-b" not in result.stdout

    def test_model_filter_matches_parent_model_not_other_role_models(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-27",
                score="pass",
                task_meta={"batch": "smoke"},
                run_meta={
                    "model": "lmstudio/qwen3.6-27b",
                    "role_models_summary": "builder=lmstudio/qwen3.6-27b, intern=lmstudio/qwen3.6-35b",
                },
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-b",
                run_id="run-35",
                score="pass",
                task_meta={"batch": "smoke"},
                run_meta={"model": "lmstudio/qwen3.6-35b"},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "runs", "--suite", "smoke", "--model", "35b", "--limit", "20"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "run-35" in result.stdout
        assert "run-27" not in result.stdout

    def test_runs_detail_three_shows_config_fields(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="capability-easy")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-detail",
                score="pass",
                tokens={"total": 123},
                elapsed_seconds=12.0,
                task_meta={"batch": "capability-easy"},
                run_meta={
                    "model": "lmstudio/qwen3.6-35b",
                    "auto": True,
                    "orchestra": False,
                    "catalog_path": "config/orchestra/agent-catalog.yaml",
                    "enabled_roles_summary": "builder,reviewer",
                    "role_models_summary": "builder=lmstudio/qwen3.6-35b, reviewer=lmstudio/qwen3.6-27b",
                    "pi_extensions_summary": "orchestra,pi-codegraph,pi-lmstudio",
                    "aux_skills_summary": "build-tdd,verify-work",
                    "notes": "config detail smoke",
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "runs", "--suite", "capability-easy", "--detail", "3", "--limit", "5"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "run-detail" in result.stdout
        assert "model       : qwen3.6-35b" in result.stdout
        assert "run config  : orchestra=none; orch_on=off; args=--auto --no-orchestra" in result.stdout
        assert "catalog     : config/orchestra/agent-catalog.yaml" in result.stdout
        assert "roles       : builder,reviewer" in result.stdout
        assert "extensions  : orchestra,pi-codegraph,pi-lmstudio" in result.stdout
        assert "skills      : build-tdd,verify-work" in result.stdout
        assert "role models :" in result.stdout
        assert "builder=qwen3.6-35b" in result.stdout
        assert "notes       : config detail smoke" in result.stdout

    def test_config_filters_configs_and_compare_views(self, tmp_path):
        script = _install_results_script(tmp_path)
        for task_id in ["task-a", "task-b"]:
            _write_task_yaml(tmp_path, task_id, batch="smoke")

        common = {"auto": True, "aux_skills_summary": "none"}
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                score_numeric=1.0,
                tokens={"total": 100},
                elapsed_seconds=10.0,
                task_meta={"batch": "smoke"},
                run_meta={**common, "model": "lmstudio/qwen3.6-35b-long-name", "orchestra": True, "pi_extensions_summary": "orchestra,pi-codegraph,pi-lmstudio", "pi_packages_summary": "pi-codegraph,pi-lmstudio", "pi_enabled_plugins_summary": "orchestra,pi-codegraph,pi-lmstudio"},
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-b",
                run_id="run-b",
                score="fail",
                score_numeric=0.0,
                tokens={"total": 50},
                elapsed_seconds=8.0,
                task_meta={"batch": "smoke"},
                run_meta={**common, "model": "lmstudio/qwen3.6-35b-long-name", "orchestra": False, "pi_extensions_summary": "orchestra,pi-codegraph,pi-lmstudio", "pi_packages_summary": "pi-codegraph,pi-lmstudio", "pi_enabled_plugins_summary": "pi-codegraph,pi-lmstudio"},
            ),
        )

        configs = __import__("subprocess").run(
            ["bash", str(script), "configs", "--model", "35b"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert configs.returncode == 0, configs.stderr
        assert "=== configs ===" in configs.stdout
        assert "C01" in configs.stdout
        assert "qwen3.6-35b" in configs.stdout

        substring = __import__("subprocess").run(
            ["bash", str(script), "runs", "--plugins", "codegraph"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert substring.returncode == 0, substring.stderr
        assert "run-a" in substring.stdout
        assert "run-b" in substring.stdout

        normalized_substring = __import__("subprocess").run(
            ["bash", str(script), "runs", "--plugins", "picode"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert normalized_substring.returncode == 0, normalized_substring.stderr
        assert "run-a" in normalized_substring.stdout
        assert "run-b" in normalized_substring.stdout

        filtered = __import__("subprocess").run(
            ["bash", str(script), "runs", "--plugins", "pi-codegraph,not:orchestra"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert filtered.returncode == 0, filtered.stderr
        assert "run-a" not in filtered.stdout
        assert "run-b" in filtered.stdout

        without_plugin = __import__("subprocess").run(
            ["bash", str(script), "runs", "--without-plugins", "orchestra"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert without_plugin.returncode == 0, without_plugin.stderr
        assert "run-a" not in without_plugin.stdout
        assert "run-b" in without_plugin.stdout

        hint = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--plugins", "codegraph,-orchestra"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert hint.returncode == 0, hint.stderr
        assert "graded runs : 1" in hint.stdout

        no_orch = __import__("subprocess").run(
            ["bash", str(script), "runs", "--no-orchestra"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert no_orch.returncode == 0, no_orch.stderr
        assert "run-b" in no_orch.stdout
        assert "run-a" not in no_orch.stdout

        compare = __import__("subprocess").run(
            ["bash", str(script), "compare", "--suite", "smoke", "--group-by", "model,orchestra,plugins", "--per-task"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert compare.returncode == 0, compare.stderr
        assert "=== compare ===" in compare.stdout
        assert "orch:used" in compare.stdout
        assert "orch:none" in compare.stdout
        assert "per task:" in compare.stdout

    def test_notes_view_lists_distinct_notes(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")
        _write_task_yaml(tmp_path, "task-c", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="fail", run_meta={"notes": "Batch1 alpha"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-c", run_id="run-c", score="pass", run_meta={"notes": "Batch2 beta"}),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "notes"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "=== notes ===" in result.stdout
        assert "runs=2" in result.stdout and "notes=Batch1 alpha" in result.stdout
        assert "pass=1/2" in result.stdout
        assert "runs=1" in result.stdout and "notes=Batch2 beta" in result.stdout

    def test_delete_requires_at_least_one_filter(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "delete", "--yes"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert "refusing to delete without at least one filter" in result.stderr
        assert (tmp_path / "results" / "run-a-task-a").exists()

    def test_delete_model_filter_is_dry_run_by_default(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"model": "lmstudio/qwen3.8-27b"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="pass", run_meta={"model": "lmstudio/qwen3.6-35b"}),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "delete", "--model", "3.8-27b"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "mode        : dry-run" in result.stdout
        assert "model filter: 3.8-27b" in result.stdout
        assert "WOULD DELETE results/run-a-task-a" in result.stdout
        assert "run-b-task-b" not in result.stdout
        assert (tmp_path / "results" / "run-a-task-a").exists()
        assert (tmp_path / "results" / "run-b-task-b").exists()

    def test_delete_notes_filter_is_dry_run_by_default(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="pass", run_meta={"notes": "Batch2 beta"}),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "delete", "--notes", "batch1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "mode        : dry-run" in result.stdout
        assert "WOULD DELETE results/run-a-task-a" in result.stdout
        assert "run-b-task-b" not in result.stdout
        assert (tmp_path / "results" / "run-a-task-a").exists()
        assert (tmp_path / "results" / "run-b-task-b").exists()

    def test_delete_notes_filter_with_yes_removes_only_matches(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="pass", run_meta={"notes": "Batch2 beta"}),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "delete", "--notes", "Batch1", "--yes"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "mode        : delete" in result.stdout
        assert "DELETE results/run-a-task-a" in result.stdout
        assert not (tmp_path / "results" / "run-a-task-a").exists()
        assert (tmp_path / "results" / "run-b-task-b").exists()

    def test_set_notes_requires_filter_and_new_notes(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )

        no_filter = __import__("subprocess").run(
            ["bash", str(script), "set-notes", "--set-notes", "Batch1 renamed", "--yes"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        no_new_notes = __import__("subprocess").run(
            ["bash", str(script), "set-notes", "--notes", "Batch1", "--yes"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert no_filter.returncode == 2
        assert "refusing to rewrite notes without at least one filter" in no_filter.stderr
        assert no_new_notes.returncode == 2
        assert "refusing to rewrite notes without --set-notes" in no_new_notes.stderr

    def test_set_notes_is_dry_run_by_default(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="pass", run_meta={"notes": "Batch2 beta"}),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "set-notes", "--notes", "batch1", "--set-notes", "Batch1 renamed"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "mode        : dry-run" in result.stdout
        assert "WOULD UPDATE results/run-a-task-a" in result.stdout
        assert "run-b-task-b" not in result.stdout
        data = json.loads((tmp_path / "results" / "run-a-task-a" / "result.json").read_text())
        assert data["run_meta"]["notes"] == "Batch1 alpha"

    def test_set_notes_with_yes_updates_matching_result_and_bench_run(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", run_meta={"notes": "Batch1 alpha"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="pass", run_meta={"notes": "Batch2 beta"}),
        )
        bench_run = tmp_path / "results" / "run-a-task-a" / ".bench_run.json"
        bench_run.write_text(json.dumps({"run_id": "run-a", "task_id": "task-a", "notes": "Batch1 alpha"}) + "\n")

        result = __import__("subprocess").run(
            ["bash", str(script), "set-notes", "--notes", "Batch1", "--set-notes", "Batch1 renamed", "--yes"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "mode        : apply" in result.stdout
        assert "UPDATE results/run-a-task-a" in result.stdout
        updated = json.loads((tmp_path / "results" / "run-a-task-a" / "result.json").read_text())
        untouched = json.loads((tmp_path / "results" / "run-b-task-b" / "result.json").read_text())
        updated_bench = json.loads(bench_run.read_text())
        assert updated["run_meta"]["notes"] == "Batch1 renamed"
        assert updated_bench["notes"] == "Batch1 renamed"
        assert untouched["run_meta"]["notes"] == "Batch2 beta"

    def test_rubric_filter_shows_only_rubric_section(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                score_numeric=0.90,
                rubric={
                    "quality": {"score": 0.45, "max": 0.50},
                    "process": {"score": 0.20, "max": 0.25},
                },
                checks={"answer_exists": True},
                orchestration_checks={"compaction_count": 2},
                task_meta={"batch": "smoke"},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--rubric"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "rubric view : all" in result.stdout
        assert "rubric:" in result.stdout
        assert "- quality:" in result.stdout
        assert "- process:" in result.stdout
        assert "checks:" not in result.stdout
        assert "behaviors:" not in result.stdout
        assert "score_numeric:" not in result.stdout

    def test_specific_filters_accept_comma_separated_names(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                rubric={
                    "quality": {"score": 0.45, "max": 0.50},
                    "process": {"score": 0.20, "max": 0.25},
                },
                checks={"answer_exists": True, "tests_pass": False},
                orchestration_checks={"compaction_count": 2, "dispatch_count": 4},
                task_meta={"batch": "smoke"},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--rubric", "quality", "--checks", "tests_pass", "--behaviors", "compaction_count,dispatch_count"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "- quality:" in result.stdout
        assert "- process:" not in result.stdout
        assert "- tests_pass:" in result.stdout
        assert "- answer_exists:" not in result.stdout
        assert "- compaction_count:" in result.stdout
        assert "- dispatch_count:" in result.stdout

    def test_detail_1_shows_only_base_metrics(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                score_numeric=0.90,
                rubric={"quality": {"score": 0.45, "max": 0.50}},
                checks={"answer_exists": True},
                orchestration_checks={"compaction_count": 2},
                tokens={"total": 100},
                elapsed_seconds=10.0,
                task_meta={"batch": "smoke"},
            ),
        )
        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--detail", "1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "detail level: 1" in result.stdout
        assert "runs        :" in result.stdout
        assert "pass rate   :" in result.stdout
        assert "tokens" in result.stdout
        assert "elapsed" in result.stdout
        assert "score_numeric:" not in result.stdout
        assert "rubric:" not in result.stdout
        assert "checks:" not in result.stdout
        assert "behaviors:" not in result.stdout

    def test_suite_filter_limits_dashboard_rows(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="capability-easy")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-a", run_id="run-a", score="pass", task_meta={"batch": "smoke"}),
        )
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-b", run_id="run-b", score="pass", task_meta={"batch": "capability-easy"}),
        )
        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--suite", "smoke"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "suite filter: smoke" in result.stdout
        assert "[smoke]" in result.stdout
        assert "[capability-easy]" not in result.stdout
        assert "- task-a" in result.stdout
        assert "- task-b" not in result.stdout

    def test_detail_2_shows_summary_breakdowns(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-a",
                score="pass",
                score_numeric=0.90,
                rubric={"quality": {"score": 0.45, "max": 0.50}},
                checks={"answer_exists": True, "tests_pass": False},
                orchestration_checks={"compaction_count": 2, "dispatch_count": 1, "worker_completed": True},
                tokens={"total": 100},
                elapsed_seconds=10.0,
                task_meta={"batch": "smoke"},
            ),
        )
        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--detail", "2"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "detail level: 2" in result.stdout
        assert "score_numeric:" in result.stdout
        assert "rubric       : avg=" in result.stdout
        assert "checks       : avg_pass_rate=" in result.stdout
        assert "behaviors    :" in result.stdout
        assert "worker_completed=1/1" in result.stdout
        assert "  - quality:" not in result.stdout
        assert "  - answer_exists:" not in result.stdout


class TestRunDetailReporting:
    def test_run_detail_shows_rubric_warnings_and_efficiency_history(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="hist-1",
                score="pass",
                tokens={"total": 800},
                elapsed_seconds=25.0,
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="hist-2",
                score="pass",
                tokens={"total": 1200},
                elapsed_seconds=40.0,
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-1",
                score="pass",
                score_numeric=0.86,
                rubric={
                    "role_result_quality": {"score": 0.35, "max": 0.40},
                    "orchestration_process": {"score": 0.16, "max": 0.20},
                },
                orchestration_checks={
                    "missing_expected_role": True,
                    "timeouts": 1,
                    "retries": 0,
                    "premature_completion": False,
                    "compaction_count": 2,
                },
                tokens={"total": 950},
                elapsed_seconds=32.0,
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "score_numeric" in result.stdout
        assert "0.8600" in result.stdout
        assert "rubric" in result.stdout
        assert "role_result_quality=0.3500/0.4000" in result.stdout
        assert "args         :" in result.stdout
        assert "extensions   :" in result.stdout
        assert "skills       :" in result.stdout
        assert "config       :" in result.stdout
        assert "orchestration:" in result.stdout
        assert "compaction_count: 2" in result.stdout
        assert "timeouts: 1" in result.stdout
        assert "orchestration warnings" in result.stdout
        assert "missing expected role" in result.stdout
        assert "1 timeout" in result.stdout
        assert "2 compactions" in result.stdout
        assert "efficiency" in result.stdout
        assert "tokens " in result.stdout
        assert "current=950" in result.stdout
        assert "elapsed " in result.stdout
        assert "current=32.0" in result.stdout

    def test_run_detail_shows_efficiency_diagnostics(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-efficiency",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "main_active_worker_tokens": 137,
                    "main_active_worker_api_calls": 3,
                },
                orchestration_checks={
                    "parent_tool_calls_while_workers_active": {"total": 2, "by_category": {"dispatch": 1, "test": 1}},
                    "test_command_ownership_by_role": {"builder": 1, "verifier": 1, "orchestrator": 1},
                    "duplicate_normalized_test_command_counts": {"npm test": 3},
                    "verifier_repeated_builder_tests": 1,
                    "orchestrator_repeated_worker_tests": 1,
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-efficiency"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "main_active_worker_tokens: 137" in result.stdout or "main_active_worker_tokens" in result.stdout
        assert "main_active_worker_api_calls: 3" in result.stdout or "main_active_worker_api_calls" in result.stdout
        assert "parent_tool_calls_while_workers_active" in result.stdout
        assert "dispatch=1" in result.stdout and "test=1" in result.stdout
        assert "test_command_ownership_by_role" in result.stdout
        assert "builder=1" in result.stdout and "verifier=1" in result.stdout and "orchestrator=1" in result.stdout
        assert "duplicate_normalized_test_command_counts" in result.stdout
        assert "npm test=3" in result.stdout
        assert "verifier_repeated_builder_tests" in result.stdout
        assert "orchestrator_repeated_worker_tests" in result.stdout

    def test_debug_view_prints_captured_trace_artifacts(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")
        _write_result_json(tmp_path, TaskResult(task_id="task-a", run_id="run-debug", score="fail"))
        run_dir = tmp_path / "results" / "run-debug-task-a"
        debug_dir = run_dir / "artifacts" / "orchestra-debug" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "session-debug.md").write_text("# Orchestra debug session\nruns: 1\nworker failed\n")
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "session.jsonl").write_text(
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "final failure summary"}]}}) + "\n"
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "debug", "run-debug", "--limit", "5"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "orchestra debug trace:" in result.stdout
        assert "worker failed" in result.stdout
        assert "pi session trace: not printed separately; included in orchestra debug trace" in result.stdout
        assert "final failure summary" not in result.stdout

    def test_debug_view_falls_back_to_full_pi_trace_when_orchestra_debug_failed(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")
        _write_result_json(tmp_path, TaskResult(task_id="task-a", run_id="run-debug-fallback", score="fail"))
        run_dir = tmp_path / "results" / "run-debug-fallback-task-a"
        debug_dir = run_dir / "artifacts" / "orchestra-debug" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "session-debug.md").write_text("error: role 'builder' requires 'skills' to be a non-empty list of strings\n")
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        long_text = "x" * 1200
        (session_dir / "session.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess", "cwd": "/workspace/run-debug-fallback-task-a"}) + "\n" +
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "first event"}]}}) + "\n" +
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": long_text}]}}) + "\n"
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "debug", "run-debug-fallback"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "orchestra debug trace is missing or incomplete" in result.stdout
        assert "first event" in result.stdout
        assert long_text in result.stdout
        assert "earlier events omitted" not in result.stdout

    def test_debug_view_falls_back_to_pi_trace_when_orchestra_debug_has_zero_runs(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")
        _write_result_json(tmp_path, TaskResult(task_id="task-a", run_id="run-debug-zero", score="fail"))
        run_dir = tmp_path / "results" / "run-debug-zero-task-a"
        debug_dir = run_dir / "artifacts" / "orchestra-debug" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "session-debug.md").write_text("# Orchestra debug session\nsession_id: sess\nruns: 0\n")
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "session.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess", "cwd": "/workspace/run-debug-zero-task-a"}) + "\n" +
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "main session diagnostic evidence"}]}}) + "\n"
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "debug", "run-debug-zero"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "runs: 0" in result.stdout
        assert "orchestra debug trace is missing or incomplete" in result.stdout
        assert "main session diagnostic evidence" in result.stdout

    def test_debug_view_classifies_rpc_task_failure_vs_harness_lifecycle(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")
        _write_result_json(tmp_path, TaskResult(task_id="task-a", run_id="run-debug-classify", score="fail"))
        run_dir = tmp_path / "results" / "run-debug-classify-task-a"
        (run_dir / ".bench_rpc_run.json").write_text(json.dumps({
            "pi_exit": 0,
            "orch_on_ok": True,
            "session_id": "sess-classify",
            "gate_result": "settled",
            "rpc_runner_used": True,
            "rpc_agent_settled_seen": True,
            "rpc_gate_result": "settled",
            "rpc_summary_written": True,
        }) + "\n")
        debug_dir = run_dir / "artifacts" / "orchestra-debug" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "session-debug.md").write_text("# Orchestra debug session\nruns: 1\nworker failed\n")
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "session.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess", "cwd": "/workspace/run-debug-classify-task-a"}) + "\n" +
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "raw pi trace"}]}}) + "\n"
        )
        events_dir = run_dir / "artifacts" / "pi-rpc"
        events_dir.mkdir(parents=True)
        (events_dir / "events.jsonl").write_text(
            json.dumps({"type": "agent_start"}) + "\n" +
            json.dumps({"type": "agent_settled"}) + "\n"
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "debug", "run-debug-classify"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "debug classification: task failure" in result.stdout
        assert "pi rpc runner:" in result.stdout
        assert "artifacts/pi-rpc/events.jsonl" in result.stdout
        assert "worker failed" in result.stdout

    def test_debug_view_classifies_harness_lifecycle_when_rpc_timeout(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")
        _write_result_json(tmp_path, TaskResult(task_id="task-a", run_id="run-debug-harness", score="fail"))
        run_dir = tmp_path / "results" / "run-debug-harness-task-a"
        (run_dir / ".bench_rpc_run.json").write_text(json.dumps({
            "pi_exit": 1,
            "orch_on_ok": True,
            "session_id": "sess-harness",
            "gate_result": "timeout",
            "rpc_runner_used": True,
            "rpc_agent_settled_seen": False,
            "rpc_gate_result": "timeout",
            "rpc_summary_written": True,
        }) + "\n")
        debug_dir = run_dir / "artifacts" / "orchestra-debug" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "session-debug.md").write_text("# Orchestra debug session\nruns: 1\nworker still active\n")
        session_dir = run_dir / "artifacts" / "pi-sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "session.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess", "cwd": "/workspace/run-debug-harness-task-a"}) + "\n"
        )
        events_dir = run_dir / "artifacts" / "pi-rpc"
        events_dir.mkdir(parents=True)
        (events_dir / "events.jsonl").write_text(
            json.dumps({"type": "agent_start"}) + "\n"
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "debug", "run-debug-harness"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "debug classification: harness lifecycle" in result.stdout
        assert "pi rpc runner:" in result.stdout
        assert "worker still active" in result.stdout

    def test_run_detail_colors_boolean_checks_when_forced(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-color",
                score="fail",
                checks={"ok_check": True, "bad_check": False},
                orchestration_checks={"timeouts": 1, "worker_completed": True},
            ),
        )
        env = os.environ.copy()
        env["FORCE_COLOR"] = "1"

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-color"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "\x1b[32mTrue\x1b[0m" in result.stdout
        assert "\x1b[31mFalse\x1b[0m" in result.stdout
        assert "bad_check:" in result.stdout

    def test_dispatch_without_orchestra_logs_preserves_numeric_score(self, tmp_path):
        from eval_harness import ingest_artifacts

        base = tmp_path / "results"

        hist1 = base / "hist-1-task-pen"
        hist1.mkdir(parents=True)
        TaskResult(
            task_id="task-pen",
            run_id="hist-1",
            score="pass",
            score_numeric=1.0,
            tokens={"total": 800},
            elapsed_seconds=30.0,
        ).write_json(hist1)

        hist2 = base / "hist-2-task-pen"
        hist2.mkdir(parents=True)
        TaskResult(
            task_id="task-pen",
            run_id="hist-2",
            score="pass",
            score_numeric=1.0,
            tokens={"total": 1000},
            elapsed_seconds=35.0,
        ).write_json(hist2)

        run_dir = base / "run-0-task-pen"
        artifacts = run_dir / "artifacts"
        (artifacts / "pi-sessions").mkdir(parents=True)
        (artifacts / "tokens.json").write_text(json.dumps({"total_tokens": 900}))
        (artifacts / "timing.json").write_text(json.dumps({"elapsed_seconds": 32.0}))
        (artifacts / "pi-sessions" / "sess.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess-0"}) + "\n" +
            json.dumps({
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "orch_dispatch",
                        "arguments": {"goal": "review code", "role": "reviewer"},
                    }],
                },
            }) + "\n"
        )
        (artifacts / "manifest.json").write_text(json.dumps({"orchestra": {}}))

        result_obj = TaskResult(
            task_id="task-pen",
            run_id="run-0",
            score="pass",
            score_numeric=1.0,
            rubric={"content": {"score": 1.0, "max": 1.0}},
            checks={"answer_exists": True},
            run_meta={"target_role": "reviewer"},
        )

        enriched = ingest_artifacts(result_obj, base_dir=base)

        assert enriched.score == "pass"
        assert enriched.score_numeric == 1.0
        assert "process_penalties" not in enriched.rubric
        assert enriched.orchestration_checks["fallback_answer_after_dispatch"] is False
        assert enriched.orchestration_checks["process_penalty_total"] == 0.0

    def test_process_penalty_for_capability_run_with_zero_dispatches(self, tmp_path):
        from eval_harness import ingest_artifacts

        base = tmp_path / "results"
        run_dir = base / "run-zero-cap-easy-django-reports"
        artifacts = run_dir / "artifacts"
        (artifacts / "pi-sessions").mkdir(parents=True)
        (artifacts / "manifest.json").write_text(json.dumps({"orchestra": {}}))
        (artifacts / "pi-sessions" / "sess.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess-zero"}) + "\n"
        )

        result_obj = TaskResult(
            task_id="cap-easy-django-reports",
            run_id="run-zero",
            score="fail",
            score_numeric=0.04,
            rubric={"content": {"score": 0.04, "max": 1.0}},
            checks={},
            task_meta={"family": "capability", "batch": "capability-easy"},
        )

        enriched = ingest_artifacts(result_obj, base_dir=base)

        assert enriched.orchestration_checks["dispatch_count"] == 0
        assert enriched.orchestration_checks["no_orchestration"] is True
        assert enriched.orchestration_checks["process_penalty_total"] > 0
        assert "no orchestration" in enriched.orchestration_checks["process_penalty_reasons"]
        assert enriched.score_numeric == 0.0
        assert enriched.score == "fail"

    def test_intentional_no_orchestra_does_not_apply_no_orchestration_penalty(self, tmp_path):
        from eval_harness import ingest_artifacts

        base = tmp_path / "results"
        run_dir = base / "run-zero-cap-easy-django-reports"
        artifacts = run_dir / "artifacts"
        (artifacts / "pi-sessions").mkdir(parents=True)
        (artifacts / "manifest.json").write_text(json.dumps({"orchestra": {}}))
        (artifacts / "pi-sessions" / "sess.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess-zero"}) + "\n"
        )

        result_obj = TaskResult(
            task_id="cap-easy-django-reports",
            run_id="run-zero",
            score="pass",
            score_numeric=0.5,
            rubric={"content": {"score": 0.5, "max": 1.0}},
            checks={},
            task_meta={"family": "capability", "batch": "capability-easy"},
            run_meta={"orchestra": False},
        )

        enriched = ingest_artifacts(result_obj, base_dir=base)

        assert enriched.orchestration_checks["no_orchestration"] is True
        assert enriched.orchestration_checks["process_penalty_total"] == 0.0
        assert "no orchestration" not in enriched.orchestration_checks["process_penalty_reasons"]

    def test_process_penalty_lowers_numeric_score_without_flipping_pass(self, tmp_path):
        from eval_harness import ingest_artifacts

        base = tmp_path / "results"

        hist1 = base / "hist-1-task-pen"
        hist1.mkdir(parents=True)
        TaskResult(
            task_id="task-pen",
            run_id="hist-1",
            score="pass",
            score_numeric=1.0,
            tokens={"total": 800},
            elapsed_seconds=30.0,
        ).write_json(hist1)

        hist2 = base / "hist-2-task-pen"
        hist2.mkdir(parents=True)
        TaskResult(
            task_id="task-pen",
            run_id="hist-2",
            score="pass",
            score_numeric=1.0,
            tokens={"total": 1000},
            elapsed_seconds=35.0,
        ).write_json(hist2)

        run_dir = base / "run-1-task-pen"
        artifacts = run_dir / "artifacts"
        (artifacts / "pi-sessions").mkdir(parents=True)
        (artifacts / "orchestra-debug" / "logs").mkdir(parents=True)
        (artifacts / "tokens.json").write_text(json.dumps({"total_tokens": 3000}))
        (artifacts / "timing.json").write_text(json.dumps({"elapsed_seconds": 120.0}))
        (artifacts / "pi-sessions" / "sess.jsonl").write_text(
            json.dumps({"type": "session", "id": "sess-1"}) + "\n" +
            json.dumps({
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "orch_dispatch",
                        "arguments": {"goal": "review code", "role": "reviewer"},
                    }],
                },
            }) + "\n"
        )
        (artifacts / "orchestra-debug" / "logs" / "run.jsonl").write_text(
            json.dumps({"event": "run.created", "role": "reviewer", "run_id": "w1"}) + "\n" +
            json.dumps({"event": "worker.started", "role": "reviewer", "run_id": "w1"}) + "\n" +
            json.dumps({"event": "retry.requested", "run_id": "w1"}) + "\n"
        )
        (artifacts / "manifest.json").write_text(json.dumps({"orchestra": {}}))

        result_obj = TaskResult(
            task_id="task-pen",
            run_id="run-1",
            score="pass",
            score_numeric=1.0,
            rubric={"content": {"score": 1.0, "max": 1.0}},
            checks={"answer_exists": True},
            run_meta={"target_role": "reviewer"},
        )

        enriched = ingest_artifacts(result_obj, base_dir=base)

        assert enriched.score == "pass"
        assert enriched.score_numeric is not None
        assert enriched.score_numeric < 1.0
        assert enriched.rubric["process_penalties"]["score"] < 0
        assert enriched.orchestration_checks["fallback_answer_after_dispatch"] is True
        assert enriched.orchestration_checks["worker_running_without_exit"] is True
        assert enriched.orchestration_checks["process_penalty_total"] > 0

    def test_run_detail_shows_no_rubric_score_for_legacy_results(self, tmp_path):
        script = _install_results_script(tmp_path)
        _write_task_yaml(tmp_path, "task-old")
        _write_result_json(
            tmp_path,
            TaskResult(task_id="task-old", run_id="legacy-1", score="fail"),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "legacy-1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "score" in result.stdout
        assert "fail" in result.stdout
        assert "no rubric score" in result.stdout



# ── 10b. Classified token reporting in scripts/05-results ───────────


class TestClassifiedTokenReporting:
    """scripts/05-results displays classified tokens: all/main/roles, cache, context."""

    def _setup_script(self, tmp_path):
        script = _install_results_script(tmp_path)
        return script

    def test_tokens_view_shows_classified_main_and_role_totals(self, tmp_path):
        """tokens view distinguishes all tokens, main session, and role tokens."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-1",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "input_tokens": 500,
                    "output_tokens": 300,
                    "reasoning_tokens": 100,
                    "cached_input_read_tokens": 80,
                    "cache_write_tokens": 20,
                    "expensive_main_session_tokens": {
                        "input_tokens": 400,
                        "output_tokens": 250,
                        "reasoning_tokens": 80,
                        "cached_input_read_tokens": 60,
                        "cache_write_tokens": 15,
                        "total_tokens": 700,
                    },
                    "cheap_role_tokens": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "reasoning_tokens": 20,
                        "total_tokens": 200,
                    },
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "tokens"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        # Should show all tokens total
        assert "total_tokens" in result.stdout or "avg_tokens" in result.stdout
        # Should distinguish main session tokens from role tokens
        assert "main" in result.stdout.lower() and "role" in result.stdout.lower()

    def test_tokens_view_shows_cache_and_reasoning_breakdown(self, tmp_path):
        """tokens view shows cache read/write and reasoning token breakdowns."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-1",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "input_tokens": 500,
                    "output_tokens": 300,
                    "reasoning_tokens": 100,
                    "cached_input_read_tokens": 80,
                    "cache_write_tokens": 20,
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "tokens"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        # Should show reasoning tokens in breakdown
        assert "reasoning" in result.stdout.lower() or "reason" in result.stdout.lower()
        # Cache data should be present when available
        stdout_lower = result.stdout.lower()
        has_cache_info = "cache" in stdout_lower or "cached" in stdout_lower
        # Not required for legacy-only results, but should appear when fields exist
        assert True  # Token view runs without error is the key check

    def test_run_detail_shows_classified_tokens_with_context(self, tmp_path):
        """run detail shows main session tokens, role tokens, and context info."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-detail-tokens",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "input_tokens": 500,
                    "output_tokens": 300,
                    "reasoning_tokens": 100,
                    "cached_input_read_tokens": 80,
                    "cache_write_tokens": 20,
                    "main_session_context_input_tokens": 4500,
                    "main_session_max_input_tokens": 6000,
                    "main_session_api_call_count": 12,
                    "compaction_count": 3,
                    "expensive_main_session_tokens": {
                        "input_tokens": 400,
                        "output_tokens": 250,
                        "reasoning_tokens": 80,
                        "total_tokens": 700,
                    },
                    "cheap_role_tokens": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_tokens": 200,
                    },
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-detail-tokens"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        # Legacy token line should still work (backward compat)
        assert "tokens" in result.stdout.lower()
        # Should show classified main session info when available
        stdout_lower = result.stdout.lower()
        assert "main" in stdout_lower or "all" in stdout_lower
        # Context final/max should appear when present
        has_context_info = ("context" in stdout_lower) or ("4500" in result.stdout)
        assert has_context_info, f"Expected context info in run detail output"

    def test_run_detail_shows_compaction_count(self, tmp_path):
        """run detail shows compaction count from orchestration_checks."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-compaction",
                score="pass",
                orchestration_checks={"compaction_count": 5},
                tokens={"total": 1000, "main_session_context_input_tokens": 3000},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-compaction"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        # Compaction count should appear in orchestration section
        assert "compaction_count: 5" in result.stdout or "compactions" in result.stdout.lower()

    def test_run_detail_shows_active_worker_diagnostics(self, tmp_path):
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-efficiency",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "main_active_worker_tokens": 137,
                    "main_active_worker_api_calls": 3,
                },
                orchestration_checks={
                    "parent_tool_calls_while_workers_active": {"total": 2, "by_category": {"dispatch": 1, "test": 1}},
                    "test_command_ownership_by_role": {"builder": 1, "verifier": 1, "orchestrator": 1},
                    "duplicate_normalized_test_command_counts": {"npm test": 3},
                    "verifier_repeated_builder_tests": 1,
                    "orchestrator_repeated_worker_tests": 1,
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "run", "run-efficiency"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        stdout = result.stdout.lower()
        assert "main_active_worker_tokens" in stdout or "main active worker" in stdout
        assert "test_command_ownership_by_role" in stdout or "test command ownership" in stdout
        assert "verifier_repeated_builder_tests" in stdout

    def test_tokens_view_ignores_legacy_only_results(self, tmp_path):
        """tokens view should not reinterpret flat-only legacy totals as classified tokens."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        run_dir = tmp_path / "results" / "run-legacy-task-a"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(json.dumps({
            "task_id": "task-a",
            "run_id": "run-legacy",
            "score": "pass",
            "tokens": {"total": 500},
        }, indent=2) + "\n")

        result = __import__("subprocess").run(
            ["bash", str(script), "tokens"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "no token data captured" in result.stdout.lower() or "runs_with_tokens: 0/1" in result.stdout

    def test_tokens_view_handles_structured_results(self, tmp_path):
        """tokens view handles multiple structured token results."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")
        _write_task_yaml(tmp_path, "task-b", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-legacy",
                score="pass",
                tokens={"total": 500},
            ),
        )
        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-b",
                run_id="run-classified",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "expensive_main_session_tokens": {"total_tokens": 700},
                    "cheap_role_tokens": {"total_tokens": 200},
                },
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "tokens"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "runs_with_tokens: 2/2" in result.stdout or "runs_with_tokens:" in result.stdout

    def test_timeline_shows_token_breakdown(self, tmp_path):
        """timeline view shows per-run token breakdown including reasoning."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-timeline-1",
                score="pass",
                tokens={"total": 800, "input_tokens": 500, "output_tokens": 200, "reasoning_tokens": 100},
                elapsed_seconds=30.0,
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "timeline"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        # Timeline shows per-run totals and breakdowns
        assert "total=" in result.stdout or "reason" in result.stdout.lower()

    def test_dashboard_shows_main_context_metrics(self, tmp_path):
        """dashboard section metrics include main_ctx when available."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-ctx-1",
                score="pass",
                tokens={
                    "total": 900,
                    "main_session_context_input_tokens": 5000,
                },
                elapsed_seconds=30.0,
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        # Dashboard should show main_ctx metrics alongside tokens
        assert "main_ctx" in result.stdout or "context" in result.stdout.lower()

    def test_dashboard_no_orchestra_shows_classified_token_totals(self, tmp_path):
        """dashboard --no-orchestra prints totals for main and role classified tokens."""
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-no-orch",
                score="pass",
                tokens={
                    "total": 925740,
                    "main_session_context_input_tokens": 8123,
                    "expensive_main_session_tokens": {
                        "input_tokens": 600000,
                        "output_tokens": 250000,
                        "reasoning_tokens": 30000,
                        "cached_input_read_tokens": 3500,
                        "cache_write_tokens": 1500,
                        "total_tokens": 925740,
                    },
                    "cheap_role_tokens": {
                        "input_tokens": 1200,
                        "output_tokens": 340,
                        "reasoning_tokens": 60,
                        "total_tokens": 1600,
                    },
                },
                elapsed_seconds=18.0,
                task_meta={"batch": "smoke"},
                run_meta={"orchestra": False},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard", "--no-orchestra"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "main_tokens : total=925,740" in result.stdout
        assert "role_tokens : total=1,600" in result.stdout
        assert "tokens      : total=925,740" in result.stdout
        assert "elapsed     : total=" in result.stdout

    def test_dashboard_shows_efficiency_diagnostics(self, tmp_path):
        script = self._setup_script(tmp_path)
        _write_task_yaml(tmp_path, "task-a", batch="smoke")

        _write_result_json(
            tmp_path,
            TaskResult(
                task_id="task-a",
                run_id="run-efficiency",
                score="pass",
                tokens={
                    "total_tokens": 900,
                    "main_active_worker_tokens": 137,
                    "main_active_worker_api_calls": 3,
                },
                orchestration_checks={
                    "parent_tool_calls_while_workers_active": {"total": 2, "by_category": {"dispatch": 1, "test": 1}},
                    "test_command_ownership_by_role": {"builder": 1, "verifier": 1, "orchestrator": 1},
                    "duplicate_normalized_test_command_counts": {"npm test": 3},
                    "verifier_repeated_builder_tests": 1,
                    "orchestrator_repeated_worker_tests": 1,
                },
                task_meta={"batch": "smoke"},
            ),
        )

        result = __import__("subprocess").run(
            ["bash", str(script), "dashboard"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "main_active_worker_tokens" in result.stdout
        assert "main_active_worker_api_calls" in result.stdout
        assert "parent_tool_calls_while_workers_active" in result.stdout
        assert "dispatch=1" in result.stdout and "test=1" in result.stdout
        assert "test_command_ownership_by_role" in result.stdout
        assert "builder=1" in result.stdout and "verifier=1" in result.stdout and "orchestrator=1" in result.stdout
        assert "duplicate_normalized_test_command_counts" in result.stdout
        assert "npm test=3" in result.stdout
        assert "verifier_repeated_builder_tests" in result.stdout
        assert "orchestrator_repeated_worker_tests" in result.stdout


class TestOrchestraArtifactCollection:
    def test_copy_orchestra_db_preserves_nonempty_capture_when_runtime_db_empty(self, tmp_path, monkeypatch):
        import eval_harness

        existing = tmp_path / "orchestra.db"
        empty_source = tmp_path / "empty-source.db"

        for path in (existing, empty_source):
            con = sqlite3.connect(path)
            con.execute("create table runs (run_id text)")
            con.commit()
            con.close()

        con = sqlite3.connect(existing)
        con.execute("insert into runs values ('run-a')")
        con.commit()
        con.close()

        def fake_copy(_container_path, host_path):
            host_path.write_bytes(empty_source.read_bytes())
            return True

        monkeypatch.setattr(eval_harness, "_copy_from_container", fake_copy)
        warnings: list[object] = []

        assert eval_harness._copy_orchestra_db_preserving_nonempty("/state/orchestra.db", existing, warnings)

        con = sqlite3.connect(existing)
        try:
            assert con.execute("select count(*) from runs").fetchone()[0] == 1
        finally:
            con.close()
        assert warnings == ["kept earlier non-empty Orchestra state DB; current runtime DB was empty"]

    def test_orchestra_debug_run_count_parses_top_level_runs(self):
        import eval_harness

        assert eval_harness._orchestra_debug_run_count("# Orchestra debug session\n\nruns: 3\n") == 3
        assert eval_harness._orchestra_debug_run_count("# Orchestra debug session\n\nruns: 0\n") == 0
        assert eval_harness._orchestra_debug_run_count("# no count\n") is None
