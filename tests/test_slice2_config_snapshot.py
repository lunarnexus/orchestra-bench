from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSlice2ConfigSnapshot:
    def test_benchmark_local_orchestra_config_files_exist(self):
        config_dir = REPO_ROOT / "config" / "orchestra"
        pi_dir = REPO_ROOT / "config" / "pi"
        assert (config_dir / "config.yaml").is_file()
        assert (config_dir / "prompts.yaml").is_file()
        assert (config_dir / "agent-catalog.yaml").is_file()
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
