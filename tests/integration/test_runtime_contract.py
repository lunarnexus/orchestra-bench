from __future__ import annotations

import json
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
    prepare_startup,
    prepare_workdir,
    recreate_container,
    start_container,
)
from bench.runtime import main as runtime_main

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
    assert "BENCH_TASKS=/bench/task-materials-source" in dockerfile
    assert "BENCH_ORCHESTRA_EXTENSION_SRC=/bench/orchestra-extension" in dockerfile
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

    assert runtime.tasks_root == Path("/bench/task-materials-source")
    assert runtime.home_dir == Path("/workspace/.pi/home/20250101T010203")
    assert runtime.pi_runtime_dir == Path("/workspace/.pi/home/20250101T010203/.pi/agent")
    assert runtime.orchestra_runtime_dir == Path("/workspace/.pi/home/20250101T010203/.pi/agent/orchestra")
    assert runtime.lmstudio_runtime_file == Path("/workspace/.pi/home/20250101T010203/.pi/agent/lmstudio.json")


def test_runtime_environment_rejects_shared_pi_agent_dir() -> None:
    with pytest.raises(ValueError, match="HOME/.pi/agent"):
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


def test_prepare_workdir_uses_hidden_task_source_without_copying_evaluate(tmp_path: Path) -> None:
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
    (fixture_dir / "seed.txt").write_text("fixture\n")

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
    assert (workdir / "Prompt.md").read_text(encoding="utf-8") == "prompt\n"
    assert (workdir / "seed.txt").read_text(encoding="utf-8") == "fixture\n"
    assert not (workdir / "evaluate").exists()


def test_init_runtime_overlays_catalog_without_requiring_orchestra_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "orchestra-config"
    extension_source = tmp_path / "orchestra-extension-src"
    skills = tmp_path / "skills"
    home_dir = tmp_path / "home" / "20250101T010203"
    runtime_dir = home_dir / ".pi" / "agent" / "orchestra"
    extension_runtime = home_dir / ".pi" / "agent" / "extensions" / "orchestra"
    lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"
    lmstudio_runtime = home_dir / ".pi" / "agent" / "lmstudio.json"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "orchestra.log"

    source.mkdir(parents=True)
    extension_source.mkdir(parents=True)
    skills.mkdir(parents=True)
    lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir()
    (source / "agent-catalog.yaml").write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: ['pi']\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: example/model\n"
        "    prompt_addition: keep me out of runtime sync\n"
    )
    (skills / "builder.md").write_text("skill\n")
    (extension_source / "index.ts").write_text(
        'ctx.ui.setStatus("orchestra", "current source")\n',
        encoding="utf-8",
    )
    extension_runtime.mkdir(parents=True, exist_ok=True)
    (extension_runtime / "index.ts").write_text(
        'ctx.ui.setWidget("orchestra", { text })\n',
        encoding="utf-8",
    )
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
        orchestra_extension_src=extension_source,
        orchestra_runtime_dir=runtime_dir,
        lmstudio_runtime_file=lmstudio_runtime,
        hermes_runtime_dir=tmp_path / "hermes-runtime",
        opencode_runtime_dir=tmp_path / "opencode-runtime",
        run_id="20250101T010203",
    )

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(log))
    monkeypatch.setenv("PI_LOG", str(tmp_path / "pi.log"))

    summary = init_runtime(runtime)

    assert summary["catalog_path"] == str(runtime_dir / "agent-catalog.yaml")
    catalog_text = (runtime_dir / "agent-catalog.yaml").read_text(encoding="utf-8")
    assert "prompt_addition" not in catalog_text
    assert "example/model" in catalog_text
    extension_text = (extension_runtime / "index.ts").read_text(encoding="utf-8")
    assert "setWidget(\"orchestra\", { text }" not in extension_text
    assert "setStatus(\"orchestra\"" in extension_text
    assert not (runtime_dir / "config.yaml").exists()
    assert not (runtime_dir / "prompts.yaml").exists()
    assert lmstudio_runtime.read_text(encoding="utf-8") == '{"url": "http://localhost:1234"}\n'
    assert (runtime.pi_skills_runtime_dir / "builder.md").read_text(encoding="utf-8") == "skill\n"
    assert log.read_text(encoding="utf-8").splitlines() == ["init pi --copy --force", "_tool-info"]


