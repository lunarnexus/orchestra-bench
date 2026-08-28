"""Run path helpers shared by harness scripts and tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunDirectory:
    """Paths for one benchmark run under results/<run_id>-<task_id>."""

    root: Path
    run_id: str
    task_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def path(self) -> Path:
        return self.root / "results" / f"{self.run_id}-{self.task_id}"

    @property
    def artifacts_dir(self) -> Path:
        return self.path / "artifacts"

    @property
    def pi_sessions_dir(self) -> Path:
        return self.artifacts_dir / "pi-sessions"

    @property
    def orchestra_debug_dir(self) -> Path:
        return self.artifacts_dir / "orchestra-debug"

    @property
    def rpc_events_path(self) -> Path:
        return self.path / "artifacts" / "pi-rpc" / "events.jsonl"

    @property
    def result_json(self) -> Path:
        return self.path / "result.json"

    @property
    def bench_run_json(self) -> Path:
        return self.path / ".bench_run.json"

    @property
    def manifest_path(self) -> Path:
        return self.artifacts_dir / "manifest.json"

    @property
    def container_workdir(self) -> str:
        return f"/workspace/{self.run_id}-{self.task_id}"


# Run ids are timestamps (YYYYMMDDTHHMMSS), which keeps this unambiguous.
_RUN_DIR_RE = re.compile(
    r"^(?P<run_id>\d{8}T\d{6})-(?P<task_id>[a-z0-9][a-z0-9_-]*)$"
)


def list_runs(root: Path | str) -> list[RunDirectory]:
    """Return existing run directories, newest first (run ids are timestamps)."""
    root = Path(root)
    results_dir = root / "results"
    if not results_dir.is_dir():
        return []
    runs: list[RunDirectory] = []
    for entry in sorted(results_dir.iterdir(), reverse=True):
        match = _RUN_DIR_RE.match(entry.name)
        if entry.is_dir() and match:
            runs.append(RunDirectory(root, match.group("run_id"), match.group("task_id")))
    return runs
