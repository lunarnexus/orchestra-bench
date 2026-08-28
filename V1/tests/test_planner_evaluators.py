"""Tests for Slice 4 — planner evaluator rubric conversion.

Verify that the three planner role-focused evaluators output valid JSON with
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

PLANNER_EVALUATORS = [
    "planner-plan-api-boundary",
    "planner-plan-migration",
    "planner-plan-risk-review",
]


def _run_evaluator(task_id: str, answer_text: str) -> dict:
    """Run an evaluator script against a synthetic answer.md text."""
    task_dir = _TASKS_DIR / task_id
    run_sh = task_dir / "evaluate" / "run.sh"
    assert run_sh.exists(), f"{task_id} has no evaluate/run.sh"

    # Create temp dir with answer.md
    import tempfile
    import os
    tmpdir = tempfile.mkdtemp(prefix=f"eval-{task_id}-")
    try:
        answer_path = Path(tmpdir) / "answer.md"
        answer_path.write_text(answer_text)

        result = sp.run(
            [sys.executable, "-c", run_sh.read_text().replace("set -euo pipefail\n", "")],
            capture_output=True, text=True, cwd=tmpdir
        )
        # Extract JSON from stdout
        for line in result.stdout.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("{"):
                return json.loads(stripped)
        raise AssertionError(f"evaluator produced no JSON output\nstdout: {result.stdout}\nstderr: {result.stderr}")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_evaluator_script(task_id: str, answer_text: str) -> dict:
    """Run evaluator by extracting the Python code and executing it."""
    task_dir = _TASKS_DIR / task_id
    run_sh = (task_dir / "evaluate" / "run.sh").read_text()

    # Extract python heredoc — find content between first line after 'python3 - <<'EOPY'' and closing EOPY
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
        code = f"\n".join(py_lines)

        result = sp.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(tmpdir)
        )

        # Parse JSON from output — first line starts with {, rest is indented
        full_out = result.stdout.strip()
        # Find the start of JSON block and parse it all
        start_idx = full_out.index("{") if "{" in full_out else -1
        if start_idx >= 0:
            return json.loads(full_out[start_idx:])

        raise AssertionError(
            f"evaluator produced no JSON output\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        import shutil
        shutil.rmtree(str(tmpdir), ignore_errors=True)


# ── Full answer that should pass all checks for each task ─────────

def _make_api_boundary_answer() -> str:
    return """Mode: plan

Verdict: Add /v2/orders/{id} endpoint with tracking_url support.

Slices:
1. Define v2 route on orderservice, map to existing order store.
2. Include tracking_url in response payload (fix 404 issue from v1).

Evidence: current API docs show v1 returns no tracking_url → 404 for caller.

Verification gates: each slice has unit + integration tests before merge.

Risks: breaking change if v1 contract assumed, track with feature flag.

Next action: builder implements slice 1.
"""


def _make_migration_answer() -> str:
    return """Mode: plan

Verdict: Migrate flat user records to nested contact structure via dual-write + backfill.

Slices:
1. Write migration schema for nested contact fields.
2. Set up dual-write path on legacy create/update endpoints.
3. Backfill existing users in chunk of 1000, reversible rollback plan.

Evidence: kb/schema.md shows current flat shape; kb/ops.md has backfill budget.

Verification gates: data integrity checks after each chunk, rollback smoke test.

Risks: stale reads during dual-write window, legacy field drift.

Next action: builder implements schema + dual-write slice.
"""


def _make_risk_review_answer() -> str:
    return """Mode: plan

Verdict: Plan risk controls for automatic refunds in checkout.

Slices:
1. Add feature flag for auto-refund, idempotency key per order.
2. Implement refund/capture logic with 5% initial threshold → ramp to 25%.
3. Rollback procedure + monitoring dashboard.

Evidence: kb/release.md describes target flow; kb/incidents.md lists prior refund bugs.

Verification gates: dry-run on staging, verify 5% batch matches expected.

Risks: double refunds without idempotency key, threshold drift above 25%.

