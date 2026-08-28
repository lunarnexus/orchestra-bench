from __future__ import annotations

import json
from pathlib import Path

from bench.harnesses.base import BaseHarness, HarnessArtifactPaths, HarnessRequest, LifecycleEvent
from bench.harnesses.process import ProcessTranscript
from bench.paths import RunPaths
from bench.result import HarnessResult


class FakeHarness(BaseHarness):
    def run(self, request: HarnessRequest) -> HarnessResult:
        transcript = ProcessTranscript(request.artifacts, command=("fake-harness",))
        transcript.record_stdout(f"prompt: {request.prompt}")
        transcript.record_event(LifecycleEvent(type="agent_started", message="boot"))
        transcript.record_event(LifecycleEvent(type="agent_settled", message="done"))
        transcript.record_stderr("warning: nothing to do")
        return transcript.finish(status="ok", exit_code=0, details={"events": len(transcript.events)})


def test_harness_request_uses_backend_neutral_artifact_paths(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
    artifacts = HarnessArtifactPaths.for_run_paths(run_paths)
    request = HarnessRequest(
        run_paths=run_paths,
        prompt="Do the work.",
        model="test-model",
        agent="fake",
        profile="default",
        timeout_seconds=3.0,
        artifacts=artifacts,
    )

    assert request.run_paths == run_paths
    assert request.artifacts.transcript_path == run_paths.artifacts_dir / "harness" / "transcript.txt"
    assert request.artifacts.events_path == run_paths.artifacts_dir / "harness" / "events.jsonl"
    assert request.artifacts.summary_path == run_paths.artifacts_dir / "harness" / "summary.json"
    assert request.artifacts.log_path == run_paths.artifacts_dir / "harness" / "run.log"
    assert "pi" not in str(request.artifacts.events_path)


def test_fake_harness_writes_transcript_events_and_summary(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
    request = HarnessRequest(
        run_paths=run_paths,
        prompt="Do the work.",
        model="test-model",
        agent="fake",
        profile="default",
        timeout_seconds=3.0,
        artifacts=HarnessArtifactPaths.for_run_paths(run_paths),
    )

    result = FakeHarness().run(request)

    assert result == HarnessResult(status="ok", exit_code=0, details={"events": 2})
    assert request.artifacts.transcript_path.read_text(encoding="utf-8") == "prompt: Do the work.\n"
    assert [json.loads(line) for line in request.artifacts.events_path.read_text(encoding="utf-8").splitlines()] == [
        {"type": "agent_started", "message": "boot", "data": {}, "timestamp": ""},
        {"type": "agent_settled", "message": "done", "data": {}, "timestamp": ""},
    ]
    assert json.loads(request.artifacts.summary_path.read_text(encoding="utf-8")) == {
        "command": ["fake-harness"],
        "details": {"events": 2},
        "error": "",
        "exit_code": 0,
        "status": "ok",
    }
    assert request.artifacts.log_path.read_text(encoding="utf-8") == "warning: nothing to do\n"
