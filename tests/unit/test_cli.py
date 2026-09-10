from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import bench.cli as bench_cli
from bench.cli import build_parser, main
from bench.orchestration import OrchestrationSettleResult
from bench.paths import RunPaths
from bench.reporting.queries import ReportEntry
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.tasks import TaskLoadError, load_task
from bench.workspace import workspace_dir


def _write_task(task_dir: Path, *, task_id: str = "alpha-run", family: str = "builder", batch: str | None = "smoke", description: str = "Sample task") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    task_yaml = [
        f"task_id: {task_id}",
        f"description: {description}",
        f"family: {family}",
        "scoring_type: pass_fail",
        "timeout_minutes: 10",
        "evaluator: evaluate/run.sh",
    ]
    if batch is not None:
        task_yaml.insert(3, f"batch: {batch}")
    (task_dir / "task.yaml").write_text("\n".join(task_yaml) + "\n", encoding="utf-8")
    (task_dir / "PRD.md").write_text("Product requirements.\n", encoding="utf-8")
    (task_dir / "Prompt.md").write_text("Do the thing.\n", encoding="utf-8")
    (task_dir / "fixture").mkdir()
    (task_dir / "evaluate").mkdir()
    (task_dir / "evaluate" / "run.sh").write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"status\":\"ok\",\"score\":\"pass\",\"checks\":{\"done\":true}}'\n",
        encoding="utf-8",
    )


def _write_catalog(catalog_path: Path) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  fake:\n"
        "    harness: command\n"
        "    command:\n"
        "    - python3\n"
        "    - -c\n"
        "    - \"print('harness ok')\"\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: fake\n"
        "    model: fake-model\n"
        "    agent: fake-agent\n"
        "    profile: default\n",
        encoding="utf-8",
    )


def _write_result(
    results_root: Path,
    run_id: str,
    task_id: str,
    *,
    batch: str = "smoke",
    model: str = "",
    orchestra: bool | None = None,
    notes: str = "",
    role: str = "builder",
    harness: str = "pi",
    backend: str = "pi",
    total_tokens: int | None = None,
    elapsed_seconds: float | None = None,
) -> Path:
    path = results_root / f"{run_id}-{task_id}" / "result.json"
    write_json_atomic(
        path,
        TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch=batch, started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={
                "provenance": {"model": model, "orchestra": orchestra, "harness": harness, "backend": backend, "notes": notes, "role": role},
                "tokens": {"total": total_tokens} if total_tokens is not None else {},
                "timing": {"elapsed_seconds": elapsed_seconds} if elapsed_seconds is not None else {},
                "notes": notes,
            },
        ),
    )
    return path


def test_help_lists_public_commands(capsys) -> None:
    assert main(["help"]) == 0
    output = capsys.readouterr().out
    first_line = output.splitlines()[0]
    assert "{help,start,run,results,04-debug,doctor}" in first_line
    assert "runtime" not in first_line
    assert "grade" not in first_line
    assert "suite" not in first_line


