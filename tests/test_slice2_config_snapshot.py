from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSlice2ConfigSnapshot:
    def test_parse_pi_settings_enabled_plugins_distinguishes_installed_from_enabled(self):
        from eval_harness import _parse_pi_settings_enabled_plugins

        settings = {
            "packages": [
                "http://git.example/pi-lmstudio",
                {"source": "http://git.example/pi-codegraph", "extensions": ["-index.ts"]},
            ],
            "extensions": ["+extensions/orchestra/index.ts", "-extensions/disabled/index.ts"],
        }

        assert _parse_pi_settings_enabled_plugins(settings) == ["orchestra", "pi-lmstudio"]

    def test_runtime_snapshot_counts_local_extensions_as_enabled_plugins(self, monkeypatch):
        import subprocess as sp
        import eval_harness

        def fake_exec(*args, env=None):
            command = " ".join(args)
            if "pi list" in command:
                return sp.CompletedProcess(args, 0, stdout="http://git.example/pi-lmstudio\n", stderr="")
            if "find /root/.pi/agent/extensions" in command:
                return sp.CompletedProcess(args, 0, stdout="orchestra\n", stderr="")
            if "settings.json" in command:
                return sp.CompletedProcess(args, 0, stdout='{"packages":["http://git.example/pi-lmstudio"]}\n', stderr="")
            return sp.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness, "_docker_exec", fake_exec)

        snapshot = eval_harness.collect_container_runtime_snapshot()

        assert snapshot["pi_enabled_plugins"] == ["orchestra", "pi-lmstudio"]
        assert snapshot["pi_enabled_plugins_summary"] == "orchestra,pi-lmstudio"

    def test_runtime_snapshot_captures_orchestra_version(self, monkeypatch):
        import json
        import subprocess as sp
        import eval_harness

        def fake_exec(*args, env=None):
            command = " ".join(args)
            if "/opt/orchestra/.venv/bin/python" in command:
                return sp.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps({
                        "orchestra_version": "0.1.3.dev18+gc4fc74df9",
                        "orchestra_module_file": "/opt/orchestra/src/orchestra/__init__.py",
                        "orchestra_source_rev": "c4fc74d",
                        "orchestra_source_dirty": False,
                    }) + "\n",
                    stderr="",
                )
            return sp.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness, "_docker_exec", fake_exec)

        snapshot = eval_harness.collect_container_runtime_snapshot()

        assert snapshot["orchestra_version"] == "0.1.3.dev18+gc4fc74df9"
        assert snapshot["orchestra_source_rev"] == "c4fc74d"
        assert snapshot["orchestra_source_dirty"] is False

    def test_runtime_snapshot_respects_disabled_local_extensions(self, monkeypatch):
        import subprocess as sp
        import eval_harness

        def fake_exec(*args, env=None):
            command = " ".join(args)
            if "pi list" in command:
                return sp.CompletedProcess(args, 0, stdout="http://git.example/pi-lmstudio\n", stderr="")
            if "find /root/.pi/agent/extensions" in command:
                return sp.CompletedProcess(args, 0, stdout="orchestra\n", stderr="")
            if "settings.json" in command:
                return sp.CompletedProcess(args, 0, stdout='{"packages":["http://git.example/pi-lmstudio"],"extensions":["-extensions/orchestra/index.ts"]}\n', stderr="")
            return sp.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness, "_docker_exec", fake_exec)

        snapshot = eval_harness.collect_container_runtime_snapshot()

        assert snapshot["pi_enabled_plugins"] == ["pi-lmstudio"]
        assert snapshot["pi_enabled_plugins_summary"] == "pi-lmstudio"
        assert snapshot["pi_extensions_summary"] == "orchestra,pi-lmstudio"

    def test_benchmark_local_orchestra_config_files_exist(self):
        config_dir = REPO_ROOT / "config" / "orchestra"
        pi_dir = REPO_ROOT / "config" / "pi"
        # Only the catalog is benchmark-local; config.yaml/prompts.yaml come
        # from the installed Orchestra version, not this repo.
        assert (config_dir / "agent-catalog.yaml").is_file()
        assert not (config_dir / "config.yaml").exists()
        assert not (config_dir / "prompts.yaml").exists()
        assert (pi_dir / "lmstudio.json").is_file()
        assert not (REPO_ROOT / "config" / "lmstudio.json").exists()

    def test_start_env_mounts_read_only_benchmark_config(self):
        start_env = (REPO_ROOT / "scripts" / "start-env").read_text()

        assert "config/orchestra" in start_env
        assert "config/pi/lmstudio.json" in start_env
        assert "/bench/orchestra-config:ro" in start_env
        assert "/bench/pi/lmstudio.json:ro" in start_env

    def test_entrypoint_copies_benchmark_config_into_runtime_dir(self):
        entrypoint = (REPO_ROOT / "docker" / "entrypoint.sh").read_text()

        assert "/bench/orchestra-config" in entrypoint
        assert "/bench/pi/lmstudio.json" in entrypoint
        assert "/root/.pi/agent/orchestra" in entrypoint
        assert "/root/.pi/agent/lmstudio.json" in entrypoint
        assert "cp -a" in entrypoint or "rsync" in entrypoint
