from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.config import resolve_harness_for_role
from bench.orchestration import OrchestrationSettleResult
from bench.provenance import build_run_metadata, snapshot_catalog_runtime
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.runner import _make_request, grade_run, prepare_run, run_and_grade, run_task
from bench.runtime import load_runtime_config_summary
from bench.tasks import load_task


def _write_task(task_dir: Path, *, task_id: str = "alpha-run") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(
        "task_id: {task_id}\n"
        "description: Sample task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 10\n"
        "evaluator: evaluate/run.sh\n".format(task_id=task_id),
        encoding="utf-8",
    )
    (task_dir / "PRD.md").write_text("Product requirements.\n", encoding="utf-8")
    (task_dir / "Prompt.md").write_text("Do the thing.\n", encoding="utf-8")
    (task_dir / "fixture").mkdir()
    (task_dir / "evaluate").mkdir()
    (task_dir / "evaluate" / "run.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")


def _write_catalog(catalog_path: Path) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  fake:\n"
        "    harness: fake-harness\n"
        "    command:\n"
        "    - fake\n"
        "    - '{prompt}'\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: fake\n"
        "    model: fake-model\n"
        "    agent: fake-agent\n"
        "    profile: default\n"
        "    env:\n"
        "      HARNESS_ENV: catalog\n"
        "    skills:\n"
        "    - builder\n",
        encoding="utf-8",
    )


def _score_from_categories(category_scores: dict[str, dict[str, object]]) -> float:
    available_points = 0.0
    scored_points = 0.0
    for payload in category_scores.values():
        if not payload.get("available"):
            continue
        weight = float(payload.get("weight") or 0.0)
        score_numeric = payload.get("score_numeric")
        if isinstance(score_numeric, (int, float)):
            scored_points += float(score_numeric)
            available_points += weight
    return round((scored_points / available_points) * 100.0, 4) if available_points else 0.0


