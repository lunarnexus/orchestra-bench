"""Tests for reviewer evaluator rubric conversion.

Verify that the three reviewer role-focused evaluators output valid JSON with
score, score_numeric, rubric breakdown, and flat checks after conversion to
the weighted rubric model using evaluate_rubric().
"""

from __future__ import annotations

import json
import subprocess as sp
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASKS_DIR = _REPO_ROOT / "tasks"

REVIEWER_EVALUATORS = [
    "reviewer-review-api-diff",
    "reviewer-review-error-handling",
    "reviewer-review-inventory",
]


def _run_evaluator_script(task_id: str, answer_text: str) -> dict:
    """Run evaluator by extracting the Python code and executing it."""
    task_dir = _TASKS_DIR / task_id
    run_sh = (task_dir / "evaluate" / "run.sh").read_text()

    lines = run_sh.splitlines()
    py_lines: list[str] = []
    in_heredoc = False
    for line in lines:
        if "python3" in line and "<<'" in line:
            marker = line.strip().split("<<'")[-1].rstrip("'")
            in_heredoc = True
            continue
        if in_heredoc:
            if line.strip() == marker:
                break
            py_lines.append(line)

    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix=f"eval-{task_id}-"))
    try:
        (tmpdir / "answer.md").write_text(answer_text)
        code = "\n".join(py_lines)

        result = sp.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(tmpdir),
        )

        full_out = result.stdout.strip()
        start_idx = full_out.index("{") if "{" in full_out else -1
        if start_idx >= 0:
            return json.loads(full_out[start_idx:])

        raise AssertionError(
            f"evaluator produced no JSON output\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        import shutil
        shutil.rmtree(str(tmpdir), ignore_errors=True)


# ── Full answers that satisfy all checks for each task ─────────

def _make_reviewer_answer(task_id: str) -> str:
    """Return a full reviewer deliverable answer that satisfies all checks."""
    base = (
        "Mode: review\n\n"
        "**Reviewer findings:**\n\n"
    )
    if task_id == "reviewer-review-api-diff":
        return (
            base
            + "- Finding 1 (high severity): `render_v2` mutates caller-owned order object.\n"
            + "  Fix: deep copy before mutation. Internal field leak detected — render_v2 leaks internal_note.\n"
        )
    elif task_id == "reviewer-review-error-handling":
        return (
            base
            + "- Finding 1 (high severity): Error swallowing in transport layer hides json parse failures.\n"
            + "  Fix: propagate errors with not found status for missing entries.\n"
        )
    elif task_id == "reviewer-review-inventory":
        return (
            base
            + "- Finding 1 (medium severity): No check for negative quantity in stock reservation logic.\n"
            + "  Fix: validate quantity before reservation update to prevent oversell.\n"
        )
    return base


ANSWER_MAP = {t: _make_reviewer_answer(t) for t in REVIEWER_EVALUATORS}


# ── 1. Output JSON shape has required fields ─────────

class TestEvaluatorOutputShape:
    """Each converted evaluator outputs score, score_numeric, rubric, and checks."""

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_has_score(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert "score" in result, f"{task_id} evaluator missing 'score' field"
        assert result["score"] in ("pass", "fail")

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_has_score_numeric(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert "score_numeric" in result, f"{task_id} evaluator missing 'score_numeric' field"
        assert isinstance(result["score_numeric"], (int, float))

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_has_rubric_dict(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert "rubric" in result, f"{task_id} evaluator missing 'rubric' field"
        assert isinstance(result["rubric"], dict)

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_has_flat_checks(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert "checks" in result, f"{task_id} evaluator missing 'checks' field"
        assert isinstance(result["checks"], dict)


# ── 2. Full pass yields correct score ─────────

class TestFullPassScore:
    """A complete answer should yield score=pass and meaningful score_numeric."""

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_full_pass_is_pass(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert result["score"] == "pass"

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_full_pass_score_above_threshold(self, task_id):
        """Full pass should score >= 0.70 (default threshold)."""
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert result["score_numeric"] >= 0.70, \
            f"{task_id} full answer scored {result['score_numeric']} < 0.70"

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_score_numeric_not_zero(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        assert result["score_numeric"] > 0


# ── 3. Empty answer yields fail ─────────

class TestEmptyAnswer:
    """An empty or missing answer.md should yield score=fail."""

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_empty_answer_fails(self, task_id):
        result = _run_evaluator_script(task_id, "")
        assert result["score"] == "fail"


# ── 4. Rubric categories have expected structure ─────────

class TestRubricCategories:
    """Each rubric category has score, max, and checks sub-fields."""

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_rubric_categories_have_score_max_checks(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        for cat_name, cat_data in result["rubric"].items():
            assert "score" in cat_data, f"{cat_name} missing 'score'"
            assert "max" in cat_data, f"{cat_name} missing 'max'"
            assert "checks" in cat_data, f"{cat_name} missing 'checks'"


# ── 5. Original check names preserved in flat output ─────────

class TestOriginalChecksPreserved:
    """All original check identifiers appear in the flat checks dict."""

    EXPECTED_CHECKS = {
        "reviewer-review-api-diff": [
            "answer_exists", "mentions_reviewer", "has_findings",
            "has_severity", "has_fix", "mutat", "internal_field_leak",
            "leak", "render_v2",
        ],
        "reviewer-review-error-handling": [
            "answer_exists", "mentions_reviewer", "has_findings",
            "has_severity", "has_fix", "swallow", "transport",
            "json", "not_found",
        ],
        "reviewer-review-inventory": [
            "answer_exists", "mentions_reviewer", "has_findings",
            "has_severity", "has_fix", "negative", "reservation",
            "quantity", "stock",
        ],
    }

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_all_original_checks_present(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id])
        flat = set(result["checks"].keys())
        expected = set(self.EXPECTED_CHECKS[task_id])
        missing = expected - flat
        assert not missing, f"{task_id} evaluator missing checks: {missing}"


# ── 6. Rubric uses evaluate_rubric pattern (code inspection) ───

class TestEvaluatorUsesRubricHelper:
    """Each evaluator script references the rubric evaluation function."""

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_evaluator_references_evaluate_rubric(self, task_id):
        run_sh = (_TASKS_DIR / task_id / "evaluate" / "run.sh").read_text()
        assert "evaluate_rubric" in run_sh, \
            f"{task_id} evaluator should call evaluate_rubric()"


# ── 7. Threshold default is 0.70 ─────────

class TestThreshold:
    """Evaluators use the default threshold of 0.70 (not overriding)."""

    @pytest.mark.parametrize("task_id", REVIEWER_EVALUATORS)
    def test_no_custom_threshold_override(self, task_id):
        run_sh = (_TASKS_DIR / task_id / "evaluate" / "run.sh").read_text()
        import re
        matches = re.findall(r'threshold\s*=\s*([0-9.]+)', run_sh)
        for m in matches:
            assert float(m) == pytest.approx(0.70), \
                f"{task_id} has non-standard threshold {m}"
