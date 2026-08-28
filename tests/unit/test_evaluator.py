from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.evaluator import EvaluationError, grade_run
from bench.paths import RepoPaths
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.tasks import load_task
from bench.workspace import prepare_workspace


def _write_task(task_dir: Path, *, task_id: str = "alpha") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(
        "task_id: {task_id}\n"
        "description: Sample task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 10\n"
        "evaluator: evaluate/run.sh\n".format(task_id=task_id)
    )
    (task_dir / "PRD.md").write_text("Product requirements.\n")
    (task_dir / "Prompt.md").write_text("Do the thing.\n")
    (task_dir / "fixture").mkdir()
    (task_dir / "evaluate").mkdir()
    (task_dir / "evaluate" / "run.sh").write_text("#!/bin/sh\nexit 0\n")



def test_grade_run_inherits_process_environment_for_grader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Graders rely on a sane inherited env (e.g. PATH); container python breaks with an empty env."""
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths)
    write_json_atomic(
        run_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )

    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    captured: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        captured["env"] = dict(kwargs["env"])
        Path(kwargs["env"]["BENCH_RESULT_JSON"]).write_text('{"status": "ok", "score": "pass"}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    grade_run(task, run_paths, runner=fake_runner)

    env = captured["env"]
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["BENCH_WORKDIR"] == str(workspace)


def test_grade_run_updates_result_and_captures_artifacts(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    write_json_atomic(run_paths.result_json, original)

    captured: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        captured["command"] = list(command)
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = dict(kwargs["env"])

        staged_root = Path(kwargs["env"]["BENCH_REPO_ROOT"])
        assert (staged_root / "evaluate" / "run.sh").is_file()
        assert not (workspace / "evaluate").exists()

        result_json = Path(kwargs["env"]["BENCH_RESULT_JSON"])
        result_json.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "score": "pass",
                    "checks": {"workspace": True},
                    "details": {"source": "result.json"},
                }
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout="stdout line\n", stderr="stderr line\n")

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result == load_result(run_paths.result_json)
    assert result.evaluation == EvaluationResult(
        status="ok",
        score="pass",
        checks={"workspace": True},
        error="",
        details={"source": "result.json"},
    )
    assert result.outcome == "pass"
    assert result.harness == original.harness
    assert captured["cwd"] == workspace
    assert captured["command"][0] == "bash"
    assert captured["command"][1].endswith("/evaluate/run.sh")
    assert Path(captured["command"][1]).name == "run.sh"
    assert (run_paths.artifacts_dir / "evaluator" / "stdout.txt").read_text(encoding="utf-8") == "stdout line\n"
    assert (run_paths.artifacts_dir / "evaluator" / "stderr.txt").read_text(encoding="utf-8") == "stderr line\n"
    assert (run_paths.artifacts_dir / "evaluator" / "log.txt").read_text(encoding="utf-8")
    assert json.loads((run_paths.manifest_path).read_text(encoding="utf-8"))["classification"] == "ok"


def test_grade_run_persists_stdout_json_to_evaluator_artifact_when_result_file_is_empty(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    write_json_atomic(run_paths.result_json, original)

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "score": "pass",
                    "checks": {"source": "stdout"},
                    "details": {"source": "stdout"},
                }
            ) + "\n",
            stderr="",
        )

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result.evaluation == EvaluationResult(
        status="ok",
        score="pass",
        checks={"source": "stdout"},
        error="",
        details={"source": "stdout"},
    )
    assert result.outcome == "pass"
    assert json.loads((run_paths.artifacts_dir / "evaluator" / "result.json").read_text(encoding="utf-8")) == {
        "checks": {"source": "stdout"},
        "details": {"source": "stdout"},
        "score": "pass",
        "status": "ok",
    }
    assert load_result(run_paths.result_json).evaluation == result.evaluation


def test_grade_run_preserves_previous_result_when_evaluator_produces_no_json(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    write_json_atomic(run_paths.result_json, original)
    original_text = run_paths.result_json.read_text(encoding="utf-8")

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom\n")

    with pytest.raises(EvaluationError, match="no JSON") as exc_info:
        grade_run(task, run_paths, runner=fake_runner)

    assert exc_info.value.classification == "crash"
    assert run_paths.result_json.read_text(encoding="utf-8") == original_text
    assert load_result(run_paths.result_json) == original
    assert json.loads((run_paths.manifest_path).read_text(encoding="utf-8"))["classification"] == "crash"


def test_grade_run_ignores_stale_evaluator_result_when_regrade_fails(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(
            status="ok",
            score="pass",
            checks={"workspace": True},
            error="",
            details={"source": "previous-success"},
        ),
        outcome="pass",
    )
    write_json_atomic(run_paths.result_json, original)

    stale_result = run_paths.artifacts_dir / "evaluator" / "result.json"
    stale_result.parent.mkdir(parents=True, exist_ok=True)
    stale_result.write_text(
        json.dumps(
            {
                "status": "ok",
                "score": "fail",
                "checks": {"stale": True},
                "details": {"source": "stale-artifact"},
            }
        ),
        encoding="utf-8",
    )
    original_text = run_paths.result_json.read_text(encoding="utf-8")

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom\n")

    with pytest.raises(EvaluationError, match="no JSON") as exc_info:
        grade_run(task, run_paths, runner=fake_runner)

    assert exc_info.value.classification == "crash"
    assert run_paths.result_json.read_text(encoding="utf-8") == original_text
    assert load_result(run_paths.result_json) == original
    assert json.loads(stale_result.read_text(encoding="utf-8"))["details"]["source"] == "stale-artifact"
    assert json.loads((run_paths.manifest_path).read_text(encoding="utf-8"))["classification"] == "crash"


@pytest.mark.parametrize("score,expected_outcome", [("pass", "pass"), ("fail", "fail")])
def test_grade_run_derives_ok_status_when_grader_omits_explicit_status(
    tmp_path: Path, score: str, expected_outcome: str
) -> None:
    """Graders emit a verdict (score/checks/details) without an explicit status field."""
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    write_json_atomic(
        run_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )

    def fake_runner(command, **kwargs):
        Path(kwargs["env"]["BENCH_RESULT_JSON"]).write_text(
            json.dumps({"score": score, "checks": {"workflow_passes": True}, "details": ""})
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result.evaluation.status == "ok"
    assert result.evaluation.score == score
    assert result.outcome == expected_outcome
    artifact_result = run_paths.artifacts_dir / "evaluator" / "result.json"
    assert artifact_result.stat().st_mode & 0o777 == 0o644
