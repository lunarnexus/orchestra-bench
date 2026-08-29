from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.harnesses.base import HarnessRequest
from bench.harnesses.command import CommandHarness
from bench.paths import RunPaths
from bench.workspace import workspace_dir


class TestCommandHarness:
    def test_command_harness_expands_template_omitting_empty_optional_values_and_merges_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
        request = HarnessRequest(
            run_paths=run_paths,
            prompt="hello world",
            model="gpt-4.1",
            agent="",
            profile="",
            timeout_seconds=3.0,
            env={"SHARED": "request", "RUN_ONLY": "1"},
        )

        captured: dict[str, object] = {}
        monkeypatch.setenv("LEAK_SECRET", "top-secret")

        def fake_run(command, **kwargs):
            captured["command"] = list(command)
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, 0, stdout="stdout line\n", stderr="stderr line\n")

        harness = CommandHarness.from_resolved_config(
            {
                "command": [
                    "tool",
                    "{prompt}",
                    "--model",
                    "{model}",
                    "--workdir",
                    "{workdir}",
                    "{agent}",
                    "{profile}",
                ],
                "env": {"HARNESS_ONLY": "yes", "SHARED": "harness"},
            }
        )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = harness.run(request)

        assert captured["command"] == ["tool", "hello world", "--model", "gpt-4.1", "--workdir", str(workspace_dir(run_paths))]
        assert captured["kwargs"]["capture_output"] is True
        assert captured["kwargs"]["text"] is True
        assert captured["kwargs"]["timeout"] == 3.0
        assert captured["kwargs"]["cwd"] == workspace_dir(run_paths)
        env = captured["kwargs"]["env"]
        assert env["HARNESS_ONLY"] == "yes"
        assert env["RUN_ONLY"] == "1"
        assert env["SHARED"] == "request"
        assert "LEAK_SECRET" not in env
        assert result.status == "ok"
        assert result.exit_code == 0
        assert result.error == ""
        assert result.details["command"] == ["tool", "hello world", "--model", "gpt-4.1", "--workdir", str(workspace_dir(run_paths))]
        assert result.details["returncode"] == 0
        assert result.details["artifacts"]["transcript"] == str(request.artifacts.transcript_path)
        assert request.artifacts.transcript_path.read_text(encoding="utf-8") == "stdout line\n"
        assert request.artifacts.log_path.read_text(encoding="utf-8") == "stderr line\n"
        assert json.loads(request.artifacts.summary_path.read_text(encoding="utf-8")) == {
            "command": ["tool", "hello world", "--model", "gpt-4.1", "--workdir", str(workspace_dir(run_paths))],
            "details": {
                "artifacts": {
                    "stderr": str(request.artifacts.log_path),
                    "summary": str(request.artifacts.summary_path),
                    "transcript": str(request.artifacts.transcript_path),
                },
                "command": ["tool", "hello world", "--model", "gpt-4.1", "--workdir", str(workspace_dir(run_paths))],
                "returncode": 0,
                "timeout_seconds": 3.0,
                "workdir": str(workspace_dir(run_paths)),
            },
            "error": "",
            "exit_code": 0,
            "status": "ok",
        }

    def test_command_harness_classifies_nonzero_exit_as_lifecycle_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
        request = HarnessRequest(run_paths=run_paths, prompt="hello", timeout_seconds=None)
        harness = CommandHarness(["tool", "{prompt}"])

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 17, stdout="out", stderr="err")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = harness.run(request)

        assert result.status == "lifecycle_failed"
        assert result.exit_code == 17
        assert result.error == "command exited with code 17"
        assert result.details["reason"] == "nonzero_exit"
        assert request.artifacts.transcript_path.read_text(encoding="utf-8") == "out\n"
        assert request.artifacts.log_path.read_text(encoding="utf-8") == "err\n"

    def test_command_harness_classifies_timeout_as_lifecycle_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
        request = HarnessRequest(run_paths=run_paths, prompt="hello", timeout_seconds=1.5)
        harness = CommandHarness(["tool", "{prompt}"])

        def fake_run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1.5, output="partial out", stderr="partial err")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = harness.run(request)

        assert result.status == "lifecycle_failed"
        assert result.exit_code is None
        assert result.error == "command timed out after 1.5 seconds"
        assert result.details["reason"] == "timeout"
        assert request.artifacts.transcript_path.read_text(encoding="utf-8") == "partial out\n"
        assert request.artifacts.log_path.read_text(encoding="utf-8") == "partial err\n"
