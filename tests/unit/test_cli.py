from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.cli import build_parser, main
from bench.paths import RunPaths
from bench.reporting.queries import ReportEntry
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.tasks import TaskLoadError, load_task


def _write_task(task_dir: Path, *, task_id: str = "alpha-run") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(
        "task_id: {task_id}\n"
        "description: Sample task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 10\n"
        "evaluator: evaluate/run.sh\n".format(task_id=task_id),
        encoding="utf-8",
    )
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


def _write_result(results_root: Path, run_id: str, task_id: str, *, batch: str = "smoke", model: str = "", orchestra: bool | None = None, total_tokens: int | None = None, elapsed_seconds: float | None = None) -> Path:
    path = results_root / f"{run_id}-{task_id}" / "result.json"
    write_json_atomic(
        path,
        TaskResult(
            run_meta=RunMeta(run_id=run_id, task_id=task_id, batch=batch, started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="ok", score="pass"),
            outcome="pass",
            details={
                "provenance": {"model": model, "orchestra": orchestra},
                "tokens": {"total": total_tokens} if total_tokens is not None else {},
                "timing": {"elapsed_seconds": elapsed_seconds} if elapsed_seconds is not None else {},
            },
        ),
    )
    return path


def test_help_lists_public_commands(capsys) -> None:
    assert main(["help"]) == 0
    output = capsys.readouterr().out
    first_line = output.splitlines()[0]
    assert "{help,start,run,results,debug,doctor}" in first_line
    assert "runtime" not in first_line
    assert "grade" not in first_line
    assert "suite" not in first_line