class _SuccessHarness:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def run(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        assert request.metadata["run_meta"]["started_at"]
        assert request.metadata["provenance"]["model"] == "fake-model"
        assert request.metadata["bench_run"]["started_at"] == request.metadata["run_meta"]["started_at"]
        assert request.artifacts.summary_path.parent.name == "harness"
        assert request.env["HARNESS_ENV"] == "catalog"
        assert request.model == "fake-model"
        assert request.agent == "fake-agent"
        assert request.profile == "default"
        assert request.artifacts.transcript_path.parent.is_dir()
        request.artifacts.transcript_path.write_text("prompt seen\n", encoding="utf-8")
        return HarnessResult(status="ok", exit_code=0, details={"steps": 1})


class _UsageHarness:
    def run(self, request):  # type: ignore[no-untyped-def]
        request.artifacts.events_path.write_text(
            "\n".join(
                json.dumps(event)
                for event in (
                    {"type": "message_update", "usage": {"input": 100, "output": 10, "totalTokens": 110}},
                    {"type": "message_end"},
                    {"type": "message_update", "usage": {"input": 150, "output": 20, "totalTokens": 170}},
                    {"type": "agent_end"},
                    {"command": "get_state", "data": {"sessionId": "parent-harness-1"}},
                )
            )
            + "\n",
            encoding="utf-8",
        )
        return HarnessResult(status="ok", exit_code=0, details={"steps": 1})


class _FailingHarness:
    def run(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


class _AutoHarness:
    def run(self, request):  # type: ignore[no-untyped-def]
        return HarnessResult(status="ok", exit_code=0, details={"steps": 1})


class _PiHarness:
    def __init__(self, *, session_id: str = "sess-1", status_provider_enabled: bool = True) -> None:
        self._session_id = session_id
        self.status_calls: list[str] = []
        if not status_provider_enabled:
            self.status_provider = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def status_provider(self, session_id: str):  # type: ignore[no-untyped-def]
        self.status_calls.append(session_id)
        return {"sessionId": session_id, "active_runs": 0, "state": "settled", "raw_text": "active_runs: 0 / 1"}

    def run(self, request):  # type: ignore[no-untyped-def]
        return HarnessResult(status="ok", exit_code=0, details={"steps": 1})


def test_make_request_uses_disabled_tools_prompt_wording_only_for_auto_no_orchestra(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    (task_dir / "Prompt.md").write_text(
        "Read the fixture.\nDispatch and proceed until finished.\n",
        encoding="utf-8",
    )
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)

    modes = [
        ({"auto": True, "orchestra": False, "no_orchestra": True, "no_orch_on": True}, True),
        ({"auto": True, "orchestra": False, "no_orchestra": False, "no_orch_on": True}, False),
        ({"auto": True, "orchestra": True, "no_orchestra": False, "no_orch_on": False}, False),
    ]
    for index, (mode, disabled_tools) in enumerate(modes):
        provenance = build_run_metadata(
            task_id=task.task_id,
            run_id=f"20250101T01020{index}",
            catalog_path=catalog_path,
            **mode,
        )
        prepared = prepare_run(
            task,
            root=tmp_path,
            run_id=f"20250101T01020{index}",
            provenance=provenance,
        )

        prompt = _make_request(prepared).prompt
        if disabled_tools:
            assert "Proceed until finished." in prompt
            assert "Dispatch and proceed until finished." not in prompt
        else:
            assert "Dispatch and proceed until finished." in prompt
            assert "Proceed until finished." not in prompt
        assert "Benchmark completion protocol:" in prompt
        assert "BENCH_PARENT_DONE" in prompt


def test_run_and_grade_auto_waits_before_grading_and_preserves_gate_details(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    order: list[str] = []

    def fake_wait_until_safe_to_grade(harness, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        order.append("gate")
        assert session_id == ""
        assert status_provider is None
        assert policy is not None and policy.orchestra_enabled is False
        return OrchestrationSettleResult(
            safe_to_grade=True,
            reason="harness_terminal",
            harness_status="settled",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        order.append("grade")
        result = load_result(run_paths.result_json)
        assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True
        assert result.details["provenance"]["auto_gate"]["reason"] == "harness_terminal"
        assert result.details["provenance"]["auto_gate"]["harness_status"] == "settled"
        return result

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _AutoHarness(), prepared=prepared, auto=True, orchestra=False)

    assert order == ["gate", "grade"]
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True


def test_run_and_grade_uses_pi_session_and_status_provider_before_grading(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        auto=True,
        orchestra=True,
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    harness = _PiHarness()
    order: list[str] = []

    def fake_wait_until_safe_to_grade(harness_arg, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        order.append("gate")
        assert session_id == "sess-1"
        assert policy is not None and policy.orchestra_enabled is True
        assert status_provider is not None
        assert status_provider(session_id)["sessionId"] == "sess-1"
        return OrchestrationSettleResult(
            safe_to_grade=True,
            reason="settled",
            harness_status="settled",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        order.append("grade")
        result = load_result(run_paths.result_json)
        assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True
        assert result.details["provenance"]["auto_gate"]["reason"] == "settled"
        return result

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, harness, prepared=prepared, auto=True, orchestra=True)

    assert order == ["gate", "grade"]
    assert harness.status_calls == ["sess-1"]
    assert result.details["provenance"]["auto_gate"]["session_id"] == "sess-1"


def test_run_and_grade_infers_auto_gate_from_prepared_provenance(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        auto=True,
        orchestra=False,
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    order: list[str] = []

    def fake_wait_until_safe_to_grade(harness, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        order.append("gate")
        assert session_id == ""
        assert status_provider is None
        assert policy is not None and policy.orchestra_enabled is False
        return OrchestrationSettleResult(
            safe_to_grade=True,
            reason="harness_terminal",
            harness_status="settled",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        order.append("grade")
        result = load_result(run_paths.result_json)
        assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True
        assert result.details["provenance"]["auto_gate"]["reason"] == "harness_terminal"
        return result

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _AutoHarness(), prepared=prepared)

    assert order == ["gate", "grade"]
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is True


def test_run_and_grade_missing_pi_status_blocks_grading(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        auto=True,
        orchestra=True,
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    order: list[str] = []

    def fake_grade_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("grade")
        raise AssertionError("grade_run should not be reached")

    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _PiHarness(status_provider_enabled=False), prepared=prepared, auto=True, orchestra=True)

    assert order == []
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is False
    assert result.details["provenance"]["auto_gate"]["reason"] == "missing_status_provider"


def test_run_and_grade_skips_grading_when_gate_is_not_safe(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        auto=True,
        orchestra=False,
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)

    def fake_wait_until_safe_to_grade(harness, *, session_id="", status_provider=None, policy=None, timeout_seconds=None):
        return OrchestrationSettleResult(
            safe_to_grade=False,
            reason="timeout",
            harness_status="waiting",
            session_id=session_id,
            snapshots=(),
        )

    def fake_grade_run(task, run_paths, *, runner=None, prior_result=None):  # type: ignore[no-untyped-def]
        raise AssertionError("grade_run should not run when the gate is unsafe")

    monkeypatch.setattr("bench.runner.wait_until_safe_to_grade", fake_wait_until_safe_to_grade, raising=False)
    monkeypatch.setattr("bench.runner.grade_run", fake_grade_run)

    result = run_and_grade(task, _AutoHarness(), prepared=prepared)

    assert result.evaluation.status == "not_run"
    assert result.outcome == "not_run"
    assert result.details["provenance"]["auto_gate"]["safe_to_grade"] is False
    assert result.details["provenance"]["auto_gate"]["reason"] == "timeout"


def test_run_and_grade_success_writes_bench_run_summary_and_final_result(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    assert prepared.run_paths.bench_run_json.is_file()
    bench_run = json.loads(prepared.run_paths.bench_run_json.read_text(encoding="utf-8"))
    assert bench_run["task"]["task_id"] == task.task_id
    assert bench_run["provenance"]["model"] == "fake-model"
    assert bench_run["started_at"]

    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "pass", "checks": {"done": True}, "details": {"functionality": {"checks": {"done": True}, "evidence": {}}}}),
            stderr="",
        ),
    )

    assert result.harness == HarnessResult(status="ok", exit_code=0, details={"steps": 1})
    assert result.evaluation == EvaluationResult(status="ok", score="pass", checks={"done": True}, error="", details={"functionality": {"checks": {"done": True}, "evidence": {}}})
    assert result.outcome == "pass"
    assert result.score_numeric == 100.0
    assert result.score_display == "100/100"
    assert result.category_scores["functionality"]["score_numeric"] == 100.0
    assert result.category_scores["functionality"]["score_display"] == "100/100"
    assert result.run_meta.run_id == "20250101T010203"
    assert result.run_meta.started_at
    assert result.run_meta.finished_at
    assert load_result(prepared.run_paths.result_json) == result
    persisted = load_result(prepared.run_paths.result_json)
    assert persisted.score_numeric == 100.0
    assert persisted.score_display == "100/100"
    assert persisted.category_scores["functionality"]["score_numeric"] == 100.0
    assert result.details["result_json"] == str(prepared.run_paths.result_json)
    assert json.loads(prepared.run_paths.result_json.read_text(encoding="utf-8"))["run_meta"]["finished_at"]
    assert json.loads(prepared.run_paths.artifacts_dir.joinpath("harness", "summary.json").read_text(encoding="utf-8"))["status"] == "ok"


def _raw_result_payload(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_run_task_persists_harness_usage_metrics_in_raw_result_json(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    prepared = prepare_run(task, root=tmp_path, run_id="20250101T030405")

    run_task(task, _UsageHarness(), prepared=prepared)

    raw = _raw_result_payload(prepared.run_paths.result_json)
    assert raw["tokens"]["total"] == 280
    assert raw["tokens"]["all_sessions"]["total_tokens"] == 280
    assert raw["tokens"]["parent_session"]["total_tokens"] == 280
    assert raw["context"]["parent"] == {"final": 150, "max": 150}


class _DispatchingFailingHarness:
    def run(self, request):  # type: ignore[no-untyped-def]
        request.artifacts.events_path.write_text(
            "\n".join(
                json.dumps(event)
                for event in (
                    {"type": "tool_execution_start", "toolName": "orch_dispatch"},
                    {
                        "type": "tool_execution_end",
                        "toolName": "orch_dispatch",
                        "isError": False,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "orchestra dispatched: builder abc123\nsubagent will auto-return when finished. Do not poll while waiting.",
                                }
                            ]
                        },
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("boom")


def test_run_task_persists_orchestra_metrics_and_observed_execution_on_lifecycle_failure(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)

    prepared = prepare_run(
        task,
        root=tmp_path,
        run_id="20250101T040900",
        catalog_path=catalog_path,
        role=None,
        orchestra=True,
        no_orchestra=False,
        no_orch_on=False,
    )

    result = run_task(task, _DispatchingFailingHarness(), prepared=prepared)

    assert result.harness.status == "lifecycle_failed"
    raw = _raw_result_payload(prepared.run_paths.result_json)
    provenance = raw["details"]["provenance"]
    # Observed execution fact must be persisted even though the harness crashed and grading never ran.
    assert provenance["orchestra_tools_executed"] is True
    metrics = raw.get("details", {}).get("orchestra_metrics") or {}
    assert metrics, "expected nonempty orchestra metrics in raw result.json"
    assert metrics["dispatch"]["accepted"] == 1


def test_run_task_invokes_on_settled_between_harness_and_usage_persistence(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    prepared = prepare_run(task, root=tmp_path, run_id="20250101T030406")

    order: list[str] = []
    seen_prepared: list[object] = []

    class _OrderingHarness(_AutoHarness):
        def run(self, request):  # type: ignore[no-untyped-def]
            order.append("harness_run")
            return super().run(request)

    def on_settled(run_state):  # type: ignore[no-untyped-def]
        order.append("on_settled")
        seen_prepared.append(run_state)

    monkeypatch.setattr(
        "bench.runner._persist_usage_metrics",
        lambda result, run_paths: order.append("usage_persisted"),
    )

    run_task(task, _OrderingHarness(), prepared=prepared, on_settled=on_settled)

    assert order == ["harness_run", "on_settled", "usage_persisted"]
    assert seen_prepared[0].run_paths.run_dir == prepared.run_paths.run_dir


def test_run_and_grade_persists_correctness_only_shape_in_raw_result_json(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T040506",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T040506", provenance=provenance)
    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "score": "fail",
                    "checks": {"a": True, "b": True, "c": False},
                    "details": {"functionality": {"checks": {"a": True, "b": True, "c": False}}, "evidence": {}},
                }
            ),
            stderr="",
        ),
    )

    # Inspect the actual persisted document, not in-memory scorer output.
    raw = _raw_result_payload(prepared.run_paths.result_json)
    assert raw["score_numeric"] == round((2 / 3) * 100.0, 4)
    assert raw["score_display"] == "67/100"
    assert set(raw["category_scores"]) == {"functionality"}
    for payload in raw["category_scores"].values():
        assert "weight" not in payload
    functionality = raw["category_scores"]["functionality"]
    assert functionality["inputs"]["source"] == "details.functionality.checks"
    assert functionality["inputs"]["passed"] == 2
    assert functionality["inputs"]["total"] == 3
    # Diagnostics stay in their dedicated top-level fields, never in category scoring.
    for key in ("tokens", "context", "orchestra", "reliability"):
        assert isinstance(raw[key], dict)
    assert raw["outcome"] == result.outcome


AUTO_MODE_FACTS = [
    # full Orchestra auto run (--orchestra)
    {"run_id": "20250101T040607", "orchestra": True, "no_orchestra": False, "no_orch_on": False},
    # tools available but /orch on skipped (--no-orch-on)
    {"run_id": "20250101T040608", "orchestra": False, "no_orchestra": False, "no_orch_on": True},
    # Orchestra tools disabled and /orch on skipped (--no-orchestra --no-orch-on)
    {"run_id": "20250101T040609", "orchestra": False, "no_orchestra": True, "no_orch_on": True},
]


def test_run_and_grade_persists_distinct_mode_flags_in_raw_result_json(tmp_path_factory: pytest.TempPathFactory) -> None:
    signatures = []
    for facts in AUTO_MODE_FACTS:
        tmp_path = tmp_path_factory.mktemp(f"mode-{facts['run_id']}")
        task_dir = tmp_path / "tasks" / "alpha-run"
        _write_task(task_dir)
        task = load_task(task_dir, tmp_path / "tasks")
        catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
        _write_catalog(catalog_path)

        prepared = prepare_run(
            task,
            root=tmp_path,
            run_id=facts["run_id"],
            catalog_path=catalog_path,
            role=None,
            orchestra=facts["orchestra"],
            no_orchestra=facts["no_orchestra"],
            no_orch_on=facts["no_orch_on"],
        )
        run_and_grade(
            task,
            _SuccessHarness(),
            prepared=prepared,
            runner=lambda command, **kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"status": "ok", "score": "pass", "checks": {"a": True}, "details": {"functionality": {"checks": {"a": True}}, "evidence": {}}}),
                stderr="",
            ),
        )

        # Inspect the actual persisted document, not in-memory output.
        raw = _raw_result_payload(prepared.run_paths.result_json)
        provenance = raw["details"]["provenance"]
        assert provenance["orchestra"] == facts["orchestra"]  # existing meaning preserved
        assert provenance["no_orchestra"] is facts["no_orchestra"]
        assert provenance["no_orch_on"] is facts["no_orch_on"]
        expected_requested = bool(facts["orchestra"]) and not facts["no_orch_on"]
        assert provenance["orch_on_requested"] is expected_requested
        # Graded run with no dispatch/tool activity: flag is knowable and false.
        assert provenance["tool_orchestration_without_orch_on"] is False
        signatures.append(
            (provenance["no_orchestra"], provenance["no_orch_on"], provenance["orch_on_requested"])
        )

    # The three auto modes are distinguishable from raw JSON alone.
    assert len(set(signatures)) == 3


def _write_harness_events(run_paths, *events: dict) -> None:
    events_path = run_paths.artifacts_dir / "harness" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_run_and_grade_persists_observed_dispatch_execution_in_raw_result_json(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)

    prepared = prepare_run(
        task,
        root=tmp_path,
        run_id="20250101T040700",
        catalog_path=catalog_path,
        role=None,
        orchestra=True,
        no_orchestra=False,
        no_orch_on=False,
    )
    _write_harness_events(
        prepared.run_paths,
        {"type": "tool_execution_start", "toolName": "orch_dispatch"},
        {
            "type": "tool_execution_end",
            "toolName": "orch_dispatch",
            "isError": False,
            "result": {"text": "Orchestra dispatched: builder"},
        },
    )

    run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "pass", "checks": {"a": True}, "details": {"functionality": {"checks": {"a": True}}}, "evidence": {}}),
            stderr="",
        ),
    )

    raw = _raw_result_payload(prepared.run_paths.result_json)
    provenance = raw["details"]["provenance"]
    # Observed execution is persisted as its own fact from the dispatch event.
    assert provenance["orchestra_tools_executed"] is True
    # Configured availability stays independent and unknown (no runtime proof supplied).
    assert provenance["orchestra_tools_available"] is None


