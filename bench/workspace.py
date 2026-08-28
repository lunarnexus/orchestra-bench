"""Workspace preparation helpers for task runs."""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import RunPaths
from .tasks import TaskDefinition


class WorkspaceError(ValueError):
    """Raised when a task workspace cannot be prepared."""


def workspace_dir(run_paths: RunPaths) -> Path:
    return run_paths.run_dir / "workspace"


def _require_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise WorkspaceError(f"missing {label}: {path}")
    return path


def _require_dir(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise WorkspaceError(f"missing {label}: {path}")
    return path


def _plan_tree_files(source_dir: Path, target_root: Path) -> list[tuple[Path, Path]]:
    planned: list[tuple[Path, Path]] = []
    for entry in sorted(source_dir.iterdir(), key=lambda path: path.name):
        if entry.is_symlink():
            raise WorkspaceError(f"refusing to copy symlinked source: {entry}")
        if entry.is_dir():
            planned.extend(_plan_tree_files(entry, target_root / entry.name))
            continue
        planned.append((entry, target_root / entry.name))
    return planned


def visible_task_files(task: TaskDefinition) -> tuple[tuple[Path, Path], ...]:
    files: list[tuple[Path, Path]] = []

    if task.fixture_path is not None:
        files.extend(_plan_tree_files(_require_dir(task.fixture_path, "fixture directory"), Path()))
    files.append((_require_file(task.prd_path, "PRD.md"), Path("PRD.md")))
    files.append((_require_file(task.prompt_path, "Prompt.md"), Path("Prompt.md")))
    if task.kb_dir_path is not None:
        files.extend(_plan_tree_files(_require_dir(task.kb_dir_path, "kb directory"), Path("kb")))
    if task.kb_md_path is not None:
        files.append((_require_file(task.kb_md_path, "kb.md"), Path("kb.md")))

    return tuple(files)


def prepare_workspace(task: TaskDefinition, run_paths: RunPaths, *, dry_run: bool = False) -> Path:
    workspace = workspace_dir(run_paths)
    files = visible_task_files(task)

    if dry_run:
        return workspace

    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)

    for source, rel_target in files:
        target = workspace / rel_target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    return workspace


def cleanup_workspace(run_paths: RunPaths) -> None:
    shutil.rmtree(workspace_dir(run_paths), ignore_errors=True)
