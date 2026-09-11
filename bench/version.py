"""Version display helpers for operator-facing output."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_VERSION_ENV = "ORCHESTRA_BENCH_VERSION"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _stamped_version() -> str:
    env_value = os.environ.get(_VERSION_ENV, "").strip()
    if env_value:
        return env_value
    stamp = _repo_root() / "VERSION"
    if stamp.is_file():
        return stamp.read_text(encoding="utf-8").strip()
    return ""


def display_version() -> str:
    stamped = _stamped_version()
    if stamped:
        return stamped
    try:
        completed = subprocess.run(
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--abbrev=7"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return "0+unknown"
    if completed.returncode != 0:
        return "0+unknown"
    return completed.stdout.strip() or "0+unknown"


def product_title(view: str) -> str:
    return f"orchestra-bench {display_version()} {view}".strip()