def test_init_runtime_overlays_regular_config_directories_and_records_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestra_src = tmp_path / "orchestra-config"
    pi_src = tmp_path / "pi-config"
    hermes_src = tmp_path / "hermes-config"
    opencode_src = tmp_path / "opencode-config"
    skills = tmp_path / "skills"
    # Pi runtime lives under a run-scoped HOME so HOME/.pi/agent becomes the
    # active Pi agent dir.
    home_dir = tmp_path / "home" / "20250101T010203"
    pi_runtime = home_dir / ".pi" / "agent"
    runtime_dir = pi_runtime / "orchestra"
    hermes_runtime = tmp_path / "runtime" / "hermes"
    opencode_runtime = tmp_path / "runtime" / "opencode"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "orchestra.log"

    for path in (orchestra_src, pi_src, hermes_src, opencode_src, skills, bin_dir):
        path.mkdir(parents=True, exist_ok=True)

    (orchestra_src / "agent-catalog.yaml").write_text("default_role: builder\n")
    (orchestra_src / "config.yaml").write_text("version: one\n")
    (pi_src / "settings.json").write_text('{"enableInstallTelemetry": false}\n')
    (pi_src / "lmstudio.json").write_text('{"url": "http://localhost:1234"}\n')
    (hermes_src / "config.yaml").write_text("model: hermes-test\n")
    (opencode_src / "opencode.json").write_text('{"model": "opencode-test"}\n')
    (skills / "builder" / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (skills / "builder" / "SKILL.md").write_text("skill\n")

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
        orchestra_config_src=orchestra_src,
        lmstudio_config_src=pi_src / "lmstudio.json",
        pi_config_src=pi_src,
        hermes_config_src=hermes_src,
        opencode_config_src=opencode_src,
        pi_skills_src=skills,
        home_dir=home_dir,
        orchestra_runtime_dir=runtime_dir,
        lmstudio_runtime_file=pi_runtime / "lmstudio.json",
        hermes_runtime_dir=hermes_runtime,
        opencode_runtime_dir=opencode_runtime,
        run_id="20250101T010203",
    )

    monkeypatch.setattr("bench.runtime.PI_AGENT_STATE_SRC", tmp_path / "root-agent", raising=False)
    (tmp_path / "root-agent" / "settings.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "root-agent" / "settings.json").write_text(
        '{"packages": ["http://git.lunarnexus.local:3000/james/pi-lmstudio"]}\n',
        encoding="utf-8",
    )
    (tmp_path / "root-agent" / "git" / "git.lunarnexus.local" / "james" / "pi-lmstudio").mkdir(parents=True, exist_ok=True)
    (tmp_path / "root-agent" / "git" / "git.lunarnexus.local" / "james" / "pi-lmstudio" / "marker.txt").write_text("installed\n", encoding="utf-8")

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(log))
    monkeypatch.setenv("PI_LOG", str(tmp_path / "pi.log"))

    summary = init_runtime(runtime)

    assert summary["orchestra_config_files"] == ["agent-catalog.yaml", "config.yaml"]
    assert summary["pi_config_files"] == ["lmstudio.json", "settings.json"]
    assert summary["hermes_config_files"] == ["config.yaml"]
    assert summary["opencode_config_files"] == ["opencode.json"]
    assert (runtime_dir / "agent-catalog.yaml").read_text(encoding="utf-8") == "default_role: builder\n"
    assert (runtime_dir / "config.yaml").read_text(encoding="utf-8") == "version: one\n"
    assert json.loads((pi_runtime / "settings.json").read_text(encoding="utf-8")) == {
        "enableInstallTelemetry": False,
        "packages": ["http://git.lunarnexus.local:3000/james/pi-lmstudio"],
    }
    assert (pi_runtime / "git" / "git.lunarnexus.local" / "james" / "pi-lmstudio" / "marker.txt").read_text(encoding="utf-8") == "installed\n"
    assert (pi_runtime / "lmstudio.json").read_text(encoding="utf-8") == '{"url": "http://localhost:1234"}\n'
    assert (hermes_runtime / "config.yaml").read_text(encoding="utf-8") == "model: hermes-test\n"
    assert (opencode_runtime / "opencode.json").read_text(encoding="utf-8") == '{"model": "opencode-test"}\n'
    assert (runtime.pi_skills_runtime_dir / "builder" / "SKILL.md").read_text(encoding="utf-8") == "skill\n"
    assert log.read_text(encoding="utf-8").splitlines() == ["init pi --copy --force", "_tool-info"]


