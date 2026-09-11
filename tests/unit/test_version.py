from __future__ import annotations

import subprocess

from bench import version


def test_display_version_prefers_environment_stamp(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_BENCH_VERSION", "v9.9.9-image")

    assert version.display_version() == "v9.9.9-image"


def test_display_version_uses_version_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ORCHESTRA_BENCH_VERSION", raising=False)
    monkeypatch.setattr(version, "_repo_root", lambda: tmp_path)
    (tmp_path / "VERSION").write_text("v8.8.8-file\n", encoding="utf-8")

    assert version.display_version() == "v8.8.8-file"


def test_display_version_uses_git_version_tag(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_BENCH_VERSION", raising=False)
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args[0], 0, stdout="v0.2.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert version.display_version() == "v0.2.0"


def test_display_version_uses_git_describe_distance(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_BENCH_VERSION", raising=False)
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args[0], 0, stdout="v0.2.0-3-gabc1234\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert version.display_version() == "v0.2.0-3-gabc1234"


def test_display_version_falls_back_to_unknown_on_git_failure(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_BENCH_VERSION", raising=False)
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args[0], 128, stdout="", stderr="fatal")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert version.display_version() == "0+unknown"


def test_display_version_falls_back_to_unknown_on_exception(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_BENCH_VERSION", raising=False)
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.SubprocessError("boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert version.display_version() == "0+unknown"


def test_product_title_includes_git_version(monkeypatch):
    monkeypatch.setattr(version, "display_version", lambda: "v0.2.0")

    assert version.product_title("dashboard") == "orchestra-bench v0.2.0 dashboard"
