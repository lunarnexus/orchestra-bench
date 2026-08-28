from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bench.runtime import (
    CONTAINER_NAME,
    DEFAULT_IMAGE_NAME,
    RuntimeEnvironment,
    build_image,
    cleanup_workdir,
    container_exec,
    doctor,
    init_runtime,
    prepare_workdir,
    recreate_container,
    start_container,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_static_runtime_contract_files_encode_thin_entrypoint_and_image_contract() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    runtime = (REPO_ROOT / "bench" / "runtime.py").read_text(encoding="utf-8")

    assert "python3 -m bench.runtime" in entrypoint
    assert "exec tail -f /dev/null" in entrypoint
    assert "COPY bench/ /opt/orchestra-bench/bench/" in dockerfile
    assert "ENV PYTHONPATH=/opt/orchestra-bench" in dockerfile
    assert "BENCH_TASKS=/bench/task-materials-visible" in dockerfile
    assert "PI_CODING_AGENT_DIR=/workspace/.pi/agent" not in dockerfile
    assert "PI_ORCHESTRA_RUNTIME_DIR=/workspace/.pi/agent/orchestra" not in dockerfile
    assert "PI_LMSTUDIO_RUNTIME_FILE=/workspace/.pi/agent/lmstudio.json" not in dockerfile
    assert "pi install \"$PI_LMSTUDIO_PLUGIN_URL\"" in dockerfile
    assert "#RUN pi install \"$PI_CODEGRAPH_PLUGIN_URL\"" in dockerfile
    assert "#RUN pi install \"$PI_WEB_TOOLS_PLUGIN_URL\"" in dockerfile
    # Docker build inputs must exist so the image can be built from this tree.
    assert (REPO_ROOT / "config" / "pi" / "settings.json").is_file()
    assert (REPO_ROOT / "config" / "skills").is_dir()
    assert "pkg-config" in dockerfile
    assert '"orchestra", "init", "pi", "--copy", "--force"' in runtime
    assert "agent-catalog.yaml" in runtime
    assert "prepare-workdir" in runtime
    assert "cleanup" in runtime
    assert "doctor" in runtime


def test_runtime_environment_uses_run_scoped_pi_agent_dir_by_default() -> None:
    runtime = RuntimeEnvironment.from_env(
        {
            "BENCH_WORKSPACE": "/workspace",
            "BENCH_RUN_ID": "20250101T010203",
        }
    )

    assert runtime.orchestra_runtime_dir == Path("/workspace/.pi/agent/20250101T010203/orchestra")
    assert runtime.lmstudio_runtime_file == Path("/workspace/.pi/agent/20250101T010203/lmstudio.json")


def test_runtime_environment_rejects_shared_pi_agent_dir() -> None:
    with pytest.raises(ValueError, match="run-scoped"):
        RuntimeEnvironment.from_env(
            {
                "BENCH_WORKSPACE": "/workspace",
                "BENCH_RUN_ID": "20250101T010203",
                "PI_CODING_AGENT_DIR": "/workspace/.pi/agent",
            }
        )


def test_prepare_workdir_copies_only_agent_visible_task_files(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "runtime-task"
    fixture_dir = task_dir / "fixture"
    kb_dir = task_dir / "kb"
    fixture_dir.mkdir(parents=True)
    kb_dir.mkdir()

    (task_dir / "task.yaml").write_text(
        "task_id: runtime-task\n"
        "description: runtime contract\n"
        "family: smoke\n"
        "batch: smoke\n"
        "timeout_minutes: 5\n"
        "evaluator: evaluate/run.sh\n"
        "split: dev\n"
    )
    (task_dir / "PRD.md").write_text("prd\n")
    (task_dir / "Prompt.md").write_text("prompt\n")
    (fixture_dir / "seed.txt").write_text("fixture\n")
    (kb_dir / "notes.md").write_text("kb\n")
    (task_dir / "secret.txt").write_text("hidden\n")

    runtime = RuntimeEnvironment(
        tasks_root=tasks_root,
        results_root=tmp_path / "results",
        artifacts_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspace",
        orchestra_config_src=tmp_path / "orchestra-config",
        lmstudio_config_src=tmp_path / "config" / "pi" / "lmstudio.json",
        pi_skills_src=tmp_path / "skills",
        orchestra_runtime_dir=tmp_path / "runtime" / "orchestra",
        lmstudio_runtime_file=tmp_path / "runtime" / "lmstudio.json",
        run_id="20250101T010203",
    )

    workdir = prepare_workdir("runtime-task", runtime)

    assert workdir == tmp_path / "workspace" / "20250101T010203-runtime-task"
    assert (workdir / "PRD.md").read_text(encoding="utf-8") == "prd\n"
    assert (workdir / "Prompt.md").read_text(encoding="utf-8") == "prompt\n"
    assert (workdir / "seed.txt").read_text(encoding="utf-8") == "fixture\n"
    assert (workdir / "kb" / "notes.md").read_text(encoding="utf-8") == "kb\n"
    assert not (workdir / "evaluate").exists()
    assert not (workdir / "secret.txt").exists()


def test_prepare_workdir_rejects_exposed_evaluate_directory(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "runtime-task"
    fixture_dir = task_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (task_dir / "evaluate").mkdir()
    (task_dir / "task.yaml").write_text(
        "task_id: runtime-task\n"
        "description: runtime contract\n"
        "family: smoke\n"
        "batch: smoke\n"
        "timeout_minutes: 5\n"
        "evaluator: evaluate/run.sh\n"
        "split: dev\n"
    )
    (task_dir / "PRD.md").write_text("prd\n")
    (task_dir / "Prompt.md").write_text("prompt\n")

    runtime = RuntimeEnvironment(
        tasks_root=tasks_root,
        results_root=tmp_path / "results",
        artifacts_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspace",
        orchestra_config_src=tmp_path / "orchestra-config",
        lmstudio_config_src=tmp_path / "config" / "pi" / "lmstudio.json",
        pi_skills_src=tmp_path / "skills",
        orchestra_runtime_dir=tmp_path / "runtime" / "orchestra",
        lmstudio_runtime_file=tmp_path / "runtime" / "lmstudio.json",
        run_id="20250101T010203",
    )

    with pytest.raises(ValueError, match="must not expose evaluate"):
        prepare_workdir("runtime-task", runtime)


def test_init_runtime_overlays_catalog_without_requiring_orchestra_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "orchestra-config"
    skills = tmp_path / "skills"
    runtime_dir = tmp_path / "runtime" / "orchestra"
    lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"
    lmstudio_runtime = tmp_path / "runtime" / "lmstudio.json"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "orchestra.log"

    source.mkdir(parents=True)
    skills.mkdir(parents=True)
    lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir()
    (source / "agent-catalog.yaml").write_text("default_role: builder\n")
    (skills / "builder.md").write_text("skill\n")
    lmstudio_source.write_text('{"url": "http://localhost:1234"}\n')

    _write_executable(
        bin_dir / "orchestra",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n"
    )
    _write_executable(
        bin_dir / "pi",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "if [ \"${1:-}\" = '--version' ]; then\n"
        "  printf 'pi 0.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' \"$*\" >> \"$PI_LOG\"\n"
    )

    runtime = RuntimeEnvironment(
        tasks_root=tmp_path / "tasks",
        results_root=tmp_path / "results",
        artifacts_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspace",
        orchestra_config_src=source,
        lmstudio_config_src=lmstudio_source,
        pi_skills_src=skills,
        orchestra_runtime_dir=runtime_dir,
        lmstudio_runtime_file=lmstudio_runtime,
        run_id="20250101T010203",
    )

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(log))
    monkeypatch.setenv("PI_LOG", str(tmp_path / "pi.log"))

    summary = init_runtime(runtime)

    assert summary["catalog_path"] == str(runtime_dir / "agent-catalog.yaml")
    assert (runtime_dir / "agent-catalog.yaml").read_text(encoding="utf-8") == "default_role: builder\n"
    assert not (runtime_dir / "config.yaml").exists()
    assert not (runtime_dir / "prompts.yaml").exists()
    assert lmstudio_runtime.read_text(encoding="utf-8") == '{"url": "http://localhost:1234"}\n'
    assert (runtime.pi_skills_runtime_dir / "builder.md").read_text(encoding="utf-8") == "skill\n"
    assert log.read_text(encoding="utf-8").splitlines() == ["init pi --copy --force"]


def test_cleanup_and_doctor_keep_runtime_separate_from_prepared_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "orchestra-config"
    tasks_root = tmp_path / "tasks"
    workdir_task = tasks_root / "runtime-task"
    source.mkdir(parents=True)
    workdir_task.mkdir(parents=True)
    (source / "agent-catalog.yaml").write_text("default_role: builder\n")
    (workdir_task / "task.yaml").write_text(
        "task_id: runtime-task\n"
        "description: runtime contract\n"
        "family: smoke\n"
        "batch: smoke\n"
        "timeout_minutes: 5\n"
        "evaluator: evaluate/run.sh\n"
        "split: dev\n"
    )
    (workdir_task / "PRD.md").write_text("prd\n")
    (workdir_task / "Prompt.md").write_text("prompt\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "orchestra",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n"
    )
    _write_executable(
        bin_dir / "pi",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "if [ \"${1:-}\" = '--version' ]; then\n"
        "  printf 'pi 0.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )

    workspace_root = tmp_path / "workspace"
    runtime = RuntimeEnvironment(
        tasks_root=tasks_root,
        results_root=tmp_path / "results",
        artifacts_root=tmp_path / "artifacts",
        workspace_root=workspace_root,
        orchestra_config_src=source,
        lmstudio_config_src=tmp_path / "config" / "pi" / "lmstudio.json",
        pi_skills_src=tmp_path / "skills",
        orchestra_runtime_dir=workspace_root / ".pi" / "agent" / "20250101T010203" / "orchestra",
        lmstudio_runtime_file=workspace_root / ".pi" / "agent" / "20250101T010203" / "lmstudio.json",
        run_id="20250101T010203",
    )
    runtime.lmstudio_config_src.parent.mkdir(parents=True, exist_ok=True)
    runtime.lmstudio_config_src.write_text('{"url": "http://localhost:1234"}\n')
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(tmp_path / "orchestra.log"))

    init_runtime(runtime)
    workdir = prepare_workdir("runtime-task", runtime)
    assert workdir.exists()
    assert doctor(runtime) == 0

    removed = cleanup_workdir("runtime-task", runtime)

    assert removed == [workdir]
    assert not workdir.exists()
    assert (runtime.orchestra_runtime_dir / "agent-catalog.yaml").exists()


def _write_fake_docker(bin_dir: Path) -> Path:
    log = bin_dir / "docker.log"
    script = bin_dir / "docker"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$FAKE_DOCKER_LOG"\n'
        'case "${1:-}" in\n'
        '  inspect)\n'
        '    if [ -f "$FAKE_DOCKER_STATE_FILE" ]; then cat "$FAKE_DOCKER_STATE_FILE"; exit 0; fi\n'
        "    exit 1\n"
        "    ;;\n"
        '  image)\n'
        '    if [ -f "$FAKE_DOCKER_IMAGE_OK_FILE" ]; then exit 0; fi\n'
        "    exit 1\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return log


def _write_build_inputs(root: Path) -> None:
    (root / "docker").mkdir(parents=True, exist_ok=True)
    (root / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (root / "config" / "pi").mkdir(parents=True)
    (root / "config" / "pi" / "settings.json").write_text("{}\n", encoding="utf-8")
    (root / "config" / "pi" / "lmstudio.json").write_text('{"url": "http://localhost:1234"}\n', encoding="utf-8")
    (root / "config" / "skills").mkdir(parents=True, exist_ok=True)
    (root / "V1" / "tasks").mkdir(parents=True, exist_ok=True)


def test_build_image_invokes_docker_with_repo_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    _write_build_inputs(root)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))

    report = build_image(root)

    assert report["action"] == "build"
    assert report["image"] == DEFAULT_IMAGE_NAME
    command_lines = log.read_text(encoding="utf-8").splitlines()
    assert len(command_lines) == 1
    command = command_lines[0].split()
    assert command[:1] == ["build"]
    assert "--build-arg" in command and any(part.startswith("SOURCE_PLUGIN_CACHE_BUST=") for part in command)
    assert str(root / "docker" / "Dockerfile") in command
    assert DEFAULT_IMAGE_NAME in command
    assert str(root) in command


def test_build_image_fails_fast_when_config_inputs_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / "docker").mkdir(parents=True)
    (root / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_docker(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    with pytest.raises(FileNotFoundError, match="config/pi/settings.json"):
        build_image(root)


def test_start_container_reuses_running_and_starts_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    _write_build_inputs(root)
    (root / "config" / "orchestra").mkdir(parents=True)
    (root / "config" / "orchestra" / "agent-catalog.yaml").write_text("default_role: builder\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    state_file = bin_dir / "fake-container-state"
    (bin_dir / "fake-image-ok").touch()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_STATE_FILE", str(state_file))
    monkeypatch.setenv("FAKE_DOCKER_IMAGE_OK_FILE", str(bin_dir / "fake-image-ok"))

    state_file.write_text("true\n")
    report = start_container(root)
    assert report["action"] == "reuse"
    assert log.read_text(encoding="utf-8").splitlines() == [f"inspect -f {{{{.State.Running}}}} {CONTAINER_NAME}"]

    state_file.write_text("false\n")
    log.write_text("")
    report = start_container(root)
    assert report["action"] == "start"
    assert log.read_text(encoding="utf-8").splitlines()[-1] == f"start {CONTAINER_NAME}"


def test_start_container_creates_fresh_with_v2_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    _write_build_inputs(root)
    (root / "config" / "orchestra").mkdir(parents=True)
    catalog = root / "config" / "orchestra" / "agent-catalog.yaml"
    catalog.write_text("default_role: builder\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    (bin_dir / "fake-image-ok").touch()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_IMAGE_OK_FILE", str(bin_dir / "fake-image-ok"))

    report = start_container(root)

    assert report["action"] == "create"
    run_line = [line for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("run ")]
    assert len(run_line) == 1
    mounts = run_line[0].split()
    expected_mounts = [
        f"{root / 'results'}:/bench/results",
        f"{root / 'artifacts'}:/bench/artifacts",
        f"{catalog}:/bench/orchestra-config/agent-catalog.yaml:ro",
        f"{root / 'config' / 'pi' / 'lmstudio.json'}:/bench/pi/lmstudio.json:ro",
        f"{root / 'config' / 'skills'}:/bench/skills:ro",
        f"{root / 'V1' / 'tasks'}:/bench/task-materials-visible:ro",
    ]
    for expected in expected_mounts:
        assert "-v" in mounts and expected in mounts
    assert (root / "results").is_dir()
    assert (root / "artifacts").is_dir()


def test_start_container_requires_project_catalog_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    _write_build_inputs(root)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    (bin_dir / "fake-image-ok").touch()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_IMAGE_OK_FILE", str(bin_dir / "fake-image-ok"))

    with pytest.raises(FileNotFoundError, match="agent-catalog.yaml"):
        start_container(root)


def test_recreate_container_removes_then_creates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    _write_build_inputs(root)
    (root / "config" / "orchestra").mkdir(parents=True)
    (root / "config" / "orchestra" / "agent-catalog.yaml").write_text("default_role: builder\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    state_file = bin_dir / "fake-container-state"
    (bin_dir / "fake-image-ok").touch()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_STATE_FILE", str(state_file))
    monkeypatch.setenv("FAKE_DOCKER_IMAGE_OK_FILE", str(bin_dir / "fake-image-ok"))

    state_file.write_text("true\n")
    report = recreate_container(root)

    assert report["action"] == "recreate"
    lines = log.read_text(encoding="utf-8").splitlines()
    rm_index = next(i for i, line in enumerate(lines) if line == f"rm -f {CONTAINER_NAME}")
    run_index = next(i for i, line in enumerate(lines) if line.startswith("run "))
    assert rm_index < run_index


def test_container_exec_builds_docker_exec_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))

    completed = container_exec(
        ["python3", "-m", "bench.cli", "run", "--auto", "alpha-run"],
        workdir="/bench",
        env={"BENCH_IN_CONTAINER": "1"},
        verbose=False,
    )

    assert completed.returncode == 0
    log_line = log.read_text(encoding="utf-8").splitlines()[-1]
    assert log_line.startswith("exec -e BENCH_IN_CONTAINER=1 -w /bench orchestra-bench-runner python3 -m bench.cli run --auto alpha-run")


@pytest.mark.skipif(os.environ.get("BENCH_RUN_DOCKER") != "1", reason="set BENCH_RUN_DOCKER=1 to enable real Docker smoke")
def test_real_docker_smoke_is_gated(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker unavailable")

    dockerfile = REPO_ROOT / "docker" / "Dockerfile"
    image = "orchestra-bench-runtime-contract:test"

    orchestra_src = tmp_path / "orchestra-config"
    skills_src = tmp_path / "skills"
    task_materials_root = tmp_path / "task-materials"
    workspace_root = tmp_path / "workspace"
    results_root = tmp_path / "results"
    artifacts_root = tmp_path / "artifacts"
    lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"
    runtime_dir = workspace_root / ".pi" / "agent" / "20250101T010203" / "orchestra"
    lmstudio_runtime = workspace_root / ".pi" / "agent" / "20250101T010203" / "lmstudio.json"
    task_dir = task_materials_root / "runtime-task"

    orchestra_src.mkdir(parents=True)
    skills_src.mkdir(parents=True)
    task_dir.mkdir(parents=True)
    workspace_root.mkdir(parents=True)
    results_root.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    (orchestra_src / "agent-catalog.yaml").write_text("default_role: builder\n")
    (skills_src / "builder.md").write_text("skill\n")
    lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
    lmstudio_source.write_text('{"url": "http://localhost:1234"}\n')
    (task_dir / "task.yaml").write_text(
        "task_id: runtime-task\n"
        "description: runtime contract\n"
        "family: smoke\n"
        "batch: smoke\n"
        "timeout_minutes: 5\n"
        "evaluator: evaluate/run.sh\n"
        "split: dev\n"
    )
    (task_dir / "PRD.md").write_text("prd\n")
    (task_dir / "Prompt.md").write_text("prompt\n")
    (task_dir / "fixture").mkdir()
    (task_dir / "fixture" / "seed.txt").write_text("fixture\n")

    subprocess.run(["docker", "build", "-f", str(dockerfile), "-t", image, str(REPO_ROOT)], check=True)

    mounts = [
        "-v", f"{orchestra_src}:/bench/orchestra-config:ro",
        "-v", f"{lmstudio_source}:/bench/pi/lmstudio.json:ro",
        "-v", f"{skills_src}:/bench/skills:ro",
        "-v", f"{task_materials_root}:/bench/task-materials-visible:ro",
        "-v", f"{workspace_root}:/workspace",
        "-v", f"{results_root}:/bench/results",
        "-v", f"{artifacts_root}:/bench/artifacts",
    ]
    env = [
        "-e", "BENCH_RUN_ID=20250101T010203",
        "-e", "BENCH_TASKS=/bench/task-materials-visible",
        "-e", "BENCH_RESULTS=/bench/results",
        "-e", "BENCH_ARTIFACTS=/bench/artifacts",
        "-e", "BENCH_WORKSPACE=/workspace",
        "-e", "BENCH_ORCHESTRA_CONFIG_SRC=/bench/orchestra-config",
        "-e", "BENCH_LMSTUDIO_CONFIG_SRC=/bench/pi/lmstudio.json",
        "-e", "BENCH_PI_SKILLS_SRC=/bench/skills",
    ]

    subprocess.run(["docker", "run", "--rm", *env, *mounts, image, "init-runtime"], check=True)
    subprocess.run(["docker", "run", "--rm", *env, *mounts, image, "prepare-workdir", "runtime-task"], check=True)
    subprocess.run(["docker", "run", "--rm", *env, *mounts, image, "doctor"], check=True)

    assert (runtime_dir / "agent-catalog.yaml").read_text(encoding="utf-8") == "default_role: builder\n"
    assert (lmstudio_runtime).read_text(encoding="utf-8") == '{"url": "http://localhost:1234"}\n'
    assert (workspace_root / "20250101T010203-runtime-task" / "seed.txt").read_text(encoding="utf-8") == "fixture\n"
    assert not (task_materials_root / "runtime-task" / "evaluate" / "run.sh").exists()
