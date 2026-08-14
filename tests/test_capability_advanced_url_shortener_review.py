"""Focused tests for the capability-advanced ShortLink Desk task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-advanced-url-shortener-review"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


def _copy_tree(src: Path, dst: Path) -> None:
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def _run_evaluator(workspace: Path) -> tuple[int, dict]:
    env = os.environ.copy()
    env.update(
        {
            "BENCH_TASK_ID": _TASK_ID,
            "BENCH_RUN_ID": "pytest-run",
            "BENCH_WORKDIR": str(workspace),
            "PYTHONPATH": f"{_REPO_ROOT}:{env.get('PYTHONPATH', '')}",
        }
    )
    result = sp.run(
        [_TASK_DIR / "evaluate" / "run.sh"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        parsed = json.loads(result.stdout[result.stdout.index("{") :])
    except Exception as exc:  # pragma: no cover - assertion helper
        raise AssertionError(f"evaluator did not print JSON\nstdout={result.stdout}\nstderr={result.stderr}") from exc
    return result.returncode, parsed


class TestCapabilityAdvancedUrlShortenerReviewTask:
    def test_task_metadata_marks_capability_advanced_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-advanced-url-shortener-review" in text
        assert "batch: capability-advanced" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow: planner,researcher,builder,verifier,reviewer,appsec" in text
        assert "source_benchmark: SaaSBench+SWE-bench-inspired" in text

    def test_task_docs_describe_live_e2e_shortlink_requirements(self):
        prd = (_TASK_DIR / "PRD.md").read_text()
        prompt = (_TASK_DIR / "Prompt.md").read_text()
        kb = (_TASK_DIR / "kb" / "url_safety.md").read_text()
        evaluator = (_TASK_DIR / "evaluate" / "run.sh").read_text()

        for text in [prd, prompt, kb]:
            assert "ShortLink Desk" in text
        for text in [prd, kb]:
            assert "javascript:" in text
            assert "data:" in text
        assert "X-Admin-Token" in prd
        for route in ["GET /", "POST /shorten", "GET /s/{code}", "GET /stats/{code}", "GET /links", "GET /admin/review"]:
            assert route in prd
        assert "do not leave `uvicorn`" in prompt
        assert "do not leave `uvicorn`" in prd
        assert "functional_suspicious_review_flow" in evaluator
        assert "functional_persistence_sqlite" in evaluator
        assert "uvicorn" in evaluator
        assert "urllib.request" in evaluator

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_homepage"] is False
        assert result["checks"]["functional_normal_shorten_redirect_stats"] is False
        assert result["checks"]["functional_suspicious_review_flow"] is False

    def test_reference_solution_passes(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_homepage"] is True
        assert result["checks"]["functional_normal_shorten_redirect_stats"] is True
        assert result["checks"]["functional_duplicate_and_links_filtering"] is True
        assert result["checks"]["functional_suspicious_review_flow"] is True
        assert result["checks"]["functional_admin_auth_and_decision_errors"] is True
        assert result["checks"]["functional_url_safety_and_escaping"] is True
        assert result["checks"]["functional_audit_history"] is True
        assert result["checks"]["functional_persistence_sqlite"] is True
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

    def test_missing_workflow_evidence_reduces_score_without_hard_fail(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
            (tmp_path / name).unlink()

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] == 0.7
        assert result["checks"]["plan_present"] is False
        assert result["checks"]["research_present"] is False
        assert result["checks"]["appsec_present"] is False

    def test_security_stub_fails_live_e2e_checks(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        app_py = tmp_path / "app.py"
        text = app_py.read_text()
        text = text.replace("{html.escape(row['url'])}", "{row['url']}")
        app_py.write_text(text)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_url_safety_and_escaping"] is False or result["checks"]["functional_suspicious_review_flow"] is False
