"""Tests for shared capability workflow evidence scoring helper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from capability_helpers import evaluate_workflow_evidence  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestCapabilityWorkflowEvidenceShape:
    def test_returns_json_serializable_rubric_shape(self, tmp_path):
        _write(tmp_path / "PLAN.md", "Plan steps for api change with tests and files.")

        result = evaluate_workflow_evidence(
            tmp_path,
            final_answer="Implemented src/app.py and tests/test_app.py with verification evidence.",
            changed_files=["src/app.py", "tests/test_app.py"],
        )

        assert result["score"] >= 0
        assert result["max"] > 0
        assert isinstance(result["checks"], dict)
        assert isinstance(result["details"], dict)
        json.dumps(result)


class TestCapabilityWorkflowEvidenceRelevance:
    def test_presence_alone_scores_below_relevant_content(self, tmp_path):
        _write(tmp_path / "PLAN.md", "placeholder")

        weak = evaluate_workflow_evidence(tmp_path)

        _write(
            tmp_path / "PLAN.md",
            "Plan implementation steps, tests, and files for the ticket workflow.",
        )
        strong = evaluate_workflow_evidence(tmp_path)

        assert weak["checks"]["plan_present"] is True
        assert weak["checks"]["plan_relevant"] is False
        assert strong["checks"]["plan_relevant"] is True
        assert strong["details"]["plan"]["score"] > weak["details"]["plan"]["score"]

    def test_keyword_stub_does_not_count_as_relevant_content(self, tmp_path):
        _write(tmp_path / "PLAN.md", "plan steps tests files")

        result = evaluate_workflow_evidence(tmp_path)

        assert result["checks"]["plan_present"] is True
        assert result["checks"]["plan_relevant"] is False

    def test_token_salad_fails_when_substantive_lines_required(self, tmp_path):
        _write(
            tmp_path / "PLAN.md",
            "plan steps tests files app.py sqlite triage audit pagination",
        )

        result = evaluate_workflow_evidence(
            tmp_path,
            artifact_specs={
                "plan": {
                    "min_words": 8,
                    "min_substantive_lines": 2,
                    "evidence_terms": ["app.py", "sqlite", "triage"],
                    "min_evidence_terms": 2,
                }
            },
        )

        assert result["checks"]["plan_present"] is True
        assert result["checks"]["plan_relevant"] is False
        assert result["details"]["plan"]["substantive_line_count"] == 0

    def test_missing_artifacts_reduce_score_without_hard_fail(self, tmp_path):
        _write(
            tmp_path / "PLAN.md",
            "Plan the work, tests, and files for the API change.",
        )

        result = evaluate_workflow_evidence(
            tmp_path,
            final_answer="Implemented src/app.py with tests and verification notes.",
            changed_files=["src/app.py"],
        )

        assert result["score"] > 0
        assert result["score"] < result["max"]
        assert result["checks"]["review_present"] is False
        assert result["checks"]["appsec_present"] is False


class TestCapabilityWorkflowEvidenceConfiguration:
    def test_supports_task_local_artifact_names_and_keywords(self, tmp_path):
        _write(
            tmp_path / "SECURITY_NOTES.md",
            "Security review of upload path, auth boundary, and input validation.",
        )

        result = evaluate_workflow_evidence(
            tmp_path,
            artifact_specs={
                "appsec": {
                    "names": ["SECURITY_NOTES.md"],
                    "keywords": ["security", "auth", "validation"],
                    "weight": 2.0,
                }
            },
        )

        assert result["checks"]["appsec_present"] is True
        assert result["checks"]["appsec_relevant"] is True
        assert result["details"]["appsec"]["max"] == pytest.approx(2.0)


class TestCapabilityWorkflowEvidenceConsistency:
    def test_scores_changed_file_consistency_when_artifact_mentions_files(self, tmp_path):
        _write(
            tmp_path / "VERIFY.md",
            "Verified src/app.py and tests/test_app.py with focused test results.",
        )

        result = evaluate_workflow_evidence(
            tmp_path,
            changed_files=["src/app.py", "tests/test_app.py"],
        )

        assert result["checks"]["verify_mentions_changed_files"] is True
        assert result["details"]["verify"]["mentioned_changed_files"] == [
            "src/app.py",
            "tests/test_app.py",
        ]

    def test_partial_changed_file_mentions_get_partial_consistency_credit(self, tmp_path):
        _write(
            tmp_path / "VERIFY.md",
            "Verified src/app.py with focused test results.",
        )

        result = evaluate_workflow_evidence(
            tmp_path,
            changed_files=["src/app.py", "tests/test_app.py"],
        )

        verify = result["details"]["verify"]
        assert result["checks"]["verify_mentions_changed_files"] is True
        assert verify["mentioned_changed_files"] == ["src/app.py"]
        assert verify["missing_changed_files"] == ["tests/test_app.py"]
        assert verify["changed_file_coverage"] == pytest.approx(0.5)
        assert verify["score"] == pytest.approx(0.35 + 0.45 + 0.10)

    def test_final_answer_can_supply_consistency_evidence(self, tmp_path):
        result = evaluate_workflow_evidence(
            tmp_path,
            final_answer=(
                "Build Result: changed src/app.py and tests/test_app.py; "
                "verified behavior with focused tests and review notes."
            ),
            changed_files=["src/app.py", "tests/test_app.py"],
        )

        assert result["checks"]["final_summary_present"] is True
        assert result["checks"]["final_summary_mentions_changed_files"] is True
        assert result["details"]["final_summary"]["mentioned_changed_files"] == [
            "src/app.py",
            "tests/test_app.py",
        ]
        assert result["details"]["final_summary"]["changed_file_coverage"] == pytest.approx(1.0)

    def test_missing_final_answer_does_not_add_impossible_score_bucket(self, tmp_path):
        without_final = evaluate_workflow_evidence(tmp_path)
        with_final = evaluate_workflow_evidence(tmp_path, final_answer="changed src/app.py with tests")

        assert without_final["details"]["final_summary"]["max"] == 0.0
        assert "final_summary_present" not in without_final["checks"]
        assert "final_summary_relevant" not in without_final["checks"]
        assert "final_summary_mentions_changed_files" not in without_final["checks"]
        assert without_final["max"] == pytest.approx(with_final["max"] - 1.0)
