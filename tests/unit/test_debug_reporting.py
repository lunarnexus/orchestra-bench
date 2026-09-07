from __future__ import annotations

import json
from pathlib import Path

from bench.paths import RunPaths
from bench.reporting.debug import build_debug_report, format_debug_report
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, write_json_atomic


def _write(path: Path, text: str = "ok\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_run_artifacts(run_paths: RunPaths) -> None:
    _write(run_paths.artifacts_dir / "harness" / "transcript.txt", "prompt: do the thing\n")
    _write(run_paths.artifacts_dir / "harness" / "events.jsonl", '{"type":"agent_settled"}\n')
    _write(run_paths.artifacts_dir / "harness" / "run.log", "harness log\n")
    _write_json(run_paths.artifacts_dir / "harness" / "summary.json", {"status": "ok", "exit_code": 0})
    _write(run_paths.artifacts_dir / "evaluator" / "stdout.txt", "grader stdout\n")
    _write(run_paths.artifacts_dir / "evaluator" / "stderr.txt", "")
    _write(run_paths.artifacts_dir / "evaluator" / "log.txt", "evaluator log\n")
    _write_json(run_paths.artifacts_dir / "evaluator" / "result.json", {"status": "ok", "score": "fail"})
    _write_json(
        run_paths.manifest_path,
        {
            "classification": "ok",
            "command": ["bash", "evaluate/run.sh"],
            "returncode": 0,
            "source": "result_json",
        },
    )
    _write(run_paths.pi_rpc_events_path, '{"type":"agent_settled"}\n')
    _write(
        run_paths.orchestra_debug_dir / "status.jsonl",
        '{"active_runs":1,"descendants_terminal":false,"session_report_available":true,"session_report_delivered":false,"state":"running"}\n',
    )


def test_build_debug_report_summarizes_artifacts_and_orchestration_snapshots(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010203", "task-one")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_run_artifacts(run_paths)
    result = TaskResult(
        run_meta=RunMeta(
            run_id=run_paths.run_id,
            task_id=run_paths.task_id,
            batch="smoke",
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:10:00Z",
        ),
        harness=HarnessResult(status="ok", exit_code=0),
        evaluation=EvaluationResult(status="ok", score="fail"),
        outcome="fail",
        details={"provenance": {"model": "agent-x", "orchestra": True}},
    )
    write_json_atomic(run_paths.result_json, result)

    report = build_debug_report(run_paths)
    text = format_debug_report(report)

    assert report.classification == "task failure"
    assert report.trace_status == "present"
    assert "status: task failure" in text
    assert "trace_status: present" in text
    assert "harness transcript: present" in text
    assert "harness events: present" in text
    assert "harness run.log: present" in text
    assert "harness summary: present" in text
    assert "evaluator result: present" in text
    assert "rpc events: present" in text
    assert "orchestra-debug: present" in text
    assert "orchestration snapshots:" in text
    assert "active_runs=1" in text
    assert str(run_paths.result_json) in text


def test_build_debug_report_distinguishes_failure_types_and_missing_trace(tmp_path: Path) -> None:
    harness_failed_paths = RunPaths(tmp_path, "20250101T010204", "task-two")
    harness_failed_paths.run_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        harness_failed_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=harness_failed_paths.run_id, task_id=harness_failed_paths.task_id, batch="smoke"),
            harness=HarnessResult(status="lifecycle_failed", exit_code=137, error="pi exited"),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )
    harness_failed_paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    _write_json(harness_failed_paths.artifacts_dir / "harness" / "summary.json", {"status": "lifecycle_failed"})

    evaluator_failed_paths = RunPaths(tmp_path, "20250101T010205", "task-three")
    evaluator_failed_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        evaluator_failed_paths.artifacts_dir / "evaluator" / "manifest.json",
        {"classification": "timeout", "returncode": None, "source": "stdout"},
    )
    write_json_atomic(
        evaluator_failed_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=evaluator_failed_paths.run_id, task_id=evaluator_failed_paths.task_id, batch="smoke"),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="failed", error="grader timed out"),
            outcome="not_run",
        ),
    )

    missing_trace_paths = RunPaths(tmp_path, "20250101T010206", "task-four")

    cases = [
        (harness_failed_paths, "harness lifecycle failure"),
        (evaluator_failed_paths, "evaluator failure"),
        (missing_trace_paths, "missing trace"),
    ]

    for run_paths, expected in cases:
        report = build_debug_report(run_paths)
        text = format_debug_report(report)
        assert report.classification == expected
        assert expected in text
        assert "result.json" in text
        assert "harness transcript" in text