def test_run_and_grade_persists_false_observed_execution_when_no_dispatch(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)

    prepared = prepare_run(
        task,
        root=tmp_path,
        run_id="20250101T040800",
        catalog_path=catalog_path,
        role=None,
        orchestra=False,
        no_orchestra=True,
        no_orch_on=True,
    )
    _write_harness_events(
        prepared.run_paths,
        {"type": "tool_execution_end", "toolName": "bash", "isError": False},
    )

    run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "pass", "checks": {"a": True}, "details": {"functionality": {"checks": {"a": True}}}, "evidence": {}}),
            stderr="",
        ),
    )

    raw = _raw_result_payload(prepared.run_paths.result_json)
    provenance = raw["details"]["provenance"]
    # --no-orchestra with no tool execution records observed false.
    assert provenance["orchestra_tools_executed"] is False
    assert provenance["tool_orchestration_without_orch_on"] is False


def test_run_and_grade_observed_execution_null_when_no_harness_events(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)

    prepared = prepare_run(
        task,
        root=tmp_path,
        run_id="20250101T040900",
        catalog_path=catalog_path,
        role=None,
        orchestra=False,
        no_orchestra=True,
        no_orch_on=True,
    )

    run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "pass", "checks": {"a": True}, "details": {"functionality": {"checks": {"a": True}}}, "evidence": {}}),
            stderr="",
        ),
    )

    raw = _raw_result_payload(prepared.run_paths.result_json)
    # No readable event source: the fact is unproven, not false.
    assert raw["details"]["provenance"]["orchestra_tools_executed"] is None


