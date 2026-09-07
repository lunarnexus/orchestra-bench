from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

import pytest
import yaml

from bench.tasks import discover_tasks

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = REPO_ROOT / "tasks"
CAPABILITY_NORMAL_TASKS = [
    "cap-normal-python-worker-sync",
    "cap-normal-ruby-billing-ledger",
    "cap-normal-ts-approval-queue",
]


def _copy_tree(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _run_evaluator(task_id: str, workspace: Path) -> tuple[int, dict]:
    env = os.environ.copy()
    env["BENCH_REPO_ROOT"] = str(REPO_ROOT)
    env["BENCH_TASKS"] = str(TASKS_ROOT)
    env["BENCH_CURRENT_TASK"] = task_id
    result = sp.run(
        ["bash", str(TASKS_ROOT / task_id / "evaluate" / "run.sh")],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = result.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"evaluator produced no JSON\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.returncode, json.loads(stdout[start:])


@pytest.mark.parametrize("task_id", CAPABILITY_NORMAL_TASKS)
def test_slice11_batch6_tasks_are_discovered(task_id: str) -> None:
    discovered = {path.name for path in discover_tasks(TASKS_ROOT)}
    assert task_id in discovered


@pytest.mark.parametrize("task_id", CAPABILITY_NORMAL_TASKS)
def test_capability_normal_task_metadata_declares_numeric_scoring(task_id: str) -> None:
    task_yaml = yaml.safe_load((TASKS_ROOT / task_id / "task.yaml").read_text(encoding="utf-8"))

    assert task_yaml["family"] == "capability"
    assert task_yaml["batch"] == "capability-normal"
    assert task_yaml["required_roles"] == ["builder", "verifier"]
    assert task_yaml["scoring_type"] == "numeric"
    assert task_yaml["timeout_minutes"] == 35
    assert task_yaml["evaluator"] == "evaluate/run.sh"
    assert task_yaml["split"] == "dev"


@pytest.mark.parametrize("task_id", CAPABILITY_NORMAL_TASKS)
def test_capability_normal_tasks_have_workspace_assets(task_id: str) -> None:
    task_dir = TASKS_ROOT / task_id
    assert (task_dir / "PRD.md").is_file()
    assert (task_dir / "Prompt.md").is_file()
    assert (task_dir / "fixture").is_dir()
    assert (task_dir / "kb").is_dir()
    assert (task_dir / "evaluate" / "run.sh").is_file()
    assert (task_dir / "evaluate" / "solved").is_dir()


@pytest.mark.parametrize(
    "task_id, expected_check",
    [
        ("cap-normal-python-worker-sync", "functional_document_and_job_flow"),
        ("cap-normal-ruby-billing-ledger", "functional_idempotency_and_ledger"),
        ("cap-normal-ts-approval-queue", "functional_submission_and_moderation_flow"),
    ],
)
def test_capability_normal_task_evaluators_fail_on_fixture(task_id: str, expected_check: str, tmp_path: Path) -> None:
    _copy_tree(TASKS_ROOT / task_id / "fixture", tmp_path)

    code, result = _run_evaluator(task_id, tmp_path)

    assert code != 0
    assert result["score"] == "fail"
    assert result["checks"][expected_check] is False
    assert result["checks"] == result["details"]["functionality"]["checks"]


@pytest.mark.parametrize(
    "task_id, expected_check",
    [
        ("cap-normal-python-worker-sync", "functional_document_and_job_flow"),
        ("cap-normal-ruby-billing-ledger", "functional_idempotency_and_ledger"),
        ("cap-normal-ts-approval-queue", "functional_submission_and_moderation_flow"),
    ],
)
def test_capability_normal_task_evaluators_pass_on_reference_solution(task_id: str, expected_check: str, tmp_path: Path) -> None:
    _copy_tree(TASKS_ROOT / task_id / "evaluate" / "solved", tmp_path)

    code, result = _run_evaluator(task_id, tmp_path)

    assert code == 0
    assert result["score"] == "pass"
    assert isinstance(result["checks"], dict)
    assert result["checks"] == result["details"]["functionality"]["checks"]
    assert result["checks"][expected_check] is True
    assert all(result["checks"].values())
