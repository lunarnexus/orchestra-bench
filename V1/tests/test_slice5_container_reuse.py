from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_docker_stub(tmp_path: Path) -> tuple[Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "docker.log"
    state_file = tmp_path / "container.state"
    id_file = tmp_path / "container.id"

    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
        "cmd=\"$1\"\n"
        "shift || true\n"
        "case \"$cmd\" in\n"
        "  image)\n"
        "    exit 0\n"
        "    ;;\n"
        "  inspect)\n"
        "    if [ -f \"$STATE_FILE\" ] && [ \"$(cat \"$STATE_FILE\")\" = running ]; then\n"
        "      if [ -n \"${1:-}\" ] && [ \"$1\" = -f ]; then\n"
        "        printf 'true\\n'\n"
        "      fi\n"
        "      exit 0\n"
        "    fi\n"
        "    exit 1\n"
        "    ;;\n"
        "  rm)\n"
        "    rm -f \"$STATE_FILE\" \"$ID_FILE\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  run)\n"
        "    printf 'container-1\\n' > \"$ID_FILE\"\n"
        "    printf 'running\\n' > \"$STATE_FILE\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  start)\n"
        "    printf 'running\\n' > \"$STATE_FILE\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  restart)\n"
        "    printf 'running\\n' > \"$STATE_FILE\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  exec)\n"
        "    exit 0\n"
        "    ;;\n"
        "  logs)\n"
        "    exit 0\n"
        "    ;;\n"
        "  *)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
    )
    docker.chmod(0o755)
    return bin_dir, log_file, state_file


class TestReusableContainerSemantics:
    def test_start_env_reuses_existing_container_by_default(self, tmp_path):
        bin_dir, log_file, state_file = _write_docker_stub(tmp_path)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "DOCKER_LOG": str(log_file),
                "STATE_FILE": str(state_file),
                "ID_FILE": str(tmp_path / "container.id"),
            }
        )

        script = REPO_ROOT / "scripts" / "start-env"
        subprocess.run(["bash", str(script), "start"], env=env, check=True, capture_output=True, text=True)
        subprocess.run(["bash", str(script), "start"], env=env, check=True, capture_output=True, text=True)

        log_lines = log_file.read_text().splitlines()
        run_lines = [line for line in log_lines if line.startswith("run -d --name orchestra-bench-runner")]
        assert len(run_lines) == 1
        assert "/bench/tasks" not in run_lines[0]
        assert "rm -f orchestra-bench-runner" not in log_lines

    def test_start_env_recreate_forces_new_container(self, tmp_path):
        bin_dir, log_file, state_file = _write_docker_stub(tmp_path)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "DOCKER_LOG": str(log_file),
                "STATE_FILE": str(state_file),
                "ID_FILE": str(tmp_path / "container.id"),
            }
        )

        script = REPO_ROOT / "scripts" / "start-env"
        subprocess.run(["bash", str(script), "start"], env=env, check=True, capture_output=True, text=True)
        subprocess.run(["bash", str(script), "recreate"], env=env, check=True, capture_output=True, text=True)

        log_lines = log_file.read_text().splitlines()
        assert "rm -f orchestra-bench-runner" in log_lines
        run_lines = [line for line in log_lines if line.startswith("run -d --name orchestra-bench-runner")]
        assert len(run_lines) == 2
        assert all("/bench/tasks" not in line for line in run_lines)

    def test_readme_documents_numbered_reuse_path(self):
        readme = (REPO_ROOT / "README.md").read_text()

        assert "scripts/01-start start" in readme
        assert "scripts/start-env start" not in readme
        assert "scripts/start-env recreate" not in readme
        assert "Runtime internals and troubleshooting checks live in `ARCHITECTURE.md`" in readme