def test_run_and_grade_flags_tool_orchestration_without_orch_on_when_activity_observed(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    metrics = {
        "dispatch": {"attempts": 1, "accepted": 1, "rejected": 0, "rejection_reasons": {}},
        "roles": {"requested": ["builder"], "returned": ["builder"]},
        "child_sessions": {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0},
        "parent": {"waited": True, "integrated": True, "finalized_before_children": False},
        "duplicate_same_slice_dispatches": 0,
        "same_slice_dispatches": 0,
        "evidence": {"pi_sessions": True, "harness_events": True},
    }
    monkeypatch.setattr("bench.runner.extract_orchestra_metrics", lambda run_dir: metrics)

    prepared = prepare_run(
        task,
        root=tmp_path,
        run_id="20250101T040610",
        catalog_path=catalog_path,
        role=None,
        orchestra=False,
        no_orchestra=False,
        no_orch_on=True,
    )
    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "fail", "checks": {"core": True, "workflow": False}, "details": {"functionality": {"checks": {"core": True, "workflow": False}}, "evidence": {}}}),
            stderr="",
        ),
    )

    raw = _raw_result_payload(prepared.run_paths.result_json)
    provenance = raw["details"]["provenance"]
    assert provenance["no_orch_on"] is True
    assert provenance["tool_orchestration_without_orch_on"] is True
    # The diagnostic stays out of correctness scoring.
    assert "orchestration" not in result.category_scores
    assert set(raw["category_scores"]) == {"functionality"}
    assert raw["score_numeric"] == 50.0
    assert load_result(prepared.run_paths.result_json) == result


