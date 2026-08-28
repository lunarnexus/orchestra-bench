"""Tests for Slice 6 — operator flow and run metadata capture."""

from __future__ import annotations

import json
import subprocess as sp
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Import after path setup
from __init__ import TaskMeta, TaskResult  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────

def _make_result(task_id="task-a", run_id="run-1", score="pass"):
    return TaskResult(
        task_id=task_id,
        run_id=run_id,
        score=score,
        checks={"check_ok": True},
    )


# ── 1. Run metadata persistence in results ────────────────────────

class TestRunMetadataPersistence:
    """TaskResult.run_meta carries model, orchestra, skills info and roundtrips."""

    def test_run_meta_defaults_empty_dict(self):
        r = _make_result()
        assert isinstance(r.run_meta, dict)
        assert len(r.run_meta) == 0

    def test_run_meta_stores_model(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            run_meta={"model": "google/gemini-2.5-flash"},
        )
        assert r.run_meta["model"] == "google/gemini-2.5-flash"

    def test_run_meta_stores_orchestra_flag(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            run_meta={"orchestra": True},
        )
        assert r.run_meta["orchestra"] is True

    def test_run_meta_stores_extra_skills(self):
        r = TaskResult(
            task_id="t1", run_id="r1", score="pass",
            run_meta={
                "model": "gpt-4o",
                "orchestra": False,
                "extra_skills": ["research-first"],
            },
        )
        assert r.run_meta["extra_skills"] == ["research-first"]

    def test_run_meta_roundtrips_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            meta = {
                "model": "claude-sonnet-4-20250514",
                "orchestra": True,
                "extra_skills": ["builder"],
                "notes": "testing v2 catalog",
            }
            r = TaskResult(
                task_id="t1", run_id="r1", score="pass",
                run_meta=meta,
            )
            out = r.write_json(Path(td) / "result.json")
            loaded = TaskResult.from_json(out)
            assert loaded.run_meta["model"] == meta["model"]
            assert loaded.run_meta["orchestra"] is True

    def test_old_result_no_run_meta_loads(self):
        """Results without run_meta should still load."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            old_data = {
                "task_id": "t1",
                "run_id": "r1",
                "score": "pass",
                "checks": {},
            }
            p = Path(td) / "result.json"
            p.write_text(json.dumps(old_data))
            r = TaskResult.from_json(p)
            assert isinstance(r.run_meta, dict)


# ── 2. Run config file (.bench_run.json) format ───────────────────

class TestBenchRunConfig:
    """The .bench_run.json run config captures operator choices."""

    def test_config_file_structure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / ".bench_run.json"
            expected = {
                "run_id": "test-run-1",
                "task_id": "smoke-public-admin-handoff",
                "model": "google/gemini-2.5-flash",
                "orchestra": True,
                "extra_skills": [],
                "notes": "",
            }
            config_path.write_text(json.dumps(expected))
            data = json.loads(config_path.read_text())
            assert data["run_id"] == expected["run_id"]
            assert data["model"] == expected["model"]

    def test_config_file_minimal_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / ".bench_run.json"
            minimal = {
                "run_id": "r1",
                "task_id": "smoke-public-admin-handoff",
                "model": "",
                "orchestra": None,
                "extra_skills": [],
                "notes": "",
            }
            config_path.write_text(json.dumps(minimal))
            data = json.loads(config_path.read_text())
            assert len(data) >= 6


# ── 3. Run metadata enrichment from .bench_run.json ───────────────

class TestRunMetadataEnrichment:
    """grade() reads .bench_run.json and merges into result.run_meta."""

    def test_enrich_from_bench_run_file(self, tmp_path):
        """When a .bench_run.json exists in the results dir, merge it into run_meta."""
        from eval_harness import _enrich_result_with_bench_run

        # Simulate: the task-open flow wrote this into results/<run_id>-<task_id>/
        result_dir = tmp_path / "results" / "r1-smoke-public-admin-handoff"
        result_dir.mkdir(parents=True)
        config_file = result_dir / ".bench_run.json"
        config_file.write_text(json.dumps({
            "run_id": "r1",
            "task_id": "smoke-public-admin-handoff",
            "model": "google/gemini-2.5-flash",
            "orchestra": True,
            "extra_skills": ["builder"],
            "notes": "first trial",
        }))

        result = _make_result(run_id="r1", task_id="smoke-public-admin-handoff")
        enriched = _enrich_result_with_bench_run(result, base_dir=tmp_path / "results")

        assert enriched.run_meta.get("model") == "google/gemini-2.5-flash"
        assert enriched.run_meta.get("orchestra") is True
        assert enriched.run_meta.get("extra_skills") == ["builder"]
        assert enriched.run_meta.get("notes") == "first trial"

    def test_enrich_no_config_file_is_noop(self, tmp_path):
        """When .bench_run.json doesn't exist, result stays unchanged."""
        from eval_harness import _enrich_result_with_bench_run

        # Create empty results dir (no config file)
        result_dir = tmp_path / "results" / "r2-smoke-public-admin-handoff"
        result_dir.mkdir(parents=True)

        result = _make_result(run_id="r2", task_id="smoke-public-admin-handoff")
        enriched = _enrich_result_with_bench_run(result, base_dir=tmp_path / "results")

        assert len(enriched.run_meta) == 0