def test_build_debug_report_uses_artifact_clues_when_result_json_is_missing_or_invalid(tmp_path: Path) -> None:
    harness_only_paths = RunPaths(tmp_path, "20250101T010207", "task-five")
    harness_only_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(harness_only_paths.artifacts_dir / "harness" / "summary.json", {"status": "lifecycle_failed", "exit_code": 137})
    _write(harness_only_paths.artifacts_dir / "harness" / "transcript.txt", "prompt: do the thing\n")

    evaluator_only_paths = RunPaths(tmp_path, "20250101T010208", "task-six")
    evaluator_only_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write(evaluator_only_paths.result_json, "{not-json}\n")
    _write_json(
        evaluator_only_paths.manifest_path,
        {"classification": "timeout", "returncode": None, "source": "stdout"},
    )
    _write(evaluator_only_paths.artifacts_dir / "evaluator" / "stdout.txt", "grader stdout\n")

    harness_report = build_debug_report(harness_only_paths)
    harness_text = format_debug_report(harness_report)
    assert harness_report.classification == "harness lifecycle failure"
    assert harness_report.result_present is False
    assert harness_report.result_error == "missing result.json"
    assert "harness summary: present" in harness_text
    assert "status: harness lifecycle failure" in harness_text
    assert "result: outcome=n/a harness=lifecycle_failed evaluation=n/a score=n/a" in harness_text

    evaluator_report = build_debug_report(evaluator_only_paths)
    evaluator_text = format_debug_report(evaluator_report)
    assert evaluator_report.classification == "evaluator failure"
    assert evaluator_report.result_present is False
    assert evaluator_report.result_error.startswith("JSONDecodeError:")
    assert "evaluator manifest: present" in evaluator_text
    assert "status: evaluator failure" in evaluator_text
    assert "evaluation=timeout" in evaluator_text


def _write_child_session(run_paths: RunPaths, name: str = "orchestra-worker-a1b2c3d4e5f6.jsonl", *, error: str | None = None) -> Path:
    events = [
        {"type": "session", "version": 3, "id": "orchestra-worker-a1b2c3d4e5f6"},
        {"type": "model_change", "provider": "lmstudio", "modelId": "qwen-test-model"},
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "do the assigned work"}]},
        },
    ]
    if error is not None:
        events.append({"type": "error", "message": error})
    path = run_paths.pi_sessions_dir / name
    _write(path, "".join(json.dumps(event) + "\n" for event in events))
    return path


