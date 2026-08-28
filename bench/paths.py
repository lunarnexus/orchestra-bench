"""Deterministic repository and run path helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_RUN_DIR_RE = re.compile(r"^(?P<run_id>\d{8}T\d{6})-(?P<task_id>[a-z0-9][a-z0-9_-]*)$")
_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def validate_task_id(task_id: str) -> str:
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"invalid task_id: {task_id!r}")
    return task_id


@dataclass(frozen=True)
class RepoPaths:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    def run(self, run_id: str, task_id: str) -> "RunPaths":
        return RunPaths(self.root, run_id, task_id)

    def list_runs(self) -> list["RunPaths"]:
        return list_runs(self.root)


@dataclass(frozen=True)
class RunPaths:
    root: Path
    run_id: str
    task_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        validate_task_id(self.task_id)

    @property
    def run_dir(self) -> Path:
        return self.root / "results" / f"{self.run_id}-{self.task_id}"

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / "artifacts"

    @property
    def pi_sessions_dir(self) -> Path:
        return self.artifacts_dir / "pi-sessions"

    @property
    def orchestra_debug_dir(self) -> Path:
        return self.artifacts_dir / "orchestra-debug"

    @property
    def pi_rpc_dir(self) -> Path:
        return self.artifacts_dir / "pi-rpc"

    @property
    def pi_rpc_events_path(self) -> Path:
        return self.pi_rpc_dir / "events.jsonl"

    @property
    def result_json(self) -> Path:
        return self.run_dir / "result.json"

    @property
    def bench_run_json(self) -> Path:
        return self.run_dir / ".bench_run.json"

    @property
    def manifest_path(self) -> Path:
        return self.artifacts_dir / "manifest.json"

    @property
    def container_workdir(self) -> str:
        return f"/workspace/{self.run_id}-{self.task_id}"


def list_runs(root: Path | str) -> list[RunPaths]:
    root = Path(root)
    results_dir = root / "results"
    if not results_dir.is_dir():
        return []

    runs: list[RunPaths] = []
    for entry in sorted(results_dir.iterdir(), reverse=True):
        match = _RUN_DIR_RE.match(entry.name)
        if entry.is_dir() and match:
            runs.append(RunPaths(root, match.group("run_id"), validate_task_id(match.group("task_id"))))
    return runs