def test_results_help_is_public_and_concise(capsys) -> None:
    assert main(["results", "--help"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines()[0] == "usage: scripts/03-results [command] [run-id]"
    assert "Show benchmark results. Bare scripts/03-results prints the dashboard and recent runs." in output
    assert "bench results" not in output
    assert "--root" not in output
    assert "--tasks-root" not in output
    assert "other commands: tokens, timing, compare, rescore, delete" in output
    assert "scripts/04-debug <run-id> orch|full|raw" in output
    # After root wrappers were removed, every shell reference must use the scripts/ path.
    for token in ("03-results", "04-debug"):
        lines = [line for line in output.splitlines() if token in line]
        assert lines
        assert all(f"scripts/{token}" in line for line in lines)
    assert "[--no-tools]" not in output
    assert "[--no-color]" not in output
    assert "[--plain]" not in output
    assert "03-results debug" not in output


def test_public_debug_routes_session_views_and_raw_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    run_id = "20250101T010101"
    task_id = "alpha-run"
    run_dir = tmp_path / "results" / f"{run_id}-{task_id}"
    session_dir = run_dir / "artifacts" / "pi-sessions"
    session_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text('{"run_id":"20250101T010101","task_id":"alpha-run","score":"pass"}\n', encoding="utf-8")
    (session_dir / "2025-01-01T01-01-01_main.jsonl").write_text(
        json.dumps({"type": "session", "id": "main-session", "cwd": "/workspace/run"}) + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, object]] = []

    def fail_select_results(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("select_results should not be used for public debug")

    def fake_format_session_debug(session_dir, *, view="orch", no_tools=False, plain=False, no_color=False, isatty=None):  # type: ignore[no-untyped-def]
        calls.append(("debug", session_dir, {"view": view, "no_tools": no_tools, "plain": plain, "no_color": no_color, "isatty": isatty}))
        return f"{view} view\n"

    def fake_format_session_raw(session_dir):  # type: ignore[no-untyped-def]
        calls.append(("raw", session_dir))
        return "raw view\n"

    monkeypatch.setattr("bench.cli.select_results", fail_select_results, raising=False)
    monkeypatch.setattr("bench.cli.format_session_debug", fake_format_session_debug, raising=False)
    monkeypatch.setattr("bench.cli.format_session_raw", fake_format_session_raw, raising=False)

    run_ref = run_id[:12]
    assert main(["04-debug", run_ref, "orch", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "orch view\n"
    assert main(["04-debug", run_ref, "full", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "full view\n"
    assert main(["04-debug", run_ref, "raw", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "raw view\n"

    for flag in ("--no-tools", "--no-color", "--plain"):
        with pytest.raises(SystemExit) as excinfo:
            main(["04-debug", run_ref, "orch", flag])
        assert excinfo.value.code == 2

    assert calls[0] == ("debug", session_dir, {"view": "orch", "no_tools": False, "plain": False, "no_color": False, "isatty": None})
    assert calls[1] == ("debug", session_dir, {"view": "full", "no_tools": False, "plain": False, "no_color": False, "isatty": None})
    assert calls[2] == ("raw", session_dir)


def test_public_debug_falls_back_to_harness_artifacts_when_pi_sessions_are_missing(tmp_path: Path, capsys) -> None:
    run_id = "20260902T225856"
    task_id = "smoke-dependent-setup-chain"
    run_dir = tmp_path / "results" / f"{run_id}-{task_id}"
    harness_dir = run_dir / "artifacts" / "harness"
    harness_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text('{"run_id":"20260902T225856","task_id":"smoke-dependent-setup-chain","score":"pass"}\n', encoding="utf-8")
    (harness_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "id": "harness-session", "cwd": "/workspace/run"}),
                json.dumps({"type": "custom", "customType": "orchestra-command", "data": {"text": "enable orchestra tools"}}),
                json.dumps({"type": "custom", "customType": "orch_dispatch", "data": {"text": "dispatch builder"}}),
                json.dumps({"type": "custom", "customType": "orch_status", "data": {"text": "children active"}}),
                json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Read PRD.md"}]}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (harness_dir / "transcript.txt").write_text(
        "prompt: enable orchestra tools\n"
        "prompt: # Run Prompt\n"
        "Read `PRD.md`, inspect the fixture, implement the requested behavior, and leave the workspace in a runnable state.\n",
        encoding="utf-8",
    )

    run_ref = run_id[:12]
    assert main(["04-debug", run_ref, "orch", "--root", str(tmp_path)]) == 0
    orch = capsys.readouterr().out
    assert "no session transcripts found" not in orch
    assert "enable orchestra tools" in orch
    assert "orch_dispatch" in orch
    assert "orch_status" in orch

    assert main(["04-debug", run_ref, "full", "--root", str(tmp_path)]) == 0
    full = capsys.readouterr().out
    assert "no session transcripts found" not in full
    assert "Prompt" in full
    assert "Read `PRD.md`" in full

    assert main(["04-debug", run_ref, "raw", "--root", str(tmp_path)]) == 0
    raw = capsys.readouterr().out
    assert f"path: {harness_dir / 'events.jsonl'}" in raw
    assert f"path: {harness_dir / 'transcript.txt'}" in raw
    assert '"customType": "orch_dispatch"' in raw
    assert "prompt: enable orchestra tools" in raw


def test_public_debug_reports_missing_and_ambiguous_run_refs(tmp_path: Path, capsys) -> None:
    assert main(["04-debug", "20250101T010101", "--root", str(tmp_path)]) == 1
    assert "error: run not found: 20250101T010101" in capsys.readouterr().err

    results_root = tmp_path / "results"
    (results_root / "20250101T010101-alpha-run").mkdir(parents=True)
    (results_root / "20250101T010101-beta-run").mkdir(parents=True)

    assert main(["04-debug", "20250101T010101", "--root", str(tmp_path)]) == 1
    assert "error: run reference is ambiguous: 20250101T010101" in capsys.readouterr().err


def test_results_dash_is_default_and_supports_common_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run", description="Alpha")
    _write_task(task_root / "beta-run", task_id="beta-run", description="Beta")
    results_root = tmp_path / "results"
    _write_result(results_root, "20250101T010101", "alpha-run", model="model-a", orchestra=True, notes="ready to go", role="builder", total_tokens=120, elapsed_seconds=12.5)
    _write_result(results_root, "20250101T010102", "beta-run", model="model-b", orchestra=False, notes="secondary run", role="reviewer", total_tokens=240, elapsed_seconds=24.0)
    monkeypatch.chdir(tmp_path)

    assert main(["results", "--root", str(results_root), "--tasks-root", str(task_root)]) == 0
    output = capsys.readouterr().out
    assert "=== orchestra-bench " in output
    assert " dashboard ===" in output
    assert "runs       : 2" in output

    assert main(["results", "dash", "--root", str(results_root), "--tasks-root", str(task_root), "--suite", "SMOKE", "--model", "MODEL-A", "--result", "PASS", "--orchestra", "yes", "--filter", "backend:PI,notes:READY", "--role", "Buil"]) == 0
    filtered = capsys.readouterr().out
    assert "runs       : 1" in filtered
    assert "passed     : 1" in filtered
    assert "beta-run" not in filtered


def test_run_help_shows_public_wrapper_modes_and_examples(capsys) -> None:
    assert main(["run", "--help"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines()[0] == "usage:"
    assert "02-run <pi|hermes|opencode> [task-id|args...]" in output
    assert "02-run --auto [pi|hermes|opencode] <task-or-suite|all> [--verbose]" in output
    assert "02-run --list         list suites with their tasks" in output
    assert "02-run --list-suites" not in output
    assert "If the first argument after pi/hermes/opencode is a known task id, 02-run opens that task session and prints Prompt.md first." in output
    assert "Automatic runs default to the catalog role/harness; 02-run --auto smoke keeps that default, while 02-run --auto pi smoke selects Pi explicitly." in output
    assert "Orchestra tools are available by default." in output
    assert "  --no-orchestra          disable Orchestra tools for this run (only opt-out)" in output
    assert "02-run pi smoke-dependent-setup-chain" in output
    assert "02-run pi config" in output
    assert "02-run hermes --version" in output
    assert "02-run --auto smoke-dependent-setup-chain" in output
    assert "02-run --auto pi smoke-dependent-setup-chain" in output
    assert "02-run --auto hermes smoke" in output
    assert "02-run --auto opencode smoke" in output
    assert "02-run --auto smoke" in output
    assert "02-run --auto all" in output
    assert "02-run --auto smoke --verbose" in output
    assert "02-run --verbose" not in output
    assert "./scripts/" not in output
    for needle in ["bench run", "--root", "--tasks-root", "--run-id", "--role", "--catalog-label"]:
        assert needle not in output


def test_list_shows_repo_tasks_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo_root = tmp_path / "repo"
    task_root = repo_root / "tasks" / "smoke-dependent-setup-chain"
    legacy_task = repo_root / "V1" / "tasks" / "legacy-task"
    task_root.mkdir(parents=True)
    legacy_task.mkdir(parents=True)
    (task_root / "task.yaml").write_text(
        "task_id: smoke-dependent-setup-chain\n"
        "description: Smoke task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 7\n"
        "evaluator: evaluate/run.sh\n",
        encoding="utf-8",
    )
    (task_root / "PRD.md").write_text("prd\n", encoding="utf-8")
    (task_root / "Prompt.md").write_text("prompt\n", encoding="utf-8")
    (task_root / "evaluate").mkdir()
    (legacy_task / "task.yaml").write_text(
        "task_id: legacy-task\n"
        "description: Legacy task\n"
        "family: builder\n"
        "batch: role-focused\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 8\n"
        "evaluator: evaluate/run.sh\n",
        encoding="utf-8",
    )
    (legacy_task / "PRD.md").write_text("prd\n", encoding="utf-8")
    (legacy_task / "Prompt.md").write_text("prompt\n", encoding="utf-8")
    (legacy_task / "evaluate").mkdir()
    monkeypatch.setattr("bench.tasks._REPO_ROOT", repo_root)

    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "smoke-dependent-setup-chain" in output
    assert "legacy-task" not in output


def test_run_list_and_suite_listing_discover_tasks_without_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run", description="Alpha")
    _write_task(task_root / "beta-run", task_id="beta-run", description="Beta")
    _write_task(task_root / "gamma-run", task_id="gamma-run", family="reviewer", batch="role-focused", description="Gamma")
    _write_task(task_root / "delta-run", task_id="delta-run", family="appsec", batch=None, description="Delta")
    monkeypatch.chdir(tmp_path)

    assert main(["run", "--list", "--tasks-root", str(task_root)]) == 0
    output = capsys.readouterr().out.splitlines()
    assert output == [
        "[smoke]",
        "  alpha-run                          (smoke/builder)",
        "      Alpha",
        "  beta-run                           (smoke/builder)",
        "      Beta",
        "",
        "[role-focused]",
        "  gamma-run                          (role-focused/reviewer)",
        "      Gamma",
        "",
        "[unbatched]",
        "  delta-run                          (unbatched/appsec)",
        "      Delta",
    ]

    assert main(["run", "--list-suites", "--tasks-root", str(task_root)]) == 1
    assert "unknown option: --list-suites" in capsys.readouterr().err


def test_run_and_grade_fake_task(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr(RunPaths, "container_workdir", property(lambda self: str(self.run_dir / "workspace")))

    run_id = "20250101T010203"
    assert (
        main(
            [
                "run",
                "alpha-run",
                "--tasks-root",
                str(task_root),
                "--root",
                str(tmp_path),
                "--catalog",
                str(catalog_path),
                "--run-id",
                run_id,
            ]
        )
        == 0
    )
    run_output = json.loads(capsys.readouterr().out)
    assert run_output["run_meta"]["run_id"] == run_id
    assert run_output["evaluation"]["score"] == "pass"
    result_path = tmp_path / "results" / f"{run_id}-alpha-run" / "result.json"
    assert load_result(result_path).outcome == "pass"


def test_run_public_harness_passthrough_routes_through_container_exec(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = "pi config output\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["run", "pi", "config"]) == 0
    assert [call["command"] for call in calls] == [list(SYNC_COMMAND), ["pi", "config"]]
    assert calls[1]["env"] == {
        "BENCH_IN_CONTAINER": "1",
        "HOME": f"{tmp_path}/.pi/home/run-1",
        "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/home/run-1/.pi/agent",
        "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/home/run-1/.pi/agent/orchestra",
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == ["pi", "config"]
    assert payload["stdout"] == "pi config output\n"


def test_run_known_task_opens_prompted_session_before_harness(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)

    run_id = "20250101T010203"
    calls: list[dict[str, object]] = []
    order: list[str] = []

    class _Completed:
        def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                sync_run_id = (env or {}).get("BENCH_RUN_ID", "run-1")
                self.stdout = _sync_summary_payload(tmp_path, sync_run_id) + "\n"
            elif list(command) == ["python3", "-m", "bench.runtime", "prepare-workdir", "alpha-run"]:
                self.stdout = f"/workspace/{run_id}-alpha-run\n"
            elif list(command)[:2] == ["sh", "-lc"]:
                self.stdout = ""
            else:
                self.stdout = "task session output\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        order.append("container" if list(command) != SYNC_COMMAND else "sync")
        return _Completed(list(command), kwargs.get("env"))

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        order.append("grade")
        assert run_paths.run_id == run_id
        return TaskResult(
            run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch, started_at="2025-01-01T01:02:03Z", finished_at="2025-01-01T01:02:04Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={},
        )

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)
    monkeypatch.setattr("bench.cli.grade_run", fake_grade_run)

    assert main(["run", "--tasks-root", str(task_root), "--catalog", str(catalog_path), "--run-id", run_id, "pi", "alpha-run"]) == 0
    assert [call["command"] for call in calls[:3]] == [
        list(SYNC_COMMAND),
        ["python3", "-m", "bench.runtime", "prepare-workdir", "alpha-run"],
        ["pi", "--model", "fake-model"],
    ]
    assert calls[0]["env"]["BENCH_RUN_ID"] == run_id
    assert calls[3]["command"][:2] == ["sh", "-lc"]
    assert f"/workspace/{run_id}-alpha-run" in calls[3]["command"][2]
    assert f"/bench/results/{run_id}-alpha-run/workspace" in calls[3]["command"][2]
    assert order == ["sync", "container", "container", "container", "container", "grade"]
    assert calls[1]["workdir"] == Path("/bench")
    assert calls[2]["workdir"] == Path(f"/workspace/{run_id}-alpha-run")
    assert calls[2]["env"] == {
        "BENCH_IN_CONTAINER": "1",
        "HOME": f"{tmp_path}/.pi/home/{run_id}",
        "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/home/{run_id}/.pi/agent",
        "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/home/{run_id}/.pi/agent/orchestra",
    }
    output = capsys.readouterr().out
    assert "] task: alpha-run" in output
    assert "Prompt.md" in output
    assert "Do the thing." in output
    assert "task session output" in output
    assert "] graded: pass" in output
    assert str(tmp_path / "results" / f"{run_id}-alpha-run" / "result.json") in output


def test_run_task_session_skips_grading_and_copies_harness_failure_output(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)

    run_id = "20250101T010203"
    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
            if list(command) == SYNC_COMMAND:
                self.returncode = 0
                sync_run_id = (env or {}).get("BENCH_RUN_ID", "run-1")
                self.stdout = _sync_summary_payload(tmp_path, sync_run_id) + "\n"
                self.stderr = ""
            elif list(command)[:2] == ["python3", "-m"] and list(command)[2:4] == ["bench.runtime", "prepare-workdir"]:
                self.returncode = 0
                self.stdout = f"/workspace/{run_id}-alpha-run\n"
                self.stderr = ""
            elif list(command)[:2] == ["sh", "-lc"]:
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""
            else:
                self.returncode = 3
                self.stdout = "pi stdout\n"
                self.stderr = "pi stderr\n"

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command), kwargs.get("env"))

    def fake_grade_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("grade_run must not be called when the harness fails to start")

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)
    monkeypatch.setattr("bench.cli.grade_run", fake_grade_run)

    assert main(["run", "--tasks-root", str(task_root), "--catalog", str(catalog_path), "--run-id", run_id, "pi", "alpha-run"]) == 3
    result_path = tmp_path / "results" / f"{run_id}-alpha-run" / "result.json"
    result = load_result(result_path)
    assert result.harness.status == "lifecycle_failed"
    assert result.evaluation.status == "not_run"
    assert result.outcome == "error"
    harness_root = tmp_path / "results" / f"{run_id}-alpha-run" / "artifacts" / "harness"
    assert harness_root.joinpath("transcript.txt").read_text(encoding="utf-8") == "pi stdout\npi stderr\n"
    assert harness_root.joinpath("run.log").read_text(encoding="utf-8") == "pi stdout\npi stderr\n"
    assert calls[0]["env"]["BENCH_RUN_ID"] == run_id
    assert calls[2]["env"]["HOME"] == f"{tmp_path}/.pi/home/{run_id}"
    output = capsys.readouterr().out
    assert "] harness failed:" in output
    assert "] graded:" not in output


def test_container_copyback_scripts_chown_results_trees_to_the_host_user(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    run_dir = tmp_path / "results" / "20250101T010203-alpha-run"
    bench_cli._sync_task_workspace_from_container(tmp_path / "workspace", run_dir)
    bench_cli._collect_pi_sessions_from_container({"home_dir": str(tmp_path / "home")}, run_dir)

    assert len(calls) == 2
    for call in calls:
        script = call["command"][2]
        assert "chown -R \"$BENCH_HOST_UID:$BENCH_HOST_GID\" \"$dst\"" in script


def test_run_raw_escape_hatch_preserves_literal_harness_commands(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "config", task_id="config")
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = "raw passthrough output\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["run", "--tasks-root", str(task_root), "--raw", "pi", "config"]) == 0
    assert [call["command"] for call in calls] == [list(SYNC_COMMAND), ["pi", "config"]]
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == ["pi", "config"]
    assert payload["stdout"] == "raw passthrough output\n"


def test_exec_passthrough_uses_tty_and_transcript_when_available(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._has_interactive_tty", lambda: True, raising=False)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = ""
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        transcript_path = kwargs.get("transcript_path")
        if transcript_path is not None:
            Path(transcript_path).parent.mkdir(parents=True, exist_ok=True)
            Path(transcript_path).write_text("tty transcript\n", encoding="utf-8")
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "pi", "config"]) == 0
    assert calls[1]["interactive"] is True
    assert calls[1]["tty"] is True
    assert Path(calls[1]["transcript_path"]).read_text(encoding="utf-8") == "tty transcript\n"
    assert calls[1]["env"] == {
        "BENCH_IN_CONTAINER": "1",
        "HOME": f"{tmp_path}/.pi/home/run-1",
        "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/home/run-1/.pi/agent",
        "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/home/run-1/.pi/agent/orchestra",
    }


def test_run_suite_routes_batch_execution(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run")
    _write_task(task_root / "beta-run", task_id="beta-run")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr(RunPaths, "container_workdir", property(lambda self: str(self.run_dir / "workspace")))

    calls: list[tuple[str, object]] = []

    def fake_list_tasks(tasks_root=None):  # type: ignore[no-untyped-def]
        calls.append(("list_tasks", tasks_root))
        return [
            load_task(task_root / "alpha-run"),
            load_task(task_root / "beta-run"),
        ]

    def fake_resolve_harness_for_role(catalog, role=None):  # type: ignore[no-untyped-def]
        calls.append(("resolve", str(catalog), role))
        return {
            "command": ["python3", "-c", "print('harness ok')"],
            "model": "fake-model",
            "agent": "fake-agent",
            "profile": "default",
            "env": {},
        }

    class FakeHarness:
        pass

    def fake_from_resolved_config(cls, resolved):  # type: ignore[no-untyped-def]
        calls.append(("harness", resolved["model"]))
        return FakeHarness()

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(("run_and_grade", task.task_id, kwargs.get("run_id")))
        return TaskResult(
            run_meta=RunMeta(run_id=kwargs.get("run_id") or f"generated-{task.task_id}", task_id=task.task_id, batch=task.batch, started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={"result_json": str(tmp_path / "results" / f"{kwargs.get('run_id') or f'generated-{task.task_id}'}-{task.task_id}" / "result.json")},
        )

    monkeypatch.setattr("bench.cli.list_tasks", fake_list_tasks, raising=False)
    monkeypatch.setattr("bench.cli.resolve_harness_for_role", fake_resolve_harness_for_role, raising=False)
    monkeypatch.setattr("bench.cli.CommandHarness.from_resolved_config", classmethod(fake_from_resolved_config), raising=False)
    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert (
        main(
            [
                "run",
                "smoke",
                "--tasks-root",
                str(task_root),
                "--root",
                str(tmp_path),
                "--catalog",
                str(catalog_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "] auto suite: smoke (2 tasks)" in output
    assert "] auto: alpha-run" in output
    assert "] auto: beta-run" in output
    assert "] suite complete: passed=2 failed=0" in output
    assert [call[0] for call in calls] == ["list_tasks", "resolve", "harness", "run_and_grade", "harness", "run_and_grade"]


def test_run_all_routes_suites_in_order(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "smoke-task", task_id="smoke-task", batch="smoke")
    _write_task(task_root / "easy-task", task_id="easy-task", batch="capability-easy")
    _write_task(task_root / "normal-task", task_id="normal-task", batch="capability-normal")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr(RunPaths, "container_workdir", property(lambda self: str(self.run_dir / "workspace")))

    calls: list[str] = []

    def fake_resolve_harness_for_role(catalog, role=None):  # type: ignore[no-untyped-def]
        return {"command": ["python3", "-c", "print('harness ok')"], "model": "fake-model", "agent": "fake-agent", "profile": "default", "env": {}}

    class FakeHarness:
        pass

    def fake_from_resolved_config(cls, resolved):  # type: ignore[no-untyped-def]
        return FakeHarness()

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(task.task_id)
        return TaskResult(
            run_meta=RunMeta(run_id=kwargs.get("run_id") or f"generated-{task.task_id}", task_id=task.task_id, batch=task.batch),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
        )

    monkeypatch.setattr("bench.cli.resolve_harness_for_role", fake_resolve_harness_for_role, raising=False)
    monkeypatch.setattr("bench.cli.CommandHarness.from_resolved_config", classmethod(fake_from_resolved_config), raising=False)
    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert main(["run", "all", "--tasks-root", str(task_root), "--root", str(tmp_path), "--catalog", str(catalog_path), "--auto"]) == 0

    output = capsys.readouterr().out
    assert "] auto all: 3 suites" in output
    assert "] auto suite: smoke (1 tasks)" in output
    assert "] auto suite: capability-easy (1 tasks)" in output
    assert "] auto suite: capability-normal (1 tasks)" in output
    assert calls == ["smoke-task", "easy-task", "normal-task"]


@pytest.mark.parametrize("argv", [["run", "alpha-run"], ["run", "smoke"]])
def test_run_rejects_host_side_benchmark_runs_without_auto(monkeypatch, capsys, argv) -> None:
    monkeypatch.setattr("bench.cli._inside_container", lambda: False, raising=False)
    called = False

    def fake_run_and_grade(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        raise AssertionError("run_and_grade should not be reached")

    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert main(argv) == 1
    assert not called
    assert "require --auto" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv, expected_command",
    [
        (
            ["run", "--auto", "alpha-run"],
            [
                "python3",
                "-m",
                "bench.cli",
                "run",
                "--root",
                "/bench",
                "--tasks-root",
                "/bench/task-materials-source",
                "alpha-run",
                "--run-id",
                "run-1",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
                "--auto",
            ],
        ),
        (
            ["run", "--auto", "pi"],
            [
                "python3",
                "-m",
                "bench.cli",
                "run",
                "--root",
                "/bench",
                "--tasks-root",
                "/bench/task-materials-source",
                "pi",
                "--run-id",
                "run-1",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
                "--auto",
            ],
        ),
        (
            ["run", "--auto", "pi", "alpha-run"],
            [
                "python3",
                "-m",
                "bench.cli",
                "run",
                "--root",
                "/bench",
                "--tasks-root",
                "/bench/task-materials-source",
                "alpha-run",
                "--run-id",
                "run-1",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
                "--auto-harness",
                "pi",
                "--auto",
            ],
        ),
        (
            ["run", "--auto", "hermes", "alpha-run"],
            [
                "python3",
                "-m",
                "bench.cli",
                "run",
                "--root",
                "/bench",
                "--tasks-root",
                "/bench/task-materials-source",
                "alpha-run",
                "--run-id",
                "run-1",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
                "--auto-harness",
                "hermes",
                "--auto",
            ],
        ),
        (
            ["run", "--auto", "opencode", "alpha-run"],
            [
                "python3",
                "-m",
                "bench.cli",
                "run",
                "--root",
                "/bench",
                "--tasks-root",
                "/bench/task-materials-source",
                "alpha-run",
                "--run-id",
                "run-1",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
                "--auto-harness",
                "opencode",
                "--auto",
            ],
        ),
        (
            ["run", "--auto", "smoke"],
            [
                "python3",
                "-m",
                "bench.cli",
                "run",
                "--root",
                "/bench",
                "--tasks-root",
                "/bench/task-materials-source",
                "smoke",
                "--run-id",
                "run-1",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
                "--auto",
            ],
        ),
    ],
)

def test_auto_run_routes_inside_container_and_maps_catalog(tmp_path: Path, monkeypatch, capsys, argv, expected_command) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    monkeypatch.setattr("bench.cli._now_run_id", lambda: "run-1", raising=False)

    class _Completed:
        def __init__(self, command: list[str], env: dict[str, str] | None = None, *, verbose: bool = False) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                run_id = (env or {}).get("BENCH_RUN_ID")
                assert run_id == "run-1"
                self.stdout = _sync_summary_payload(tmp_path, run_id) + "\n"
            else:
                self.stdout = "[12:34] auto: alpha-run\n[12:34] auto result: ok\n"
            self.stderr = ""
            if verbose and self.stdout:
                sys.stdout.write(self.stdout)

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command), kwargs.get("env"), verbose=bool(kwargs.get("verbose")))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(argv) == 0
    assert calls == [
        {"command": list(SYNC_COMMAND), "workdir": Path("/bench"), "env": {"BENCH_IN_CONTAINER": "1", "BENCH_RUN_ID": "run-1"}, "verbose": False},
        {
            "command": expected_command,
            "workdir": Path("/bench"),
            "env": {
                "BENCH_IN_CONTAINER": "1",
                "BENCH_RUN_ID": "run-1",
                "HOME": f"{tmp_path}/.pi/home/run-1",
                "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/home/run-1/.pi/agent",
                "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/home/run-1/.pi/agent/orchestra",
            },
            "verbose": True,
        },
    ]
    output = capsys.readouterr().out
    assert "] auto result:" in output
    assert "{" not in output


def test_auto_run_verbose_passes_verbose_flag_to_container_exec(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str], *, verbose: bool = False) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = "full harness session\n"
            self.stderr = ""
            if verbose and self.stdout:
                sys.stdout.write(self.stdout)

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command), verbose=bool(kwargs.get("verbose")))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["run", "--auto", "alpha-run", "--verbose"]) == 0
    assert calls[1]["verbose"] is True
    assert capsys.readouterr().out == "full harness session\n"


def test_auto_run_rejects_ambiguous_task_and_suite_targets(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "smoke", task_id="smoke")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)

    assert main(["run", "--auto", "smoke", "--tasks-root", str(task_root), "--root", str(tmp_path), "--catalog", str(catalog_path)]) == 1
    assert "ambiguous" in capsys.readouterr().err


def test_auto_run_prints_concise_milestones_without_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr("bench.cli.load_task", lambda task_id, tasks_root: SimpleNamespace(task_id=task_id), raising=False)
    monkeypatch.setattr(
        "bench.cli._resolve_catalog_and_harness",
        lambda args: (
            Path("/bench/orchestra-config/agent-catalog.yaml"),
            {
                "command": ["fake-harness"],
                "env": {},
                "model": "fake-model",
                "agent": "fake-agent",
                "profile": "default",
            },
        ),
        raising=False,
    )
    seen: dict[str, object] = {}

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        seen["stream_output"] = kwargs["stream_output"]
        return TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id=task.task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={
                "result_json": str(tmp_path / "results" / "run-1-alpha-run" / "result.json"),
                "artifacts": {"harness": {"root": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness")}},
            },
        )

    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert main(["run", "--auto", "alpha-run"]) == 0
    output = capsys.readouterr().out
    assert "] auto: alpha-run" in output
    assert "] auto result: alpha-run -> pass" in output
    assert "{" not in output
    assert seen["stream_output"] is False


def test_auto_run_verbose_streams_inner_output_and_plumbs_stream_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr("bench.cli.load_task", lambda task_id, tasks_root: SimpleNamespace(task_id=task_id), raising=False)
    monkeypatch.setattr(
        "bench.cli._resolve_catalog_and_harness",
        lambda args: (
            Path("/bench/orchestra-config/agent-catalog.yaml"),
            {
                "command": ["fake-harness"],
                "env": {},
                "model": "fake-model",
                "agent": "fake-agent",
                "profile": "default",
            },
        ),
        raising=False,
    )
    seen: dict[str, object] = {}

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        seen["stream_output"] = kwargs["stream_output"]
        if kwargs["stream_output"]:
            print("inner harness line")
        return TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id=task.task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={"result_json": str(tmp_path / "results" / "run-1-alpha-run" / "result.json")},
        )

    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert main(["run", "--auto", "alpha-run", "--verbose"]) == 0
    output = capsys.readouterr().out
    assert seen["stream_output"] is True
    assert "inner harness line" in output
    assert "] auto result: alpha-run -> pass" in output


def test_auto_run_propagates_synced_runtime_summary_into_run_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    seen: dict[str, object] = {}
    runtime_summary = {
        "pi_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent",
        "orchestra_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent/orchestra",
    }

    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr("bench.cli.load_task", lambda task_id, tasks_root: SimpleNamespace(task_id=task_id), raising=False)
    monkeypatch.setattr(
        "bench.cli._resolve_catalog_and_harness",
        lambda args: (
            Path("/bench/orchestra-config/agent-catalog.yaml"),
            {
                "command": ["fake-harness"],
                "env": {"HARNESS_ENV": "catalog"},
                "model": "fake-model",
                "agent": "fake-agent",
                "profile": "default",
            },
        ),
        raising=False,
    )
    monkeypatch.setattr("bench.cli.load_runtime_config_summary", lambda: runtime_summary, raising=False)

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        seen["env"] = kwargs["env"]
        seen["runtime_snapshot"] = kwargs["runtime_snapshot"]
        seen["harness"] = tuple(harness.command_template)
        return TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id=task.task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={
                "result_json": str(tmp_path / "results" / "run-1-alpha-run" / "result.json"),
                "artifacts": {
                    "harness": {
                        "root": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness"),
                        "transcript": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "transcript.txt"),
                        "events": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "events.jsonl"),
                        "summary": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "summary.json"),
                        "log": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "run.log"),
                    },
                    "evaluator": {
                        "root": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator"),
                        "stdout": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "stdout.txt"),
                        "stderr": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "stderr.txt"),
                        "log": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "run.log"),
                        "result": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "result.json"),
                    },
                },
            },
        )

    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert main(["run", "--auto", "alpha-run"]) == 0
    output = capsys.readouterr().out
    assert "] auto: alpha-run" in output
    assert "] auto result: alpha-run -> pass" in output
    assert str(tmp_path / "results" / "run-1-alpha-run" / "result.json") in output
    assert seen["runtime_snapshot"] == runtime_summary
    assert seen["env"] == {
        "HARNESS_ENV": "catalog",
        "HOME": "/workspace/.pi/home/run-1",
        "PI_CODING_AGENT_DIR": "/workspace/.pi/home/run-1/.pi/agent",
        "PI_ORCHESTRA_RUNTIME_DIR": "/workspace/.pi/home/run-1/.pi/agent/orchestra",
    }
    assert seen["harness"] == ("fake-harness",)


