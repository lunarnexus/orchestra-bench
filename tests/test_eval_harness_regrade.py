from __future__ import annotations

import subprocess as sp
from pathlib import Path

import pytest


def test_grade_restores_existing_result_when_evaluator_fails_without_json(tmp_path, monkeypatch):
    import eval_harness
    from eval_harness import TaskMeta, TaskResult

    root = tmp_path
    task_id = "dummy-task"
    run_id = "run-restore"
    task_dir = root / "tasks" / task_id / "evaluate"
    task_dir.mkdir(parents=True)
    (task_dir / "run.sh").write_text("#!/bin/sh\nexit 1\n")
    (root / "capability_helpers.py").write_text("# helper\n")
    (root / "rubric_helpers.py").write_text("# helper\n")

    result_dir = root / "results" / f"{run_id}-{task_id}"
    result_dir.mkdir(parents=True)
    original = TaskResult(task_id=task_id, run_id=run_id, score="pass", checks={"old": True})
    original.write_json(result_dir / "result.json")
    original_text = (result_dir / "result.json").read_text()

    monkeypatch.setattr(eval_harness, "_REPO_ROOT", root)
    monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
    monkeypatch.setattr(eval_harness, "collect_container_runtime_snapshot", lambda: {})
    monkeypatch.setattr(eval_harness, "collect_run_artifacts", lambda task_id, run_id: None)
    monkeypatch.setattr(eval_harness, "ingest_artifacts", lambda result: None)
    monkeypatch.setattr(eval_harness, "_enrich_result_with_bench_run", lambda result: None)

    def fake_docker_exec(*args, env=None):
        if args[:2] == ("rm", "-rf") or args[:2] == ("mkdir", "-p"):
            return sp.CompletedProcess(args, 0, "", "")
        # Simulate bench-entrypoint/evaluator failure before JSON output.
        if args and args[0] == "bench-entrypoint":
            return sp.CompletedProcess(args, 1, "", "workdir not found")
        return sp.CompletedProcess(args, 0, "", "")

    real_sp_run = sp.run

    def fake_sp_run(cmd, *args, **kwargs):
        # docker cp support files succeeds.
        if isinstance(cmd, list) and cmd[:2] == ["docker", "cp"]:
            return sp.CompletedProcess(cmd, 0, "", "")
        return real_sp_run(cmd, *args, **kwargs)

    monkeypatch.setattr(eval_harness, "_docker_exec", fake_docker_exec)
    monkeypatch.setattr(eval_harness.sp, "run", fake_sp_run)

    with pytest.raises(RuntimeError, match="workdir not found"):
        eval_harness.grade(
            task_id,
            run_id,
            task_meta=TaskMeta(
                task_id=task_id,
                family="capability",
                batch="capability-normal",
                scoring_type="numeric",
                evaluator="evaluate/run.sh",
            ),
        )

    restored = result_dir / "result.json"
    assert restored.exists()
    assert restored.read_text() == original_text
    assert not (result_dir / ".result.json.previous").exists()
