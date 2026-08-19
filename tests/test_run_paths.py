"""Tests for bench.run_paths.RunDirectory."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from bench.run_paths import RunDirectory, list_runs  # noqa: E402


def test_run_directory_paths(tmp_path):
    run = RunDirectory(tmp_path, "20260101T000000", "smoke-task")
    assert run.path == tmp_path / "results" / "20260101T000000-smoke-task"
    assert run.artifacts_dir == run.path / "artifacts"
    assert run.pi_sessions_dir == run.path / "artifacts" / "pi-sessions"
    assert run.orchestra_debug_dir == run.path / "artifacts" / "orchestra-debug"
    assert run.rpc_events_path == run.path / "artifacts" / "pi-rpc" / "events.jsonl"
    assert run.result_json == run.path / "result.json"
    assert run.bench_run_json == run.path / ".bench_run.json"
    assert run.manifest_path == run.artifacts_dir / "manifest.json"
    assert run.container_workdir == "/workspace/20260101T000000-smoke-task"


def test_list_runs_newest_first(tmp_path):
    (tmp_path / "results").mkdir()
    for name in ("20250101T000000-old", "20260101T000000-new"):
        (tmp_path / "results" / name).mkdir()
    (tmp_path / "results" / "not-a-run").mkdir()
    runs = list_runs(tmp_path)
    assert [r.task_id for r in runs] == ["new", "old"]


def test_list_runs_empty(tmp_path):
    assert list_runs(tmp_path) == []