def test_init_runtime_mirrors_run_scoped_pi_config_without_clobbering_existing_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestra_src = tmp_path / "orchestra-config"
    pi_src = tmp_path / "pi-config"
    skills = tmp_path / "skills"
    home_dir = tmp_path / "home" / "20250101T010203"
    pi_runtime = home_dir / ".pi" / "agent"
    runtime_dir = pi_runtime / "orchestra"
    hermes_runtime = tmp_path / "runtime" / "hermes"
    opencode_runtime = tmp_path / "runtime" / "opencode"
    mirrored_pi_runtime = tmp_path / "root" / ".pi" / "agent"
    bin_dir = tmp_path / "bin"

    for path in (orchestra_src, pi_src, skills, bin_dir, mirrored_pi_runtime):
        path.mkdir(parents=True, exist_ok=True)

    (orchestra_src / "agent-catalog.yaml").write_text("default_role: builder\n")
    (pi_src / "settings.json").write_text('{"enableInstallTelemetry": false}\n')
    (pi_src / "lmstudio.json").write_text('{"url": "http://localhost:1234"}\n')
    (skills / "builder" / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (skills / "builder" / "SKILL.md").write_text("skill\n")
    (mirrored_pi_runtime / "keep.txt").write_text("keep me\n")
    (mirrored_pi_runtime / "extensions" / "lmstudio" / "plugin.json").parent.mkdir(parents=True, exist_ok=True)
    (mirrored_pi_runtime / "extensions" / "lmstudio" / "plugin.json").write_text('{"enabled": true}\n')

    _write_executable(
        bin_dir / "orchestra",
        "#!/usr/bin/env bash\nset -eu\nprintf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n",
    )

    runtime = RuntimeEnvironment(
        tasks_root=tmp_path / "tasks",
        results_root=tmp_path / "results",
        artifacts_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspace",
        orchestra_config_src=orchestra_src,
        lmstudio_config_src=pi_src / "lmstudio.json",
        pi_config_src=pi_src,
        pi_skills_src=skills,
        home_dir=home_dir,
        orchestra_runtime_dir=runtime_dir,
        lmstudio_runtime_file=pi_runtime / "lmstudio.json",
        hermes_runtime_dir=hermes_runtime,
        opencode_runtime_dir=opencode_runtime,
        run_id="20250101T010203",
    )

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(tmp_path / "orchestra.log"))
    monkeypatch.setenv("BENCH_IN_CONTAINER", "1")
    monkeypatch.setenv("PI_HERMES_RUNTIME_DIR", str(hermes_runtime))
    monkeypatch.setenv("PI_OPENCODE_RUNTIME_DIR", str(opencode_runtime))
    monkeypatch.setattr("bench.runtime.PI_AGENT_RUNTIME_DIR", mirrored_pi_runtime, raising=False)

    summary = init_runtime(runtime)

    assert summary["home_dir"] == str(tmp_path / "home" / "20250101T010203")
    assert summary["pi_runtime_dir"] == str(pi_runtime)
    assert (mirrored_pi_runtime / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert not (mirrored_pi_runtime / "lmstudio.json").exists()
    assert not (mirrored_pi_runtime / "settings.json").exists()
    assert not (mirrored_pi_runtime / "orchestra").exists()
    assert (mirrored_pi_runtime / "extensions" / "lmstudio" / "plugin.json").read_text(encoding="utf-8") == '{"enabled": true}\n'
    assert (pi_runtime / "lmstudio.json").read_text(encoding="utf-8") == '{"url": "http://localhost:1234"}\n'
    assert (pi_runtime / "settings.json").read_text(encoding="utf-8") == '{\n  "enableInstallTelemetry": false\n}\n'
    assert (pi_runtime / "orchestra" / "agent-catalog.yaml").read_text(encoding="utf-8") == "default_role: builder\n"


def test_init_runtime_command_prints_json_summary_for_host_passthrough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    orchestra_src = tmp_path / "orchestra-config"
    skills = tmp_path / "skills"
    workspace_root = tmp_path / "workspace"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "orchestra.log"

    pi_src = tmp_path / "pi-config"
    for path in (orchestra_src, skills, bin_dir, pi_src):
        path.mkdir(parents=True, exist_ok=True)
    (orchestra_src / "agent-catalog.yaml").write_text("default_role: builder\n")
    _write_executable(
        bin_dir / "orchestra",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n",
    )

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(log))
    for key, value in {
        "BENCH_WORKSPACE": str(workspace_root),
        "BENCH_RUN_ID": "20250101T010203",
        "BENCH_TASKS": str(tmp_path / "tasks"),
        "BENCH_RESULTS": str(tmp_path / "results"),
        "BENCH_ARTIFACTS": str(tmp_path / "artifacts"),
        "BENCH_ORCHESTRA_CONFIG_SRC": str(orchestra_src),
        "BENCH_PI_CONFIG_SRC": str(pi_src),
        "BENCH_PI_SKILLS_SRC": str(skills),
        # Keep the sync off host-privileged defaults; only stdout is asserted here.
        "PI_HERMES_RUNTIME_DIR": str(tmp_path / "hermes-runtime"),
        "PI_OPENCODE_RUNTIME_DIR": str(tmp_path / "opencode-runtime"),
    }.items():
        monkeypatch.setenv(key, value)

    assert runtime_main(["init-runtime"]) == 0
    summary = json.loads(capsys.readouterr().out)
    home_dir = workspace_root / ".pi" / "home" / "20250101T010203"
    pi_runtime_dir = home_dir / ".pi" / "agent"
    # The host-side interactive passthrough parses these keys to point the
    # session at the run-scoped dirs populated by the in-container sync.
    assert summary["home_dir"] == str(home_dir)
    assert summary["pi_runtime_dir"] == str(pi_runtime_dir)
    assert summary["orchestra_runtime_dir"] == str(pi_runtime_dir / "orchestra")
    assert (pi_runtime_dir / "orchestra" / "agent-catalog.yaml").read_text(encoding="utf-8") == "default_role: builder\n"