def test_grade_run_regrades_legacy_weighted_categories_to_correctness_only(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T070809")
    legacy = TaskResult(run_meta=prepared.run_meta)
    legacy.harness = HarnessResult(status="ok", exit_code=0)
    legacy.evaluation = EvaluationResult(
        status="ok",
        score="pass",
        details={"functionality": {"checks": {"a": True, "b": False}}},
    )
    legacy.outcome = "fail"
    legacy.score_numeric = 100.0
    legacy.category_scores = {
        name: {"available": True, "factor": 1.0, "weight": weight, "score_numeric": weight, "score_display": f"{int(weight)}/{int(weight)}", "inputs": {}}
        for name, weight in (("functionality", 40.0), ("orchestration", 35.0), ("reliability", 15.0), ("efficiency", 10.0))
    }
    legacy.tokens = {"parent": {"total": 123}}
    write_json_atomic(prepared.run_paths.result_json, legacy)

    grade_run(
        task,
        prepared.run_paths,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "score": "fail",
                    "checks": {"a": True, "b": False},
                    "details": {"functionality": {"checks": {"a": True, "b": False}}, "evidence": {}},
                }
            ),
            stderr="",
        ),
    )

    raw = _raw_result_payload(prepared.run_paths.result_json)
    assert raw["score_numeric"] == 50.0
    assert set(raw["category_scores"]) == {"functionality"}
    for payload in raw["category_scores"].values():
        assert "weight" not in payload
    # Dedicated diagnostic fields survive re-grading instead of being folded into categories.
    assert raw["tokens"] == {"parent": {"total": 123}}
    for key in ("context", "orchestra", "reliability"):
        assert isinstance(raw[key], dict)


