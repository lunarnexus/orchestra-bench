"""Task discovery and loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml

from .paths import validate_task_id

_REPO_ROOT = Path(__file__).resolve().parent.parent


class TaskLoadError(ValueError):
    """Raised when a task directory or task.yaml is invalid."""


@dataclass(frozen=True)
class TaskMeta:
    task_id: str
    description: str = ""
    family: str = "default"
    batch: str = ""
    scoring_type: str = "pass_fail"
    timeout_minutes: int = 10
    evaluator: str = "evaluate/run.sh"
    split: str = "dev"


@dataclass(frozen=True)
class TaskDefinition(TaskMeta):
    task_dir: Path = Path()
    task_yaml_path: Path = Path()
    prd_path: Path = Path()
    prompt_path: Path = Path()
    fixture_path: Path | None = None
    kb_dir_path: Path | None = None
    kb_md_path: Path | None = None
    evaluate_path: Path = Path()

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_dir", Path(self.task_dir))
        object.__setattr__(self, "task_yaml_path", Path(self.task_yaml_path))
        object.__setattr__(self, "prd_path", Path(self.prd_path))
        object.__setattr__(self, "prompt_path", Path(self.prompt_path))
        object.__setattr__(self, "fixture_path", Path(self.fixture_path) if self.fixture_path is not None else None)
        object.__setattr__(self, "kb_dir_path", Path(self.kb_dir_path) if self.kb_dir_path is not None else None)
        object.__setattr__(self, "kb_md_path", Path(self.kb_md_path) if self.kb_md_path is not None else None)
        object.__setattr__(self, "evaluate_path", Path(self.evaluate_path))


def _default_tasks_root() -> Path:
    env = os.environ.get("BENCH_TASKS")
    if env:
        return Path(env).expanduser()
    v1_tasks = _REPO_ROOT / "V1" / "tasks"
    if v1_tasks.is_dir():
        return v1_tasks
    return _REPO_ROOT / "tasks"


def _resolve_tasks_root(tasks_root: Path | str | None) -> Path:
    if tasks_root is None:
        return _default_tasks_root()
    return Path(tasks_root).expanduser()


def discover_tasks(tasks_root: Path | str | None = None) -> list[Path]:
    base = _resolve_tasks_root(tasks_root)
    if not base.is_dir():
        return []
    return [entry for entry in sorted(base.iterdir()) if entry.is_dir() and (entry / "task.yaml").is_file()]


def _task_dir_for(task_path: Path | str, tasks_root: Path | str | None = None) -> Path:
    candidate = Path(task_path)
    if candidate.is_dir() and (candidate / "task.yaml").is_file():
        return candidate
    if candidate.is_file() and candidate.name == "task.yaml":
        return candidate.parent

    base = _resolve_tasks_root(tasks_root)
    resolved = base / candidate.name
    if resolved.is_dir() and (resolved / "task.yaml").is_file():
        return resolved
    return candidate


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise TaskLoadError(f"malformed task.yaml at {path}: {exc}") from exc
    except FileNotFoundError as exc:
        raise TaskLoadError(f"task.yaml not found: {path}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TaskLoadError(f"task.yaml must contain a mapping: {path}")
    return data


def _require_text(data: dict[str, Any], key: str, path: Path, default: str | None = None) -> str:
    value = data.get(key, default)
    if value is None:
        raise TaskLoadError(f"task.yaml missing required field {key!r}: {path}")
    if not isinstance(value, str):
        raise TaskLoadError(f"task.yaml field {key!r} must be a string: {path}")
    value = value.strip()
    if not value and default is None:
        raise TaskLoadError(f"task.yaml field {key!r} must not be empty: {path}")
    return value if value else (default or "")


def _require_int(data: dict[str, Any], key: str, path: Path, default: int) -> int:
    value = data.get(key, default)
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise TaskLoadError(f"task.yaml field {key!r} must be an integer: {path}") from exc
    if timeout <= 0:
        raise TaskLoadError(f"task.yaml field {key!r} must be positive: {path}")
    return timeout


def load_task(task_path: Path | str, tasks_root: Path | str | None = None) -> TaskDefinition:
    task_dir = _task_dir_for(task_path, tasks_root)
    task_yaml_path = task_dir / "task.yaml"
    if not task_yaml_path.is_file():
        raise TaskLoadError(f"task.yaml not found: {task_yaml_path}")

    data = _load_yaml(task_yaml_path)
    task_id = _require_text(data, "task_id", task_yaml_path)
    try:
        task_id = validate_task_id(task_id)
    except ValueError as exc:
        raise TaskLoadError(f"invalid task_id: {task_yaml_path}: {exc}") from exc
    description = _require_text(data, "description", task_yaml_path, default="")
    family = _require_text(data, "family", task_yaml_path, default="default")
    batch = _require_text(data, "batch", task_yaml_path, default="")
    scoring_type = _require_text(data, "scoring_type", task_yaml_path, default="pass_fail")
    timeout_minutes = _require_int(data, "timeout_minutes", task_yaml_path, default=10)
    evaluator = _require_text(data, "evaluator", task_yaml_path, default="evaluate/run.sh")
    split = _require_text(data, "split", task_yaml_path, default="dev")

    prd_path = task_dir / "PRD.md"
    prompt_path = task_dir / "Prompt.md"
    fixture_path = task_dir / "fixture" if (task_dir / "fixture").exists() else None
    kb_dir_path = task_dir / "kb" if (task_dir / "kb").is_dir() else None
    kb_md_path = task_dir / "kb.md" if (task_dir / "kb.md").is_file() else None
    evaluate_path = task_dir / "evaluate"

    if not prd_path.is_file():
        raise TaskLoadError(f"missing PRD.md: {prd_path}")
    if not prompt_path.is_file():
        raise TaskLoadError(f"missing Prompt.md: {prompt_path}")
    if fixture_path is not None and not fixture_path.exists():
        fixture_path = None
    if not evaluate_path.is_dir():
        raise TaskLoadError(f"missing evaluate directory: {evaluate_path}")

    return TaskDefinition(
        task_id=task_id,
        description=description,
        family=family,
        batch=batch,
        scoring_type=scoring_type,
        timeout_minutes=timeout_minutes,
        evaluator=evaluator,
        split=split,
        task_dir=task_dir,
        task_yaml_path=task_yaml_path,
        prd_path=prd_path,
        prompt_path=prompt_path,
        fixture_path=fixture_path,
        kb_dir_path=kb_dir_path,
        kb_md_path=kb_md_path,
        evaluate_path=evaluate_path,
    )


_SUITE_ORDER = ["smoke", "role-focused", "capability-easy", "capability-normal", "capability-advanced"]


def list_suites(tasks_root: Path | str | None = None) -> list[str]:
    tasks = [load_task(task_dir, tasks_root) for task_dir in discover_tasks(tasks_root)]
    suites: list[str] = []
    seen: set[str] = set()

    for preferred in _SUITE_ORDER:
        for task in tasks:
            if task.batch == preferred and task.batch not in seen:
                seen.add(task.batch)
                suites.append(task.batch)

    for task in tasks:
        if task.batch and task.batch not in seen:
            seen.add(task.batch)
            suites.append(task.batch)

    return suites


def list_tasks(tasks_root: Path | str | None = None) -> list[TaskDefinition]:
    return [load_task(task_dir, tasks_root) for task_dir in discover_tasks(tasks_root)]


__all__ = [
    "TaskLoadError",
    "TaskMeta",
    "TaskDefinition",
    "discover_tasks",
    "load_task",
    "list_suites",
    "list_tasks",
]