Next action: builder implements slice 1 with feature flag.
"""


ANSWER_MAP = {
    "planner-plan-api-boundary": _make_api_boundary_answer,
    "planner-plan-migration": _make_migration_answer,
    "planner-plan-risk-review": _make_risk_review_answer,
}


# ── 1. Output JSON shape has required fields ─────────

class TestEvaluatorOutputShape:
    """Each converted evaluator outputs score, score_numeric, rubric, and checks."""

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_has_score(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert "score" in result, f"{task_id} evaluator missing 'score' field"
        assert result["score"] in ("pass", "fail")

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_has_score_numeric(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert "score_numeric" in result, f"{task_id} evaluator missing 'score_numeric' field"
        assert isinstance(result["score_numeric"], (int, float))

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_has_rubric_dict(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert "rubric" in result, f"{task_id} evaluator missing 'rubric' field"
        assert isinstance(result["rubric"], dict)

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_has_flat_checks(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert "checks" in result, f"{task_id} evaluator missing 'checks' field"
        assert isinstance(result["checks"], dict)


# ── 2. Full pass yields correct score ─────────

class TestFullPassScore:
    """A complete answer should yield score=pass and meaningful score_numeric."""

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_full_pass_is_pass(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert result["score"] == "pass"

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_full_pass_score_above_threshold(self, task_id):
        """Full pass should score >= 0.70 (default threshold)."""
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert result["score_numeric"] >= 0.70, \
            f"{task_id} full answer scored {result['score_numeric']} < 0.70"

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_score_numeric_not_zero(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        assert result["score_numeric"] > 0


# ── 3. Empty answer yields fail ─────────

class TestEmptyAnswer:
    """An empty or missing answer.md should yield score=fail."""

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_empty_answer_fails(self, task_id):
        result = _run_evaluator_script(task_id, "")
        assert result["score"] == "fail"


# ── 4. Rubric categories have expected structure ─────────

class TestRubricCategories:
    """Each rubric category has score, max, and checks sub-fields."""

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_rubric_categories_have_score_max_checks(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        for cat_name, cat_data in result["rubric"].items():
            assert "score" in cat_data, f"{cat_name} missing 'score'"
            assert "max" in cat_data, f"{cat_name} missing 'max'"
            assert "checks" in cat_data, f"{cat_name} missing 'checks'"


# ── 5. Original check names preserved in flat output ─────────

class TestOriginalChecksPreserved:
    """All original check identifiers appear in the flat checks dict."""

    EXPECTED_CHECKS = {
        "planner-plan-api-boundary": [
            "answer_exists", "mentions_planner", "has_steps", "has_risks",
            "has_verification", "v2", "v1", "orderservice", "tracking_url",
            "404", "verification", "risk",
        ],
        "planner-plan-migration": [
            "answer_exists", "mentions_planner", "has_steps", "has_risks",
            "has_verification", "dual_write", "backfill", "rollback",
            "legacy", "chunk", "verification", "risk",
        ],
        "planner-plan-risk-review": [
            "answer_exists", "mentions_planner", "has_steps", "has_risks",
            "has_verification", "feature_flag", "idempotency", "refund_capture",
            "rollback", "5pct", "25pct", "verification", "risk",
        ],
    }

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_all_original_checks_present(self, task_id):
        result = _run_evaluator_script(task_id, ANSWER_MAP[task_id]())
        flat = set(result["checks"].keys())
        expected = set(self.EXPECTED_CHECKS[task_id])
        missing = expected - flat
        assert not missing, f"{task_id} evaluator missing checks: {missing}"


# ── 6. Rubric uses evaluate_rubric pattern (code inspection) ───

class TestEvaluatorUsesRubricHelper:
    """Each evaluator script references the rubric evaluation function."""

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_evaluator_references_evaluate_rubric(self, task_id):
        run_sh = (_TASKS_DIR / task_id / "evaluate" / "run.sh").read_text()
        assert "evaluate_rubric" in run_sh, \
            f"{task_id} evaluator should call evaluate_rubric()"


# ── 7. Threshold default is 0.70 ─────────

class TestThreshold:
    """Evaluators use the default threshold of 0.70 (not overriding)."""

    @pytest.mark.parametrize("task_id", PLANNER_EVALUATORS)
    def test_no_custom_threshold_override(self, task_id):
        run_sh = (_TASKS_DIR / task_id / "evaluate" / "run.sh").read_text()
        # If threshold is mentioned explicitly, it should be 0.70 or not set at all
        import re
        matches = re.findall(r'threshold\s*=\s*([0-9.]+)', run_sh)
        for m in matches:
            assert float(m) == pytest.approx(0.70), \
                f"{task_id} has non-standard threshold {m}"