def test_init_runtime_persists_effective_overlay_summary_for_run_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestra_src = tmp_path / "orchestra-config"
    pi_src = tmp_path / "pi-config"
    hermes_src = tmp_path / "hermes-config"
    opencode_src = tmp_path / "opencode-config"
    skills = tmp_path / "skills"
    results_root = tmp_path / "results"
    home_dir = tmp_path / "home" / "20250101T010203"
    pi_runtime = home_dir / ".pi" / "agent"
    runtime_dir = pi_runtime / "orchestra"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "orchestra.log"

    for path in (orchestra_src, pi_src, hermes_src, opencode_src, skills, bin_dir):
        path.mkdir(parents=True, exist_ok=True)

    (orchestra_src / "agent-catalog.yaml").write_text("default_role: builder\n")
    (pi_src / "settings.json").write_text('{"enableInstallTelemetry": false}\n')
    (hermes_src / "config.yaml").write_text("model: hermes-test\n")
    (opencode_src / "opencode.json").write_text('{"model": "opencode-test"}\n')

    _write_executable(
        bin_dir / "orchestra",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n",
    )

    artifacts_root = tmp_path / "artifacts"
    runtime = RuntimeEnvironment(
        tasks_root=tmp_path / "tasks",
        results_root=results_root,
        artifacts_root=artifacts_root,
        workspace_root=tmp_path / "workspace",
        orchestra_config_src=orchestra_src,
        lmstudio_config_src=pi_src / "lmstudio.json",
        pi_config_src=pi_src,
        hermes_config_src=hermes_src,
        opencode_config_src=opencode_src,
        pi_skills_src=skills,
        home_dir=home_dir,
        orchestra_runtime_dir=runtime_dir,
        lmstudio_runtime_file=pi_runtime / "lmstudio.json",
        hermes_runtime_dir=tmp_path / "hermes-runtime",
        opencode_runtime_dir=tmp_path / "opencode-runtime",
        run_id="20250101T010203",
    )

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("ORCHESTRA_LOG", str(log))

    summary = init_runtime(runtime)

    record_path = artifacts_root / "runtime-config-sync.json"
    assert record_path.is_file()
    assert not (results_root / "runtime-config-sync.json").exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    for key in (
        "orchestra_config_files",
        "orchestra_config_sha256",
        "pi_config_files",
        "pi_config_sha256",
        "hermes_config_files",
        "hermes_config_sha256",
        "opencode_config_files",
        "opencode_config_sha256",
    ):
        assert record[key] == summary[key]


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
        hermes_runtime_dir=tmp_path / "hermes-runtime",
        opencode_runtime_dir=tmp_path / "opencode-runtime",
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
    (root / "tasks").mkdir(parents=True, exist_ok=True)
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


