from __future__ import annotations

from pathlib import Path

import pytest

from bench.paths import RepoPaths
from bench.tasks import TaskDefinition, load_task
from bench.workspace import WorkspaceError, cleanup_workspace, prepare_workspace, visible_task_files, workspace_dir


def _write_task(
    task_dir: Path,
    *,
    task_id: str = "alpha",
    include_fixture: bool = True,
    include_kb: bool = True,
    include_kb_md: bool = True,
    include_evaluate: bool = True,
) -> None:
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
    if include_fixture:
        (task_dir / "fixture").mkdir()
        (task_dir / "fixture" / "app.py").write_text("print('hello')\n")
        (task_dir / "fixture" / "tests").mkdir()
        (task_dir / "fixture" / "tests" / "test_app.py").write_text("assert True\n")
    if include_kb:
        (task_dir / "kb").mkdir()
        (task_dir / "kb" / "notes.md").write_text("kb note\n")
    if include_kb_md:
        (task_dir / "kb.md").write_text("kb markdown\n")
    if include_evaluate:
        (task_dir / "evaluate").mkdir()
        (task_dir / "evaluate" / "secret.txt").write_text("do not copy\n")


def test_prepare_workspace_copies_only_visible_files(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tasks_root)

    run_paths = RepoPaths(tmp_path).run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths)

    assert workspace == workspace_dir(run_paths)
    assert (workspace / "app.py").read_text() == "print('hello')\n"
    assert (workspace / "tests" / "test_app.py").read_text() == "assert True\n"
    assert (workspace / "PRD.md").read_text() == "Product requirements.\n"
    assert (workspace / "Prompt.md").read_text() == "Do the thing.\n"
    assert (workspace / "kb" / "notes.md").read_text() == "kb note\n"
    assert (workspace / "kb.md").read_text() == "kb markdown\n"
    assert not (workspace / "notes.md").exists()
    assert not (workspace / "evaluate").exists()
    assert not any("evaluate" in source.parts for source, _ in visible_task_files(task))


def test_prepare_workspace_dry_run_does_not_create_workspace(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tasks_root)

    run_paths = RepoPaths(tmp_path).run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths, dry_run=True)

    assert workspace == workspace_dir(run_paths)
    assert not workspace.exists()


def test_prepare_workspace_preserves_kb_directory(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tasks_root)

    run_paths = RepoPaths(tmp_path).run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths)

    assert (workspace / "kb" / "notes.md").read_text() == "kb note\n"
    assert not (workspace / "notes.md").exists()


def test_prepare_workspace_rejects_symlinked_visible_roots(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "alpha"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        "task_id: alpha\n"
        "description: Sample task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 10\n"
        "evaluator: evaluate/run.sh\n"
    )
    (task_dir / "PRD.md").write_text("Product requirements.\n")
    (task_dir / "Prompt.md").write_text("Do the thing.\n")
    (task_dir / "evaluate").mkdir()
    hidden_source = task_dir / "evaluate"
    (hidden_source / "secret.txt").write_text("do not copy\n")

    for visible_name in ("fixture", "kb"):
        visible_root = task_dir / visible_name
        visible_root.symlink_to(hidden_source, target_is_directory=True)
        task = load_task(task_dir, tasks_root)
        run_paths = RepoPaths(tmp_path).run("20250101T010203", "alpha")

        with pytest.raises(WorkspaceError, match=r"missing (fixture|kb) directory"):
            prepare_workspace(task, run_paths)

        visible_root.unlink()


def test_prepare_workspace_rejects_missing_visible_source(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha"
    task_dir.mkdir(parents=True)
    (task_dir / "Prompt.md").write_text("Do the thing.\n")
    (task_dir / "kb.md").write_text("kb markdown\n")
    (task_dir / "evaluate").mkdir()
    task = TaskDefinition(
        task_id="alpha",
        description="",
        family="builder",
        batch="smoke",
        scoring_type="pass_fail",
        timeout_minutes=10,
        evaluator="evaluate/run.sh",
        split="dev",
        task_dir=task_dir,
        task_yaml_path=task_dir / "task.yaml",
        prd_path=task_dir / "PRD.md",
        prompt_path=task_dir / "Prompt.md",
        fixture_path=task_dir / "fixture",
        kb_dir_path=None,
        kb_md_path=task_dir / "kb.md",
        evaluate_path=task_dir / "evaluate",
    )
    run_paths = RepoPaths(tmp_path).run("20250101T010203", "alpha")

    with pytest.raises(WorkspaceError, match="missing fixture directory"):
        prepare_workspace(task, run_paths)


def test_cleanup_workspace_removes_only_run_workspace(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    run_paths = repo.run("20250101T010203", "alpha")
    workspace = workspace_dir(run_paths)
    workspace.mkdir(parents=True)
    (workspace / "app.py").write_text("print('hello')\n")
    run_paths.artifacts_dir.mkdir(parents=True)
    (run_paths.artifacts_dir / "keep.txt").write_text("keep\n")

    cleanup_workspace(run_paths)

    assert not workspace.exists()
    assert (run_paths.artifacts_dir / "keep.txt").exists()