def test_debug_report_surfaces_failed_child_identity_status_and_reason(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010301", "task-child")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write(run_paths.artifacts_dir / "harness" / "transcript.txt", "prompt\n")
    error = "api request failed: connection refused after 3 retries (host lmstudio.internal:1234)"
    child_path = _write_child_session(run_paths, error=error)

    report = build_debug_report(run_paths)
    text = format_debug_report(report)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.path == child_path
    assert child.session_id == "orchestra-worker-a1b2c3d4e5f6"
    assert child.role == "worker"
    assert child.provider == "lmstudio"
    assert child.model == "qwen-test-model"
    assert child.status == "failed"
    assert error in child.reason

    assert "child session evidence:" in text
    assert f"id={child.session_id}" in text
    assert "role=worker" in text
    assert "provider=lmstudio" in text
    assert "model=qwen-test-model" in text
    assert "status=failed" in text
    assert error[:80] in text


def test_debug_report_marks_missing_child_sessions_unavailable(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010302", "task-nosessions")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)

    report = build_debug_report(run_paths)
    text = format_debug_report(report)

    assert len(report.child_sessions) == 1
    assert report.child_sessions[0].status == "unavailable"
    assert report.child_sessions[0].reason
    assert "child session evidence:" in text
    assert "status=unavailable" in text
    # diagnostics stay separate from the correctness result line
    assert "result: outcome=n/a harness=n/a evaluation=n/a score=n/a" in text


def test_debug_report_marks_collected_with_no_child_sessions_explicitly(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010304", "task-nochildren")
    run_paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    (run_paths.artifacts_dir / "pi-sessions-collection.json").write_text(
        json.dumps({"status": "collected", "source": "/tmp/sessions"}) + "\n",
        encoding="utf-8",
    )

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    assert report.child_sessions[0].status == "unavailable"
    assert report.child_sessions[0].reason == "session collection completed; no child session transcripts were present"


def test_debug_report_child_without_terminal_signal_is_not_failed(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010303", "task-childok")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)

    report = build_debug_report(run_paths)
    _write_child_session(
        run_paths,
        name="orchestra-planner-ffff00001111.jsonl",
    )
    # rewrite session id in the planner file so role/id derive correctly
    path = run_paths.pi_sessions_dir / "orchestra-planner-ffff00001111.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lines[0] = {"type": "session", "version": 3, "id": "orchestra-planner-ffff00001111"}
    path.write_text("".join(json.dumps(event) + "\n" for event in lines), encoding="utf-8")

    report = build_debug_report(run_paths)
    text = format_debug_report(report)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.session_id == "orchestra-planner-ffff00001111"
    assert child.role == "planner"
    assert child.status != "failed"
    assert f"id={child.session_id}" in text


def _write_worker_session(
    run_paths: RunPaths,
    name: str = "orchestra-worker-aaaabbbbcccc.jsonl",
    *,
    user_text: str = "do the assigned work",
    assistant_texts: tuple[str, ...] = (),
    tool_error: bool = False,
) -> Path:
    session_id = name[: -len(".jsonl")] if name.endswith(".jsonl") else name
    events: list[dict] = [
        {"type": "session", "version": 3, "id": session_id},
        {"type": "model_change", "provider": "lmstudio", "modelId": "qwen-test-model"},
        {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": user_text}]}},
    ]
    if tool_error:
        events.append(
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolName": "bash",
                    "isError": True,
                    "content": [{"type": "text", "text": "command failed: exit 1"}],
                },
            }
        )
    for text in assistant_texts:
        events.append({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
    path = run_paths.pi_sessions_dir / name
    _write(path, "".join(json.dumps(event) + "\n" for event in events))
    return path


def test_child_final_complete_overrides_intermediate_tool_errors(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010401", "task-child-terminal-ok")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_worker_session(
        run_paths,
        assistant_texts=("working on the slice", "Status: complete\nVerdict: pass"),
        tool_error=True,
    )

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.status == "completed"


def test_child_explicit_final_fail_is_failed_without_error_events(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010402", "task-child-terminal-fail")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_worker_session(
        run_paths,
        assistant_texts=("attempted the slice", "Status: failed\nVerdict: fail"),
    )

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    assert report.child_sessions[0].status == "failed"


def test_child_tool_error_without_terminal_return_is_failed(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010403", "task-child-error-noreturn")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_worker_session(run_paths, assistant_texts=("working on the slice",), tool_error=True)

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.status == "failed"
    assert child.reason


def test_child_without_terminal_return_and_without_errors_is_incomplete(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010404", "task-child-noreturn")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_worker_session(run_paths, assistant_texts=("working on the slice",))

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    assert report.child_sessions[0].status == "incomplete"


def _write_parent_session(
    run_paths: RunPaths,
    name: str = "20250101T093000_main.jsonl",
    consolidated_lines: tuple[str, ...] = ("[orchestra: 2 subagents returned]",),
) -> Path:
    session_id = name[: -len(".jsonl")]
    events = [
        {"type": "session", "version": 3, "id": session_id},
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "\n".join(consolidated_lines)}]},
        },
    ]
    path = run_paths.pi_sessions_dir / name
    _write(path, "".join(json.dumps(event) + "\n" for event in events))
    return path


def test_child_terminal_complete_clears_intermediate_error_reason(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010410", "task-child-clear-reason")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_worker_session(
        run_paths,
        assistant_texts=("working on the slice", "Status: complete\nVerdict: pass"),
        tool_error=True,
    )

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.status == "completed"
    # Terminal success clears the intermediate error; no stale failure reason remains.
    assert child.reason == ""


def test_consolidated_parent_return_completes_child_without_terminal_output(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010411", "task-child-consolidated-ok")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_parent_session(
        run_paths,
        consolidated_lines=(
            "[orchestra: 2 subagents returned]",
            "[orchestra: builder abc123def success]",
            "[orchestra: verifier def456abc success]",
        ),
    )
    # Builder transcript is truncated (no terminal assistant output).
    _write_worker_session(
        run_paths,
        name="orchestra-builder-abc123def.jsonl",
        user_text="Role: builder\n---\nGoal: implement slice-a",
        assistant_texts=("working on the slice",),
    )
    # Verifier transcript is truncated and its filename role does not carry metadata;
    # only the consolidated return names it.
    _write_worker_session(
        run_paths,
        name="orchestra-worker-def456abc.jsonl",
        assistant_texts=("working on the slice",),
    )

    report = build_debug_report(run_paths)
    text = format_debug_report(report)

    assert len(report.child_sessions) == 2
    by_name = {child.path.name: child for child in report.child_sessions}
    builder = by_name["orchestra-builder-abc123def.jsonl"]
    verifier = by_name["orchestra-worker-def456abc.jsonl"]
    assert builder.status == "completed"
    assert builder.reason == ""
    # Role comes from the consolidated return, matched by run id.
    assert verifier.role == "verifier"
    assert verifier.status == "completed"
    assert verifier.reason == ""
    assert f"id={builder.session_id}" in text
    assert "status=completed" in text


def test_consolidated_parent_failure_marks_child_failed(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010412", "task-child-consolidated-fail")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_parent_session(
        run_paths,
        consolidated_lines=("[orchestra: 1 subagent returned]", "[orchestra: verifier def456abc failed]"),
    )
    # Truncated transcript without its own error event.
    _write_worker_session(run_paths, name="orchestra-verifier-def456abc.jsonl")

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.status == "failed"
    assert child.reason


def test_child_terminal_fail_wins_over_consolidated_success(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010413", "task-child-terminal-fail-wins")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_parent_session(
        run_paths,
        consolidated_lines=("[orchestra: 1 subagent returned]", "[orchestra: builder abc123def success]"),
    )
    # Explicit terminal failure in the child transcript overrides the parent return.
    _write_worker_session(
        run_paths,
        name="orchestra-builder-abc123def.jsonl",
        assistant_texts=("attempted the slice", "Status: failed\nVerdict: fail"),
    )

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.status == "failed"


def test_timestamp_prefixed_child_matches_consolidated_return(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010415", "task-child-ts-prefix")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_parent_session(
        run_paths,
        consolidated_lines=("[orchestra: 1 subagent returned]", "[orchestra: verifier 2fe7403262c8 success]"),
    )
    # Real child filenames are timestamp-prefixed; the session id carries the same prefix.
    _write_worker_session(run_paths, name="20260715T123400_orchestra-worker-2fe7403262c8.jsonl")

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.session_id == "20260715T123400_orchestra-worker-2fe7403262c8"
    # Run id must be found after the timestamp prefix so the consolidated return matches.
    assert child.role == "verifier"
    assert child.status == "completed"
    assert child.reason == ""


def test_child_without_terminal_or_consolidated_match_stays_incomplete(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010414", "task-child-no-match")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_parent_session(
        run_paths,
        consolidated_lines=("[orchestra: 1 subagent returned]", "[orchestra: builder abc123def success]"),
    )
    # Unrelated run id: no terminal signal and no matching consolidated return.
    _write_worker_session(run_paths, name="orchestra-worker-zzzz9999.jsonl")

    report = build_debug_report(run_paths)

    assert len(report.child_sessions) == 1
    child = report.child_sessions[0]
    assert child.status == "incomplete"
    assert child.reason == ""


def test_child_roles_come_from_transcript_metadata_not_filename(tmp_path: Path) -> None:
    run_paths = RunPaths(tmp_path, "20250101T010405", "task-child-roles")
    run_paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_worker_session(
        run_paths,
        name="orchestra-worker-bbbb11112222.jsonl",
        user_text="Role: builder\nSkill directory: /skills/builder\n---\nGoal: implement slice-a",
        assistant_texts=("Status: complete",),
    )
    _write_worker_session(
        run_paths,
        name="orchestra-worker-cccc33334444.jsonl",
        user_text="Role: verifier\nSkill directory: /skills/verifier\n---\nGoal: verify slice-a",
        assistant_texts=("Status: complete",),
    )
    _write_worker_session(
        run_paths,
        name="orchestra-worker-ffff55556666.jsonl",
        user_text="do the assigned work",
    )

    report = build_debug_report(run_paths)

    roles_by_name = {path.name: child.role for path, child in zip([c.path for c in report.child_sessions], report.child_sessions)}
    assert len(report.child_sessions) == 3
    assert roles_by_name["orchestra-worker-bbbb11112222.jsonl"] == "builder"
    assert roles_by_name["orchestra-worker-cccc33334444.jsonl"] == "verifier"
    # No transcript metadata: filename is the only remaining evidence.
    assert roles_by_name["orchestra-worker-ffff55556666.jsonl"] == "worker"