def test_build_image_does_not_require_optional_config_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Config directories are runtime mounts (D-CONFIG-004), not build inputs;
    # absent optional config dirs must not block the image build.
    root = tmp_path / "repo"
    (root / "docker").mkdir(parents=True)
    (root / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))

    report = build_image(root)

    assert report["action"] == "build"
    assert log.read_text(encoding="utf-8").splitlines()[0].startswith("build ")


def test_build_image_streams_live_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "repo"
    (root / "docker").mkdir(parents=True)
    (root / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        'printf \"%s\\n\" "$*" >> "$FAKE_DOCKER_LOG"\n'
        'case "${1:-}" in\n'
        '  build)\n'
        '    printf \"STEP 1: pulling base image\\n\"\n'
        '    printf \"STEP 2: layering repo\\n\"\n'
        '    exit 0\n'
        '    ;;&\n'
        'esac\n'
        'exit 1\n',
    )
    log = bin_dir / "docker.log"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))

    report = build_image(root, stream_output=True)
    captured = capfd.readouterr()

    assert report["action"] == "build"
    assert "STEP 1: pulling base image" in captured.out
    assert "STEP 2: layering repo" in captured.out


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
    orchestra_config = root / "config" / "orchestra"
    orchestra_config.mkdir(parents=True)
    (orchestra_config / "agent-catalog.yaml").write_text("default_role: builder\n", encoding="utf-8")
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
        f"{root / 'config' / 'orchestra'}:/bench/orchestra-config:ro",
        f"{root / 'config' / 'pi'}:/bench/pi:ro",
        f"{root / 'config' / 'hermes'}:/bench/hermes:ro",
        f"{root / 'config' / 'opencode'}:/bench/opencode:ro",
        f"{root / 'config' / 'skills'}:/bench/skills:ro",
        f"{root / 'tasks'}:/bench/task-materials-source:ro",
    ]
    for expected in expected_mounts:
        assert "-v" in mounts and expected in mounts
    assert all("V1/tasks" not in token for token in mounts)
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


