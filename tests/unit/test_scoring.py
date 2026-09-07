from __future__ import annotations

from pathlib import Path

import pytest

from bench.reporting.queries import ReportEntry
from bench.reporting.scoring import score_report_entry, score_task_result
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult


CANONICAL_CHECKS_4_OF_5 = {
    "ingest_event_accepts_new_events": True,
    "ingest_event_rejects_duplicates": True,
    "invoice_customer_summarizes_usage": True,
    "build_webhook_signs_canonical_payload": True,
    "build_webhook_hides_secret": False,
}

FULL_ORCHESTRA_METRICS: dict[str, object] = {
    "dispatch": {"attempts": 1, "accepted": 1, "rejected": 0},
    "roles": {"requested": ["builder"], "returned": ["builder"]},
    "child_sessions": {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0},
    "parent": {"waited": True, "integrated": True, "finalized_before_children": False},
    "duplicate_same_slice_dispatches": 0,
}


def _result(
    run_id: str = "20250101T090000",
    *,
    checks: dict[str, object] | None = None,
    verdict: str | None = None,
    outcome: str | None = None,
    details: dict[str, object] | None = None,
    top_checks: dict[str, object] | None = None,
    harness_status: str = "ok",
    evaluation_status: str = "ok",
    orchestra: bool | None = None,
    orchestra_metrics: dict[str, object] | None = None,
) -> TaskResult:
    checks = CANONICAL_CHECKS_4_OF_5 if checks is None else checks
    if details is None:
        details = {
            "functionality": {
                "checks": dict(checks),
                "evidence": {"sample": "evidence"},
            }
        }
    if orchestra is not None:
        details = dict(details)
        details["provenance"] = {"orchestra": orchestra}
    if orchestra_metrics is not None:
        details = dict(details)
        details["orchestra_metrics"] = dict(orchestra_metrics)
    if verdict is None:
        verdict = "pass" if all(value is True for value in checks.values()) else "fail"
    if outcome is None:
        outcome = verdict if evaluation_status == "ok" else "error"
    return TaskResult(
        run_meta=RunMeta(run_id=run_id, task_id="task-a", batch="smoke", started_at="2025-01-01T00:00:00Z", finished_at="2025-01-01T00:10:00Z"),
        harness=HarnessResult(status=harness_status, exit_code=0 if harness_status == "ok" else 1),
        evaluation=EvaluationResult(
            status=evaluation_status,
            score=verdict,
            checks=top_checks if top_checks is not None else dict(checks),
            details=details,
        ),
        outcome=outcome,
    )


def _entry(tmp_path: Path, result: TaskResult) -> ReportEntry:
    return ReportEntry(
        path=tmp_path / f"{result.run_id}-{result.task_id}" / "result.json",
        result=result,
        batch=result.batch,
        model="model-a",
        orchestra=None,
        score_numeric=result.score_numeric,
        score_display=result.score_display,
        category_scores=result.category_scores,
        harness_status=result.harness.status,
        harness_exit_code=result.harness.exit_code,
        evaluation_status=result.evaluation.status,
        evaluation_score=result.evaluation.score,
        artifact_paths={},
        tokens={},
        timing={},
        provenance={},
        orchestra_metrics={},
    )


def test_canonical_functionality_checks_score_fail_80_of_100() -> None:
    scored = score_task_result(_result())

    assert scored.available is True
    assert scored.score_numeric == pytest.approx(80.0)
    assert scored.score_display == "80/100"
    assert scored.category_scores["functionality"]["inputs"]["passed"] == 4
    assert scored.category_scores["functionality"]["inputs"]["total"] == 5


def test_all_functionality_checks_true_scores_pass_100_of_100() -> None:
    checks = {key: True for key in CANONICAL_CHECKS_4_OF_5}

    scored = score_task_result(_result(checks=checks))

    assert scored.available is True
    assert scored.score_numeric == pytest.approx(100.0)
    assert scored.score_display == "100/100"


def test_arbitrary_check_ratio_scores_directly() -> None:
    checks = {"a": True, "b": True, "c": True, "d": False, "e": False, "f": False}

    scored = score_task_result(_result(checks=checks))

    assert scored.available is True
    assert scored.score_numeric == pytest.approx(50.0)
    assert scored.score_display == "50/100"


