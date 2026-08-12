"""Slice 1 — Result schema for numeric/rubric data.

Tests that TaskResult carries score_numeric, rubric, orchestration_checks,
and efficiency fields with backward-compatible deserialization.
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from __init__ import TaskResult  # noqa: E402


class TestNewOptionalFieldsExist:
    """TaskResult has the new optional fields with correct defaults."""

    def test_score_numeric_defaults_to_none(self):
        r = TaskResult(task_id="t", run_id="r")
        assert r.score_numeric is None

    def test_rubric_defaults_to_empty_dict(self):
        r = TaskResult(task_id="t", run_id="r")
        assert r.rubric == {}

    def test_orchestration_checks_defaults_to_empty_dict(self):
        r = TaskResult(task_id="t", run_id="r")
        assert r.orchestration_checks == {}

    def test_efficiency_defaults_to_empty_dict(self):
        r = TaskResult(task_id="t", run_id="r")
        assert r.efficiency == {}

    def test_score_numeric_can_be_set(self):
        r = TaskResult(task_id="t", run_id="r", score_numeric=0.85)
        assert r.score_numeric == 0.85

    def test_rubric_can_be_populated(self):
        rubric = {"role_result_quality": {"score": 0.35, "max": 0.40}}
        r = TaskResult(task_id="t", run_id="r", rubric=rubric)
        assert r.rubric == rubric

    def test_orchestration_checks_can_be_populated(self):
        checks = {"target_role_dispatched": True, "timeouts": 0}
        r = TaskResult(task_id="t", run_id="r", orchestration_checks=checks)
        assert r.orchestration_checks == checks

    def test_efficiency_can_be_populated(self):
        eff = {"tokens_position": "normal"}
        r = TaskResult(task_id="t", run_id="r", efficiency=eff)
        assert r.efficiency == eff


class TestIsPassUnchanged:
    """is_pass() still uses top-level score, not rubric data."""

    def test_is_pass_with_score_pass(self):
        r = TaskResult(task_id="t", run_id="r", score="pass")
        assert r.is_pass() is True

    def test_is_fail_with_score_fail(self):
        r = TaskResult(task_id="t", run_id="r", score="fail")
        assert r.is_pass() is False

    def test_is_fail_when_empty(self):
        r = TaskResult(task_id="t", run_id="r")
        assert r.is_pass() is False

    def test_is_not_affected_by_score_numeric(self):
        """Numeric score alone does not flip is_pass()."""
        r = TaskResult(
            task_id="t", run_id="r", score="pass", score_numeric=0.95
        )
        assert r.is_pass() is True

    def test_is_fail_despite_high_score(self):
        """High numeric but score='fail' means not passing."""
        r = TaskResult(
            task_id="t", run_id="r", score="fail", score_numeric=0.95
        )
        assert r.is_pass() is False


class TestSerialization:
    """to_dict and write_json / from_json round-trip with new fields."""

    def test_to_dict_includes_new_fields(self):
        r = TaskResult(
            task_id="t", run_id="r", score="pass", score_numeric=0.85,
            rubric={"cat": {"score": 0.3}},
            orchestration_checks={"dispatched": True},
            efficiency={"pos": "normal"},
        )
        d = r.to_dict()
        assert d["score_numeric"] == 0.85
        assert d["rubric"]["cat"]["score"] == 0.3
        assert d["orchestration_checks"]["dispatched"] is True
        assert d["efficiency"]["pos"] == "normal"

    def test_to_dict_empty_defaults(self):
        r = TaskResult(task_id="t", run_id="r")
        d = r.to_dict()
        assert d["score_numeric"] is None
        assert d["rubric"] == {}
        assert d["orchestration_checks"] == {}
        assert d["efficiency"] == {}

    def test_write_json_roundtrip(self, tmp_path):
        """Write result with new fields and read back identical."""
        r = TaskResult(
            task_id="t", run_id="r", score="pass", score_numeric=0.85,
            rubric={"cat": {"score": 0.3}},
            orchestration_checks={"dispatched": True},
            efficiency={"pos": "normal"},
        )

        result_dir = tmp_path / "results" / "r-t"
        path = r.write_json(result_dir)

        loaded = TaskResult.from_json(path)
        assert loaded.task_id == "t"
        assert loaded.run_id == "r"
        assert loaded.score == "pass"
        assert loaded.score_numeric == 0.85
        assert loaded.rubric["cat"]["score"] == 0.3
        assert loaded.orchestration_checks["dispatched"] is True
        assert loaded.efficiency["pos"] == "normal"


class TestBackwardCompatibility:
    """Old result JSON without new fields deserializes cleanly."""

    def test_from_old_json_no_new_fields(self, tmp_path):
        """A result.json with only the original fields still loads."""
        old_data = {
            "task_id": "t",
            "run_id": "r1",
            "score": "pass",
            "checks": {"ok": True},
            "workdir": "/tmp/wd",
            "task_meta": {},
            "run_meta": {},
            "tokens": {},
            "split": "",
            "details": "",
        }

        result_dir = tmp_path / "results" / "r1-t"
        result_dir.mkdir(parents=True)
        path = result_dir / "result.json"
        path.write_text(_json.dumps(old_data, indent=2))

        r = TaskResult.from_json(path)
        assert r.task_id == "t"
        assert r.run_id == "r1"
        assert r.score == "pass"
        assert r.is_pass() is True
        # New fields filled by defaults
        assert r.score_numeric is None
        assert r.rubric == {}
        assert r.orchestration_checks == {}
        assert r.efficiency == {}

    def test_from_minimal_json(self, tmp_path):
        """A result.json with only task_id still loads."""
        minimal = {"task_id": "t", "run_id": "r1"}

        path = tmp_path / "result.json"
        path.write_text(_json.dumps(minimal))

        r = TaskResult.from_json(path)
        assert r.task_id == "t"
        assert r.run_id == "r1"
        assert r.score_numeric is None
        assert r.rubric == {}
        assert r.orchestration_checks == {}
        assert r.efficiency == {}

    def test_old_result_still_has_other_fields(self, tmp_path):
        """Old result with elapsed_seconds and roles_used still works."""
        old_data = {
            "task_id": "t",
            "run_id": "r1",
            "score": "pass",
            "elapsed_seconds": 42.5,
            "roles_used": ["builder", "reviewer"],
        }

        path = tmp_path / "result.json"
        path.write_text(_json.dumps(old_data))

        r = TaskResult.from_json(path)
        assert r.elapsed_seconds == 42.5
        assert r.roles_used == ["builder", "reviewer"]
        assert r.score_numeric is None


class TestFullRubricShape:
    """A realistic rubric payload serializes without loss."""

    def test_full_rubric_roundtrip(self, tmp_path):
        r = TaskResult(
            task_id="planner-plan-risk-review",
            run_id="run-1",
            score="pass",
            score_numeric=0.86,
            rubric={
                "role_result_quality": {
                    "score": 0.35,
                    "max": 0.40,
                    "checks": {"scenario_constraints": True},
                },
                "evidence_scope_quality": {
                    "score": 0.18,
                    "max": 0.20,
                    "checks": {},
                },
            },
            orchestration_checks={
                "target_role_dispatched": True,
                "worker_completed": True,
                "timeouts": 0,
                "retries": 0,
            },
            efficiency={"tokens_position": "normal"},
        )

        path = r.write_json(tmp_path / "result.json")
        loaded = TaskResult.from_json(path)

        assert loaded.score_numeric == 0.86
        assert loaded.rubric["role_result_quality"]["score"] == 0.35
        assert (
            loaded.rubric["role_result_quality"]["checks"]["scenario_constraints"]
            is True
        )
        assert loaded.orchestration_checks["target_role_dispatched"] is True
        assert loaded.efficiency["tokens_position"] == "normal"