def test_prepare_startup_builds_recreates_and_syncs_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls: list[tuple[object, ...]] = []
    progress_messages: list[str] = []

    def fake_build_image(*, root=None, image_name=None, stream_output=False):  # type: ignore[no-untyped-def]
        calls.append(("build", Path(root), image_name, stream_output))
        return {"action": "build", "image": "orchestra-bench-env", "root": str(Path(root))}

    def fake_recreate_container(*, root=None, image_name=None, container_name=None):  # type: ignore[no-untyped-def]
        calls.append(("recreate", Path(root), image_name, container_name))
        return {"action": "recreate", "container": container_name, "image": "orchestra-bench-env"}

    def fake_sync_runtime_config_inside_container():
        calls.append(("sync",))
        return {"home_dir": "/workspace/.pi/home/20250101T010203", "pi_runtime_dir": "/workspace/.pi/home/20250101T010203/.pi/agent", "orchestra_runtime_dir": "/workspace/.pi/home/20250101T010203/.pi/agent/orchestra"}

    monkeypatch.setattr("bench.runtime.build_image", fake_build_image)
    monkeypatch.setattr("bench.runtime.recreate_container", fake_recreate_container)
    monkeypatch.setattr("bench.runtime._sync_runtime_config_inside_container", fake_sync_runtime_config_inside_container)

    summary = prepare_startup(root, progress=progress_messages.append, stream_build_output=True)

    assert calls == [
        ("build", root.resolve(), None, True),
        ("recreate", root.resolve(), None, CONTAINER_NAME),
        ("sync",),
    ]
    assert progress_messages == ["Building image...", "Recreating container...", "Applying runtime config...", "Ready."]
    assert summary == {
        "status": "ok",
        "image": "orchestra-bench-env",
        "container": CONTAINER_NAME,
        "runtime": {
            "home_dir": "/workspace/.pi/home/20250101T010203",
            "pi_runtime_dir": "/workspace/.pi/home/20250101T010203/.pi/agent",
            "orchestra_runtime_dir": "/workspace/.pi/home/20250101T010203/.pi/agent/orchestra",
        },
    }


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
    assert log_line.startswith(
        f"exec -e BENCH_IN_CONTAINER=1 -e BENCH_HOST_UID={os.getuid()} -e BENCH_HOST_GID={os.getgid()} -w /bench orchestra-bench-runner python3 -m bench.cli run --auto alpha-run"
    )


def test_container_exec_uses_script_wrapper_for_interactive_tty_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = _write_fake_docker(bin_dir)
    script_log = bin_dir / "script.log"
    _write_executable(
        bin_dir / "script",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_SCRIPT_LOG\"\n"
        "typescript=\"$3\"\n"
        "printf '%s\\n' 'transcript from script wrapper' > \"$typescript\"\n"
        "sh -lc \"$2\"\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(docker_log))
    monkeypatch.setenv("FAKE_SCRIPT_LOG", str(script_log))

    transcript = tmp_path / "artifacts" / "02-run" / "tty.typescript"
    completed = container_exec(
        ["pi", "config"],
        workdir="/bench",
        env={"BENCH_IN_CONTAINER": "1"},
        interactive=True,
        tty=True,
        transcript_path=transcript,
    )

    assert completed.returncode == 0
    assert transcript.read_text(encoding="utf-8") == "transcript from script wrapper\n"
    assert script_log.read_text(encoding="utf-8").splitlines()[-1].startswith("-qefc ")
    assert (
        f"docker exec -i -t -e BENCH_IN_CONTAINER=1 -e BENCH_HOST_UID={os.getuid()} -e BENCH_HOST_GID={os.getgid()} -w /bench orchestra-bench-runner pi config"
        in script_log.read_text(encoding="utf-8")
    )
    assert docker_log.read_text(encoding="utf-8").splitlines()[-1].startswith(
        f"exec -i -t -e BENCH_IN_CONTAINER=1 -e BENCH_HOST_UID={os.getuid()} -e BENCH_HOST_GID={os.getgid()} -w /bench orchestra-bench-runner pi config"
    )


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
    runtime_dir = workspace_root / ".pi" / "home" / "20250101T010203" / ".pi" / "agent" / "orchestra"
    lmstudio_runtime = workspace_root / ".pi" / "home" / "20250101T010203" / ".pi" / "agent" / "lmstudio.json"
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
        "-v", f"{task_materials_root}:/bench/task-materials-source:ro",
        "-v", f"{workspace_root}:/workspace",
        "-v", f"{results_root}:/bench/results",
        "-v", f"{artifacts_root}:/bench/artifacts",
    ]
    env = [
        "-e", "BENCH_RUN_ID=20250101T010203",
        "-e", "BENCH_TASKS=/bench/task-materials-source",
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
