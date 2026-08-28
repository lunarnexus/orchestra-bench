from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.cli import build_parser, main
from bench.paths import RunPaths
from bench.reporting.queries import ReportEntry
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result
from bench.tasks import load_task


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


def test_help_lists_public_commands(capsys) -> None:
    assert main(["help"]) == 0
    output = capsys.readouterr().out
    first_line = output.splitlines()[0]
    assert "{help,start,run,results,debug,doctor}" in first_line
    assert "runtime" not in first_line
    assert "grade" not in first_line
    assert "suite" not in first_line


def test_list_shows_v1_tasks(capsys) -> None:
    assert main(["list", "--tasks-root", "V1/tasks"]) == 0
    output = capsys.readouterr().out
    assert "cap-easy-fastapi-helpdesk" in output
    assert "cap-normal-ts-approval-queue" in output


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
    assert output["suite"] == "smoke"
    assert [item["run_meta"]["task_id"] for item in output["results"]] == ["alpha-run", "beta-run"]
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
        returncode = 0
        stdout = "{\"status\": \"ok\"}\n"
        stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed()

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(argv) == 0
    assert calls == [{"command": expected_command, "workdir": Path("/bench"), "env": {"BENCH_IN_CONTAINER": "1"}, "verbose": False}]
    assert capsys.readouterr().out == "{\"status\": \"ok\"}\n"


def test_exec_routes_passthrough_harness_inside_container(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    calls: list[dict[str, object]] = []

    class _Completed:
        returncode = 0
        stdout = "pi config output\n"
        stderr = ""

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed()

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "pi", "config"]) == 0
    assert calls == [{"command": ["pi", "config"], "workdir": Path("/bench"), "env": {"BENCH_IN_CONTAINER": "1"}, "verbose": False}]
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
        returncode = 0
        stdout = None
        stderr = None

    def fake_container_exec(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"command": list(command), **kwargs})
        return _Completed()

    monkeypatch.setattr("bench.cli.container_exec", fake_container_exec, raising=False)

    assert main(["exec", "--verbose", "pi", "config"]) == 0
    assert calls == [{"command": ["pi", "config"], "workdir": Path("/bench"), "env": {"BENCH_IN_CONTAINER": "1"}, "verbose": True}]
    assert capsys.readouterr().out == ""


def test_start_parser_accepts_documented_actions() -> None:
    for action in ("build", "start", "recreate", "init"):
        args = build_parser().parse_args(["start", action])
        assert args.start_action == action


def test_start_parser_rejects_unknown_action() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["start", "bogus"])


def test_start_build_dispatches_to_image_builder(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    def fake_build_image(root=None, image_name=None):  # type: ignore[no-untyped-def]
        seen["root"] = root
        return {"action": "build", "image": "orchestra-bench-env"}

    monkeypatch.setattr("bench.cli.build_image", fake_build_image)

    assert main(["start", "build"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "build"
    assert Path(seen["root"]) == Path.cwd()


def test_start_routes_container_actions(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    def fake_start_container(root=None, image_name=None):  # type: ignore[no-untyped-def]
        seen["start"] = root
        return {"action": "reuse", "container": "orchestra-bench-runner"}

    def fake_recreate_container(root=None, image_name=None):  # type: ignore[no-untyped-def]
        seen["recreate"] = root
        return {"action": "recreate", "container": "orchestra-bench-runner"}

    monkeypatch.setattr("bench.cli.start_container", fake_start_container)
    monkeypatch.setattr("bench.cli.recreate_container", fake_recreate_container)

    assert main(["start", "start"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "reuse"
    assert main(["start", "recreate"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "recreate"
    assert Path(seen["start"]) == Path.cwd()
    assert Path(seen["recreate"]) == Path.cwd()


def test_start_init_routes_through_runtime_init(monkeypatch, capsys) -> None:
    fake_env = object()
    seen: dict[str, object] = {}

    monkeypatch.setattr("bench.cli.RuntimeEnvironment.from_env", classmethod(lambda cls: fake_env))

    def fake_runtime_init(env):  # type: ignore[no-untyped-def]
        seen["env"] = env
        return {"status": "ok"}

    monkeypatch.setattr("bench.cli.runtime_init", fake_runtime_init, raising=False)

    assert main(["start", "init"]) == 0
    assert seen["env"] is fake_env
    assert capsys.readouterr().out == '{\n  "status": "ok"\n}\n'


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

    def fake_collect_results(results_dir=None, tasks_dir=None):  # type: ignore[no-untyped-def]
        calls.append(("collect", results_dir, tasks_dir))
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

    monkeypatch.setattr("bench.cli.collect_results", fake_collect_results, raising=False)
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

    assert [call[0] for call in calls] == ["collect", "dashboard", "collect", "runs", "collect", "run", "collect", "tokens", "collect", "timing", "collect", "debug", "debug_format", "collect", "dashboard"]
    assert calls[0] == ("collect", tmp_path, None)
    assert calls[5][1].run_id == run_id
    assert calls[10] == ("collect", None, None)
    assert calls[11][1].run_id == run_id
    assert calls[11][2] == entry
