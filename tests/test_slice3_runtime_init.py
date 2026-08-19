from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSlice3RuntimeInit:
    def test_init_runtime_rejects_missing_config_source(self, tmp_path):
        runtime = tmp_path / "pi-runtime"
        lmstudio_runtime = tmp_path / "home" / ".pi" / "agent" / "lmstudio.json"
        bin_dir = tmp_path / "bin"
        results = tmp_path / "results"
        artifacts = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        log = tmp_path / "orchestra.log"
        lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"

        bin_dir.mkdir()
        results.mkdir()
        lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir()
        workspace.mkdir()
        lmstudio_source.write_text('{"url":"http://192.168.1.209:1234"}\n')

        orchestra = bin_dir / "orchestra"
        orchestra.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n"
        )
        orchestra.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "BENCH_ORCHESTRA_CONFIG_SRC": str(tmp_path / "missing-config"),
                "BENCH_LMSTUDIO_CONFIG_SRC": str(lmstudio_source),
                "PI_ORCHESTRA_RUNTIME_DIR": str(runtime),
                "PI_LMSTUDIO_RUNTIME_FILE": str(lmstudio_runtime),
                "BENCH_RESULTS": str(results),
                "BENCH_ARTIFACTS": str(artifacts),
                "BENCH_WORKSPACE": str(workspace),
                "ORCHESTRA_LOG": str(log),
            }
        )

        script = REPO_ROOT / "docker" / "entrypoint.sh"

        result = subprocess.run(
            ["bash", str(script), "init-runtime"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

        assert result.returncode != 0
        assert "orchestra config source not found" in result.stderr
        # Orchestra init now runs before the benchmark overlay, so its fake
        # invocation is logged even when the catalog sync fails.
        assert log.read_text().splitlines() == ["init pi --copy --force"]
        assert not runtime.exists()

    def test_init_runtime_syncs_config_and_runs_orchestra_init(self, tmp_path):
        source = tmp_path / "orchestra-config-src"
        runtime = tmp_path / "pi-runtime"
        lmstudio_runtime = tmp_path / "home" / ".pi" / "agent" / "lmstudio.json"
        bin_dir = tmp_path / "bin"
        results = tmp_path / "results"
        artifacts = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        log = tmp_path / "orchestra.log"
        lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"

        source.mkdir()
        bin_dir.mkdir()
        lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
        results.mkdir()
        artifacts.mkdir()
        workspace.mkdir()
        lmstudio_source.write_text('{"url":"http://192.168.1.209:1234"}\n')

        (source / "config.yaml").write_text("version: one\n")
        (source / "prompts.yaml").write_text("prompt: one\n")
        (source / "agent-catalog.yaml").write_text("catalog: one\n")

        orchestra = bin_dir / "orchestra"
        orchestra.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n"
        )
        orchestra.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "BENCH_ORCHESTRA_CONFIG_SRC": str(source),
                "BENCH_LMSTUDIO_CONFIG_SRC": str(lmstudio_source),
                "PI_ORCHESTRA_RUNTIME_DIR": str(runtime),
                "PI_LMSTUDIO_RUNTIME_FILE": str(lmstudio_runtime),
                "BENCH_RESULTS": str(results),
                "BENCH_ARTIFACTS": str(artifacts),
                "BENCH_WORKSPACE": str(workspace),
                "ORCHESTRA_LOG": str(log),
            }
        )

        script = REPO_ROOT / "docker" / "entrypoint.sh"

        subprocess.run(
            ["bash", str(script), "init-runtime"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )

        assert (runtime / "config.yaml").read_text() == "version: one\n"
        assert (runtime / "prompts.yaml").read_text() == "prompt: one\n"
        assert (runtime / "agent-catalog.yaml").read_text() == "catalog: one\n"
        assert lmstudio_runtime.read_text() == '{"url":"http://192.168.1.209:1234"}\n'
        assert log.read_text().splitlines() == ["init pi --copy --force"]

        (source / "config.yaml").write_text("version: two\n")
        subprocess.run(
            ["bash", str(script), "init-runtime"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )

        assert (runtime / "config.yaml").read_text() == "version: two\n"
        assert lmstudio_runtime.read_text() == '{"url":"http://192.168.1.209:1234"}\n'
        assert log.read_text().splitlines() == [
            "init pi --copy --force",
            "init pi --copy --force",
        ]

    def test_eval_does_not_resync_orchestra_config_or_delete_state(self, tmp_path):
        source = tmp_path / "orchestra-config-src"
        runtime = tmp_path / "pi-runtime"
        lmstudio_runtime = tmp_path / "home" / ".pi" / "agent" / "lmstudio.json"
        bin_dir = tmp_path / "bin"
        results = tmp_path / "results"
        artifacts = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"
        run_id = "testrun"
        task_id = "task-a"

        source.mkdir()
        bin_dir.mkdir()
        results.mkdir()
        artifacts.mkdir()
        lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
        workdir = workspace / f"{run_id}-{task_id}"
        workdir.mkdir(parents=True)
        lmstudio_source.write_text('{"url":"http://192.168.1.209:1234"}\n')
        (source / "config.yaml").write_text("version: source\n")
        (source / "prompts.yaml").write_text("prompt: source\n")
        (source / "agent-catalog.yaml").write_text("catalog: source\n")
        runtime.mkdir()
        (runtime / "config.yaml").write_text("version: runtime\n")
        (runtime / "state").mkdir()
        (runtime / "state" / "orchestra.db").write_text("run state")
        (runtime / "logs").mkdir()
        (runtime / "logs" / "run.jsonl").write_text("run log")

        env = os.environ.copy()
        env.update(
            {
                "BENCH_RUN_ID": run_id,
                "BENCH_ORCHESTRA_CONFIG_SRC": str(source),
                "BENCH_LMSTUDIO_CONFIG_SRC": str(lmstudio_source),
                "PI_ORCHESTRA_RUNTIME_DIR": str(runtime),
                "PI_LMSTUDIO_RUNTIME_FILE": str(lmstudio_runtime),
                "BENCH_RESULTS": str(results),
                "BENCH_ARTIFACTS": str(artifacts),
                "BENCH_WORKSPACE": str(workspace),
            }
        )

        script = REPO_ROOT / "docker" / "entrypoint.sh"
        result = subprocess.run(
            ["bash", str(script), "eval", task_id, "true"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

        assert result.returncode == 0
        assert (runtime / "config.yaml").read_text() == "version: runtime\n"
        assert (runtime / "state" / "orchestra.db").read_text() == "run state"
        assert (runtime / "logs" / "run.jsonl").read_text() == "run log"

    def test_init_runtime_copies_lmstudio_config_into_pi_agent_dir(self, tmp_path):
        orchestra_source = tmp_path / "orchestra-config-src"
        lmstudio_source = tmp_path / "config" / "pi" / "lmstudio.json"
        orchestra_runtime = tmp_path / "pi-runtime"
        lmstudio_runtime = tmp_path / "home" / ".pi" / "agent" / "lmstudio.json"
        bin_dir = tmp_path / "bin"
        results = tmp_path / "results"
        artifacts = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        log = tmp_path / "orchestra.log"

        orchestra_source.mkdir()
        bin_dir.mkdir()
        lmstudio_source.parent.mkdir(parents=True, exist_ok=True)
        results.mkdir()
        artifacts.mkdir()
        workspace.mkdir()
        lmstudio_source.write_text('{"url":"http://192.168.1.209:1234"}\n')

        (orchestra_source / "config.yaml").write_text("version: one\n")
        (orchestra_source / "prompts.yaml").write_text("prompt: one\n")
        (orchestra_source / "agent-catalog.yaml").write_text("catalog: one\n")

        orchestra = bin_dir / "orchestra"
        orchestra.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$ORCHESTRA_LOG\"\n"
        )
        orchestra.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "BENCH_ORCHESTRA_CONFIG_SRC": str(orchestra_source),
                "BENCH_LMSTUDIO_CONFIG_SRC": str(lmstudio_source),
                "PI_ORCHESTRA_RUNTIME_DIR": str(orchestra_runtime),
                "PI_LMSTUDIO_RUNTIME_FILE": str(lmstudio_runtime),
                "BENCH_RESULTS": str(results),
                "BENCH_ARTIFACTS": str(artifacts),
                "BENCH_WORKSPACE": str(workspace),
                "ORCHESTRA_LOG": str(log),
            }
        )

        script = REPO_ROOT / "docker" / "entrypoint.sh"

        subprocess.run(
            ["bash", str(script), "init-runtime"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )

        assert lmstudio_runtime.read_text() == '{"url":"http://192.168.1.209:1234"}\n'

    def test_agent_catalog_defines_pi_default_and_optional_fallback_harnesses(self):
        catalog = (REPO_ROOT / "config" / "orchestra" / "agent-catalog.yaml").read_text()

        assert "harness: pi" in catalog
        assert "harness_config: pi" in catalog
        assert "harness: hermes" in catalog
        assert "harness_fallback" in catalog
        assert "nested_dispatch_depth" in catalog
        assert "worker_budget" not in catalog


class TestSlice3StartEnv:
    def test_start_env_mounts_repo_entrypoint_into_the_container(self, tmp_path):
        bin_dir = tmp_path / "bin"
        log = tmp_path / "docker.log"
        bin_dir.mkdir()

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  image) exit 0 ;;\n"
            "  inspect) exit 1 ;;\n"
            "  rm) exit 0 ;;\n"
            "  run) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "DOCKER_LOG": str(log),
            }
        )

        script = REPO_ROOT / "scripts" / "start-env"
        subprocess.run(["bash", str(script), "start"], env=env, check=True)

        run_line = next(line for line in log.read_text().splitlines() if line.startswith("run "))
        assert "/usr/local/bin/bench-entrypoint:ro" in run_line
        assert f"{REPO_ROOT / 'scripts' / '..' / 'docker' / 'entrypoint.sh'}:/usr/local/bin/bench-entrypoint:ro" in run_line
        assert f"{REPO_ROOT / 'scripts' / '..' / 'config' / 'pi' / 'lmstudio.json'}:/bench/pi/lmstudio.json:ro" in run_line


class TestSlice3Documentation:
    def test_architecture_mentions_runtime_init_and_doctor_checks(self):
        architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text()

        assert "orchestra init pi --copy --force" in architecture
        assert "`orchestra doctor` passes" in architecture
        assert "`/orch doctor` works from Pi inside the container" in architecture