def test_results_help_is_public_and_concise(capsys) -> None:
    assert main(["results", "--help"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines()[0] == "usage: scripts/03-results [dashboard|runs|run|tokens|timing|debug|compare|rescore|delete]"
    assert "Inspect, compare, rescore, and safely delete benchmark results." in output
    assert "bench results" not in output
    assert "--root" not in output
    assert "--tasks-root" not in output
    assert "delete-preview" in output
    assert "delete-confirmation" in output


def test_run_help_shows_public_wrapper_modes_and_examples(capsys) -> None:
    assert main(["run", "--help"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines()[0] == "usage: scripts/02-run [--verbose] [--auto <task-or-suite>] pi|hermes|opencode <args...>"
    assert "Public operator wrapper for harness passthrough and automatic benchmark runs." in output
    assert "Modes:" in output
    assert "scripts/02-run pi config" in output
    assert "scripts/02-run --auto smoke-dependent-setup-chain" in output
    assert "scripts/02-run --verbose" in output
    for needle in ["bench run", "--root", "--tasks-root", "--run-id", "--role", "--catalog-label", "--catalog", "--dry-run"]:
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
                self.stdout = "pi version output\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["run", "pi", "--version"]) == 0
    assert [call["command"] for call in calls] == [list(SYNC_COMMAND), ["pi", "--version"]]
    assert calls[1]["env"] == {
        "BENCH_IN_CONTAINER": "1",
        "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/agent/run-1",
        "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/agent/run-1/orchestra",
    }


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
        "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/agent/run-1",
        "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/agent/run-1/orchestra",
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
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "failed": 0,
        "policy": "continue",
        "return_code": 0,
        "suite": "smoke",
        "task_count": 2,
        "passed": 2,
        "results": [
            {
                "batch": "smoke",
                "evaluation": {"score": "pass", "status": "ok"},
                "outcome": "pass",
                "result_json": str(tmp_path / "results" / "generated-alpha-run-alpha-run" / "result.json"),
                "run_id": "generated-alpha-run",
                "task_id": "alpha-run",
            },
            {
                "batch": "smoke",
                "evaluation": {"score": "pass", "status": "ok"},
                "outcome": "pass",
                "result_json": str(tmp_path / "results" / "generated-beta-run-beta-run" / "result.json"),
                "run_id": "generated-beta-run",
                "task_id": "beta-run",
            },
        ],
    }
    assert [call[0] for call in calls] == ["list_tasks", "resolve", "harness", "run_and_grade", "harness", "run_and_grade"]


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
                "/bench/task-materials-visible",
                "alpha-run",
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
                "/bench/task-materials-visible",
                "pi",
                "--catalog-label",
                "config/orchestra/agent-catalog.yaml",
                "--catalog",
                "/bench/orchestra-config/agent-catalog.yaml",
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
                "/bench/task-materials-visible",
                "smoke",
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

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = "{\"status\": \"ok\"}\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(argv) == 0
    assert calls == [
        {"command": list(SYNC_COMMAND), "workdir": Path("/bench"), "env": {"BENCH_IN_CONTAINER": "1"}, "verbose": False},
        {
            "command": expected_command,
            "workdir": Path("/bench"),
            "env": {
                "BENCH_IN_CONTAINER": "1",
                "PI_CODING_AGENT_DIR": f"{tmp_path}/.pi/agent/run-1",
                "PI_ORCHESTRA_RUNTIME_DIR": f"{tmp_path}/.pi/agent/run-1/orchestra",
            },
            "verbose": False,
        },
    ]
    assert capsys.readouterr().out == "{\"status\": \"ok\"}\n"


def test_auto_run_verbose_passes_verbose_flag_to_container_exec(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = "full harness session\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["run", "--auto", "alpha-run", "--verbose"]) == 0
    assert calls[1]["verbose"] is True
    assert capsys.readouterr().out == ""


def test_auto_run_rejects_ambiguous_task_and_suite_targets(tmp_path: Path, monkeypatch, capsys) -> None:
    task_root = tmp_path / "tasks"
    _write_task(task_root / "smoke", task_id="smoke")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bench.cli._inside_container", lambda: True, raising=False)

    assert main(["run", "--auto", "smoke", "--tasks-root", str(task_root), "--root", str(tmp_path), "--catalog", str(catalog_path)]) == 1
    assert "ambiguous" in capsys.readouterr().err


def test_auto_run_propagates_synced_runtime_summary_into_run_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    seen: dict[str, object] = {}
    runtime_summary = {
        "pi_runtime_dir": "/workspace/.pi/agent/run-1",
        "orchestra_runtime_dir": "/workspace/.pi/agent/run-1/orchestra",
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
    summary = json.loads(capsys.readouterr().out)
    assert summary["run_id"] == "run-1"
    assert summary["task_id"] == "alpha-run"
    assert summary["batch"] == "smoke"
    assert summary["outcome"] == "pass"
    assert summary["evaluation"] == {"score": "pass", "status": "ok"}
    assert summary["result_json"] == str(tmp_path / "results" / "run-1-alpha-run" / "result.json")
    assert summary["artifacts"] == {
        "evaluator": {
            "log": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "run.log"),
            "result": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "result.json"),
            "root": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator"),
            "stderr": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "stderr.txt"),
            "stdout": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "evaluator" / "stdout.txt"),
        },
        "harness": {
            "events": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "events.jsonl"),
            "log": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "run.log"),
            "root": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness"),
            "summary": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "summary.json"),
            "transcript": str(tmp_path / "results" / "run-1-alpha-run" / "artifacts" / "harness" / "transcript.txt"),
        },
    }
    assert seen["runtime_snapshot"] == runtime_summary
    assert seen["env"] == {
        "HARNESS_ENV": "catalog",
        "PI_CODING_AGENT_DIR": "/workspace/.pi/agent/run-1",
        "PI_ORCHESTRA_RUNTIME_DIR": "/workspace/.pi/agent/run-1/orchestra",
    }
    assert seen["harness"] == ("fake-harness",)


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
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "failed": 1,
        "passed": 1,
        "policy": "continue",
        "return_code": 1,
        "suite": "smoke",
        "task_count": 2,
        "results": [
            {
                "batch": "smoke",
                "evaluation": {"score": "pass", "status": "ok"},
                "outcome": "pass",
                "result_json": str(tmp_path / "results" / "generated-alpha-run-alpha-run" / "result.json"),
                "run_id": "generated-alpha-run",
                "task_id": "alpha-run",
            },
            {
                "batch": "smoke",
                "evaluation": {"score": "fail", "status": "ok"},
                "outcome": "fail",
                "result_json": str(tmp_path / "results" / "generated-beta-run-beta-run" / "result.json"),
                "run_id": "generated-beta-run",
                "task_id": "beta-run",
            },
        ],
    }
    assert run_order == ["alpha-run", "beta-run"]


def test_exec_routes_passthrough_harness_inside_container(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = json.dumps({"pi_runtime_dir": "/workspace/.pi/agent/run-1", "orchestra_runtime_dir": "/workspace/.pi/agent/run-1/orchestra"}) + "\n"
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
                "PI_CODING_AGENT_DIR": "/workspace/.pi/agent/run-1",
                "PI_ORCHESTRA_RUNTIME_DIR": "/workspace/.pi/agent/run-1/orchestra",
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
                self.stdout = json.dumps({"pi_runtime_dir": "/workspace/.pi/agent/run-1", "orchestra_runtime_dir": "/workspace/.pi/agent/run-1/orchestra"}) + "\n"
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
            "PI_CODING_AGENT_DIR": "/workspace/.pi/agent/run-1",
            "PI_ORCHESTRA_RUNTIME_DIR": "/workspace/.pi/agent/run-1/orchestra",
        },
        "verbose": True,
        "interactive": False,
        "tty": False,
        "transcript_path": None,
    }
    assert capsys.readouterr().out == ""