def test_auto_run_inside_container_no_orchestra_disables_tools_default(tmp_path: Path, monkeypatch) -> None:
    args = SimpleNamespace(
        run_id="run-1",
        task_id="alpha-run",
        role=None,
        notes="",
        catalog=Path("/bench/orchestra-config/agent-catalog.yaml"),
        catalog_label="config/orchestra/agent-catalog.yaml",
        auto=True,
        auto_harness=None,
        dry_run=False,
        verbose=False,
        orchestra=False,
    )
    seen: dict[str, object] = {}

    def fake_sync_runtime_config_inside_container(*, run_id=None, orchestra_tools_enabled=None):  # type: ignore[no-untyped-def]
        seen["sync"] = {"run_id": run_id, "orchestra_tools_enabled": orchestra_tools_enabled}
        return {
            "home_dir": f"{tmp_path}/.pi/home/{run_id}",
            "pi_runtime_dir": f"{tmp_path}/.pi/home/{run_id}/.pi/agent",
            "orchestra_runtime_dir": f"{tmp_path}/.pi/home/{run_id}/.pi/agent/orchestra",
        }

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        seen["command"] = list(command)
        seen["env"] = dict(kwargs["env"])
        return _Completed()

    monkeypatch.setattr("bench.cli._sync_runtime_config_inside_container", fake_sync_runtime_config_inside_container, raising=False)
    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert bench_cli._run_auto_inside_container(args) == 0
    assert seen["sync"] == {"run_id": "run-1", "orchestra_tools_enabled": False}
    assert "--no-orchestra" in seen["command"]
    assert seen["env"]["BENCH_RUN_ID"] == "run-1"
    assert seen["env"]["HOME"] == f"{tmp_path}/.pi/home/run-1"
    assert seen["env"]["PI_CODING_AGENT_DIR"] == f"{tmp_path}/.pi/home/run-1/.pi/agent"
    assert seen["env"]["PI_ORCHESTRA_RUNTIME_DIR"] == f"{tmp_path}/.pi/home/run-1/.pi/agent/orchestra"