def test_run_and_grade_persists_orchestra_metrics_and_scores_full_orchestra(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        orchestra=True,
    )
    metrics = {
        "dispatch": {"attempts": 1, "accepted": 1, "rejected": 0, "rejection_reasons": {}},
        "roles": {"requested": ["builder"], "returned": ["builder"]},
        "child_sessions": {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0},
        "parent": {"waited": True, "integrated": True, "finalized_before_children": False},
        "duplicate_same_slice_dispatches": 0,
        "same_slice_dispatches": 0,
        "evidence": {"pi_sessions": True, "harness_events": True},
    }
    monkeypatch.setattr("bench.runner.extract_orchestra_metrics", lambda run_dir: metrics)

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "fail", "checks": {"core": True, "workflow": False}, "details": {"functionality": {"checks": {"core": True, "workflow": False}, "evidence": {}}}}),
            stderr="",
        ),
    )

    assert result.orchestra == metrics
    assert result.details["orchestra_metrics"] == metrics
    assert result.details["provenance"]["orchestra"] is True
    assert "orchestration" not in result.category_scores
    assert result.score_numeric == 50.0
    assert result.score_display == "50/100"
    assert load_result(prepared.run_paths.result_json) == result


def test_run_and_grade_persists_tool_activity_without_orch_on_without_orchestration_points(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
        orchestra=False,
    )
    metrics = {
        "dispatch": {"attempts": 1, "accepted": 1, "rejected": 0, "rejection_reasons": {}},
        "roles": {"requested": ["builder"], "returned": ["builder"]},
        "child_sessions": {"completed": 1, "failed": 0, "timed_out": 0, "reconciled": 0, "active": 0},
        "parent": {"waited": True, "integrated": True, "finalized_before_children": False},
        "duplicate_same_slice_dispatches": 0,
        "same_slice_dispatches": 0,
        "evidence": {"pi_sessions": True, "harness_events": True},
    }
    monkeypatch.setattr("bench.runner.extract_orchestra_metrics", lambda run_dir: metrics)

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ok", "score": "fail", "checks": {"core": True, "workflow": False}, "details": {"functionality": {"checks": {"core": True, "workflow": False}, "evidence": {}}}}),
            stderr="",
        ),
    )

    assert result.orchestra == metrics
    assert result.details["orchestra_metrics"] == metrics
    assert result.details["provenance"]["orchestra"] is False
    assert "orchestration" not in result.category_scores
    assert result.orchestra["dispatch"]["attempts"] == 1
    assert result.score_numeric == 50.0
    assert result.score_display == "50/100"
    assert load_result(prepared.run_paths.result_json) == result


