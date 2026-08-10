"""orchestra-bench — lightweight SaaSBench-style benchmark harness."""

from __future__ import annotations

import json as _json
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ── Paths (relative to repo root) ────────────────────────────────────
TASKS_DIR = "tasks"
RESULTS_DIR = "results"
ARTIFACTS_DIR = "artifacts"

CONTAINER_NAME = "orchestra-bench-runner"


# ── Shared result schema ─────────────────────────────────────────────

@dataclass
class TaskResult:
    """Standardized benchmark result for a single task run."""

    # Identity
    task_id: str
    run_id: str

    # Score — "pass", "fail", or numeric string like "0.75"
    score: str = ""

    # Per-check breakdown (evaluator writes this)
    checks: dict[str, object] = field(default_factory=dict)

    # Workdir used inside the container
    workdir: str = ""

    # Task metadata snapshot (from task.yaml)
    task_meta: dict[str, object] = field(default_factory=dict)

    # Run metadata — model, orchestration config, etc.
    run_meta: dict[str, object] = field(default_factory=dict)

    # Token usage summary (ingested from artifacts if available)
    tokens: dict[str, object] = field(default_factory=dict)

    # Elapsed time in seconds for this task run
    elapsed_seconds: float | None = None

    # Roles used during execution (e.g. ["builder", "reviewer"])
    roles_used: list[str] = field(default_factory=list)

    # Dev vs holdout split label for comparison reporting
    split: str = ""

    # Free-form notes from evaluator or harness
    details: str = ""

    def is_pass(self) -> bool:
        return self.score == "pass"

    def to_dict(self) -> dict:
        return asdict(self)

    def write_json(self, path: Path | None = None) -> Path:
        """Write result.json into results/<run_id>-<task_id>/ and return the file."""
        if path is not None:
            out_dir = path
        else:
            out_dir = (Path(RESULTS_DIR) / f"{self.run_id}-{self.task_id}").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / "result.json"
        dest.write_text(_json.dumps(self.to_dict(), indent=2) + "\n")
        return dest

    @classmethod
    def from_json(cls, path: Path | str) -> TaskResult:
        data = _json.loads(Path(path).read_text())
        if "task_id" not in data:
            raise ValueError(f"result missing task_id: {path}")
        return cls(**data)


# ── Task metadata schema (loaded from task.yaml) ─────────────────────

@dataclass
class TaskMeta:
    """Metadata loaded from a task's task.yaml."""

    task_id: str
    description: str = ""
    family: str = "default"
    batch: str = ""
    scoring_type: str = "pass_fail"  # pass_fail | numeric
    timeout_minutes: int = 10
    evaluator: str = "evaluate/run.sh"
    split: str = "dev"  # dev (for iteration) or holdout (for final comparison)
