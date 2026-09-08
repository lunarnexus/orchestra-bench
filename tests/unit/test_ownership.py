from __future__ import annotations

import os
from pathlib import Path

from bench.ownership import HOST_GID_ENV, HOST_UID_ENV, normalize_run_ownership


def test_normalize_run_ownership_recurses_through_run_tree(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "results" / "20250101T010203-alpha-run"
    nested = run_dir / "artifacts" / "pi-sessions"
    nested.mkdir(parents=True)
    (nested / "session.jsonl").write_text("{}\n", encoding="utf-8")

    calls: list[tuple[Path, int, int, bool]] = []
    chmods: list[tuple[Path, int]] = []

    def fake_chown(path, uid, gid, *, follow_symlinks=True):  # type: ignore[no-untyped-def]
        calls.append((Path(path), uid, gid, follow_symlinks))

    def fake_chmod(path, mode):  # type: ignore[no-untyped-def]
        chmods.append((Path(path), mode))

    monkeypatch.setenv("BENCH_IN_CONTAINER", "1")
    monkeypatch.setenv(HOST_UID_ENV, "1234")
    monkeypatch.setenv(HOST_GID_ENV, "4321")
    monkeypatch.setattr(os, "chown", fake_chown)
    monkeypatch.setattr(os, "chmod", fake_chmod)

    normalize_run_ownership(run_dir)

    assert calls[0] == (run_dir, 1234, 4321, False)
    assert (nested, 1234, 4321, False) in calls
    assert (nested / "session.jsonl", 1234, 4321, False) in calls
    assert (run_dir, 0o755) in chmods
    assert (nested, 0o755) in chmods
    assert (nested / "session.jsonl", 0o644) in chmods