def test_run_task_records_harness_failure_overwrites_prior_result_with_error(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    original = TaskResult(
        run_meta=RunMeta(run_id="20250101T010203", task_id=task.task_id, batch=task.batch, started_at="2025-01-01T01:02:03Z", finished_at="2025-01-01T01:02:04Z"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass", checks={"prior": True}),
        outcome="pass",
    )
    run_paths = tmp_path / "results" / "20250101T010203-alpha-run" / "result.json"
    write_json_atomic(run_paths, original)
    original_text = run_paths.read_text(encoding="utf-8")

    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    result = run_task(task, _FailingHarness(), prepared=prepared)

    assert result.harness.status == "lifecycle_failed"
    assert result.evaluation.status == "not_run"
    assert result.outcome == "error"
    assert result.harness.error == "harness crashed: boom"
    assert prepared.run_paths.result_json.read_text(encoding="utf-8") != original_text
    assert load_result(prepared.run_paths.result_json) == result


def test_grade_run_preserves_prior_result_and_returns_evaluator_failure_when_no_json(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    original = TaskResult(
        run_meta=RunMeta(run_id="20250101T010203", task_id=task.task_id, batch=task.batch, started_at="2025-01-01T01:02:03Z", finished_at="2025-01-01T01:02:04Z"),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="pass", checks={"prior": True}),
        outcome="pass",
        score_numeric=95.0,
        score_display="95/100",
        category_scores={"functionality": {"score_numeric": 40.0, "score_display": "40/40"}},
    )
    run_paths = tmp_path / "results" / "20250101T010203-alpha-run" / "result.json"
    write_json_atomic(run_paths, original)
    original_text = run_paths.read_text(encoding="utf-8")

    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)
    result = run_and_grade(
        task,
        _SuccessHarness(),
        prepared=prepared,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="", stderr="boom\n"),
    )

    assert result.harness.status == "ok"
    assert result.evaluation.status == "failed"
    assert "no JSON" in result.evaluation.error
    assert result.outcome == "error"
    assert result.score_numeric is None
    assert result.score_display == ""
    assert result.category_scores == {}
    assert prepared.run_paths.result_json.read_text(encoding="utf-8") != original_text
    assert load_result(prepared.run_paths.result_json) == result


