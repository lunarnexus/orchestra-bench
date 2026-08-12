"""Tests for Slice 10 — task artifact migration from task.md to PRD.md + Prompt.md."""

from __future__ import annotations

import json
import subprocess as sp
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ────────────────────────────────────────────────────────

def _task_dirs():
    """Return all task directories that have a task.yaml."""
    tasks_dir = _REPO_ROOT / "tasks"
    if not tasks_dir.exists():
        return []
    return sorted(d for d in tasks_dir.iterdir() if (d / "task.yaml").exists())


# ── 1. Every task has PRD.md and Prompt.md ────────────────────────

class TestTaskArtifactPresence:
    """Each task folder must have PRD.md and Prompt.md, not task.md."""

    @pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda d: d.name)
    def test_task_has_prd(self, task_dir):
        prd = task_dir / "PRD.md"
        assert prd.exists(), f"{task_dir.name} missing PRD.md"

    @pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda d: d.name)
    def test_task_has_prompt(self, task_dir):
        prompt = task_dir / "Prompt.md"
        assert prompt.exists(), f"{task_dir.name} missing Prompt.md"

    @pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda d: d.name)
    def test_task_no_legacy_task_md(self, task_dir):
        task_md = task_dir / "task.md"
        assert not task_md.exists(), f"{task_dir.name} still has legacy task.md — should be removed after migration to PRD.md + Prompt.md"

    @pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda d: d.name)
    def test_prd_non_empty(self, task_dir):
        prd = (task_dir / "PRD.md").read_text().strip()
        assert len(prd) > 50, f"{task_dir.name}/PRD.md is too short — should contain product requirements"

    @pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda d: d.name)
    def test_prompt_non_empty(self, task_dir):
        prompt = (task_dir / "Prompt.md").read_text().strip()
        assert len(prompt) > 30, f"{task_dir.name}/Prompt.md is too short — should contain agent instructions"

    @pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda d: d.name)
    def test_prompt_mentions_dispatch_early(self, task_dir):
        prompt_lines = (task_dir / "Prompt.md").read_text().splitlines()
        early_text = "\n".join(prompt_lines[:6]).lower()
        assert "dispatch" in early_text, (
            f"{task_dir.name}/Prompt.md should mention dispatch near the top of the initial prompt"
        )


# ── 2. Scripts reference Prompt.md not task.md ────────────────────

class TestScriptArtifactRefs:
    """Operator scripts must reference Prompt.md, not task.md."""

    def test_open_pi_uses_prompt_md(self):
        script = (_REPO_ROOT / "scripts" / "02-open-pi").read_text()
        assert "Prompt.md" in script, "02-open-pi should reference Prompt.md"
        # Should not use task.md as the primary prompt source
        lines = [l for l in script.splitlines() if "task.md" in l.lower()]
        assert len(lines) < 3, f"02-open-pi still references task.md: {lines}"

    def test_entrypoint_copies_prd(self):
        """Entrypoint 'run' command should copy PRD.md into the workdir."""
        entrypoint = (_REPO_ROOT / "docker" / "entrypoint.sh").read_text()
        assert "PRD.md" in entrypoint, "entrypoint should copy PRD.md into workdir"


# ── 3. Entrypoint copies agent-visible artifacts correctly ───────

class TestEntrypointArtifactCopy:
    """The bench-entrypoint 'run' command copies the right files."""

    def test_entrypoint_copies_fixture(self):
        entrypoint = (_REPO_ROOT / "docker" / "entrypoint.sh").read_text()
        assert "fixture" in entrypoint, "entrypoint should copy fixture contents"

    def test_entrypoint_does_not_copy_evaluate(self):
        """Evaluator materials should not be copied into the workdir."""
        entrypoint = (_REPO_ROOT / "docker" / "entrypoint.sh").read_text()
        # In the 'run' section, evaluate/ shouldn't be copied
        run_section = entrypoint.split("run)")[1].split("\n")[:20]
        run_text = "\n".join(run_section)
        assert "evaluate" not in run_text.lower(), "entrypoint should not copy evaluate/ into workdir during 'run'"


# ── 4. README documents the artifact model correctly ─────────────

class TestReadmeArtifactModel:
    """README must document PRD.md + Prompt.md as the task artifact model."""

    def test_readme_documents_prd(self):
        readme = (_REPO_ROOT / "README.md").read_text()
        assert "PRD.md" in readme, "README should document PRD.md"

    def test_readme_documents_prompt(self):
        readme = (_REPO_ROOT / "README.md").read_text()
        assert "Prompt.md" in readme, "README should document Prompt.md"

    def test_readme_no_legacy_task_md_note(self):
        """README shouldn't say tasks currently use task.md."""
        readme = (_REPO_ROOT / "README.md").read_text()
        # Check the artifact model section doesn't mention legacy task.md as current state
        lines = readme.splitlines()
        for i, line in enumerate(lines):
            if "task.md" in line.lower():
                # Allow mentioning it if it's about migration history, not current state
                assert "(planned)" not in line and "currently" not in line.lower(), \
                    f"README still marks PRD/Prompt as planned or mentions task.md as current: {line}"


# ── 5. Task/evaluator contract clarity ─────────────────────────

class TestTaskEvaluatorContractClarity:
    """PRDs should disclose evaluator-required output fields when specific."""

    def test_admin_handoff_prd_names_admin_note_field(self):
        prd = (_REPO_ROOT / "tasks" / "smoke-public-admin-handoff" / "PRD.md").read_text()
        evaluator = (_REPO_ROOT / "tasks" / "smoke-public-admin-handoff" / "evaluate" / "run.sh").read_text()
        assert "admin_note" in evaluator
        assert "admin_note" in prd

    def test_admin_handoff_prd_says_submit_returns_request_dict(self):
        prd = (_REPO_ROOT / "tasks" / "smoke-public-admin-handoff" / "PRD.md").read_text().lower()
        evaluator = (_REPO_ROOT / "tasks" / "smoke-public-admin-handoff" / "evaluate" / "run.sh").read_text()
        assert "r=support.submit_request" in evaluator
        assert "returns the created request dict" in prd

    def test_billing_prd_says_webhook_returns_dict(self):
        prd = (_REPO_ROOT / "tasks" / "smoke-billing-webhook-lifecycle" / "PRD.md").read_text().lower()
        evaluator = (_REPO_ROOT / "tasks" / "smoke-billing-webhook-lifecycle" / "evaluate" / "run.sh").read_text()
        assert "hook['payload']" in evaluator
        assert "returns a dict containing `payload` and `signature` keys" in prd


# ── 6. KB artifacts are markdown where they exist ────────────────

class TestKBMarkdown:
    """Knowledge base files should be markdown."""

    def test_kb_files_are_markdown(self):
        tasks_dir = _REPO_ROOT / "tasks"
        for task_dir in tasks_dir.iterdir():
            if not (task_dir / "task.yaml").exists():
                continue
            # Check kb/ directory if it exists
            kb_dir = task_dir / "kb"
            if kb_dir.exists() and kb_dir.is_dir():
                for f in kb_dir.iterdir():
                    assert f.suffix.lower() == ".md", \
                        f"{task_dir.name}/kb/{f.name} should be markdown (.md)"
