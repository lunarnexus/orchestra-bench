"""Debug artifact navigation for one benchmark run."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from bench.artifacts import EvaluatorArtifactPaths
from bench.harnesses.base import HarnessArtifactPaths
from bench.paths import RunPaths
from bench.reporting.queries import ReportEntry
from bench.result import TaskResult, load_result

_SNAPSHOT_KEYS = {
    "active_runs",
    "descendants_terminal",
    "session_report_available",
    "session_report_delivered",
    "state",
}


@dataclass(frozen=True)
class DebugArtifactStatus:
    label: str
    path: Path
    status: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class DebugOrchestrationSnapshot:
    path: Path
    count: int = 0
    state: str = ""
    active_runs: int | None = None
    descendants_terminal: bool | None = None
    session_report_available: bool | None = None
    session_report_delivered: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class DebugReport:
    run_id: str
    task_id: str
    run_dir: Path
    result_path: Path
    batch: str = ""
    model: str = ""
    orchestra: bool | None = None
    outcome: str = ""
    harness_status: str = ""
    evaluation_status: str = ""
    evaluation_score: str = ""
    classification: str = "missing trace"
    trace_status: str = "missing"
    result_present: bool = False
    result_error: str = ""
    harness_summary: dict[str, Any] = field(default_factory=dict)
    evaluator_manifest: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[DebugArtifactStatus, ...] = ()
    orchestration_snapshots: tuple[DebugOrchestrationSnapshot, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["run_dir"] = str(self.run_dir)
        payload["result_path"] = str(self.result_path)
        payload["artifacts"] = [artifact.to_dict() for artifact in self.artifacts]
        payload["orchestration_snapshots"] = [snapshot.to_dict() for snapshot in self.orchestration_snapshots]
        return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _artifact_status(path: Path, label: str) -> DebugArtifactStatus:
    if not path.exists():
        return DebugArtifactStatus(label=label, path=path, status="missing")
    if path.is_dir():
        files = [child for child in path.rglob("*") if child.is_file()]
        if not files:
            return DebugArtifactStatus(label=label, path=path, status="empty")
        return DebugArtifactStatus(label=label, path=path, status="present", note=f"{len(files)} file(s)")
    size = path.stat().st_size
    if size == 0:
        return DebugArtifactStatus(label=label, path=path, status="empty")
    return DebugArtifactStatus(label=label, path=path, status="present", note=f"{size} byte(s)")


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in {"true", "True", "1", 1}:
        return True
    if value in {"false", "False", "0", 0}:
        return False
    return None


def _coerce_model(result: TaskResult | None, entry: ReportEntry | None) -> str:
    if entry is not None:
        return entry.model
    if result is None:
        return ""
    details = result.details if isinstance(result.details, dict) else {}
    provenance = details.get("provenance")
    if isinstance(provenance, dict) and provenance.get("model"):
        return str(provenance.get("model") or "")
    return ""


def _coerce_orchestra(result: TaskResult | None, entry: ReportEntry | None) -> bool | None:
    if entry is not None:
        return entry.orchestra
    if result is None:
        return None
    details = result.details if isinstance(result.details, dict) else {}
    provenance = details.get("provenance")
    if isinstance(provenance, dict) and provenance.get("orchestra") is not None:
        return _coerce_bool(provenance.get("orchestra"))
    return None


def _family_present(artifacts: Iterable[DebugArtifactStatus]) -> bool:
    return any(artifact.status != "missing" for artifact in artifacts)


def _artifact_only_classification(harness_summary: dict[str, Any], evaluator_manifest: dict[str, Any]) -> str:
    harness_status = str(harness_summary.get("status") or "")
    if harness_status == "lifecycle_failed":
        return "harness lifecycle failure"

    manifest_classification = str(evaluator_manifest.get("classification") or "")
    if manifest_classification in {"timeout", "crash", "invalid_json", "no_json"}:
        return "evaluator failure"

    return ""


def _classify(
    result: TaskResult | None,
    *,
    harness_summary: dict[str, Any],
    evaluator_manifest: dict[str, Any],
    trace_status: str,
    result_read_error: str,
) -> str:
    if result is None:
        artifact_classification = _artifact_only_classification(harness_summary, evaluator_manifest)
        if artifact_classification:
            return artifact_classification
        if trace_status == "missing":
            return "missing trace"
        if result_read_error or trace_status == "partial":
            return "missing result"
        return "missing result"

    harness_status = str(harness_summary.get("status") or result.harness.status or "")
    evaluation_status = str(result.evaluation.status or "")
    manifest_classification = str(evaluator_manifest.get("classification") or "")

    if harness_status == "lifecycle_failed" or result.harness.status == "lifecycle_failed":
        return "harness lifecycle failure"
    if evaluation_status == "failed" or manifest_classification in {"timeout", "crash", "invalid_json"}:
        return "evaluator failure"
    if result.outcome == "fail" or result.evaluation.score == "fail":
        return "task failure"
    if trace_status == "missing" or result_read_error:
        return "missing trace"
    return "complete"


def _load_orchestration_snapshots(path: Path) -> tuple[DebugOrchestrationSnapshot, ...]:
    if not path.is_dir():
        return ()

    snapshots: list[DebugOrchestrationSnapshot] = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        suffix = child.suffix.lower()
        if suffix not in {".json", ".jsonl", ".txt", ".md"}:
            continue
        if suffix == ".jsonl":
            records = []
            for line in child.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        else:
            try:
                value = json.loads(child.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            records = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
        if not records:
            continue
        matched = [record for record in records if isinstance(record, dict) and any(key in record for key in _SNAPSHOT_KEYS)]
        if not matched:
            continue
        last = matched[-1]
        active_runs = last.get("active_runs")
        if active_runs is not None:
            try:
                active_runs = int(active_runs)
            except (TypeError, ValueError):
                active_runs = None
        snapshots.append(
            DebugOrchestrationSnapshot(
                path=child,
                count=len(matched),
                state=str(last.get("state") or ""),
                active_runs=active_runs,
                descendants_terminal=_coerce_bool(last.get("descendants_terminal")),
                session_report_available=_coerce_bool(last.get("session_report_available")),
                session_report_delivered=_coerce_bool(last.get("session_report_delivered")),
            )
        )
    return tuple(snapshots)


def build_debug_report(run_paths: RunPaths, *, entry: ReportEntry | None = None) -> DebugReport:
    result: TaskResult | None = None
    result_error = ""
    if entry is not None:
        result = entry.result
    elif run_paths.result_json.is_file():
        try:
            result = load_result(run_paths.result_json)
        except Exception as exc:
            result_error = f"{type(exc).__name__}: {exc}"

    if result is None and not result_error and not run_paths.result_json.is_file():
        result_error = "missing result.json"

    batch = entry.batch if entry is not None else (result.run_meta.batch if result is not None else "")
    model = _coerce_model(result, entry)
    orchestra = _coerce_orchestra(result, entry)

    harness_paths = HarnessArtifactPaths.for_run_paths(run_paths)
    evaluator_paths = EvaluatorArtifactPaths.for_run_paths(run_paths)
    artifacts = (
        _artifact_status(run_paths.result_json, "result.json"),
        _artifact_status(harness_paths.transcript_path, "harness transcript"),
        _artifact_status(harness_paths.events_path, "harness events"),
        _artifact_status(harness_paths.log_path, "harness run.log"),
        _artifact_status(harness_paths.summary_path, "harness summary"),
        _artifact_status(evaluator_paths.stdout_path, "evaluator stdout"),
        _artifact_status(evaluator_paths.stderr_path, "evaluator stderr"),
        _artifact_status(evaluator_paths.log_path, "evaluator log"),
        _artifact_status(evaluator_paths.result_json_path, "evaluator result"),
        _artifact_status(evaluator_paths.manifest_path, "evaluator manifest"),
        _artifact_status(run_paths.pi_rpc_events_path, "rpc events"),
        _artifact_status(run_paths.orchestra_debug_dir, "orchestra-debug"),
    )

    harness_summary = _read_json(harness_paths.summary_path)
    evaluator_manifest = _read_json(evaluator_paths.manifest_path)
    harness_present = _family_present(artifacts[1:5])
    evaluator_present = _family_present(artifacts[5:10])
    rpc_present = artifacts[10].status != "missing"
    orchestra_present = artifacts[11].status != "missing"
    if harness_present and evaluator_present:
        trace_status = "present"
    elif harness_present or evaluator_present or rpc_present or orchestra_present:
        trace_status = "partial"
    else:
        trace_status = "missing"

    if result is not None:
        outcome = result.outcome
        harness_status = result.harness.status
        evaluation_status = result.evaluation.status
        evaluation_score = result.evaluation.score
    else:
        outcome = ""
        harness_status = str(harness_summary.get("status") or "")
        evaluation_status = str(evaluator_manifest.get("classification") or "")
        evaluation_score = ""

    classification = _classify(
        result,
        harness_summary=harness_summary,
        evaluator_manifest=evaluator_manifest,
        trace_status=trace_status,
        result_read_error=result_error,
    )

    return DebugReport(
        run_id=run_paths.run_id,
        task_id=run_paths.task_id,
        run_dir=run_paths.run_dir,
        result_path=run_paths.result_json,
        batch=batch,
        model=model,
        orchestra=orchestra,
        outcome=outcome,
        harness_status=harness_status,
        evaluation_status=evaluation_status,
        evaluation_score=evaluation_score,
        classification=classification,
        trace_status=trace_status,
        result_present=result is not None,
        result_error=result_error,
        harness_summary=harness_summary,
        evaluator_manifest=evaluator_manifest,
        artifacts=artifacts,
        orchestration_snapshots=_load_orchestration_snapshots(run_paths.orchestra_debug_dir),
    )


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _fmt_lines(*items: str) -> str:
    return "\n".join(item for item in items if item != "") + "\n"


def _artifact_line(artifact: DebugArtifactStatus) -> str:
    suffix = f" ({artifact.note})" if artifact.note else ""
    return f"- {artifact.label}: {artifact.status} -> {artifact.path}{suffix}"


def _snapshot_line(snapshot: DebugOrchestrationSnapshot) -> str:
    parts = [f"state={snapshot.state or 'n/a'}"]
    if snapshot.active_runs is not None:
        parts.append(f"active_runs={snapshot.active_runs}")
    parts.append(f"descendants_terminal={_fmt_bool(snapshot.descendants_terminal)}")
    parts.append(f"session_report_available={_fmt_bool(snapshot.session_report_available)}")
    parts.append(f"session_report_delivered={_fmt_bool(snapshot.session_report_delivered)}")
    suffix = f" ({snapshot.count} snapshot(s))" if snapshot.count else ""
    return f"- {snapshot.path}: {' '.join(parts)}{suffix}"


def format_debug_report(report: DebugReport) -> str:
    body = [
        "debug",
        f"run_id: {report.run_id}",
        f"task_id: {report.task_id}",
        f"status: {report.classification}",
        f"trace_status: {report.trace_status}",
        f"result: outcome={report.outcome or 'n/a'} harness={report.harness_status or 'n/a'} evaluation={report.evaluation_status or 'n/a'} score={report.evaluation_score or 'n/a'}",
        f"batch: {report.batch or 'unlabeled'}",
        f"model: {report.model or 'n/a'}",
        f"orchestra: {_fmt_bool(report.orchestra)}",
        "artifact status:",
    ]
    body.extend(_artifact_line(artifact) for artifact in report.artifacts)
    if report.result_error:
        body.append(f"result_error: {report.result_error}")
    if report.harness_summary:
        body.append(f"harness_summary: {report.harness_summary}")
    if report.evaluator_manifest:
        body.append(f"evaluator_manifest: {report.evaluator_manifest}")
    if report.orchestration_snapshots:
        body.append("orchestration snapshots:")
        body.extend(_snapshot_line(snapshot) for snapshot in report.orchestration_snapshots)
    return _fmt_lines(*body)


__all__ = [
    "DebugArtifactStatus",
    "DebugOrchestrationSnapshot",
    "DebugReport",
    "build_debug_report",
    "format_debug_report",
]
