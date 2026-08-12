from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSlice1RuntimeContract:
    def test_dockerfile_installs_orchestra_and_plugin_from_required_sources(self):
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text()

        assert "http://git.lunarnexus.local:3000/james/orchestra" in dockerfile
        assert "http://git.lunarnexus.local:3000/james/pi-lmstudio" in dockerfile
        assert "http://git.lunarnexus.local:3000/james/pi-codegraph" in dockerfile
        assert "http://git.lunarnexus.local:3000/james/pi-web-tools" in dockerfile
        assert 'python3 -m pip install -e "' in dockerfile
        assert "[dev]" in dockerfile
        assert "/opt/orchestra/.venv/bin" in dockerfile
        assert "pi install" in dockerfile

    def test_dockerfile_copies_benchmark_local_skills(self):
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text()

        assert (REPO_ROOT / "config" / "skills").is_dir()
        assert "COPY config/skills/" in dockerfile
        assert "/root/.pi/agent/skills" in dockerfile
        assert "cp -a /tmp/bench-skills/." in dockerfile

    def test_dockerfile_includes_pkg_config_for_sqlite3_gem_build(self):
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text()

        assert "gem install --no-document sinatra sqlite3 rack-test minitest" in dockerfile
        assert "pkg-config" in dockerfile

    def test_readme_mentions_numbered_runtime_entrypoint(self):
        readme = (REPO_ROOT / "README.md").read_text()

        assert "scripts/01-start start" in readme
        assert "scripts/01-start build" not in readme
        assert "scripts/start-env start" not in readme
        assert "Runtime internals and troubleshooting checks live in `ARCHITECTURE.md`" in readme
