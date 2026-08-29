from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_script(script: str, *args: str, cwd: Path, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}".rstrip(":")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(REPO_ROOT / script), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_shell_wrappers_dispatch_owned_subcommands(tmp_path: Path) -> None:
    wrappers = {
        "scripts/01-start": "python3 -m bench.cli start \"$@\"",
        "scripts/02-run": "python3 -m bench.cli run \"$@\"",
        "scripts/03-results": "python3 -m bench.cli results \"$@\"",
    }
    run_script = (REPO_ROOT / "scripts" / "02-run").read_text(encoding="utf-8")
    assert run_script.strip().endswith("exec python3 -m bench.cli run \"$@\"")
    for script, expected in wrappers.items():
        assert expected in (REPO_ROOT / script).read_text(encoding="utf-8")

    start = _run_script("scripts/01-start", "--help", cwd=tmp_path)
    assert start.returncode == 0, start.stderr
    assert start.stdout.startswith("usage:")

    run = _run_script("scripts/02-run", "--help", cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("usage:")

    results = _run_script("scripts/03-results", "--help", cwd=tmp_path)
    assert results.returncode == 0, results.stderr
    assert results.stdout.splitlines()[0] == "usage: scripts/03-results [dashboard|runs|run|tokens|timing|debug|compare|rescore|delete]"
    assert "bench results" not in results.stdout
    assert "--root" not in results.stdout
    assert "--tasks-root" not in results.stdout
    assert "delete-preview" in results.stdout
    assert "delete-confirmation" in results.stdout


def test_run_wrapper_rejects_host_side_non_auto_runs(tmp_path: Path) -> None:
    result = _run_script("scripts/02-run", "alpha-run", cwd=tmp_path)
    assert result.returncode == 1
    assert "require --auto" in result.stderr


def test_run_wrapper_ignores_later_harness_tokens_in_auto_run(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "python3-argv.txt"
    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$PYTHON3_ARGV_LOG\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = _run_script(
        "scripts/02-run",
        "--auto",
        "alpha-run",
        "--notes",
        "pi",
        cwd=tmp_path,
        env_overrides={"PATH": f"{bin_dir}:{os.environ['PATH']}", "PYTHON3_ARGV_LOG": str(argv_log)},
    )

    assert result.returncode == 0, result.stderr
    assert argv_log.read_text(encoding="utf-8").splitlines() == ["-m", "bench.cli", "run", "--auto", "alpha-run", "--notes", "pi"]


def test_start_wrapper_rejects_transitional_actions(tmp_path: Path) -> None:
    result = _run_script("scripts/01-start", "start", cwd=tmp_path)
    assert result.returncode == 2
    assert "unrecognized arguments: start" in result.stderr


def test_start_wrapper_no_args_defaults_to_start_without_argparse_usage(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "python3-argv.txt"
    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$PYTHON3_ARGV_LOG\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PYTHON3_ARGV_LOG"] = str(argv_log)

    result = subprocess.run(
        ["./01-start"],
        cwd=REPO_ROOT / "scripts",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert argv_log.read_text(encoding="utf-8").splitlines() == ["-m", "bench.cli", "start"]


def test_start_wrapper_help_is_public_and_concise(tmp_path: Path) -> None:
    result = _run_script("scripts/01-start", "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "usage: 01-start",
        "",
        "Set up the benchmark container (build, recreate, configure).",
        "",
        "Examples:",
        "  scripts/01-start",
        "  ./01-start",
    ]
    assert "bench start" not in result.stdout
    assert "--root" not in result.stdout


def test_public_wrappers_work_when_invoked_from_scripts_directory() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    for script in ("02-run", "03-results"):
        result = subprocess.run(
            [f"./{script}", "--help"],
            cwd=REPO_ROOT / "scripts",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{script} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        if script == "02-run":
            assert result.stdout.startswith("usage: scripts/02-run"), result.stdout
            assert "bench run" not in result.stdout
            assert "--root" not in result.stdout
        else:
            assert result.stdout.startswith("usage: scripts/03-results"), result.stdout



