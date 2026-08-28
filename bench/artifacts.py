"""Artifact path and manifest helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import RunPaths


@dataclass(frozen=True)
class EvaluatorArtifactPaths:
    root: Path
    stdout_path: Path
    stderr_path: Path
    log_path: Path
    result_json_path: Path
    manifest_path: Path

    @classmethod
    def for_run_paths(cls, run_paths: RunPaths) -> "EvaluatorArtifactPaths":
        root = run_paths.artifacts_dir / "evaluator"
        return cls(
            root=root,
            stdout_path=root / "stdout.txt",
            stderr_path=root / "stderr.txt",
            log_path=root / "log.txt",
            result_json_path=root / "result.json",
            manifest_path=run_paths.manifest_path,
        )

    def ensure(self) -> "EvaluatorArtifactPaths":
        self.root.mkdir(parents=True, exist_ok=True)
        return self


def write_json_manifest(path: Path | str, payload: Mapping[str, Any]) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def load_json_manifest(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
