from __future__ import annotations

import json
import subprocess as sp
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from __init__ import TaskResult  # noqa: E402
from eval_harness import build_run_metadata, resolve_catalog_model, _enrich_result_with_bench_run  # noqa: E402


class TestCatalogModelProvenance:
    def test_resolve_catalog_model_defaults_to_default_role(self, tmp_path):
        catalog = tmp_path / "agent-catalog.yaml"
        catalog.write_text(
            "default_role: builder\n"
            "roles:\n"
            "  builder:\n"
            "    model: openai-codex/gpt-5.4-mini\n"
            "  verifier:\n"
            "    model: openai-codex/gpt-5.4\n"
        )

        resolved = resolve_catalog_model(catalog)

        assert resolved["role"] == "builder"
        assert resolved["default_role"] == "builder"
        assert resolved["model"] == "openai-codex/gpt-5.4-mini"
        assert resolved["catalog_sha256"]

    def test_resolve_catalog_model_uses_explicit_role(self, tmp_path):
        catalog = tmp_path / "agent-catalog.yaml"
        catalog.write_text(
            "default_role: builder\n"
            "roles:\n"
            "  builder:\n"
            "    model: openai-codex/gpt-5.4-mini\n"
            "  verifier:\n"
            "    model: openai-codex/gpt-5.4\n"
        )

        resolved = resolve_catalog_model(catalog, role="verifier")

        assert resolved["role"] == "verifier"
        assert resolved["model"] == "openai-codex/gpt-5.4"


class TestRunMetadataProvenance:
    def test_build_run_metadata_includes_catalog_provenance(self, tmp_path):
        catalog = tmp_path / "agent-catalog.yaml"
        catalog.write_text(
            "default_role: builder\n"
            "roles:\n"
            "  builder:\n"
            "    model: openai-codex/gpt-5.4-mini\n"
            "    skills: [builder]\n"
            "  reviewer:\n"
            "    model: openai-codex/gpt-5.4\n"
        )

        meta = build_run_metadata(
            task_id="smoke",
            run_id="r1",
            catalog_path=catalog,
            catalog_label="config/orchestra/agent-catalog.yaml",
            role="reviewer",
            orchestra=True,
            extra_skills=["builder"],
            notes="first trial",
        )

        assert meta["task_id"] == "smoke"
        assert meta["run_id"] == "r1"
        assert meta["role"] == "reviewer"
        assert meta["default_role"] == "builder"
        assert meta["model"] == "openai-codex/gpt-5.4"
        assert meta["orchestra"] is True
        assert meta["extra_skills"] == ["builder"]
        assert meta["catalog_path"] == "config/orchestra/agent-catalog.yaml"
        assert meta["catalog_sha256"]

    def test_enrich_result_merges_all_bench_run_fields(self, tmp_path):
        result_dir = tmp_path / "results" / "r1-smoke"
        result_dir.mkdir(parents=True)

        bench_run = {
            "run_id": "r1",
            "task_id": "smoke",
            "role": "builder",
            "default_role": "builder",
            "model": "openai-codex/gpt-5.4-mini",
            "catalog_path": "config/orchestra/agent-catalog.yaml",
            "catalog_sha256": "abc123",
            "orchestra": False,
            "extra_skills": ["builder"],
            "notes": "manual run",
        }
        (result_dir / ".bench_run.json").write_text(json.dumps(bench_run))

        result = TaskResult(task_id="smoke", run_id="r1", score="pass")
        enriched = _enrich_result_with_bench_run(result, base_dir=tmp_path / "results")

        assert enriched.run_meta["model"] == "openai-codex/gpt-5.4-mini"
        assert enriched.run_meta["role"] == "builder"
        assert enriched.run_meta["catalog_sha256"] == "abc123"
        assert enriched.run_meta["orchestra"] is False


class TestOperatorScriptHelp:
    def test_build_task_help_mentions_role_and_not_pi_model(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "_prepare-task-run", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "--role" in result.stdout
        assert "PI_MODEL" not in result.stdout

    def test_open_pi_help_mentions_catalog_derived_model(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "02-open-pi", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "catalog-derived model" in result.stdout
        assert "PI_MODEL" not in result.stdout

    def test_run_suite_help_does_not_mention_pi_model(self):
        result = sp.run(
            [_REPO_ROOT / "scripts" / "04-run-suite", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "PI_MODEL" not in result.stdout
        assert "--model" not in result.stdout

    def test_run_suite_source_does_not_read_pi_model(self):
        script = (_REPO_ROOT / "scripts" / "04-run-suite").read_text()
        assert "PI_MODEL" not in script