def test_run_single_task_uses_pi_rpc_harness_for_orchestrated_pi_catalog(tmp_path: Path, monkeypatch) -> None:
    args = SimpleNamespace(
        root=tmp_path,
        run_id="run-1",
        role="builder",
        orchestra=True,
        auto=True,
        notes="",
        catalog_label="config/orchestra/agent-catalog.yaml",
        verbose=False,
    )
    task = SimpleNamespace(task_id="alpha-run")
    catalog_path = Path("/bench/orchestra-config/agent-catalog.yaml")
    resolved = {
        "backend": "pi",
        "harness": "pi",
        "command": ["pi", "--mode", "rpc"],
        "env": {"HARNESS_ENV": "catalog"},
        "model": "fake-model",
        "agent": "fake-agent",
        "profile": "default",
    }
    created: dict[str, object] = {}

    monkeypatch.setattr("bench.cli.load_runtime_config_summary", lambda: None, raising=False)

    class FakePiHarness:
        def __init__(self, command, **kwargs):  # type: ignore[no-untyped-def]
            created["command"] = list(command)
            created["harness_kwargs"] = kwargs

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        created["harness"] = harness
        created["run_kwargs"] = kwargs
        return TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id=task.task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={"result_json": str(tmp_path / "results" / "run-1-alpha-run" / "result.json")},
        )

    monkeypatch.setattr("bench.cli.CommandHarness.from_resolved_config", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CommandHarness should not be used")), raising=False)
    monkeypatch.setattr("bench.cli.PiRpcHarness", FakePiHarness, raising=False)
    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    result = bench_cli._run_single_task(args, task, catalog=catalog_path, resolved=resolved)

    assert result.outcome == "pass"
    assert created["command"] == ["pi", "--model", "fake-model", "--mode", "rpc"]
    assert created["harness_kwargs"] == {"env": {"HARNESS_ENV": "catalog"}}
    assert created["run_kwargs"]["env"] == {"HARNESS_ENV": "catalog"}
    assert created["run_kwargs"]["auto"] is True
    assert created["run_kwargs"]["orchestra"] is True
    assert created["run_kwargs"]["orchestra_tools_available"] is None
    assert isinstance(created["harness"], FakePiHarness)


def test_run_single_task_disables_tools_when_no_orchestra(tmp_path: Path, monkeypatch) -> None:
    args = SimpleNamespace(
        root=tmp_path,
        run_id="run-1",
        role="builder",
        orchestra=False,
        auto=True,
        notes="",
        catalog_label="config/orchestra/agent-catalog.yaml",
        verbose=False,
    )
    task = SimpleNamespace(task_id="alpha-run")
    catalog_path = Path("/bench/orchestra-config/agent-catalog.yaml")
    resolved = {
        "backend": "pi",
        "harness": "pi",
        "command": ["pi", "--mode", "rpc"],
        "env": {"HARNESS_ENV": "catalog"},
        "model": "fake-model",
        "agent": "fake-agent",
        "profile": "default",
    }
    created: dict[str, object] = {}

    monkeypatch.setattr(
        "bench.cli.load_runtime_config_summary",
        lambda: {"orchestra_tools_enabled_by_default": False},
        raising=False,
    )
    monkeypatch.setattr("bench.cli.CommandHarness.from_resolved_config", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CommandHarness should not be used")), raising=False)

    class FakePiHarness:
        def __init__(self, command, **kwargs):  # type: ignore[no-untyped-def]
            created["command"] = list(command)
            created["harness_kwargs"] = kwargs

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        created["harness"] = harness
        created["run_kwargs"] = kwargs
        return TaskResult(
            run_meta=RunMeta(run_id="run-1", task_id=task.task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={"result_json": str(tmp_path / "results" / "run-1-alpha-run" / "result.json")},
        )

    monkeypatch.setattr("bench.cli.PiRpcHarness", FakePiHarness, raising=False)
    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    result = bench_cli._run_single_task(args, task, catalog=catalog_path, resolved=resolved)

    assert result.outcome == "pass"
    assert created["command"] == ["pi", "--model", "fake-model", "--mode", "rpc"]
    assert created["harness_kwargs"] == {"env": {"HARNESS_ENV": "catalog"}}
    assert created["run_kwargs"]["env"] == {"HARNESS_ENV": "catalog"}
    assert created["run_kwargs"]["orchestra_tools_available"] is False
    assert created["run_kwargs"]["request_metadata"]["orchestra_tools_enabled"] is False
    assert isinstance(created["harness"], FakePiHarness)


def _run_auto_pi_single_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    home_dir: Path | None,
    create_sessions: bool = True,
    run_id: str = "run-1",
    block_target: bool = False,
) -> TaskResult:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    args = SimpleNamespace(
        root=tmp_path,
        run_id=run_id,
        role="builder",
        orchestra=False,
        auto=True,
        notes="",
        catalog_label="config/orchestra/agent-catalog.yaml",
        verbose=False,
    )
    resolved = {
        "backend": "pi",
        "harness": "pi",
        "command": ["pi", "--mode", "rpc"],
        "env": {},
        "model": "fake-model",
        "agent": "fake-agent",
        "profile": "default",
    }

    class FakePiHarness:
        session_id = ""
        last_settle_status = "settled"

        def __init__(self, command, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def run(self, request):  # type: ignore[no-untyped-def]
            if home_dir is not None and create_sessions:
                sessions = home_dir / ".pi" / "agent" / "sessions"
                sessions.mkdir(parents=True, exist_ok=True)
                cwd = str(workspace_dir(request.run_paths))
                (sessions / "parent-session.jsonl").write_text(
                    json.dumps({"type": "session", "cwd": cwd, "id": "parent-session"}) + "\n"
                    + json.dumps({"type": "message_end", "usage": {"input": 10, "output": 5}}) + "\n",
                    encoding="utf-8",
                )
                (sessions / "orchestra-worker-child-1.jsonl").write_text(
                    json.dumps({"type": "session", "cwd": cwd, "id": "orchestra-worker-child-1"}) + "\n"
                    + json.dumps({"type": "message_end", "usage": {"input": 7, "output": 3}}) + "\n",
                    encoding="utf-8",
                )
            return HarnessResult(status="ok", exit_code=0)

    monkeypatch.setattr("bench.cli.PiRpcHarness", FakePiHarness, raising=False)
    monkeypatch.setattr(
        "bench.cli.load_runtime_config_summary",
        lambda: ({} if home_dir is None else {"home_dir": str(home_dir)}),
        raising=False,
    )
    monkeypatch.setattr(
        "bench.runner.wait_until_safe_to_grade",
        lambda harness, **kwargs: OrchestrationSettleResult(
            safe_to_grade=True,
            reason="harness_terminal",
            harness_status="settled",
            session_id="",
            snapshots=(),
        ),
        raising=False,
    )

    def fake_grade_run(task_arg, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        return load_result(run_paths.result_json)

    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    if block_target:
        target = tmp_path / "results" / f"{run_id}-alpha-run" / "artifacts" / "pi-sessions"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("blocker", encoding="utf-8")

    return bench_cli._run_single_task(args, task, catalog=catalog_path, resolved=resolved)


def _collection_record(tmp_path: Path, run_id: str = "run-1") -> dict:
    path = tmp_path / "results" / f"{run_id}-alpha-run" / "artifacts" / "pi-sessions-collection.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_auto_run_collects_pi_sessions(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "runtime-home"
    result = _run_auto_pi_single_task(tmp_path, monkeypatch, home_dir=home_dir)

    assert result.harness.status == "ok"
    sessions_target = tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "pi-sessions"
    assert (sessions_target / "parent-session.jsonl").is_file()
    assert (sessions_target / "orchestra-worker-child-1.jsonl").is_file()
    record = _collection_record(tmp_path)
    assert record["status"] == "collected"
    assert record["source"] == str(home_dir / ".pi" / "agent" / "sessions")


def test_auto_run_records_unavailable_when_pi_sessions_source_missing(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "runtime-home-empty"
    home_dir.mkdir(parents=True)
    result = _run_auto_pi_single_task(
        tmp_path, monkeypatch, home_dir=home_dir, create_sessions=False
    )

    assert result.harness.status == "ok"
    record = _collection_record(tmp_path)
    assert record["status"] == "unavailable"
    assert record["reason"] == "source_missing"
    assert not (tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "pi-sessions").exists()


def test_auto_run_records_copy_failure_when_pi_sessions_target_is_blocked(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "runtime-home"
    result = _run_auto_pi_single_task(tmp_path, monkeypatch, home_dir=home_dir, block_target=True)

    assert result.harness.status == "ok"
    record = _collection_record(tmp_path)
    assert record["status"] == "unavailable"
    assert record["reason"] == "copy_failed"
    assert record.get("error")


def test_run_single_task_does_not_claim_orchestra_tools_for_non_pi_backend(tmp_path: Path, monkeypatch) -> None:
    args = SimpleNamespace(
        root=tmp_path,
        run_id="run-1",
        role="builder",
        orchestra=None,
        auto=True,
        notes="",
        catalog_label="config/orchestra/agent-catalog.yaml",
        verbose=False,
    )
    task = SimpleNamespace(task_id="alpha-run")
    catalog_path = Path("/bench/orchestra-config/agent-catalog.yaml")
    resolved = {
        "backend": "hermes",
        "harness": "hermes",
        "command": ["hermes"],
        "env": {},
        "model": "fake-model",
        "agent": "fake-agent",
        "profile": "default",
    }
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "bench.cli.load_runtime_config_summary",
        lambda: {"orchestra_tools_enabled_by_default": True},
        raising=False,
    )
    monkeypatch.setattr("bench.cli.CommandHarness.from_resolved_config", lambda *args, **kwargs: object(), raising=False)

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return "result"

    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert bench_cli._run_single_task(args, task, catalog=catalog_path, resolved=resolved) == "result"
    assert seen["orchestra_tools_available"] is None


def test_orchestra_tools_availability_uses_backend_and_runtime_evidence() -> None:
    assert bench_cli._derive_orchestra_tools_available(
        "pi", {"orchestra_tools_enabled_by_default": False}
    ) is False
    assert bench_cli._derive_orchestra_tools_available(
        "pi", {"orchestra_tools_enabled_by_default": True}
    ) is True
    assert bench_cli._derive_orchestra_tools_available(
        "hermes", {"orchestra_tools_enabled_by_default": True}
    ) is None


def test_auto_suite_continues_serially_and_returns_failure_code_when_any_task_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run", task_id="alpha-run")
    _write_task(task_root / "beta-run", task_id="beta-run")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)
    monkeypatch.setattr("bench.cli.load_task", lambda task_id, tasks_root=None: (_ for _ in ()).throw(TaskLoadError("missing")), raising=False)
    monkeypatch.setattr(
        "bench.cli.list_tasks",
        lambda tasks_root=None: [load_task(task_root / "alpha-run"), load_task(task_root / "beta-run")],
        raising=False,
    )
    monkeypatch.setattr(
        "bench.cli._resolve_catalog_and_harness",
        lambda args: (
            Path("/bench/orchestra-config/agent-catalog.yaml"),
            {
                "command": ["fake-harness"],
                "env": {"HARNESS_ENV": "catalog"},
                "model": "fake-model",
                "agent": "fake-agent",
                "profile": "default",
            },
        ),
        raising=False,
    )

    run_order: list[str] = []

    def fake_run_and_grade(task, harness, **kwargs):  # type: ignore[no-untyped-def]
        run_order.append(task.task_id)
        outcome = "pass" if task.task_id == "alpha-run" else "fail"
        score = "pass" if task.task_id == "alpha-run" else "fail"
        run_id = kwargs.get("run_id") or f"generated-{task.task_id}"
        return TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task.task_id, batch=task.batch, started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:00:01Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score=score),
            outcome=outcome,
            details={"result_json": str(tmp_path / "results" / f"{run_id}-{task.task_id}" / "result.json")},
        )

    monkeypatch.setattr("bench.cli.run_and_grade", fake_run_and_grade, raising=False)

    assert main(["run", "--auto", "smoke"]) == 1
    output = capsys.readouterr().out
    assert "] auto suite: smoke (2 tasks)" in output
    assert "] auto: alpha-run" in output
    assert "] auto: beta-run" in output
    assert "] suite complete: passed=1 failed=1" in output
    assert run_order == ["alpha-run", "beta-run"]


def test_exec_routes_passthrough_harness_inside_container(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = json.dumps({"pi_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent", "orchestra_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent/orchestra"}) + "\n"
            else:
                self.stdout = "pi config output\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "pi", "config"]) == 0
    # Contract: in-container config sync first (D-RUN-003 + Slice 2.1), then the opaque harness passthrough.
    assert calls == [
        {
            "command": list(SYNC_COMMAND),
            "workdir": Path("/bench"),
            "env": {"BENCH_IN_CONTAINER": "1"},
            "verbose": False,
        },
        {
            "command": ["pi", "config"],
            "workdir": Path("/bench"),
            "env": {
                "BENCH_IN_CONTAINER": "1",
                "HOME": "/workspace/.pi/home/run-1",
                "PI_CODING_AGENT_DIR": "/workspace/.pi/home/run-1/.pi/agent",
                "PI_ORCHESTRA_RUNTIME_DIR": "/workspace/.pi/home/run-1/.pi/agent/orchestra",
            },
            "verbose": False,
            "interactive": False,
            "tty": False,
            "transcript_path": None,
        },
    ]
    assert json.loads(capsys.readouterr().out) == {
        "container": "orchestra-bench-runner",
        "command": ["pi", "config"],
        "returncode": 0,
        "stdout": "pi config output\n",
    }


def test_exec_verbose_stream_flag_reaches_container_exec(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            # Sync output is captured even in verbose mode; only the harness streams.
            if list(command) == SYNC_COMMAND:
                self.stdout = json.dumps({"pi_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent", "orchestra_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent/orchestra"}) + "\n"
            else:
                self.stdout = None
            self.stderr = None

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "--verbose", "pi", "config"]) == 0
    # The verbose stream flag reaches the harness exec; the sync step stays captured.
    assert calls[1] == {
        "command": ["pi", "config"],
        "workdir": Path("/bench"),
        "env": {
            "BENCH_IN_CONTAINER": "1",
            "HOME": "/workspace/.pi/home/run-1",
            "PI_CODING_AGENT_DIR": "/workspace/.pi/home/run-1/.pi/agent",
            "PI_ORCHESTRA_RUNTIME_DIR": "/workspace/.pi/home/run-1/.pi/agent/orchestra",
        },
        "verbose": True,
        "interactive": False,
        "tty": False,
        "transcript_path": None,
    }
    assert capsys.readouterr().out == ""


SYNC_COMMAND = ["python3", "-m", "bench.runtime", "init-runtime"]


def _sync_summary_payload(tmp_path: Path, run_id: str = "run-1") -> str:
    return json.dumps(
        {
            "home_dir": f"{tmp_path}/.pi/home/{run_id}",
            "pi_runtime_dir": f"{tmp_path}/.pi/home/{run_id}/.pi/agent",
            "orchestra_runtime_dir": f"{tmp_path}/.pi/home/{run_id}/.pi/agent/orchestra",
        }
    )


def _fake_container_exec(tmp_path: Path, calls: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    class _Completed:
        def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                run_id = (env or {}).get("BENCH_RUN_ID", "run-1")
                self.stdout = _sync_summary_payload(tmp_path, run_id) + "\n"
            else:
                self.stdout = f"harness output for {command[1] if len(command) > 1 else ''}\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command), kwargs.get("env"))

    return fake_container_exec


def test_exec_syncs_runtime_config_in_container_before_harness(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr("bench.cli.container_exec", _fake_container_exec(tmp_path, calls), raising=False)

    assert main(["exec", "pi", "config"]) == 0
    assert [call["command"] for call in calls] == [
        list(SYNC_COMMAND),
        ["pi", "config"],
    ]
    sync_call, harness_call = calls
    assert sync_call["workdir"] == Path("/bench")
    assert sync_call["env"] == {"BENCH_IN_CONTAINER": "1"}
    assert sync_call["verbose"] is False
    # The interactive pi session must be pointed at the run-scoped runtime dir
    # that the in-container sync populated, so it sees config/pi/ overrides.
    assert harness_call["env"]["PI_CODING_AGENT_DIR"] == f"{tmp_path}/.pi/home/run-1/.pi/agent"
    assert harness_call["env"]["PI_ORCHESTRA_RUNTIME_DIR"] == f"{tmp_path}/.pi/home/run-1/.pi/agent/orchestra"


def test_exec_syncs_runtime_config_in_container_with_preamble_json_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = (
                    "starting runtime sync\n"
                    "running orchestra init pi --copy --force\n"
                    "{\n"
                    '  "pi_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent",\n'
                    '  "orchestra_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent/orchestra"\n'
                    "}\n"
                )
            else:
                self.stdout = "pi config output\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "pi", "config"]) == 0
    assert [call["command"] for call in calls] == [
        list(SYNC_COMMAND),
        ["pi", "config"],
    ]
    sync_call, harness_call = calls
    assert sync_call["env"] == {"BENCH_IN_CONTAINER": "1"}
    assert harness_call["env"]["PI_CODING_AGENT_DIR"] == "/workspace/.pi/home/run-1/.pi/agent"
    assert harness_call["env"]["PI_ORCHESTRA_RUNTIME_DIR"] == "/workspace/.pi/home/run-1/.pi/agent/orchestra"


def test_exec_aborts_before_harness_when_sync_stdout_is_not_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = "starting runtime sync\nnot-json\n"
            else:
                raise AssertionError("harness must not run when sync output is invalid")
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "pi", "config"]) == 1
    assert [call["command"] for call in calls] == [list(SYNC_COMMAND)]
    assert "did not return a JSON summary" in capsys.readouterr().err


def test_exec_hermes_passthrough_syncs_without_pi_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr("bench.cli.container_exec", _fake_container_exec(tmp_path, calls), raising=False)

    assert main(["exec", "hermes", "--version"]) == 0
    assert [call["command"] for call in calls] == [
        list(SYNC_COMMAND),
        ["hermes", "--version"],
    ]
    # Hermes reads its overrides from the container-default runtime dir that the
    # shared sync populates; it must not receive Pi-specific env.
    assert calls[1]["env"] == {"BENCH_IN_CONTAINER": "1"}


def test_exec_aborts_before_harness_when_config_sync_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        returncode = 127
        stdout = ""
        stderr = "orchestra: command not found\n"

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed()

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "pi", "config"]) == 1
    # Harness must never run when the in-container config sync fails.
    assert [call["command"] for call in calls] == [list(SYNC_COMMAND)]


