"""Run-tree ownership normalization helpers."""

from __future__ import annotations

import os
from pathlib import Path

CONTAINER_CONTEXT_ENV = "BENCH_IN_CONTAINER"
HOST_UID_ENV = "BENCH_HOST_UID"
HOST_GID_ENV = "BENCH_HOST_GID"


def host_ownership_env() -> dict[str, str]:
    if os.environ.get(CONTAINER_CONTEXT_ENV) in {"1", "true", "yes"}:
        return {}
    if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        return {}
    return {
        HOST_UID_ENV: str(os.getuid()),
        HOST_GID_ENV: str(os.getgid()),
    }


def normalize_run_ownership(root: Path | str) -> None:
    if os.environ.get(CONTAINER_CONTEXT_ENV) not in {"1", "true", "yes"}:
        return

    uid = os.environ.get(HOST_UID_ENV)
    gid = os.environ.get(HOST_GID_ENV)
    if uid is None or gid is None:
        return

    run_root = Path(root)
    if not run_root.exists():
        return

    uid_int = int(uid)
    gid_int = int(gid)

    def _chown(path: Path) -> None:
        os.chown(path, uid_int, gid_int, follow_symlinks=False)

    _chown(run_root)
    for current, _dirnames, filenames in os.walk(run_root, topdown=False, followlinks=False):
        current_path = Path(current)
        if current_path != run_root:
            _chown(current_path)
        for filename in filenames:
            _chown(current_path / filename)