# ── 4. Collect-results shows run metadata in summary ───────────────

class TestCollectResultsMetadata:
    """collect-results output includes model/orchestra info when available."""

    def test_summary_includes_run_metadata(self, tmp_path):
        from eval_harness import summarize_results_with_meta

        base = tmp_path / "results"

        # Write result with run_meta
        d1 = base / "r1-task-a"
        d1.mkdir(parents=True)
        r1 = TaskResult(
            task_id="task-a", run_id="r1", score="pass",
            run_meta={"model": "gpt-4o", "orchestra": True},
        )
        r1.write_json(d1 / "result.json")

        # Write result without run_meta (old format)
        d2 = base / "r2-task-a"
        d2.mkdir(parents=True)
        r2 = TaskResult(task_id="task-a", run_id="r2", score="fail")
        r2.write_json(d2 / "result.json")

        summary = summarize_results_with_meta(base)
        assert isinstance(summary, dict)


# ── 5. _prepare-task-run script exists and is executable ─────────────

class TestBuildTaskScript:
    """scripts/_prepare-task-run exists with correct structure."""

    def test_script_exists(self):
        p = _REPO_ROOT / "scripts" / "_prepare-task-run"
        assert p.exists(), f"scripts/_prepare-task-run not found at {p}"

    def test_script_is_executable(self):
        import os
        p = _REPO_ROOT / "scripts" / "_prepare-task-run"
        assert p.exists()
        mode = os.stat(p).st_mode
        assert mode & 0o111, "scripts/_prepare-task-run is not executable"

    def test_script_shows_usage(self):
        import subprocess
        result = sp.run(
            [_REPO_ROOT / "scripts" / "_prepare-task-run", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode in (0, 1, 2), f"unexpected exit: {result.returncode}"


# ── 6. 02-open-pi script exists and is executable ────────────────

class TestOpenPiScript:
    """scripts/02-open-pi exists with correct structure."""

    def test_script_exists(self):
        p = _REPO_ROOT / "scripts" / "02-open-pi"
        assert p.exists(), f"scripts/02-open-pi not found at {p}"

    def test_script_is_executable(self):
        import os
        p = _REPO_ROOT / "scripts" / "02-open-pi"
        assert p.exists()
        mode = os.stat(p).st_mode
        assert mode & 0o111, "scripts/02-open-pi is not executable"

    def test_script_shows_usage(self):
        import subprocess
        result = sp.run(
            [_REPO_ROOT / "scripts" / "02-open-pi", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode in (0, 1, 2)
        assert "--auto" in result.stdout
        assert "--no-orchestra" in result.stdout
        assert "--list" in result.stdout
        assert "config" in result.stdout

    def test_task_list_order_uses_current_public_suites(self):
        script = (_REPO_ROOT / "scripts" / "02-open-pi").read_text()
        assert "order = ['smoke', 'role-focused', 'capability-easy', 'capability-normal', 'capability-advanced']" in script
        assert "order = ['smoke', 'role-focused', 'capability']" not in script

    def test_task_list_shows_capability_easy_and_normal_tasks(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "02-open-pi", "--list"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0
        assert "[capability-easy]" in result.stdout
        assert "[capability-normal]" in result.stdout
        assert "cap-easy-fastapi-helpdesk" in result.stdout
        assert "cap-easy-express-inventory" in result.stdout
        assert "cap-easy-django-reports" in result.stdout
        assert "cap-normal-python-worker-sync" in result.stdout
        assert "cap-normal-ruby-billing-ledger" in result.stdout
        assert "cap-normal-ts-approval-queue" in result.stdout
        assert "[capability-advanced]" in result.stdout
        assert "cap-advanced-url-shortener-review" in result.stdout


class TestBuildStartScript:
    """scripts/01-start exists with correct structure."""

    def test_script_exists(self):
        p = _REPO_ROOT / "scripts" / "01-start"
        assert p.exists(), f"scripts/01-start not found at {p}"

    def test_script_is_executable(self):
        import os
        p = _REPO_ROOT / "scripts" / "01-start"
        assert p.exists()
        mode = os.stat(p).st_mode
        assert mode & 0o111, "scripts/01-start is not executable"

    def test_script_shows_usage(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "01-start", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0
        help_text = result.stdout
        assert "start" in help_text.lower()
        assert "stop" in help_text.lower()
        assert "build|start" not in help_text

    def test_start_busts_source_plugin_cache_only(self):
        script = (_REPO_ROOT / "scripts" / "01-start").read_text()
        dockerfile = (_REPO_ROOT / "docker" / "Dockerfile").read_text()
        assert "--no-cache" not in script
        assert "--build-arg SOURCE_PLUGIN_CACHE_BUST=" in script
        assert "ARG SOURCE_PLUGIN_CACHE_BUST" in dockerfile
        assert dockerfile.index("ARG SOURCE_PLUGIN_CACHE_BUST") < dockerfile.index("git clone \"$ORCHESTRA_REPO_URL\"")
        assert dockerfile.index("ARG SOURCE_PLUGIN_CACHE_BUST") < dockerfile.index("pi install \"$PI_LMSTUDIO_PLUGIN_URL\"")

    def test_stop_removes_container(self, tmp_path):
        import os

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"
        docker = bin_dir / "docker"
        state_file = tmp_path / "container-exists"
        state_file.write_text("yes")
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) [ -f \"$STATE_FILE\" ] && exit 0 || exit 1 ;;\n"
            "  rm) rm -f \"$STATE_FILE\"; exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
            "STATE_FILE": str(state_file),
        })
        result = sp.run(
            [_REPO_ROOT / "scripts" / "01-start", "stop"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "rm -f orchestra-bench-runner" in docker_log.read_text()


class TestOpenPiInteractiveSession:
    """02-open-pi should open Pi interactively instead of print mode."""

    def test_open_pi_command_omits_print_mode(self, tmp_path):
        import os

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) printf 'true\\n'; exit 0 ;;\n"
            "  exec) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
        })

        results_dir = _REPO_ROOT / "results"
        before = {p for p in results_dir.glob("*-smoke-public-admin-handoff")}
        try:
            result = sp.run(
                [_REPO_ROOT / "scripts" / "02-open-pi", "smoke-public-admin-handoff"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
        finally:
            import shutil
            for p in results_dir.glob("*-smoke-public-admin-handoff"):
                if p not in before:
                    shutil.rmtree(p, ignore_errors=True)

        assert result.returncode == 0
        script_text = (_REPO_ROOT / "scripts" / "02-open-pi").read_text()
        assert "cat $PROMPT_MD" in script_text
        assert "exec pi --model" in script_text
        assert "task_prompt=$(cat" not in script_text
        assert "--print" not in script_text
        log = docker_log.read_text()
        assert "exec pi --model" in log
        assert "--print" not in log
        assert '-p "$prompt"' not in log

    def test_open_pi_auto_uses_print_mode(self, tmp_path):
        import os

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) printf 'true\\n'; exit 0 ;;\n"
            "  exec) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
        })

        results_dir = _REPO_ROOT / "results"
        before = {p for p in results_dir.glob("*-smoke-public-admin-handoff")}
        try:
            result = sp.run(
                [_REPO_ROOT / "scripts" / "02-open-pi", "smoke-public-admin-handoff", "--auto", "--auto-runner", "print"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
        finally:
            import shutil
            for p in results_dir.glob("*-smoke-public-admin-handoff"):
                if p not in before:
                    shutil.rmtree(p, ignore_errors=True)

        assert result.returncode == 0
        assert "--auto" in result.stdout or "auto:" in result.stdout
        log = docker_log.read_text()
        assert "pi --model" in log
        assert " -p " in log
        assert "BENCH_AUTO_ORCH_ON=true" in log
        assert '-p "/orch on"' in log
        assert "--continue --model" in log

    def test_auto_orchestra_preflight_is_verified_and_task_prompt_gets_skill(self):
        script = (_REPO_ROOT / "scripts" / "02-open-pi").read_text()
        assert "preflight_output=$(pi --model \"$BENCH_MODEL\" -p \"/orch on\" 2>&1)" in script
        assert "Orchestra orchestrator skill refreshed" in script
        assert "orchestrator_skill=$(orchestra _orchestrator-skill)" in script
        assert 'prompt="$orchestrator_skill' in script

    def test_auto_flow_collects_artifacts_before_grading_cleanup(self):
        script = (_REPO_ROOT / "scripts" / "02-open-pi").read_text()
        assert "from eval_harness import collect_run_artifacts" in script
        assert script.index("collect_run_artifacts(sys.argv[2], sys.argv[3])") < script.index("$ROOT/scripts/03-collect-results")

    def test_auto_flow_uses_run_process_cleanup_without_task_timeout(self):
        open_pi = (_REPO_ROOT / "scripts" / "02-open-pi").read_text()
        collect = (_REPO_ROOT / "scripts" / "03-collect-results").read_text()
        cleanup = (_REPO_ROOT / "scripts" / "_cleanup-run-processes")

        assert cleanup.exists()
        assert cleanup.stat().st_mode & 0o111
        assert "cleanup_run_processes" in open_pi
        assert "trap cleanup_run_processes EXIT" in open_pi
        assert "\"$ROOT/scripts/_cleanup-run-processes\" \"$task_id\" --run-id \"$BENCH_RUN_ID\"" in open_pi
        assert "\"$ROOT/scripts/_cleanup-run-processes\" \"$task_id\" --run-id \"$run_id\"" in collect
        assert "timeout" not in cleanup.read_text().lower()

    def test_open_pi_auto_can_skip_orch_on_for_baseline(self, tmp_path):
        import os
        import shutil

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) printf 'true\\n'; exit 0 ;;\n"
            "  exec) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
        })

        results_dir = _REPO_ROOT / "results"
        before = {p for p in results_dir.glob("*-smoke-public-admin-handoff")}
        try:
            result = sp.run(
                [_REPO_ROOT / "scripts" / "02-open-pi", "smoke-public-admin-handoff", "--auto", "--no-orchestra", "--auto-runner", "print"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
        finally:
            for p in results_dir.glob("*-smoke-public-admin-handoff"):
                if p not in before:
                    shutil.rmtree(p, ignore_errors=True)

        assert result.returncode == 0
        assert "/orch on preflight skipped" in result.stdout
        log = docker_log.read_text()
        assert "BENCH_AUTO_ORCH_ON=false" in log
        assert "BENCH_ROLE_INSTRUCTION" not in log
        assert '-p "/orch on"' in log  # shell branch remains present but gated by BENCH_AUTO_ORCH_ON
        assert "First use /orch on" not in log
        assert "This task expects Orchestra workflow behavior" not in log
        assert "parent/coordinator" not in log

    def test_role_focused_auto_keeps_workflow_instruction_in_task_prompt_only(self, tmp_path):
        import os
        import shutil

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) printf 'true\\n'; exit 0 ;;\n"
            "  exec) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
        })

        task_id = "planner-plan-migration"
        results_dir = _REPO_ROOT / "results"
        before = {p for p in results_dir.glob(f"*-{task_id}")}
        try:
            result = sp.run(
                [_REPO_ROOT / "scripts" / "02-open-pi", task_id, "--auto", "--auto-runner", "print"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            created = [p for p in results_dir.glob(f"*-{task_id}") if p not in before]
            assert created, "expected 02-open-pi to create a run metadata dir"
            cfg = json.loads((created[0] / ".bench_run.json").read_text())
        finally:
            for p in results_dir.glob(f"*-{task_id}"):
                if p not in before:
                    shutil.rmtree(p, ignore_errors=True)

        assert result.returncode == 0
        assert "role:   builder" in result.stdout
        assert "target: planner" in result.stdout
        assert cfg["role"] == "builder"
        assert cfg["target_role"] == "planner"
        assert cfg["orchestra"] is True
        log = docker_log.read_text()
        assert "BENCH_ROLE_INSTRUCTION" not in log
        assert "parent/coordinator" not in log
        assert "dispatch to the planner role" not in log
        assert "dispatch the $target_role role" not in log
        assert "dispatch the $BENCH_TARGET_ROLE role" not in log

    def test_orchestrator_task_auto_marks_orchestra_without_verbose_prompt_injection(self, tmp_path):
        import os
        import shutil

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) printf 'true\\n'; exit 0 ;;\n"
            "  exec) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
        })

        task_id = "smoke-migration-release-check"
        results_dir = _REPO_ROOT / "results"
        before = {p for p in results_dir.glob(f"*-{task_id}")}
        try:
            result = sp.run(
                [_REPO_ROOT / "scripts" / "02-open-pi", task_id, "--auto", "--auto-runner", "print"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            created = [p for p in results_dir.glob(f"*-{task_id}") if p not in before]
            assert created, "expected 02-open-pi to create a run metadata dir"
            cfg = json.loads((created[0] / ".bench_run.json").read_text())
        finally:
            for p in results_dir.glob(f"*-{task_id}"):
                if p not in before:
                    shutil.rmtree(p, ignore_errors=True)

        assert result.returncode == 0
        assert cfg["orchestra"] is True
        log = docker_log.read_text()
        assert '-p "/orch on"' in log
        assert "BENCH_ROLE_INSTRUCTION" not in log
        assert "dispatch to planner, researcher, builder, verifier, reviewer, appsec" not in log
        assert "First use /orch on" not in log
        assert "parent/coordinator" not in log

    def test_smoke_auto_uses_task_prompt_without_workflow_injection(self, tmp_path):
        import os
        import shutil

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_log = tmp_path / "docker.log"

        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
            "case \"$1\" in\n"
            "  inspect) printf 'true\\n'; exit 0 ;;\n"
            "  exec) exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        docker.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
        })

        task_id = "smoke-migration-release-check"
        results_dir = _REPO_ROOT / "results"
        before = {p for p in results_dir.glob(f"*-{task_id}")}
        try:
            result = sp.run(
                [_REPO_ROOT / "scripts" / "02-open-pi", task_id, "--auto", "--auto-runner", "print"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            created = [p for p in results_dir.glob(f"*-{task_id}") if p not in before]
            assert created, "expected 02-open-pi to create a run metadata dir"
            cfg = json.loads((created[0] / ".bench_run.json").read_text())
        finally:
            for p in results_dir.glob(f"*-{task_id}"):
                if p not in before:
                    shutil.rmtree(p, ignore_errors=True)

        assert result.returncode == 0
        assert cfg["orchestra"] is True
        log = docker_log.read_text()
        assert '-p "/orch on"' in log
        assert "BENCH_ROLE_INSTRUCTION" not in log
        assert "dispatch to planner, researcher, builder, verifier, reviewer, appsec" not in log
        assert "This task expects Orchestra workflow behavior" not in log
        assert "First use /orch on" not in log
        assert "parent/coordinator" not in log


class TestCollectResultsUsage:
    """03-collect-results docs should match grading behavior."""

    def test_collect_results_does_not_run_results_dashboard(self):
        script = (_REPO_ROOT / "scripts" / "03-collect-results").read_text()
        assert '"$ROOT/scripts/05-results"' not in script
        assert "Use scripts/05-results explicitly for reporting" in script

    def test_help_describes_grade_all_default(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "03-collect-results", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        help_text = result.stdout
        assert "grade every prepared/ungraded run" in help_text.lower()
        assert "already-graded runs are skipped" in help_text.lower()
        assert "use scripts/05-results explicitly for reporting" in help_text.lower()
        assert "--force" in help_text
        assert "compare" in help_text.lower()


# ── 7. 04-run-suite script exists and is executable ──────────────

class TestRunSuiteScript:
    """scripts/04-run-suite exists with correct structure."""

    def test_script_exists(self):
        p = _REPO_ROOT / "scripts" / "04-run-suite"
        assert p.exists(), f"scripts/04-run-suite not found at {p}"

    def test_script_is_executable(self):
        import os
        p = _REPO_ROOT / "scripts" / "04-run-suite"
        assert p.exists()
        mode = os.stat(p).st_mode
        assert mode & 0o111, "scripts/04-run-suite is not executable"

    def test_script_shows_usage(self):
        import subprocess
        result = sp.run(
            [_REPO_ROOT / "scripts" / "04-run-suite", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode in (0, 1, 2)
        assert "--auto" in result.stdout
        assert "--collect-only" not in result.stdout
        assert "--no-orchestra" in result.stdout
        assert "default dogfood suite flow" in result.stdout.lower()

    def test_script_runs_open_pi_auto_before_collecting(self):
        script = (_REPO_ROOT / "scripts" / "04-run-suite").read_text()
        assert 'open_pi_args=("$task_id" --auto)' in script
        assert '"$ROOT/scripts/02-open-pi" "${open_pi_args[@]}"' in script
        assert '"$ROOT/scripts/03-collect-results" "$task_id"' in script
        assert script.index('"$ROOT/scripts/02-open-pi" "${open_pi_args[@]}"') < script.index('"$ROOT/scripts/03-collect-results" "$task_id"')

    def test_script_does_not_keep_collect_only_mode(self):
        script = (_REPO_ROOT / "scripts" / "04-run-suite").read_text()
        assert "--collect-only" not in script
        assert "run_auto=false" not in script

    def test_script_supports_no_orchestra_passthrough(self):
        script = (_REPO_ROOT / "scripts" / "04-run-suite").read_text()
        assert "--no-orchestra" in script
        assert "no_orchestra=false" in script
        assert "no_orchestra=true" in script
        assert "open_pi_args+=(--no-orchestra)" in script

    def test_script_lists_current_public_suites(self):
        script = (_REPO_ROOT / "scripts" / "04-run-suite").read_text()
        assert "capability-easy" in script
        assert "capability-normal" in script
        assert "capability-advanced" in script
        assert "capability\n" not in script

    def test_capability_suite_counts_include_restored_tasks(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "04-run-suite", "--list"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0
        assert "capability-easy" in result.stdout and "3 tasks" in result.stdout
        assert "capability-normal" in result.stdout and "3 tasks" in result.stdout
        assert "capability-advanced" in result.stdout and "1 tasks" in result.stdout

    def test_unknown_suite_still_fails(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "04-run-suite", "capability"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode != 0
        assert "unknown suite: capability" in result.stderr

    def test_multiple_suites_before_options_run_sequentially(self, tmp_path):
        import os

        root = tmp_path
        scripts = root / "scripts"
        tasks = root / "tasks"
        results = root / "results"
        scripts.mkdir()
        tasks.mkdir()
        results.mkdir()

        (scripts / "04-run-suite").write_text((_REPO_ROOT / "scripts" / "04-run-suite").read_text())
        (scripts / "04-run-suite").chmod(0o755)

        (scripts / "02-open-pi").write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf 'open %s notes=%s\\n' \"$*\" \"${BENCH_NOTES:-}\" >> \"$BENCH_LOG\"\n"
        )
        (scripts / "02-open-pi").chmod(0o755)
        (scripts / "03-collect-results").write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf 'collect %s\\n' \"$*\" >> \"$BENCH_LOG\"\n"
        )
        (scripts / "03-collect-results").chmod(0o755)
        (root / "cli.py").write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.exit(0)\n"
        )
        (root / "cli.py").chmod(0o755)

        for suite, task_id in [("smoke", "smoke-alpha"), ("capability-easy", "easy-alpha")]:
            task_dir = tasks / task_id
            task_dir.mkdir()
            (task_dir / "task.yaml").write_text(f"task_id: {task_id}\nbatch: {suite}\n")

        bench_log = root / "bench.log"
        env = os.environ.copy()
        env.update({
            "BENCH_LOG": str(bench_log),
            "PATH": f"{scripts}:{env['PATH']}",
        })

        result = sp.run(
            [scripts / "04-run-suite", "smoke", "capability-easy", "--no-orchestra", "--notes", "hello"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert bench_log.read_text().splitlines() == [
            "open smoke-alpha --auto --no-orchestra notes=hello",
            "collect smoke-alpha",
            "open easy-alpha --auto --no-orchestra notes=hello",
            "collect easy-alpha",
        ]


class TestResultsScript:
    """scripts/05-results exposes historical reporting views."""

    def test_script_exists_and_has_help(self):
        import os
        p = _REPO_ROOT / "scripts" / "05-results"
        assert p.exists(), f"scripts/05-results not found at {p}"
        assert os.stat(p).st_mode & 0o111, "scripts/05-results is not executable"
        result = sp.run([p, "--help"], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0
        assert "dashboard" in result.stdout
        assert "tokens" in result.stdout
        assert "timeline" in result.stdout


# ── 8. Full flow: build -> metadata -> eval with metadata ─────────

class TestFullOperatorFlow:
    """End-to-end: config file written during task prep is read during eval."""

    def test_prepare_task_writes_config(self, tmp_path):
        """task prep should create .bench_run.json in results dir."""
        # Simulate what the script does: write a run config
        import json as _json
        result_dir = tmp_path / "results" / "test-run-smoke"
        result_dir.mkdir(parents=True)

        config = {
            "run_id": "test-run",
            "task_id": "smoke-public-admin-handoff",
            "model": "google/gemini-2.5-flash",
            "orchestra": True,
            "extra_skills": [],
            "notes": "",
        }
        (result_dir / ".bench_run.json").write_text(_json.dumps(config))

        # Verify the config is readable
        loaded = _json.loads((result_dir / ".bench_run.json").read_text())
        assert loaded["model"] == config["model"]

    def test_full_flow_metadata_persists(self, tmp_path):
        """When eval enriches result with .bench_run.json, it persists in result.json."""
        from eval_harness import _enrich_result_with_bench_run

        # 1. task prep writes config
        result_dir = tmp_path / "results" / "full-test-smoke-public-admin-handoff"
        result_dir.mkdir(parents=True)
        (result_dir / ".bench_run.json").write_text(json.dumps({
            "run_id": "full-test",
            "task_id": "smoke-public-admin-handoff",
            "model": "gpt-4o",
            "orchestra": False,
            "extra_skills": ["builder"],
            "notes": "manual run test",
        }))

        # 2. Eval creates result
        result = TaskResult(task_id="smoke-public-admin-handoff", run_id="full-test", score="pass")

        # 3. Enrich from config file
        enriched = _enrich_result_with_bench_run(result, base_dir=tmp_path / "results")

        # 4. Write final result
        out = enriched.write_json(result_dir)

        # 5. Reload and verify metadata persisted
        loaded = TaskResult.from_json(out)
        assert loaded.run_meta.get("model") == "gpt-4o"
        assert loaded.run_meta.get("orchestra") is False
        assert loaded.run_meta.get("extra_skills") == ["builder"]


class TestEvalFlowUsesExistingWorkdir:
    """Eval should enter the existing workdir instead of recreating it."""

    def test_grade_enters_existing_workdir(self, tmp_path, monkeypatch):
        import eval_harness

        base_results = tmp_path / "results"
        run_dir = base_results / "run-1-smoke-public-admin-handoff"
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(eval_harness, "RESULTS_DIR", str(base_results))

        calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []
        cp_calls: list[tuple[str, ...]] = []

        def fake_docker_exec(*args: str, env: dict[str, str] | None = None):
            calls.append((args, env))
            return sp.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")

        def fake_run(*args, **kwargs):
            argv = tuple(args[0])
            if argv[:2] == ("docker", "cp"):
                cp_calls.append(argv)
            return sp.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_exec", fake_docker_exec)
        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness.sp, "run", fake_run)

        result = eval_harness.grade(
            "smoke-public-admin-handoff",
            "run-1",
            task_meta=TaskMeta(task_id="smoke-public-admin-handoff", description="smoke", family="smoke"),
        )

        assert result.score == "pass"
        assert calls, "expected docker exec to be called"
        eval_calls = [(argv, env) for argv, env in calls if argv[:3] == ("bench-entrypoint", "eval", "smoke-public-admin-handoff")]
        assert eval_calls, calls
        argv, env = eval_calls[0]
        assert "run" not in argv[:3]
        assert "/tmp/bench-eval-run-1-smoke-public-admin-handoff/evaluate/run.sh" in argv
        assert env and env["BENCH_RUN_ID"] == "run-1"
        assert env["BENCH_TASK_ID"] == "smoke-public-admin-handoff"
        assert env["BENCH_TASKS"] == str(eval_harness._REPO_ROOT / eval_harness.TASKS_DIR)
        assert env["BENCH_REPO_ROOT"] == "/tmp/bench-eval-run-1-smoke-public-admin-handoff/evaluate"

        copied = {argv[2]: argv[3] for argv in cp_calls}
        eval_tmp = "/tmp/bench-eval-run-1-smoke-public-admin-handoff/evaluate"
        assert str(eval_harness._REPO_ROOT / "tasks" / "smoke-public-admin-handoff" / "evaluate" / "run.sh") in copied
        assert copied[str(eval_harness._REPO_ROOT / "tasks" / "smoke-public-admin-handoff" / "evaluate" / "run.sh")] == f"{eval_harness.CONTAINER_NAME}:{eval_tmp}/run.sh"
        assert copied[str(eval_harness._REPO_ROOT / "capability_helpers.py")] == f"{eval_harness.CONTAINER_NAME}:{eval_tmp}/capability_helpers.py"
        assert copied[str(eval_harness._REPO_ROOT / "rubric_helpers.py")] == f"{eval_harness.CONTAINER_NAME}:{eval_tmp}/rubric_helpers.py"

    def test_grade_preserves_rubric_fields_from_noisy_stdout(self, tmp_path, monkeypatch):
        import eval_harness

        base_results = tmp_path / "results"
        run_dir = base_results / "run-1-smoke-public-admin-handoff"
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(eval_harness, "RESULTS_DIR", str(base_results))
        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness.sp, "run", lambda *a, **k: sp.CompletedProcess(args=a[0], returncode=0, stdout="", stderr=""))

        stdout_payload = """[bench-entrypoint] evaluator starting
{
  \"score\": \"pass\",
  \"score_numeric\": 0.86,
  \"rubric\": {
    \"role_result_quality\": {\"score\": 0.35, \"max\": 0.40}
  },
  \"checks\": {\"answer_exists\": true}
}
"""

        def fake_docker_exec(*args: str, env: dict[str, str] | None = None):
            if args[:3] == ("bench-entrypoint", "eval", "smoke-public-admin-handoff"):
                return sp.CompletedProcess(args=["docker"], returncode=0, stdout=stdout_payload, stderr="")
            return sp.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_exec", fake_docker_exec)

        result = eval_harness.grade(
            "smoke-public-admin-handoff",
            "run-1",
            task_meta=TaskMeta(task_id="smoke-public-admin-handoff", description="smoke", family="smoke"),
        )

        assert result.score == "pass"
        assert result.score_numeric == pytest.approx(0.86)
        assert result.rubric == {
            "role_result_quality": {"score": 0.35, "max": 0.40}
        }
        assert result.checks == {"answer_exists": True}

    def test_grade_force_regrade_preserves_existing_elapsed_without_completion_time(self, tmp_path, monkeypatch):
        import eval_harness

        base_results = tmp_path / "results"
        run_dir = base_results / "run-1-smoke-public-admin-handoff"
        run_dir.mkdir(parents=True)
        (run_dir / ".bench_run.json").write_text(json.dumps({
            "run_id": "run-1",
            "task_id": "smoke-public-admin-handoff",
            "started_epoch": 1000,
        }))
        TaskResult(
            task_id="smoke-public-admin-handoff",
            run_id="run-1",
            score="pass",
            elapsed_seconds=55.0,
        ).write_json(run_dir)

        monkeypatch.setattr(eval_harness, "RESULTS_DIR", str(base_results))
        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness, "time", type("T", (), {"time": staticmethod(lambda: 1100)})())
        monkeypatch.setattr(eval_harness.sp, "run", lambda *a, **k: sp.CompletedProcess(args=a[0], returncode=0, stdout="", stderr=""))

        def fake_docker_exec(*args: str, env: dict[str, str] | None = None):
            if args[:3] == ("bench-entrypoint", "eval", "smoke-public-admin-handoff"):
                return sp.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout='{"score": "pass", "checks": {"answer_exists": true}}',
                    stderr="",
                )
            return sp.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_exec", fake_docker_exec)

        result = eval_harness.grade(
            "smoke-public-admin-handoff",
            "run-1",
            task_meta=TaskMeta(task_id="smoke-public-admin-handoff", description="smoke", family="smoke"),
        )

        assert result.elapsed_seconds == 55.0
        assert result.efficiency["elapsed"]["current"] == 55.0

    def test_grade_elapsed_fallback_is_available_to_efficiency(self, tmp_path, monkeypatch):
        import eval_harness

        base_results = tmp_path / "results"
        run_dir = base_results / "run-1-smoke-public-admin-handoff"
        run_dir.mkdir(parents=True)
        (run_dir / ".bench_run.json").write_text(json.dumps({
            "run_id": "run-1",
            "task_id": "smoke-public-admin-handoff",
            "started_epoch": 1000,
        }))

        monkeypatch.setattr(eval_harness, "RESULTS_DIR", str(base_results))
        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness, "time", type("T", (), {"time": staticmethod(lambda: 1123.45)})())
        monkeypatch.setattr(eval_harness.sp, "run", lambda *a, **k: sp.CompletedProcess(args=a[0], returncode=0, stdout="", stderr=""))

        def fake_docker_exec(*args: str, env: dict[str, str] | None = None):
            if args[:3] == ("bench-entrypoint", "eval", "smoke-public-admin-handoff"):
                return sp.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout='{"score": "pass", "checks": {"answer_exists": true}}',
                    stderr="",
                )
            return sp.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_exec", fake_docker_exec)

        result = eval_harness.grade(
            "smoke-public-admin-handoff",
            "run-1",
            task_meta=TaskMeta(task_id="smoke-public-admin-handoff", description="smoke", family="smoke"),
        )

        assert result.elapsed_seconds == pytest.approx(123.45)
        assert result.efficiency["elapsed"]["current"] == pytest.approx(123.45)

    def test_grade_fails_when_regrade_returns_no_json(self, tmp_path, monkeypatch):
        import eval_harness

        base_results = tmp_path / "results"
        run_dir = base_results / "run-1-smoke-public-admin-handoff"
        run_dir.mkdir(parents=True)
        TaskResult(
            task_id="smoke-public-admin-handoff",
            run_id="run-1",
            score="pass",
            checks={"answer_exists": True},
            score_numeric=0.86,
            rubric={"role_result_quality": {"score": 0.35, "max": 0.40}},
            tokens={"total": 900},
            elapsed_seconds=55.0,
        ).write_json(run_dir)

        monkeypatch.setattr(eval_harness, "RESULTS_DIR", str(base_results))
        monkeypatch.setattr(eval_harness, "_docker_ok", lambda: True)
        monkeypatch.setattr(eval_harness.sp, "run", lambda *a, **k: sp.CompletedProcess(args=a[0], returncode=0, stdout="", stderr=""))

        def fake_docker_exec(*args: str, env: dict[str, str] | None = None):
            if args[:3] == ("bench-entrypoint", "eval", "smoke-public-admin-handoff"):
                return sp.CompletedProcess(args=["docker"], returncode=1, stdout="", stderr="")
            return sp.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(eval_harness, "_docker_exec", fake_docker_exec)

        with pytest.raises(RuntimeError, match="evaluator failed without JSON"):
            eval_harness.grade(
                "smoke-public-admin-handoff",
                "run-1",
                task_meta=TaskMeta(task_id="smoke-public-admin-handoff", description="smoke", family="smoke"),
            )


class TestOperatorDocs:
    def test_readme_matches_thin_operator_flow(self):
        readme = (_REPO_ROOT / "README.md").read_text()

        assert "scripts/01-start" in readme
        assert "scripts/02-open-pi <task-id>" in readme
        assert "scripts/02-open-pi --list" in readme
        assert "scripts/03-collect-results" in readme
        assert "The operator interface uses numbered scripts only" in readme
        assert "scripts/04-run-suite <suite>" in readme
        assert "scripts/_prepare-task-run <task-id>" not in readme
        assert "scripts/start-env start" not in readme