def test_start_parser_accepts_bare_setup_only() -> None:
    args = build_parser().parse_args(["start"])
    assert not hasattr(args, "start_action")


def test_start_parser_rejects_unknown_arguments() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["start", "bogus"])


def test_start_help_uses_public_script_name_and_example() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "01-start"
    completed = subprocess.run(["bash", str(script), "--help"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [
        "usage: 01-start",
        "",
        "Set up the benchmark container (build, recreate, configure).",
        "",
        "Examples:",
        "  01-start",
    ]


def test_start_dispatches_to_full_setup(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}
    progress_messages: list[str] = []

    def fake_prepare_startup(root=None, image_name=None, container_name=None, progress=None, stream_build_output=False):  # type: ignore[no-untyped-def]
        seen["root"] = root
        seen["image_name"] = image_name
        seen["container_name"] = container_name
        seen["stream_build_output"] = stream_build_output
        if progress is not None:
            for message in ("Building image...", "Recreating container...", "Applying runtime config...", "Ready."):
                progress_messages.append(message)
                progress(message)
        return {
            "status": "ok",
            "image": "orchestra-bench-env",
            "container": "orchestra-bench-runner",
            "runtime": {
                "pi_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent",
                "orchestra_runtime_dir": "/workspace/.pi/home/run-1/.pi/agent/orchestra",
            },
        }

    monkeypatch.setattr("bench.cli.prepare_startup", fake_prepare_startup)

    assert main(["start"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Building image...",
        "Recreating container...",
        "Applying runtime config...",
        "Ready.",
        "Setup complete:",
        "  image: orchestra-bench-env",
        "  container: orchestra-bench-runner",
        "  pi runtime dir: /workspace/.pi/home/run-1/.pi/agent",
        "  orchestra runtime dir: /workspace/.pi/home/run-1/.pi/agent/orchestra",
    ]
    assert progress_messages == ["Building image...", "Recreating container...", "Applying runtime config...", "Ready."]
    assert Path(seen["root"]) == Path.cwd()
    assert seen["image_name"] is None
    assert seen["container_name"] is None
    assert seen["stream_build_output"] is True


def test_results_routes_through_reporting_views(tmp_path: Path, monkeypatch, capsys) -> None:
    run_id = "20250101T010203"
    task_id = "alpha-run"
    entry = ReportEntry(
        path=tmp_path / "results" / f"{run_id}-{task_id}" / "result.json",
        result=TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
        ),
        batch="smoke",
        model="fake-model",
        orchestra=True,
    )
    calls: list[tuple[str, object]] = []

    def fake_select_results(results_dir=None, tasks_dir=None, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(("select", results_dir, tasks_dir, kwargs))
        return [entry]

    def fake_format_dashboard(entries):  # type: ignore[no-untyped-def]
        calls.append(("dashboard", list(entries)))
        return "dashboard view\n"

    def fake_format_runs(entries):  # type: ignore[no-untyped-def]
        calls.append(("runs", list(entries)))
        return "runs view\n"

    def fake_format_run_detail(found_entry):  # type: ignore[no-untyped-def]
        calls.append(("run", found_entry))
        return "run view\n"

    def fake_format_tokens(entries):  # type: ignore[no-untyped-def]
        calls.append(("tokens", list(entries)))
        return "tokens view\n"

    def fake_format_timing(entries):  # type: ignore[no-untyped-def]
        calls.append(("timing", list(entries)))
        return "timing view\n"

    def fake_format_session_debug(session_dir, *, view="orch", no_tools=False, plain=False, no_color=False, isatty=None):  # type: ignore[no-untyped-def]
        calls.append(("debug", session_dir, {"view": view, "no_tools": no_tools, "plain": plain, "no_color": no_color, "isatty": isatty}))
        return "debug view\n"

    monkeypatch.setattr("bench.cli.select_results", fake_select_results, raising=False)
    monkeypatch.setattr("bench.cli.format_dashboard", fake_format_dashboard, raising=False)
    monkeypatch.setattr("bench.cli.format_runs", fake_format_runs, raising=False)
    monkeypatch.setattr("bench.cli.format_run_detail", fake_format_run_detail, raising=False)
    monkeypatch.setattr("bench.cli.format_tokens", fake_format_tokens, raising=False)
    monkeypatch.setattr("bench.cli.format_timing", fake_format_timing, raising=False)
    monkeypatch.setattr("bench.cli.format_session_debug", fake_format_session_debug, raising=False)

    assert main(["results", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "dashboard view\n"
    assert main(["results", "runs"]) == 0
    assert capsys.readouterr().out == "runs view\n"
    assert main(["results", "run", f"{run_id}-{task_id}"]) == 0
    assert capsys.readouterr().out == "run view\n"
    assert main(["results", "tokens"]) == 0
    assert capsys.readouterr().out == "tokens view\n"
    assert main(["results", "timing"]) == 0
    assert capsys.readouterr().out == "timing view\n"
    with pytest.raises(SystemExit) as excinfo:
        main(["results", "debug", f"{run_id}-{task_id}", "--root", str(tmp_path)])
    assert excinfo.value.code == 2
    assert main(["results"]) == 0
    assert capsys.readouterr().out == "dashboard view\n"

    assert [call[0] for call in calls] == ["select", "dashboard", "select", "runs", "select", "run", "select", "tokens", "select", "timing", "select", "dashboard"]
    assert calls[0] == ("select", tmp_path, None, {"task": None, "suite": None, "model": None, "orchestra": None, "sort": "finished_at", "reverse": True, "limit": None})
    assert calls[5][1].run_id == run_id
    assert calls[8] == ("select", None, None, {"task": None, "suite": None, "model": None, "orchestra": None, "sort": "finished_at", "reverse": True, "limit": None})


def test_results_run_reports_no_valid_scored_runs_for_invalid_legacy_artifacts(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run")
    results_root = tmp_path / "results"
    run_dir = results_root / "20250101T010203-alpha-run"
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text('{"run_id":"20250101T010203","task_id":"alpha-run","score":"pass"}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["results", "run", "20250101T010203", "--root", str(results_root), "--tasks-root", str(task_root)]) == 0
    assert capsys.readouterr().out == "no valid scored runs\n"


def test_results_comp_routes_through_selector_comparison_views(tmp_path: Path, monkeypatch, capsys) -> None:
    run_id = "20250101T010101"
    task_id = "alpha-run"
    entry = ReportEntry(
        path=tmp_path / "results" / f"{run_id}-{task_id}" / "result.json",
        result=TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
        ),
        batch="smoke",
        model="model-a",
        orchestra=True,
    )
    calls: list[tuple[str, object]] = []

    def fake_select_results(results_dir=None, tasks_dir=None, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(("select", results_dir, tasks_dir, kwargs))
        return [entry]

    def fake_compare_selected_results(entries, parent_selector, children_selector):  # type: ignore[no-untyped-def]
        calls.append(("compare", list(entries), parent_selector, children_selector))
        return {"mode": "run-vs-group", "parent": {"label": "run 20250101T010101-alpha-run", "selector": parent_selector, "kind": "run", "runs": 1, "passed": 1, "failed": 0, "error": 0, "scored": 1, "pass_rate": 1.0, "score": {}, "categories": {}, "tokens": {}, "elapsed": {}, "orchestra": {}, "failure_reasons": []}, "children": {"label": "model=model-a", "selector": children_selector, "kind": "group", "runs": 1, "passed": 1, "failed": 0, "error": 0, "scored": 1, "pass_rate": 1.0, "score": {}, "categories": {}, "tokens": {}, "elapsed": {}, "orchestra": {}, "failure_reasons": []}}

    def fake_format_comparison_results(summary):  # type: ignore[no-untyped-def]
        calls.append(("format", summary))
        return "comparison view\n"

    monkeypatch.setattr("bench.cli.select_results", fake_select_results, raising=False)
    monkeypatch.setattr("bench.cli.compare_selected_results", fake_compare_selected_results, raising=False)
    monkeypatch.setattr("bench.cli.format_comparison_results", fake_format_comparison_results, raising=False)

    assert main(["results", "comp", "run:20250101T010101", "model:model-a", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "comparison view\n"
    assert calls[0][3] == {"task": None, "suite": None, "model": None, "orchestra": None, "sort": "finished_at", "reverse": True, "limit": None}
    assert calls[1][2:] == ("run:20250101T010101", "model:model-a")
    assert calls[2][1]["mode"] == "run-vs-group"


def test_results_compare_rescore_and_delete_support_filters_and_safety(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "alpha-run")
    _write_task(task_root / "beta-run", task_id="beta-run")
    results_root = tmp_path / "results"
    alpha_one = _write_result(results_root, "20250101T010101", "alpha-run", model="model-a", orchestra=True, total_tokens=120, elapsed_seconds=12.5)
    alpha_two = _write_result(results_root, "20250101T010103", "alpha-run", model="model-a", orchestra=True, total_tokens=90, elapsed_seconds=9.0)
    beta_one = _write_result(results_root, "20250101T010102", "beta-run", model="model-b", orchestra=False, total_tokens=240, elapsed_seconds=24.0)
    monkeypatch.chdir(tmp_path)

    assert main(["results", "compare", "--task", "alpha-run", "--root", str(results_root), "--tasks-root", str(task_root)]) == 0
    compare_output = capsys.readouterr().out
    assert "compare" in compare_output
    assert "runs: 2" in compare_output
    assert "suite=smoke" in compare_output
    assert "model=model-a" in compare_output

    from bench.evaluator import EvaluationError

    def failing_grade_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise EvaluationError("boom", classification="crash")

    monkeypatch.setattr("bench.runner._grade_run", failing_grade_run, raising=False)
    assert main(["results", "rescore", "--task", "alpha-run", "--root", str(results_root), "--tasks-root", str(task_root)]) == 0
    rescore_output = capsys.readouterr().out
    assert "rescore" in rescore_output
    assert "selected    : 2" in rescore_output
    assert "evaluation=ok" in rescore_output
    assert "score=pass" not in rescore_output
    assert load_result(Path(alpha_two)).outcome == "pass"

    assert main(["results", "delete", "--task", "alpha-run", "--root", str(results_root), "--tasks-root", str(task_root)]) == 0
    delete_preview = capsys.readouterr().out
    assert "mode        : dry-run" in delete_preview
    assert "WOULD DELETE" in delete_preview
    assert "20250101T010101-alpha-run" in delete_preview
    assert "20250101T010103-alpha-run" in delete_preview
    assert alpha_one.parent.exists()
    assert alpha_two.parent.exists()
    assert beta_one.parent.exists()

    assert main(["results", "delete", "--task", "alpha-run", "--root", str(results_root), "--tasks-root", str(task_root), "--yes"]) == 0
    delete_confirmed = capsys.readouterr().out
    assert "mode        : delete" in delete_confirmed
    assert "DELETE" in delete_confirmed
    assert not alpha_one.parent.exists()
    assert not alpha_two.parent.exists()
    assert beta_one.parent.exists()
