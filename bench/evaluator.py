"""Task evaluator execution and grading helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .artifacts import EvaluatorArtifactPaths, write_json_manifest
from .paths import RunPaths
from .result import EvaluationResult, ResultSchemaError, RunMeta, TaskResult, load_result, write_json_atomic
from .tasks import TaskDefinition
from .workspace import workspace_dir

EvaluatorRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass
class EvaluationError(RuntimeError):
    classification: str
    details: dict[str, Any]

    def __init__(self, message: str, *, classification: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.classification = classification
        self.details = dict(details or {})


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_text(path: Path, text: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_coerce_text(text), encoding="utf-8")


def _parse_json_payload(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if 0 <= start < end:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _payload_to_evaluation(payload: Mapping[str, Any]) -> EvaluationResult:
    candidate: Mapping[str, Any] = payload
    for key in ("evaluation", "result"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidate = nested
            break

    base = EvaluationResult.from_dict(dict(candidate))
    extras = {
        key: value
        for key, value in dict(payload).items()
        if key not in {"status", "score", "checks", "error", "details", "evaluation", "result"}
    }
    if extras:
        details = dict(base.details)
        raw = dict(details.get("raw") or {})
        raw.update(extras)
        details["raw"] = raw
        base.details = details
    return base


def _result_from_run(task: TaskDefinition, run_paths: RunPaths) -> TaskResult:
    if run_paths.result_json.is_file():
        return load_result(run_paths.result_json)
    return TaskResult(run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch))


def _evaluate_artifacts(run_paths: RunPaths) -> EvaluatorArtifactPaths:
    return EvaluatorArtifactPaths.for_run_paths(run_paths).ensure()


def _stage_evaluator_sources(task: TaskDefinition, staging_root: Path) -> Path:
    staged_eval = staging_root / "evaluate"
    shutil.copytree(task.evaluate_path, staged_eval)
    support_root = Path(__file__).resolve().parent.parent
    for support_name in ("capability_helpers.py", "rubric_helpers.py", "evaluator_helpers.py"):
        support_path = support_root / support_name
        if support_path.is_file():
            shutil.copy2(support_path, staging_root / support_name)
    return staged_eval


def _default_command(staged_eval_dir: Path, evaluator: str) -> list[str]:
    script = staged_eval_dir.parent / evaluator
    if script.suffix == ".sh" or not script.exists():
        return ["bash", str(script)]
    return [str(script)]


def _write_manifest(
    artifacts: EvaluatorArtifactPaths,
    *,
    command: list[str],
    classification: str,
    returncode: int | None,
    source: str,
    result_path: Path | None,
    error: str = "",
) -> None:
    payload: dict[str, Any] = {
        "classification": classification,
        "command": command,
        "error": error,
        "returncode": returncode,
        "source": source,
    }
    if result_path is not None:
        payload["result_path"] = str(result_path)
    write_json_manifest(artifacts.manifest_path, payload)


def grade_run(
    task: TaskDefinition,
    run_paths: RunPaths,
    *,
    runner: EvaluatorRunner | None = None,
) -> TaskResult:
    """Grade a completed workspace and update the run result."""
    artifacts = _evaluate_artifacts(run_paths)
    workspace = workspace_dir(run_paths)
    if not workspace.is_dir():
        raise EvaluationError(
            f"workspace missing: {workspace}",
            classification="missing_workspace",
            details={"workspace": str(workspace)},
        )

    result = _result_from_run(task, run_paths)
    runner = runner or subprocess.run
    result_json_path: Path | None = None

    try:
        with tempfile.TemporaryDirectory(prefix=".evaluator-", dir=artifacts.root) as temp_dir:
            staging_root = Path(temp_dir)
            staged_eval = _stage_evaluator_sources(task, staging_root)
            command = _default_command(staged_eval, task.evaluator)
            result_file_handle = tempfile.NamedTemporaryFile(
                prefix=".result-", suffix=".json", dir=artifacts.root, delete=False
            )
            result_file_handle.close()
            result_json_path = Path(result_file_handle.name)
            # Inherit the process environment (PATH, HOME, ...): graders and their
            # child interpreters break when spawned with a bare BENCH_*-only env.
            env = os.environ.copy()
            env.update(
                {
                    "BENCH_REPO_ROOT": str(staging_root),
                "BENCH_RESULT_JSON": str(result_json_path),
                "BENCH_RUN_ID": run_paths.run_id,
                "BENCH_TASK_ID": task.task_id,
                "BENCH_TASKS": str(task.task_dir.parent),
                    "BENCH_WORKDIR": str(workspace),
                }
            )
            timeout_seconds = max(1.0, task.timeout_minutes * 60.0)
            try:
                completed = runner(
                    command,
                    cwd=workspace,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                stdout_text = _coerce_text(getattr(exc, "output", ""))
                stderr_text = _coerce_text(getattr(exc, "stderr", ""))
                _write_text(artifacts.stdout_path, stdout_text)
                _write_text(artifacts.stderr_path, stderr_text)
                _write_text(
                    artifacts.log_path,
                    f"command: {' '.join(command)}\nworkspace: {workspace}\nclassification: timeout\n",
                )
                _write_manifest(
                    artifacts,
                    command=command,
                    classification="timeout",
                    returncode=None,
                    source="stdout",
                    result_path=None,
                    error=f"evaluator timed out after {timeout_seconds} seconds",
                )
                raise EvaluationError(
                    f"evaluator timed out after {timeout_seconds} seconds",
                    classification="timeout",
                    details={"command": command, "workspace": str(workspace)},
                ) from exc
            except Exception as exc:
                _write_text(artifacts.stdout_path, "")
                _write_text(artifacts.stderr_path, "")
                _write_text(
                    artifacts.log_path,
                    f"command: {' '.join(command)}\nworkspace: {workspace}\nclassification: crash\nerror: {exc}\n",
                )
                _write_manifest(
                    artifacts,
                    command=command,
                    classification="crash",
                    returncode=None,
                    source="stdout",
                    result_path=None,
                    error=str(exc),
                )
                raise EvaluationError(
                    f"evaluator crashed: {exc}",
                    classification="crash",
                    details={"command": command, "workspace": str(workspace), "exception_type": type(exc).__name__},
                ) from exc

        stdout_text = _coerce_text(getattr(completed, "stdout", ""))
        stderr_text = _coerce_text(getattr(completed, "stderr", ""))
        _write_text(artifacts.stdout_path, stdout_text)
        _write_text(artifacts.stderr_path, stderr_text)

        payload: dict[str, Any] | None = None
        source = "stdout"
        result_file = Path(env["BENCH_RESULT_JSON"])
        if result_file.is_file() and result_file.stat().st_size > 0:
            try:
                loaded = json.loads(result_file.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise TypeError("evaluator result file must contain a JSON object")
                payload = loaded
            except (json.JSONDecodeError, TypeError) as exc:
                _write_text(
                    artifacts.log_path,
                    f"command: {' '.join(command)}\nworkspace: {workspace}\nclassification: invalid_json\nerror: {exc}\n",
                )
                _write_manifest(
                    artifacts,
                    command=command,
                    classification="invalid_json",
                    returncode=getattr(completed, "returncode", None),
                    source="result_json",
                    result_path=result_file,
                    error=str(exc),
                )
                raise EvaluationError(
                    "evaluator produced invalid JSON result file",
                    classification="invalid_json",
                    details={"command": command, "workspace": str(workspace), "result_json": str(result_file)},
                ) from exc
            else:
                source = "result_json"
        else:
            payload = _parse_json_payload(stdout_text)

        if payload is None:
            classification = "crash" if getattr(completed, "returncode", 1) != 0 else "no_json"
            message = (
                "evaluator crashed with no JSON output"
                if classification == "crash"
                else "evaluator produced no JSON"
            )
            _write_text(
                artifacts.log_path,
                f"command: {' '.join(command)}\nworkspace: {workspace}\nclassification: {classification}\nreturncode: {getattr(completed, 'returncode', None)}\n",
            )
            _write_manifest(
                artifacts,
                command=command,
                classification=classification,
                returncode=getattr(completed, "returncode", None),
                source=source,
                result_path=None,
                error=message,
            )
            raise EvaluationError(
                message,
                classification=classification,
                details={
                    "command": command,
                    "workspace": str(workspace),
                    "returncode": getattr(completed, "returncode", None),
                },
            )

        try:
            evaluation = _payload_to_evaluation(payload)
        except ResultSchemaError as exc:
            _write_manifest(
                artifacts,
                command=command,
                classification="invalid_result_schema",
                returncode=getattr(completed, "returncode", None),
                source=source,
                result_path=result_file if source == "result_json" else None,
                error=str(exc),
            )
            raise EvaluationError(
                f"evaluator produced invalid result schema: {exc}",
                classification="invalid_result_schema",
                details={"command": command, "workspace": str(workspace), "error": str(exc)},
            ) from exc
        if evaluation.status == "not_run" and evaluation.score:
            # Graders emit verdicts (score/checks/details) without an explicit
            # status field; a valid verdict means the grading run succeeded.
            evaluation.status = "ok"
        if source == "stdout":
            write_json_manifest(artifacts.result_json_path, payload)
        else:
            shutil.copy2(result_file, artifacts.result_json_path)
            # copy2 preserves the temp grader file's 0600 mode; container runs
            # as root and host operators must read run outputs.
            os.chmod(artifacts.result_json_path, 0o644)
        result.evaluation = evaluation
        if evaluation.status == "ok":
            result.outcome = "pass" if evaluation.score == "pass" else "fail"
        elif evaluation.status == "failed":
            result.outcome = "fail"
        else:
            result.outcome = "not_run"

        write_json_atomic(run_paths.result_json, result)
        _write_text(
            artifacts.log_path,
            f"command: {' '.join(command)}\nworkspace: {workspace}\nclassification: ok\nsource: {source}\nreturncode: {getattr(completed, 'returncode', None)}\n",
        )
        _write_manifest(
            artifacts,
            command=command,
            classification="ok",
            returncode=getattr(completed, "returncode", None),
            source=source,
            result_path=run_paths.result_json,
        )
        return result
    finally:
        if result_json_path is not None:
            result_json_path.unlink(missing_ok=True)
