from pathlib import Path

import pytest

from bench.paths import RepoPaths, RunPaths, list_runs


def test_repo_and_run_paths_contract(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    run = repo.run("20250101T010203", "task-one")

    assert repo.root == tmp_path
    assert repo.tasks_dir == tmp_path / "tasks"
    assert repo.results_dir == tmp_path / "results"
    assert repo.artifacts_dir == tmp_path / "artifacts"
    assert repo.config_dir == tmp_path / "config"

    assert run.root == tmp_path
    assert run.run_dir == tmp_path / "results" / "20250101T010203-task-one"
    assert run.artifacts_dir == run.run_dir / "artifacts"
    assert run.pi_sessions_dir == run.artifacts_dir / "pi-sessions"
    assert run.orchestra_debug_dir == run.artifacts_dir / "orchestra-debug"
    assert run.pi_rpc_dir == run.artifacts_dir / "pi-rpc"
    assert run.pi_rpc_events_path == run.pi_rpc_dir / "events.jsonl"
    assert run.result_json == run.run_dir / "result.json"
    assert run.bench_run_json == run.run_dir / ".bench_run.json"
    assert run.manifest_path == run.artifacts_dir / "manifest.json"
    assert run.container_workdir == "/workspace/20250101T010203-task-one"


def test_repo_paths_rejects_unsafe_task_id(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)

    with pytest.raises(ValueError, match="invalid task_id"):
        repo.run("20250101T010203", "../escape")


def test_list_runs_returns_newest_first(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    (results_dir / "20250101T010203-task-one").mkdir(parents=True)
    (results_dir / "20241231T235959-task-two").mkdir()
    (results_dir / "not-a-run").mkdir()

    runs = list_runs(tmp_path)

    assert [run.run_dir.name for run in runs] == [
        "20250101T010203-task-one",
        "20241231T235959-task-two",
    ]
    assert all(isinstance(run, RunPaths) for run in runs)
