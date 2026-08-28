"""Plain command harness backend for one-shot CLI tools."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from bench.harnesses.base import BaseHarness, HarnessRequest
from bench.harnesses.process import ProcessTranscript, build_process_env
from bench.result import HarnessResult
from bench.workspace import workspace_dir


class _TemplateValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


@dataclass
class CommandHarness(BaseHarness):
    command_template: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)

    def __init__(self, command_template: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
        template = tuple(str(item) for item in command_template)
        if not template:
            raise ValueError("command_template must not be empty")
        object.__setattr__(self, "command_template", template)
        object.__setattr__(self, "env", _coerce_env(env))

    @classmethod
    def from_resolved_config(cls, resolved: Mapping[str, object]) -> "CommandHarness":
        command = resolved.get("command")
        if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
            raise TypeError("resolved command must be a sequence of strings")
        env = resolved.get("env")
        if env is not None and not isinstance(env, Mapping):
            raise TypeError("resolved env must be a mapping of strings")
        return cls(command, env=_coerce_env(env))

    def _template_values(self, request: HarnessRequest) -> _TemplateValues:
        return _TemplateValues(
            prompt=request.prompt,
            model=request.model,
            workdir=request.run_paths.container_workdir,
            agent=request.agent,
            profile=request.profile,
        )

    def _expand_command(self, request: HarnessRequest) -> list[str]:
        values = self._template_values(request)
        command: list[str] = []
        for template in self.command_template:
            rendered = template.format_map(values)
            if rendered:
                command.append(rendered)
        return command

    def _build_env(self, request: HarnessRequest) -> dict[str, str]:
        return build_process_env(configured_env=self.env, request_env=request.env)

    def _base_details(self, request: HarnessRequest, command: list[str]) -> dict[str, Any]:
        return {
            "artifacts": {
                "stderr": str(request.artifacts.log_path),
                "summary": str(request.artifacts.summary_path),
                "transcript": str(request.artifacts.transcript_path),
            },
            "command": list(command),
            "timeout_seconds": request.timeout_seconds,
            "workdir": str(workspace_dir(request.run_paths)),
        }

    def _record_outputs(self, transcript: ProcessTranscript, stdout: object, stderr: object) -> None:
        transcript.record_stdout(_coerce_text(stdout))
        transcript.record_stderr(_coerce_text(stderr))

    def run(self, request: HarnessRequest) -> HarnessResult:
        command = self._expand_command(request)
        if not command:
            transcript = ProcessTranscript(request.artifacts, command=())
            return transcript.finish(
                status="lifecycle_failed",
                exit_code=None,
                error="command template expanded to no argv",
                details=self._base_details(request, command),
            )

        transcript = ProcessTranscript(request.artifacts, command=tuple(command))
        env = self._build_env(request)
        cwd = workspace_dir(request.run_paths)
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(  # noqa: S603 - intentional command execution boundary
                command,
                capture_output=True,
                cwd=cwd,
                env=env,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self._record_outputs(transcript, getattr(exc, "output", None), getattr(exc, "stderr", None))
            details = self._base_details(request, command)
            details["reason"] = "timeout"
            return transcript.finish(
                status="lifecycle_failed",
                exit_code=None,
                error=f"command timed out after {request.timeout_seconds} seconds",
                details=details,
            )
        except Exception as exc:
            details = self._base_details(request, command)
            details["reason"] = "exception"
            details["exception_type"] = type(exc).__name__
            return transcript.finish(
                status="lifecycle_failed",
                exit_code=None,
                error=f"command failed: {exc}",
                details=details,
            )

        self._record_outputs(transcript, completed.stdout, completed.stderr)
        details = self._base_details(request, command)
        details["returncode"] = completed.returncode
        if completed.returncode == 0:
            return transcript.finish(status="ok", exit_code=0, details=details)

        details["reason"] = "nonzero_exit"
        return transcript.finish(
            status="lifecycle_failed",
            exit_code=completed.returncode,
            error=f"command exited with code {completed.returncode}",
            details=details,
        )


def _coerce_env(env: Mapping[str, object] | None) -> dict[str, str]:
    if env is None:
        return {}
    coerced: dict[str, str] = {}
    for key, value in env.items():
        coerced[str(key)] = str(value)
    return coerced


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
