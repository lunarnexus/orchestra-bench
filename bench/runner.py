"""Run coordination helpers for preparing, running, and grading a task."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from bench.artifacts import EvaluatorArtifactPaths
from bench.auto import CompletionPolicy, wait_until_safe_to_grade
from bench.harnesses.base import Harness, HarnessArtifactPaths, HarnessRequest
from bench.evaluator import EvaluationError, EvaluatorRunner, grade_run as _grade_run
from bench.paths import RepoPaths, RunPaths
from bench.provenance import build_run_metadata
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.runtime import load_runtime_config_summary
from bench.tasks import TaskDefinition
from bench.workspace import prepare_workspace


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


def _make_request(
    prepared: PreparedRun,
    *,
    model: str | None = None,
    agent: str | None = None,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> HarnessRequest:
    provenance = prepared.provenance
    request_env = dict(provenance.get("env") or {})
    if env is not None:
        request_env.update({str(key): str(value) for key, value in env.items()})
    request_model = model if model is not None else str(provenance.get("model") or "")
    request_agent = agent if agent is not None else str(provenance.get("agent") or "")
    request_profile = profile if profile is not None else str(provenance.get("profile") or "")
    return HarnessRequest(
        run_paths=prepared.run_paths,
        prompt=prepared.task.prompt_path.read_text(encoding="utf-8"),
        model=request_model,
        agent=request_agent,
        profile=request_profile,
        timeout_seconds=timeout_seconds if timeout_seconds is not None else prepared.task.timeout_minutes * 60.0,
        env=request_env,
        metadata={
            "bench_run": prepared.bench_run,
            "provenance": dict(prepared.provenance),
            "run_meta": asdict(prepared.run_meta),
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
        outcome="not_run",
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
    )
    request = _make_request(
        prepared,
        model=model,
        agent=agent,
        profile=profile,
        env=env,
        timeout_seconds=timeout_seconds,
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
    result = _partial_result(prepared, request, harness_result)
    if harness_result.status == "ok":
        write_json_atomic(prepared.run_paths.result_json, result)
        return result

    if prepared.prior_result is None:
        write_json_atomic(prepared.run_paths.result_json, result)
    return result


def _failure_result_from_current(task: TaskDefinition, run_paths: RunPaths, exc: EvaluationError) -> TaskResult:
    current = load_result(run_paths.result_json) if run_paths.result_json.is_file() else TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch)
    )
    current.evaluation = EvaluationResult(status="failed", error=str(exc), details=exc.details)
    current.outcome = "not_run"
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
        if prior_result is None:
            write_json_atomic(run_paths.result_json, failure)
        else:
            write_json_atomic(run_paths.result_json, prior_result)
        return failure

    if not result.run_meta.finished_at:
        result.run_meta.finished_at = _now_iso()
    write_json_atomic(run_paths.result_json, result)
    return result


class _SettlingHarnessAdapter:
    def __init__(self, harness: Harness) -> None:
        self._harness = harness

    def wait_for_settled(self, timeout: float | None = None) -> bool:
        waiter = getattr(self._harness, "wait_for_settled", None)
        if callable(waiter):
            return bool(waiter(timeout=timeout))
        return True

    @property
    def last_settle_status(self) -> str:
        return str(getattr(self._harness, "last_settle_status", "not_started") or "not_started")


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
    )
    if result.harness.status != "ok":
        return result
    effective_auto = auto if auto is not None else bool(prepared.provenance.get("auto"))
    effective_orchestra = orchestra if orchestra is not None else bool(prepared.provenance.get("orchestra"))
    if effective_auto:
        gate_result = wait_until_safe_to_grade(
            _SettlingHarnessAdapter(harness),
            session_id=str(prepared.provenance.get("session_id") or ""),
            status_provider=_auto_gate_status_provider(harness),
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
