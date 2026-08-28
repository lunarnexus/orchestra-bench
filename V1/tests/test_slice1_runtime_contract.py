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

    def test_docker_build_cache_bust_only_starts_before_source_and_plugins(self):
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text()
        apt_pos = dockerfile.index("apt-get install")
        npm_pos = dockerfile.index("npm install -g")
        gem_pos = dockerfile.index("gem install --no-document")
        bust_pos = dockerfile.index("ARG SOURCE_PLUGIN_CACHE_BUST")
        orchestra_clone_pos = dockerfile.index("git clone \"$ORCHESTRA_REPO_URL\"")
        plugin_install_pos = dockerfile.index("pi install \"$PI_LMSTUDIO_PLUGIN_URL\"")

        assert apt_pos < bust_pos
        assert npm_pos < bust_pos
        assert gem_pos < bust_pos
        assert bust_pos < orchestra_clone_pos
        assert bust_pos < plugin_install_pos

    def test_build_scripts_pass_source_plugin_cache_bust_with_repo_context(self):
        for script_name in ["01-start", "build-env"]:
            script = (REPO_ROOT / "scripts" / script_name).read_text()
            assert "--build-arg SOURCE_PLUGIN_CACHE_BUST=\"$(date +%s)\"" in script
            assert '-f "$ROOT/docker/Dockerfile"' in script
            assert '"$ROOT"' in script

    def test_readme_mentions_numbered_runtime_entrypoint(self):
        readme = (REPO_ROOT / "README.md").read_text()

        assert "scripts/01-start start" in readme
        assert "scripts/01-start build" not in readme
        assert "scripts/start-env start" not in readme
        assert "Runtime internals and troubleshooting checks live in `ARCHITECTURE.md`" in readme