def test_prepare_run_writes_operator_readable_bench_run(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)
    provenance = build_run_metadata(
        task_id=task.task_id,
        run_id="20250101T010203",
        catalog_path=catalog_path,
        notes="smoke",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot=snapshot_catalog_runtime(catalog_path),
    )
    calls: list[Path] = []
    monkeypatch.setattr("bench.runner.normalize_run_ownership", lambda root: calls.append(Path(root)))

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", provenance=provenance)

    assert prepared.run_paths.bench_run_json.stat().st_mode & 0o777 == 0o644
    assert calls == [prepared.run_paths.run_dir]


def test_prepare_run_persists_synced_config_overlay_in_provenance(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "tasks" / "alpha-run"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")
    catalog_path = tmp_path / "config" / "orchestra" / "agent-catalog.yaml"
    _write_catalog(catalog_path)

    results_root = tmp_path / "results"
    artifacts_root = tmp_path / "artifacts"
    results_root.mkdir()
    artifacts_root.mkdir()
    overlay = {
        "pi_config_files": ["lmstudio.json", "settings.json"],
        "pi_config_sha256": "31d0aa4a8e4c0bf7",
        "hermes_config_files": ["config.yaml"],
        "hermes_config_sha256": "9f2cddba",
        "opencode_config_files": [],
        "opencode_config_sha256": "",
    }
    (artifacts_root / "runtime-config-sync.json").write_text(json.dumps(overlay), encoding="utf-8")
    monkeypatch.setenv("BENCH_RESULTS", str(results_root))
    monkeypatch.setenv("BENCH_ARTIFACTS", str(artifacts_root))

    prepared = prepare_run(task, root=tmp_path, run_id="20250101T010203", catalog_path=catalog_path)

    for key in overlay:
        assert prepared.provenance[key] == overlay[key]
    bench_run = json.loads(prepared.run_paths.bench_run_json.read_text(encoding="utf-8"))
    assert bench_run["provenance"]["pi_config_files"] == ["lmstudio.json", "settings.json"]
    assert bench_run["config"]["hermes_config_sha256"] == "9f2cddba"


def test_load_runtime_config_summary_falls_back_to_results_root(tmp_path: Path, monkeypatch) -> None:
    results_root = tmp_path / "results"
    artifacts_root = tmp_path / "artifacts"
    results_root.mkdir()
    artifacts_root.mkdir()
    legacy_overlay = {"pi_config_files": ["lmstudio.json"], "pi_config_sha256": "legacy"}
    (results_root / "runtime-config-sync.json").write_text(json.dumps(legacy_overlay), encoding="utf-8")
    monkeypatch.setenv("BENCH_RESULTS", str(results_root))
    monkeypatch.setenv("BENCH_ARTIFACTS", str(artifacts_root))

    assert load_runtime_config_summary() == legacy_overlay