SYNC_COMMAND = ["python3", "-m", "bench.runtime", "init-runtime"]


def _sync_summary_payload(tmp_path: Path) -> str:
    return json.dumps(
        {
            "pi_runtime_dir": f"{tmp_path}/.pi/agent/run-1",
            "orchestra_runtime_dir": f"{tmp_path}/.pi/agent/run-1/orchestra",
        }
    )


def _fake_container_exec(tmp_path: Path, calls: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    class _Completed:
        def __init__(self, command: list[str]) -> None:
            self.returncode = 0
            if list(command) == SYNC_COMMAND:
                self.stdout = _sync_summary_payload(tmp_path) + "\n"
            else:
                self.stdout = f"harness output for {command[1] if len(command) > 1 else ''}\n"
            self.stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed(list(command))

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
    assert harness_call["env"]["PI_CODING_AGENT_DIR"] == f"{tmp_path}/.pi/agent/run-1"
    assert harness_call["env"]["PI_ORCHESTRA_RUNTIME_DIR"] == f"{tmp_path}/.pi/agent/run-1/orchestra"


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
                    '  "pi_runtime_dir": "/workspace/.pi/agent/run-1",\n'
                    '  "orchestra_runtime_dir": "/workspace/.pi/agent/run-1/orchestra"\n'
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
    assert harness_call["env"]["PI_CODING_AGENT_DIR"] == "/workspace/.pi/agent/run-1"
    assert harness_call["env"]["PI_ORCHESTRA_RUNTIME_DIR"] == "/workspace/.pi/agent/run-1/orchestra"


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
                "pi_runtime_dir": "/workspace/.pi/agent/run-1",
                "orchestra_runtime_dir": "/workspace/.pi/agent/run-1/orchestra",
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
        "  pi runtime dir: /workspace/.pi/agent/run-1",
        "  orchestra runtime dir: /workspace/.pi/agent/run-1/orchestra",
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

    def fake_build_debug_report(run_paths, *, entry=None):  # type: ignore[no-untyped-def]
        calls.append(("debug", run_paths, entry))
        return {"run_id": run_paths.run_id}

    def fake_format_debug_report(report):  # type: ignore[no-untyped-def]
        calls.append(("debug_format", report))
        return "debug view\n"

    monkeypatch.setattr("bench.cli.select_results", fake_select_results, raising=False)
    monkeypatch.setattr("bench.cli.format_dashboard", fake_format_dashboard, raising=False)
    monkeypatch.setattr("bench.cli.format_runs", fake_format_runs, raising=False)
    monkeypatch.setattr("bench.cli.format_run_detail", fake_format_run_detail, raising=False)
    monkeypatch.setattr("bench.cli.format_tokens", fake_format_tokens, raising=False)
    monkeypatch.setattr("bench.cli.format_timing", fake_format_timing, raising=False)
    monkeypatch.setattr("bench.cli.build_debug_report", fake_build_debug_report, raising=False)
    monkeypatch.setattr("bench.cli.format_debug_report", fake_format_debug_report, raising=False)

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
    assert main(["results", "debug", f"{run_id}-{task_id}"]) == 0
    assert capsys.readouterr().out == "debug view\n"
    assert main(["results"]) == 0
    assert capsys.readouterr().out == "dashboard view\n"

    assert [call[0] for call in calls] == ["select", "dashboard", "select", "runs", "select", "run", "select", "tokens", "select", "timing", "select", "debug", "debug_format", "select", "dashboard"]
    assert calls[0] == ("select", tmp_path, None, {"task": None, "suite": None, "model": None, "orchestra": None, "sort": "finished_at", "reverse": True, "limit": None})
    assert calls[5][1].run_id == run_id
    assert calls[10] == ("select", None, None, {"task": None, "suite": None, "model": None, "orchestra": None, "sort": "finished_at", "reverse": True, "limit": None})
    assert calls[11][1].run_id == run_id
    assert calls[11][2] == entry


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
    assert "evaluation=failed" in rescore_output
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
