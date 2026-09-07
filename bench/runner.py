"""Run coordination helpers for preparing, running, and grading a task."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bench.artifacts import EvaluatorArtifactPaths
from bench.auto import CompletionPolicy, wait_until_safe_to_grade
from bench.orchestration import OrchestrationSettleResult, coerce_status_snapshot
from bench.ownership import normalize_run_ownership
from bench.harnesses.base import Harness, HarnessArtifactPaths, HarnessRequest
from bench.evaluator import EvaluationError, EvaluatorRunner, grade_run as _grade_run
from bench.paths import RepoPaths, RunPaths
from bench.provenance import build_run_metadata, orchestra_tools_executed_from_events
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.runtime import load_runtime_config_summary
from bench.tasks import TaskDefinition
from bench.workspace import prepare_workspace

extract_orchestra_metrics = None


@dataclass(frozen=True)
class PreparedRun:
    task: TaskDefinition
    run_paths: RunPaths
    run_meta: RunMeta
    provenance: dict[str, Any]
    bench_run: dict[str, Any]
    prior_result: TaskResult | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(json.dumps(_jsonable(dict(payload)), indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)  # container runs as root; host operators must read run outputs
        os.replace(tmp_path, dest)
        normalize_run_ownership(dest.parent)
        return dest
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def _task_payload(task: TaskDefinition) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "description": task.description,
        "family": task.family,
        "batch": task.batch,
        "scoring_type": task.scoring_type,
        "timeout_minutes": task.timeout_minutes,
        "evaluator": task.evaluator,
        "split": task.split,
        "task_dir": str(task.task_dir),
        "task_yaml_path": str(task.task_yaml_path),
        "prd_path": str(task.prd_path),
        "prompt_path": str(task.prompt_path),
        "fixture_path": str(task.fixture_path) if task.fixture_path is not None else None,
        "kb_dir_path": str(task.kb_dir_path) if task.kb_dir_path is not None else None,
        "kb_md_path": str(task.kb_md_path) if task.kb_md_path is not None else None,
        "evaluate_path": str(task.evaluate_path),
    }


def _bench_run_payload(
    task: TaskDefinition,
    run_paths: RunPaths,
    *,
    started_at: str,
    provenance: Mapping[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    task_payload = _task_payload(task)
    provenance_payload = dict(provenance)
    run_meta = {
        "run_id": run_paths.run_id,
        "task_id": task.task_id,
        "batch": task.batch,
        "started_at": started_at,
        "finished_at": "",
    }
    return {
        "run_meta": run_meta,
        "task": task_payload,
        "config": provenance_payload,
        "provenance": provenance_payload,
        "started_at": started_at,
        "workspace": str(workspace),
        "artifacts": {
            "root": str(run_paths.artifacts_dir),
            "harness": str(HarnessArtifactPaths.for_run_paths(run_paths).root),
            "evaluator": str(EvaluatorArtifactPaths.for_run_paths(run_paths).root),
        },
    }


def _load_prior_result(run_paths: RunPaths) -> TaskResult | None:
    try:
        if run_paths.result_json.is_file():
            return load_result(run_paths.result_json)
    except Exception:
        return None
    return None


def _build_provenance(
    task: TaskDefinition,
    run_id: str,
    *,
    provenance: Mapping[str, Any] | None = None,
    catalog_path: Path | str | None = None,
    role: str | None = None,
    orchestra: bool | None = None,
    auto: bool | None = None,
    extra_skills: Sequence[str] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
    runtime_snapshot: dict[str, object] | None = None,
    no_orchestra: bool | None = None,
    no_orch_on: bool | None = None,
    orchestra_tools_available: bool | None = None,
) -> dict[str, Any]:
    if provenance is not None:
        return dict(provenance)
    if catalog_path is None:
        return {}
    return build_run_metadata(
        task_id=task.task_id,
        run_id=run_id,
        catalog_path=catalog_path,
        role=role,
        orchestra=orchestra,
        auto=auto,
        extra_skills=list(extra_skills or []),
        notes=notes,
        catalog_label=catalog_label,
        runtime_snapshot=runtime_snapshot,
        no_orchestra=no_orchestra,
        no_orch_on=no_orch_on,
        orchestra_tools_available=orchestra_tools_available,
    )


def prepare_run(
    task: TaskDefinition,
    *,
    root: Path | str | None = None,
    run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
    catalog_path: Path | str | None = None,
    role: str | None = None,
    orchestra: bool | None = None,
    auto: bool | None = None,
    extra_skills: Sequence[str] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
    runtime_snapshot: dict[str, object] | None = None,
    no_orchestra: bool | None = None,
    no_orch_on: bool | None = None,
    orchestra_tools_available: bool | None = None,
) -> PreparedRun:
    repo = RepoPaths(Path.cwd() if root is None else root)
    effective_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_paths = repo.run(effective_run_id, task.task_id)
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    HarnessArtifactPaths.for_run_paths(run_paths).root.mkdir(parents=True, exist_ok=True)
    EvaluatorArtifactPaths.for_run_paths(run_paths).root.mkdir(parents=True, exist_ok=True)
    if runtime_snapshot is None:
        # Merge the last effective regular-config overlay recorded by
        # `sync_runtime_config` so persisted run metadata names the exact config files.
        runtime_snapshot = load_runtime_config_summary() or None
    prior_result = _load_prior_result(run_paths)
    workspace = prepare_workspace(task, run_paths)
    started_at = _now_iso()
    resolved_provenance = _build_provenance(
        task,
        effective_run_id,
        provenance=provenance,
        catalog_path=catalog_path,
        role=role,
        orchestra=orchestra,
        auto=auto,
        extra_skills=extra_skills,
        notes=notes,
        catalog_label=catalog_label,
        runtime_snapshot=runtime_snapshot,
        no_orchestra=no_orchestra,
        no_orch_on=no_orch_on,
        orchestra_tools_available=orchestra_tools_available,
    )
    bench_run = _bench_run_payload(
        task,
        run_paths,
        started_at=started_at,
        provenance=resolved_provenance,
        workspace=workspace,
    )
    _write_json_atomic(run_paths.bench_run_json, bench_run)
    return PreparedRun(
        task=task,
        run_paths=run_paths,
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch, started_at=started_at),
        provenance=resolved_provenance,
        bench_run=bench_run,
        prior_result=prior_result,
    )


def _result_details(prepared: PreparedRun, request: HarnessRequest) -> dict[str, Any]:
    return {
        "workspace": str(prepared.run_paths.run_dir / "workspace"),
        "bench_run_json": str(prepared.run_paths.bench_run_json),
        "result_json": str(prepared.run_paths.result_json),
        "provenance": dict(prepared.provenance),
        "artifacts": {
            "harness": {
                "root": str(request.artifacts.root),
                "transcript": str(request.artifacts.transcript_path),
                "events": str(request.artifacts.events_path),
                "summary": str(request.artifacts.summary_path),
                "log": str(request.artifacts.log_path),
            },
            "evaluator": {
                "root": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).root),
                "stdout": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).stdout_path),
                "stderr": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).stderr_path),
                "log": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).log_path),
                "result": str(EvaluatorArtifactPaths.for_run_paths(prepared.run_paths).result_json_path),
            },
        },
    }


def _orchestra_metrics_have_activity(metrics: Mapping[str, Any]) -> bool:
    dispatch = metrics.get("dispatch") if isinstance(metrics.get("dispatch"), dict) else {}
    roles = metrics.get("roles") if isinstance(metrics.get("roles"), dict) else {}
    child_sessions = metrics.get("child_sessions") if isinstance(metrics.get("child_sessions"), dict) else {}
    if any(
        value > 0
        for value in (
            dispatch.get("attempts"),
            dispatch.get("accepted"),
            dispatch.get("rejected"),
            child_sessions.get("completed"),
            child_sessions.get("failed"),
            child_sessions.get("timed_out"),
            child_sessions.get("reconciled"),
            child_sessions.get("active"),
            child_sessions.get("inferred_active"),
        )
        if isinstance(value, (int, float))
    ):
        return True
    for key in ("requested", "returned", "started"):
        values = roles.get(key)
        if isinstance(values, list) and any(str(value).strip() for value in values):
            return True
    return bool(metrics.get("tool_activity_without_orch_on") or metrics.get("tool_orchestration_without_orch_on"))


def _persist_orchestra_metrics(result: TaskResult, run_paths: RunPaths) -> dict[str, Any]:
    global extract_orchestra_metrics

    extractor = extract_orchestra_metrics
    if not callable(extractor):
        from bench.reporting.orchestra_metrics import extract_orchestra_metrics as loaded_extractor

        extract_orchestra_metrics = loaded_extractor
        extractor = loaded_extractor
    metrics = extractor(run_paths.run_dir)
    details = result.details if isinstance(result.details, dict) else {}
    provenance = details.get("provenance")
    if not isinstance(provenance, dict):
        # Ensure a persisted container exists so the observed-execution fact is
        # recorded even when no earlier provenance section was present.
        provenance = {}
        details["provenance"] = provenance
    activity_observed = _orchestra_metrics_have_activity(metrics)
    orch_on_requested = provenance.get("orch_on_requested")
    if isinstance(orch_on_requested, bool):
        # A false value is an observed-mode claim: only report contamination when
        # the extracted metrics also show dispatch/child activity.
        provenance["tool_orchestration_without_orch_on"] = (
            activity_observed if not orch_on_requested else False
        )
    # Observed execution is its own fact, derived from actual non-error dispatch tool
    # events (never from CLI flags or configured availability); None when unproven.
    provenance["orchestra_tools_executed"] = orchestra_tools_executed_from_events(run_paths.run_dir)
    if provenance.get("orchestra") is True or activity_observed:
        payload = dict(metrics)
        result.orchestra = payload
        details["orchestra_metrics"] = payload
    return metrics


def _make_request(
    prepared: PreparedRun,
    *,
    model: str | None = None,
    agent: str | None = None,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    stream_output: bool = False,
    request_metadata: Mapping[str, Any] | None = None,
) -> HarnessRequest:
    provenance = prepared.provenance
    request_env = dict(provenance.get("env") or {})
    if env is not None:
        request_env.update({str(key): str(value) for key, value in env.items()})
    request_model = model if model is not None else str(provenance.get("model") or "")
    request_agent = agent if agent is not None else str(provenance.get("agent") or "")
    request_profile = profile if profile is not None else str(provenance.get("profile") or "")
    prompt = prepared.task.prompt_path.read_text(encoding="utf-8")
    if provenance.get("auto") is True and provenance.get("no_orchestra") is True:
        prompt = prompt.replace("Dispatch and proceed until finished.", "Proceed until finished.")
    if provenance.get("auto") is True:
        prompt = prompt.rstrip() + (
            "\n\nBenchmark completion protocol:\n"
            "You must finish by saying BENCH_PARENT_DONE.\n"
            "Do not stop before writing BENCH_PARENT_DONE.\n"
        )
    return HarnessRequest(
        run_paths=prepared.run_paths,
        prompt=prompt,
        model=request_model,
        agent=request_agent,
        profile=request_profile,
        timeout_seconds=timeout_seconds if timeout_seconds is not None else prepared.task.timeout_minutes * 60.0,
        env=request_env,
        metadata={
            "bench_run": prepared.bench_run,
            "provenance": dict(prepared.provenance),
            "run_meta": asdict(prepared.run_meta),
            "stream_output": stream_output,
            **dict(request_metadata or {}),
        },
    )


def _partial_result(prepared: PreparedRun, request: HarnessRequest, harness: HarnessResult) -> TaskResult:
    details = _result_details(prepared, request)
    run_meta = RunMeta(
        run_id=prepared.run_paths.run_id,
        task_id=prepared.task.task_id,
        batch=prepared.task.batch,
        started_at=prepared.run_meta.started_at,
        finished_at=_now_iso(),
    )
    return TaskResult(
        run_meta=run_meta,
        harness=harness,
        evaluation=EvaluationResult(status="not_run"),
        outcome="error" if harness.status != "ok" else "not_run",
        details=details,
    )


def _write_harness_summary_if_missing(request: HarnessRequest, prepared: PreparedRun, harness: HarnessResult) -> None:
    if request.artifacts.summary_path.is_file():
        return
    _write_json_atomic(
        request.artifacts.summary_path,
        {
            "status": harness.status,
            "exit_code": harness.exit_code,
            "error": harness.error,
            "details": harness.details,
            "run_id": prepared.run_paths.run_id,
            "task_id": prepared.task.task_id,
        },
    )


def _persist_usage_metrics(result: TaskResult, run_paths: RunPaths) -> None:
    from bench.reporting.usage_metrics import extract_usage_metrics

    metrics = extract_usage_metrics(run_paths.run_dir)
    result.tokens = metrics
    result.context = {}
    for label, key in (("parent", "parent_session"), ("children", "children_sessions")):
        bucket = metrics.get(key)
        if isinstance(bucket, dict):
            result.context[label] = {
                "final": bucket.get("final_context_tokens"),
                "max": bucket.get("max_context_tokens"),
            }


def run_task(
    task: TaskDefinition,
    harness: Harness,
    *,
    prepared: PreparedRun | None = None,
    root: Path | str | None = None,
    run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
    catalog_path: Path | str | None = None,
    role: str | None = None,
    orchestra: bool | None = None,
    auto: bool | None = None,
    extra_skills: Sequence[str] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
    runtime_snapshot: dict[str, object] | None = None,
    model: str | None = None,
    agent: str | None = None,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    stream_output: bool = False,
    request_metadata: Mapping[str, Any] | None = None,
    no_orchestra: bool | None = None,
    no_orch_on: bool | None = None,
    orchestra_tools_available: bool | None = None,
    on_settled: Callable[[PreparedRun], None] | None = None,
) -> TaskResult:
    prepared = prepared or prepare_run(
        task,
        root=root,
        run_id=run_id,
        provenance=provenance,
        catalog_path=catalog_path,
        role=role,
        orchestra=orchestra,
        auto=auto,
        extra_skills=extra_skills,
        notes=notes,
        catalog_label=catalog_label,
        runtime_snapshot=runtime_snapshot,
        no_orchestra=no_orchestra,
        no_orch_on=no_orch_on,
        orchestra_tools_available=orchestra_tools_available,
    )
    request = _make_request(
        prepared,
        model=model,
        agent=agent,
        profile=profile,
        env=env,
        timeout_seconds=timeout_seconds,
        stream_output=stream_output,
        request_metadata=request_metadata,
    )
    try:
        harness_result = harness.run(request)
    except Exception as exc:
        harness_result = HarnessResult(
            status="lifecycle_failed",
            exit_code=None,
            error=f"harness crashed: {exc}",
            details={"exception_type": type(exc).__name__, "message": str(exc)},
        )

    _write_harness_summary_if_missing(request, prepared, harness_result)
    if on_settled is not None:
        on_settled(prepared)
    result = _partial_result(prepared, request, harness_result)
    _persist_usage_metrics(result, prepared.run_paths)
    # Persist observed Orchestra execution/metrics for every run (including lifecycle
    # failures and evaluator-not-run results) before result.json is written; the later
    # grade_run persistence re-derives from the same artifacts and overwrites idempotently.
    _persist_orchestra_metrics(result, prepared.run_paths)
    write_json_atomic(prepared.run_paths.result_json, result)
    return result


def _failure_result_from_current(task: TaskDefinition, run_paths: RunPaths, exc: EvaluationError) -> TaskResult:
    current = load_result(run_paths.result_json) if run_paths.result_json.is_file() else TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch)
    )
    current.evaluation = EvaluationResult(status="failed", error=str(exc), details=exc.details)
    current.outcome = "error"
    current.score_numeric = None
    current.score_display = ""
    current.category_scores = {}
    if not current.run_meta.finished_at:
        current.run_meta.finished_at = _now_iso()
    return current


def grade_run(
    task: TaskDefinition,
    run_paths: RunPaths,
    *,
    runner: EvaluatorRunner | None = None,
    prior_result: TaskResult | None = None,
) -> TaskResult:
    try:
        result = _grade_run(task, run_paths, runner=runner)
    except EvaluationError as exc:
        failure = _failure_result_from_current(task, run_paths, exc)
        write_json_atomic(run_paths.result_json, failure)
        return failure

    if not result.run_meta.finished_at:
        result.run_meta.finished_at = _now_iso()

    _persist_orchestra_metrics(result, run_paths)

    from bench.reporting.scoring import score_task_result

    scored = score_task_result(result)
    if scored.available:
        result.score_numeric = scored.score_numeric
        result.score_display = scored.score_display
        result.category_scores = scored.category_scores
    else:
        result.score_numeric = None
        result.score_display = ""
        result.category_scores = {}

    write_json_atomic(run_paths.result_json, result)
    return result


class _SettlingHarnessAdapter:
    def __init__(self, harness: Harness) -> None:
        self._harness = harness

    def wait_for_settled(self, timeout: float | None = None) -> bool:
        last_status = str(getattr(self._harness, "last_settle_status", "") or "")
        if last_status == "settled":
            return True
        waiter = getattr(self._harness, "wait_for_settled", None)
        if callable(waiter):
            return bool(waiter(timeout=timeout))
        return True

    @property
    def last_settle_status(self) -> str:
        return str(getattr(self._harness, "last_settle_status", "not_started") or "not_started")


def _auto_gate_session_id(harness: Harness, prepared: PreparedRun) -> str:
    session_id = getattr(harness, "session_id", "")
    if callable(session_id):
        session_id = session_id()
    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()
    return str(prepared.provenance.get("session_id") or "")


def _auto_gate_status_provider(harness: Harness):
    provider = getattr(harness, "status_provider", None)
    return provider if callable(provider) else None


def _attach_auto_gate(result: TaskResult, gate_result: object) -> None:
    auto_gate = asdict(gate_result) if is_dataclass(gate_result) else dict(gate_result)  # type: ignore[arg-type]
    details = result.details
    provenance = details.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        details["provenance"] = provenance
    provenance["auto_gate"] = auto_gate


def run_and_grade(
    task: TaskDefinition,
    harness: Harness,
    *,
    runner: EvaluatorRunner | None = None,
    on_settled: Callable[[PreparedRun], None] | None = None,
    prepared: PreparedRun | None = None,
    root: Path | str | None = None,
    run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
    catalog_path: Path | None = None,
    role: str | None = None,
    orchestra: bool | None = None,
    auto: bool | None = None,
    extra_skills: Sequence[str] | None = None,
    notes: str = "",
    catalog_label: str | None = None,
    runtime_snapshot: dict[str, object] | None = None,
    model: str | None = None,
    agent: str | None = None,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    stream_output: bool = False,
    request_metadata: Mapping[str, Any] | None = None,
    no_orchestra: bool | None = None,
    no_orch_on: bool | None = None,
    orchestra_tools_available: bool | None = None,
) -> TaskResult:
    prepared = prepared or prepare_run(
        task,
        root=root,
        run_id=run_id,
        provenance=provenance,
        catalog_path=catalog_path,
        role=role,
        orchestra=orchestra,
        auto=auto,
        extra_skills=extra_skills,
        notes=notes,
        catalog_label=catalog_label,
        runtime_snapshot=runtime_snapshot,
        no_orchestra=no_orchestra,
        no_orch_on=no_orch_on,
        orchestra_tools_available=orchestra_tools_available,
    )
    result = run_task(
        task,
        harness,
        prepared=prepared,
        model=model,
        agent=agent,
        profile=profile,
        env=env,
        timeout_seconds=timeout_seconds,
        stream_output=stream_output,
        request_metadata=request_metadata,
        no_orchestra=no_orchestra,
        no_orch_on=no_orch_on,
        orchestra_tools_available=orchestra_tools_available,
        on_settled=on_settled,
    )
    if result.harness.status != "ok":
        return result
    effective_auto = auto if auto is not None else bool(prepared.provenance.get("auto"))
    effective_orchestra = orchestra if orchestra is not None else bool(prepared.provenance.get("orchestra"))
    if effective_auto:
        gate_session_id = _auto_gate_session_id(harness, prepared)
        gate_status_provider = _auto_gate_status_provider(harness)
        if effective_orchestra and hasattr(harness, "session_id") and not gate_session_id:
            gate_result = OrchestrationSettleResult(
                safe_to_grade=False,
                reason="missing_session_id",
                harness_status=getattr(harness, "last_settle_status", "unknown") or "unknown",
                session_id=gate_session_id,
                snapshots=(),
            )
        else:
            if effective_orchestra and gate_status_provider is not None and str(getattr(harness, "last_settle_status", "") or "") == "settled":
                snapshot = coerce_status_snapshot(gate_session_id, gate_status_provider(gate_session_id))
                if snapshot.state == "running" or (snapshot.active_runs is not None and snapshot.active_runs > 0):
                    gate_result = OrchestrationSettleResult(
                        safe_to_grade=False,
                        reason="children_active_after_parent_exit",
                        harness_status=getattr(harness, "last_settle_status", "unknown") or "unknown",
                        session_id=gate_session_id,
                        snapshots=(snapshot,),
                    )
                else:
                    gate_result = wait_until_safe_to_grade(
                        _SettlingHarnessAdapter(harness),
                        session_id=gate_session_id,
                        status_provider=gate_status_provider,
                        policy=CompletionPolicy(orchestra_enabled=bool(effective_orchestra)),
                        timeout_seconds=timeout_seconds,
                    )
            else:
                gate_result = wait_until_safe_to_grade(
                    _SettlingHarnessAdapter(harness),
                    session_id=gate_session_id,
                    status_provider=gate_status_provider,
                    policy=CompletionPolicy(orchestra_enabled=bool(effective_orchestra)),
                    timeout_seconds=timeout_seconds,
                )
        _attach_auto_gate(result, gate_result)
        write_json_atomic(prepared.run_paths.result_json, result)
        if not gate_result.safe_to_grade:
            return result
    return grade_run(task, prepared.run_paths, runner=runner, prior_result=prepared.prior_result)


__all__ = [
    "PreparedRun",
    "prepare_run",
    "run_task",
    "grade_run",
    "run_and_grade",
]