def test_canonical_functionality_score_is_not_boosted_by_diagnostics() -> None:
    result = _result(orchestra=True, orchestra_metrics=FULL_ORCHESTRA_METRICS)
    result.tokens = {"total": 500}
    result.context = {"parent": {"final_context_tokens": 400, "max_context_tokens": 450, "compactions": 0}}
    result.reliability = {"artifacts_present": True}

    history = _result("20250101T090001", orchestra=True)
    history.tokens = {"total": 9000}
    history.context = {"parent": {"final_context_tokens": 8000, "max_context_tokens": 8500, "compactions": 2}}

    scored = score_task_result(result, history=[history])

    assert scored.available is True
    assert scored.score_numeric == pytest.approx(80.0)
    assert scored.score_display == "80/100"


def test_same_check_map_scores_identically_across_orchestra_modes() -> None:
    scores = {
        "orchestra_on": score_task_result(_result("20250101T090010", orchestra=True, orchestra_metrics=FULL_ORCHESTRA_METRICS)),
        "orchestra_off": score_task_result(_result("20250101T090011", orchestra=False)),
        "no_orch_on_diagnostic": score_task_result(
            _result(
                "20250101T090012",
                orchestra=False,
                orchestra_metrics={
                    "dispatch": {"attempts": 1, "accepted": 1, "rejected": 0},
                    "roles": {"requested": ["builder"], "returned": ["builder"]},
                    "child_sessions": {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0},
                },
            )
        ),
    }

    for name, scored in scores.items():
        assert scored.available is True, name
        assert scored.score_numeric == pytest.approx(80.0), name
        assert scored.score_display == "80/100", name
    assert len({scored.score_numeric for scored in scores.values()}) == 1


@pytest.mark.parametrize(
    ("details", "reason"),
    [
        ({}, "missing functionality checks"),
        ({"functionality": {"checks": {}}}, "missing functionality checks"),
        ({"functionality": {"checks": {"a": True, "b": 1}}}, "non-boolean functionality check"),
        ({"functionality": {"checks": {"a": True, "b": "yes"}}}, "non-boolean functionality check"),
    ],
)
def test_malformed_canonical_checks_are_unscored(details: dict[str, object], reason: str) -> None:
    scored = score_task_result(
        _result(
            details=details,
            top_checks={"legacy_outer_check": True},
            verdict="pass",
            outcome="pass",
        )
    )

    assert scored.available is False
    assert scored.score_numeric is None
    assert scored.score_display == ""
    assert scored.reason == reason
    assert scored.category_scores == {}


@pytest.mark.parametrize(
    ("checks", "verdict", "outcome"),
    [
        ({"a": True, "b": False}, "pass", "pass"),
        ({"a": True, "b": True}, "fail", "fail"),
    ],
)
def test_contradictory_evaluator_verdict_is_unscored(checks: dict[str, object], verdict: str, outcome: str) -> None:
    scored = score_task_result(_result(checks=checks, verdict=verdict, outcome=outcome))

    assert scored.available is False
    assert scored.score_numeric is None
    assert scored.score_display == ""
    assert scored.reason == "contradictory evaluator verdict"


@pytest.mark.parametrize(
    ("harness_status", "evaluation_status", "outcome"),
    [
        ("lifecycle_failed", "ok", "error"),
        ("ok", "failed", "error"),
        ("ok", "not_run", "not_run"),
    ],
)
def test_infra_failures_are_unscored(harness_status: str, evaluation_status: str, outcome: str) -> None:
    scored = score_task_result(
        _result(harness_status=harness_status, evaluation_status=evaluation_status, outcome=outcome)
    )

    assert scored.available is False
    assert scored.score_numeric is None
    assert scored.score_display == ""
    assert scored.reason == "score unavailable"


def test_category_scores_store_only_functionality_view() -> None:
    scored = score_task_result(_result())

    assert set(scored.category_scores) == {"functionality"}
    functionality = scored.category_scores["functionality"]
    assert functionality["available"] is True
    assert functionality["factor"] == pytest.approx(0.8)
    assert functionality["score_numeric"] == pytest.approx(80.0)
    assert functionality["score_display"] == "80/100"
    assert functionality["inputs"]["checks"] == CANONICAL_CHECKS_4_OF_5
    assert functionality["inputs"]["source"] == "details.functionality.checks"


def test_score_report_entry_uses_same_correctness_contract(tmp_path: Path) -> None:
    result = _result()

    scored = score_report_entry(_entry(tmp_path, result))

    assert scored.available is True
    assert scored.score_numeric == pytest.approx(80.0)
    assert scored.score_display == "80/100"
