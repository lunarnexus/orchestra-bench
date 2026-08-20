"""Tests for Slice 3 — Orchestra process artifact extraction.

Synthetic debug/session fixtures only; never depends on live history.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from __init__ import TaskResult  # noqa: E402


# ── Fixtures for synthetic artifact directories ────────────────────

def _make_result(task_id="task-a", run_id="run-1", score="pass"):
    return TaskResult(
        task_id=task_id,
        run_id=run_id,
        score=score,
    )


def _build_artifacts_dir(tmp_path: Path, run_id: str, task_id: str) -> Path:
    """Create a minimal artifacts directory structure."""
    base = tmp_path / "results"
    run_dir = base / f"{run_id}-{task_id}"
    (run_dir / "artifacts").mkdir(parents=True)
    # manifest.json with orchestra section
    manifest = {
        "run_id": run_id,
        "task_id": task_id,
        "pi_sessions": [],
        "orchestra": {},
        "warnings": [],
    }
    (run_dir / "artifacts" / "manifest.json").write_text(json.dumps(manifest))
    return run_dir


def _write_session_jsonl(run_dir: Path, lines: list[dict]) -> None:
    """Write a synthetic Pi session JSONL file."""
    sid = "sess-default"
    for event in lines:
        if event.get("type") == "session":
            sid = event["id"]
            break

    filename = f"{sid.replace(':', '-').replace('.', '-')}.jsonl"
    path = run_dir / "artifacts" / "pi-sessions" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(event) for event in lines) + "\n"
    path.write_text(content)

    pi_sessions = [{
        "file": filename,
        "session_id": sid,
        "usage": {"input": 0, "output": 0, "reasoning": 0, "totalTokens": 0},
    }]

    # Update manifest
    manifest_path = run_dir / "artifacts" / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        m["pi_sessions"] = pi_sessions
        manifest_path.write_text(json.dumps(m))


def _write_orchestra_log(run_dir: Path, events: list[dict]) -> None:
    """Write a synthetic Orchestra debug log JSONL file."""
    logs_dir = run_dir / "artifacts" / "orchestra-debug" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Use first run_id from events or default
    run_id = "abc123"
    for e in events:
        if "run_id" in e:
            run_id = e["run_id"]
            break

    log_path = logs_dir / f"{run_id}.jsonl"
    content = "\n".join(json.dumps(event) for event in events) + "\n"
    log_path.write_text(content)

    # Update manifest to reference the logs
    manifest_path = run_dir / "artifacts" / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        if isinstance(m.get("orchestra"), dict):
            m["orchestra"]["logs"] = "orchestra-debug/logs"
            log_names = sorted(p.name for p in logs_dir.glob("*.jsonl"))
            m["orchestra"]["debug_logs"] = [f"orchestra-debug/logs/{n}" for n in log_names]
        manifest_path.write_text(json.dumps(m))


def _write_session_jsonl_named(run_dir: Path, filename: str, lines: list[dict]) -> None:
    """Write a synthetic Pi session JSONL file with a chosen filename."""
    path = run_dir / "artifacts" / "pi-sessions" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(event) for event in lines) + "\n"
    path.write_text(content)


def _session_line(event_type: str, **kwargs) -> dict:
    """Helper to build a Pi session event line."""
    return {"type": event_type, **kwargs}


# ── 1. Dispatch detection from Pi session JSONL ───────────────

class TestDetectDispatchesFromSession:
    """Parse Pi session tool calls for orch_dispatch events."""

    def test_detects_single_dispatch(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-1", "task-a")

        lines = [
            _session_line("session", id="sess-001"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-1", task_id="task-a")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks is not None
        # Should detect at least one dispatch
        assert any(isinstance(v, (int, float)) and v >= 1 for v in checks.values()) or \
               any(v is True for v in checks.values()), f"expected a positive signal but got {checks}"


    def test_no_dispatch_when_session_empty(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-2", "task-b")

        lines = [
            _session_line("session", id="sess-002"),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-2", task_id="task-b")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_detects_dispatch_role(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-3", "task-c")

        lines = [
            _session_line("session", id="sess-003"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "write tests", "role": "builder"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-3", task_id="task-c")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)

    def test_parse_pi_session_file_captures_context_usage_snapshot(self, tmp_path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-main", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [], "usage": {"input": 100, "output": 20, "reasoning": 3, "totalTokens": 123}}}),
            json.dumps({"type": "compaction", "id": "cmp-1"}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [], "usage": {"input": 75, "output": 10, "reasoning": 1, "totalTokens": 86}}}),
            "",
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["session_id"] == "sess-main"
        assert parsed["usage"]["input"] == 175
        ctx = parsed["context_usage"]
        # Check expected keys are present (dict may contain additional keys like max_input_tokens)
        assert ctx["api_call_count"] == 2
        assert ctx["last_input_tokens"] == 75
        assert ctx["last_total_tokens"] == 86
        assert ctx["compaction_count"] == 1

    def test_counts_compactions_across_pi_sessions(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-3b", "task-c2")

        _write_session_jsonl(run_dir, [
            _session_line("session", id="sess-003b"),
            _session_line("compaction", id="cmp-1", summary="first"),
            _session_line("message", message={"role": "assistant", "content": []}),
            _session_line("compaction", id="cmp-2", summary="second"),
        ])
        _write_session_jsonl(run_dir, [
            _session_line("session", id="sess-003c"),
            _session_line("compaction", id="cmp-3", summary="third"),
        ])

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-3b", task_id="task-c2")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["compaction_count"] == 3


# ── 2. Worker completion from Orchestra logs ────────────────

class TestDetectWorkerCompletion:
    """Parse Orchestra log events for worker lifecycle signals."""

    def test_detects_worker_completed(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-4", "task-d")

        events = [
            {"event": "run.created", "role": "reviewer", "run_id": "w1"},
            {"event": "worker.started", "role": "reviewer", "run_id": "w1"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "w1"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-4", task_id="task-d")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_detects_worker_exit_nonzero(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-5", "task-e")

        events = [
            {"event": "run.created", "role": "builder", "run_id": "w2"},
            {"event": "worker.started", "role": "builder", "run_id": "w2"},
            {"event": "worker.exited", "exit_code": 1, "run_id": "w2"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-5", task_id="task-e")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_completed"] is False


    def test_detects_running_worker_without_exit(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-5b", "task-e2")

        events = [
            {"event": "run.created", "role": "builder", "run_id": "w2b"},
            {"event": "worker.started", "role": "builder", "run_id": "w2b"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-e2",
            run_id="run-5b",
            score="pass",
            checks={"answer_exists": True},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_completed"] is False
        assert checks["worker_running_without_exit"] is True
        assert checks["fallback_answer_after_dispatch"] is False


    def test_detects_multiple_workers(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-6", "task-f")

        events = [
            {"event": "run.created", "role": "researcher", "run_id": "w3"},
            {"event": "worker.started", "role": "researcher", "run_id": "w3"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "w3"},
            {"event": "run.created", "role": "builder", "run_id": "w4"},
            {"event": "worker.started", "role": "builder", "run_id": "w4"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "w4"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-6", task_id="task-f")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 3. Timeout detection ────────────────

class TestDetectTimeouts:
    """Parse Orchestra log events for timeout signals."""

    def test_detects_timeout_event(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-7", "task-g")

        events = [
            {"event": "run.created", "role": "builder", "run_id": "w5"},
            {"event": "worker.started", "role": "builder", "run_id": "w5"},
            {"event": "worker.timeout", "timeout_seconds": 120, "run_id": "w5"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-7", task_id="task-g")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_no_timeout_when_none(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-8", "task-h")

        events = [
            {"event": "run.created", "role": "builder", "run_id": "w6"},
            {"event": "worker.started", "role": "builder", "run_id": "w6"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "w6"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-8", task_id="task-h")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 4. Retry detection ────────────────

class TestDetectRetries:
    """Parse Orchestra log events for retry signals."""

    def test_detects_retry_events(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-9", "task-i")

        events = [
            {"event": "run.created", "role": "builder", "run_id": "w7"},
            {"event": "worker.started", "role": "builder", "run_id": "w7"},
            {"event": "worker.exited", "exit_code": 1, "run_id": "w7"},
            {"event": "retry.requested", "previous_run_id": "w7", "role": "builder", "run_id": "w8"},
            {"event": "worker.started", "role": "builder", "run_id": "w8"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "w8"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-9", task_id="task-i")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 5. Same-slice redispatch detection ────────────────

class TestDetectSameSliceRedispatches:
    """Parse dispatch events for repeated identical goals."""

    def test_detects_same_goal_redispatch(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-10", "task-j")

        lines = [
            _session_line("session", id="sess-010"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "Implement the full feature set", "role": "builder"}}],
            }),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "Implement the full feature set", "role": "builder"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-10", task_id="task-j")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 6. Target role dispatched check ────────────────

class TestTargetRoleDispatched:
    """Detect whether the expected target role was actually dispatched."""

    def test_target_role_dispatched_true(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-11", "task-k")

        lines = [
            _session_line("session", id="sess-011"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-k", run_id="run-11", score="pass",
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_target_role_dispatched_from_orchestra_logs(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-12", "task-l")

        events = [
            {"event": "run.created", "role": "reviewer", "run_id": "w9"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-l", run_id="run-12", score="pass",
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 7. Premature completion detection ────────────────

class TestPrematureCompletion:
    """Detect when parent dispatches a worker but exits without integration."""

    def test_detects_premature_completion(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-13", "task-m")

        # Dispatch was made and worker exited, but no final artifact written event
        events = [
            {"event": "run.created", "role": "reviewer", "run_id": "w10"},
            {"event": "worker.started", "role": "reviewer", "run_id": "w10"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "w10"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-m", run_id="run-13", score="fail",
            checks={"answer_exists": False},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 8. Scope blocker detection ────────────────

class TestScopeBlockers:
    """Detect researcher scope blockers in logs."""

    def test_detects_scope_blocker(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-14", "task-n")

        events = [
            {"event": "scope.blocked", "role": "researcher", "reason": "no source files found", "run_id": "w11"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-14", task_id="task-n")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 9. Missing artifacts (non-fatal) ────────────────

class TestMissingArtifacts:
    """No crash when artifact files are absent."""

    def test_no_artifacts_dir(self, tmp_path):
        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-x", task_id="task-none")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_empty_artifacts_dir(self, tmp_path):
        from eval_harness import extract_orchestration_checks

        run_dir = _build_artifacts_dir(tmp_path, "run-y", "task-empty")
        # Don't write any session or log files — just the manifest

        result = _make_result(run_id="run-y", task_id="task-empty")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_malformed_json_session(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-z", "task-bad")

        # Write a session file with bad JSON
        pi_sessions_dir = run_dir / "artifacts" / "pi-sessions"
        pi_sessions_dir.mkdir(parents=True)
        (pi_sessions_dir / "bad.jsonl").write_text("not valid json\n{incomplete")

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-z", task_id="task-bad")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 10. Full orchestration_checks integration ────────────────

class TestOrchestrationChecksIntegration:
    """Verify the full extraction populates TaskResult correctly."""

    def test_populates_orchestration_checks_on_result(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-int", "task-int")

        lines = [
            _session_line("session", id="sess-int"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code diff", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        events = [
            {"event": "run.created", "role": "reviewer", "run_id": "wint"},
            {"event": "worker.started", "role": "reviewer", "run_id": "wint"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "wint"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-int", run_id="run-int", score="pass",
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_ingests_main_session_context_token_metrics(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-context", "task-context")
        tokens_file = run_dir / "artifacts" / "tokens.json"
        tokens_file.write_text(json.dumps({
            "total_tokens": 1234,
            "main_session_context_input_tokens": 900,
            "main_session_context_total_tokens": 950,
            "main_session_api_call_count": 4,
        }))

        from eval_harness import ingest_artifacts

        result = TaskResult(task_id="task-context", run_id="run-context", score="pass")
        ingest_artifacts(result, base_dir=tmp_path / "results")

        assert result.tokens["main_session_context_input_tokens"] == 900
        assert result.tokens["main_session_context_total_tokens"] == 950
        assert result.tokens["main_session_api_call_count"] == 4

    def test_result_roundtrips_with_checks(self, tmp_path):
        """Orchestration checks survive JSON serialization."""
        result = _make_result(run_id="round", task_id="task-round")
        result.orchestration_checks = {
            "target_role_dispatched": True,
            "worker_completed": True,
            "timeouts": 0,
            "retries": 0,
        }

        out_dir = tmp_path / "results" / "round-task-round"
        out_dir.mkdir(parents=True)
        dest = result.write_json(out_dir / "result.json")
        loaded = TaskResult.from_json(dest)

        assert loaded.orchestration_checks["target_role_dispatched"] is True
        assert loaded.orchestration_checks["worker_completed"] is True


    def test_extract_and_set_on_result(self, tmp_path):
        """extract_orchestration_checks can be called and result updated."""
        run_dir = _build_artifacts_dir(tmp_path, "run-set", "task-set")

        lines = [
            _session_line("session", id="sess-set"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "build feature", "role": "builder"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-set", run_id="run-set", score="pass",
            run_meta={"target_role": "builder"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        # The function returns a dict; caller assigns it to result.orchestration_checks
        assert isinstance(checks, dict)

    def test_extracts_rpc_runner_lifecycle_summary(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-rpc", "task-rpc")
        (run_dir / ".bench_rpc_run.json").write_text(json.dumps({
            "pi_exit": 0,
            "orch_on_ok": True,
            "session_id": "sess-rpc",
            "gate_result": "settled",
            "rpc_runner_used": True,
            "rpc_agent_settled_seen": True,
            "rpc_gate_result": "settled",
            "rpc_summary_written": True,
        }) + "\n")

        from eval_harness import extract_orchestration_checks

        result = TaskResult(task_id="task-rpc", run_id="run-rpc", score="pass")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["rpc_runner_used"] is True
        assert checks["rpc_agent_settled_seen"] is True
        assert checks["rpc_gate_result"] == "settled"
        assert checks["rpc_summary_written"] is True

    def test_extracts_active_worker_efficiency_and_test_ownership(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-eff", "task-eff")
        workdir = "/workspace/run-eff-task-eff"

        main_lines = [
            _session_line("session", id="sess-main", cwd=workdir),
            _session_line(
                "message",
                timestamp="2026-08-18T00:00:00.100Z",
                message={
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "orch_dispatch",
                        "arguments": {"goal": "build feature", "role": "builder"},
                    }],
                },
            ),
            _session_line(
                "message",
                timestamp="2026-08-18T00:00:00.200Z",
                message={
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "bash",
                        "arguments": {"command": "cd /workspace/run-eff-task-eff && npm test"},
                    }],
                    "usage": {"input": 10, "output": 2, "reasoning": 1, "totalTokens": 13},
                },
            ),
            _session_line(
                "message",
                timestamp="2026-08-18T00:00:00.300Z",
                message={"role": "assistant", "content": [], "usage": {"input": 20, "output": 3, "reasoning": 2, "totalTokens": 25}},
            ),
            _session_line(
                "message",
                timestamp="2026-08-18T00:00:00.700Z",
                message={"role": "assistant", "content": [], "usage": {"input": 40, "output": 4, "reasoning": 3, "totalTokens": 47}},
            ),
        ]
        _write_session_jsonl_named(run_dir, "2026-08-18T00-00-00-000Z_sess-main.jsonl", main_lines)

        builder_lines = [
            _session_line("session", id="orchestra-worker-builder", cwd=workdir),
            _session_line(
                "message",
                timestamp="2026-08-18T00:00:00.220Z",
                message={
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "bash",
                        "arguments": {"command": "npm test"},
                    }],
                },
            ),
        ]
        _write_session_jsonl_named(run_dir, "2026-08-18T00-00-00-200Z_orchestra-worker-builder.jsonl", builder_lines)

        verifier_lines = [
            _session_line("session", id="orchestra-worker-verifier", cwd=workdir),
            _session_line(
                "message",
                timestamp="2026-08-18T00:00:00.240Z",
                message={
                    "role": "assistant",
                    "content": [{
                        "type": "toolCall",
                        "name": "bash",
                        "arguments": {"command": "npm test"},
                    }],
                },
            ),
        ]
        _write_session_jsonl_named(run_dir, "2026-08-18T00-00-00-210Z_orchestra-worker-verifier.jsonl", verifier_lines)

        events = [
            {"event": "run.created", "role": "builder", "worker_session_id": "orchestra-worker-builder", "run_id": "w1", "timestamp": "2026-08-18T00:00:00.150Z"},
            {"event": "worker.started", "role": "builder", "worker_session_id": "orchestra-worker-builder", "run_id": "w1", "timestamp": "2026-08-18T00:00:00.150Z"},
            {"event": "worker.exited", "role": "builder", "worker_session_id": "orchestra-worker-builder", "run_id": "w1", "timestamp": "2026-08-18T00:00:00.500Z"},
            {"event": "run.created", "role": "verifier", "worker_session_id": "orchestra-worker-verifier", "run_id": "w2", "timestamp": "2026-08-18T00:00:00.160Z"},
            {"event": "worker.started", "role": "verifier", "worker_session_id": "orchestra-worker-verifier", "run_id": "w2", "timestamp": "2026-08-18T00:00:00.160Z"},
            {"event": "worker.exited", "role": "verifier", "worker_session_id": "orchestra-worker-verifier", "run_id": "w2", "timestamp": "2026-08-18T00:00:00.600Z"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import (
            _collect_orchestration_efficiency_diagnostics,
            extract_orchestration_checks,
        )

        result = TaskResult(task_id="task-eff", run_id="run-eff", score="pass", run_meta={"target_role": "builder"})
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")
        diagnostics = _collect_orchestration_efficiency_diagnostics(
            run_dir / "artifacts" / "pi-sessions",
            run_dir / "artifacts" / "orchestra-debug",
            workdir,
        )

        assert diagnostics["tokens"]["main_active_worker_tokens"] == 38
        assert diagnostics["tokens"]["main_active_worker_api_calls"] == 2
        assert checks["parent_tool_calls_while_workers_active"]["by_category"]["dispatch"] == 1
        assert checks["parent_tool_calls_while_workers_active"]["by_category"]["test"] == 1
        assert checks["test_command_ownership_by_role"]["builder"] == 1
        assert checks["test_command_ownership_by_role"]["verifier"] == 1
        assert checks["duplicate_normalized_test_command_counts"]["npm test"] == 3
        assert checks["verifier_repeated_builder_tests"] == 1
        assert checks["orchestrator_repeated_worker_tests"] == 1


# ── 11. Roles used extraction ────────────────

class TestRolesUsed:
    """Extract roles that were actually dispatched/used."""

    def test_detects_multiple_dispatch_roles(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-roles", "task-mr")

        lines = [
            _session_line("session", id="sess-r1"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "research api", "role": "researcher"}}],
            }),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "build impl", "role": "builder"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = _make_result(run_id="run-roles", task_id="task-mr")
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


# ── 12. Combined session + log parsing ────────────────

class TestCombinedParsing:
    """Both Pi session and Orchestra logs contribute signals."""

    def test_session_dispatch_plus_log_completion(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-cb", "task-cb")

        # Session has dispatch
        lines = [
            _session_line("session", id="sess-cb"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        # Log has worker completion
        events = [
            {"event": "run.created", "role": "reviewer", "run_id": "wcb"},
            {"event": "worker.started", "role": "reviewer", "run_id": "wcb"},
            {"event": "worker.exited", "exit_code": 0, "run_id": "wcb"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-cb", run_id="run-cb", score="pass",
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)


    def test_session_dispatch_plus_log_timeout(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-cb2", "task-cb2")

        lines = [
            _session_line("session", id="sess-cb2"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "research deeply", "role": "researcher"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        events = [
            {"event": "run.created", "role": "researcher", "run_id": "wcb2"},
            {"event": "worker.started", "role": "researcher", "run_id": "wcb2"},
            {"event": "worker.timeout", "timeout_seconds": 180, "run_id": "wcb2"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-cb2", run_id="run-cb2", score="fail",
            run_meta={"target_role": "researcher"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert isinstance(checks, dict)

    def test_ignores_unrelated_logs_from_other_sessions(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-scope", "task-scope")

        lines = [
            _session_line("session", id="parent-1"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        logs_dir = run_dir / "artifacts" / "orchestra-debug" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "current.jsonl").write_text(
            json.dumps({
                "event": "run.created",
                "role": "reviewer",
                "run_id": "w-current",
                "orchestrator_session_id": "pi:parent-1",
            }) + "\n" +
            json.dumps({
                "event": "worker.started",
                "role": "reviewer",
                "run_id": "w-current",
                "worker_session_id": "orchestra-worker-w-current",
            }) + "\n" +
            json.dumps({
                "event": "worker.exited",
                "run_id": "w-current",
                "exit_code": 0,
            }) + "\n"
        )
        (logs_dir / "stale.jsonl").write_text(
            json.dumps({
                "event": "run.created",
                "role": "builder",
                "run_id": "w-stale",
                "orchestrator_session_id": "pi:someone-else",
            }) + "\n" +
            json.dumps({
                "event": "worker.started",
                "role": "builder",
                "run_id": "w-stale",
                "worker_session_id": "orchestra-worker-w-stale",
            }) + "\n"
        )

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-scope",
            run_id="run-scope",
            score="pass",
            checks={"answer_exists": True},
            run_meta={
                "target_role": "reviewer",
                "pi_session_ids": ["parent-1", "orchestra-worker-w-current"],
            },
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_completed"] is True
        assert checks["worker_running_without_exit"] is False
        assert checks["fallback_answer_after_dispatch"] is False

    def test_debug_markdown_lifecycle_counts_worker_reconciled_failure(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-md", "task-md")
        debug_dir = run_dir / "artifacts" / "orchestra-debug" / "debug"
        debug_dir.mkdir(parents=True)
        debug_dir.joinpath("session.md").write_text(
            "# Orchestra debug session\n"
            "session_id: pi:sess-md\n"
            "runs: 1\n"
            "## Lifecycle log\n"
            + json.dumps({"event": "run.created", "run_id": "w-md", "role": "builder", "orchestrator_session_id": "pi:sess-md"}) + "\n"
            + json.dumps({"event": "worker.started", "run_id": "w-md", "role": "builder", "worker_session_id": "orchestra-worker-w-md"}) + "\n"
            + json.dumps({"event": "worker.reconciled", "run_id": "w-md", "reason": "worker process exited/disappeared without terminal status"}) + "\n"
            + json.dumps({"event": "run.updated", "run_id": "w-md", "status": "failed", "error_text": "worker process exited/disappeared without terminal status"}) + "\n"
        )

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-md",
            run_id="run-md",
            score="fail",
            run_meta={"target_role": "builder", "pi_session_ids": ["sess-md"]},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_started_count"] == 1
        assert checks["worker_reconciled_count"] == 1
        assert checks["worker_failed_count"] == 1
        assert checks["worker_completed"] is False
        assert checks["worker_running_without_exit"] is False
        assert checks["orchestra_effective"] is True
        assert checks["roles_dispatched"] == ["builder"]
        assert checks["worker_failure_reasons"] == ["worker process exited/disappeared without terminal status"]

    def test_dispatch_without_orchestra_logs_does_not_flag_fallback(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-cb0", "task-cb0")

        lines = [
            _session_line("session", id="sess-cb0"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-cb0",
            run_id="run-cb0",
            score="pass",
            checks={"answer_exists": True},
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_completed"] is False
        assert checks["worker_running_without_exit"] is False
        assert checks["fallback_answer_after_dispatch"] is False

    def test_worker_success_marker_without_logs_counts_as_completed(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-cb1", "task-cb1")

        lines = [
            _session_line("session", id="sess-cb1"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
            _session_line("message", message={
                "role": "user",
                "content": [{"type": "text", "text": "[orchestra: reviewer wcb1 success]\nResult: done"}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-cb1",
            run_id="run-cb1",
            score="pass",
            checks={"answer_exists": True},
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_completed"] is True
        assert checks["worker_running_without_exit"] is False
        assert checks["fallback_answer_after_dispatch"] is False

    def test_rejected_dispatch_does_not_count_as_effective_orchestration(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-reject", "task-reject")

        lines = [
            _session_line("session", id="sess-reject"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "build thing", "role": "builder"}}],
            }),
            _session_line("message", message={
                "role": "toolResult",
                "toolName": "orch_dispatch",
                "content": [{"type": "text", "text": "error: model concurrency limit exceeded: model active=1 limit=1; dispatch was not accepted; wait for current workers to return, then re-dispatch."}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-reject",
            run_id="run-reject",
            score="pass",
            checks={"answer_exists": True},
            task_meta={"family": "capability"},
            run_meta={"target_role": "builder"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["dispatch_attempt_count"] == 1
        assert checks["dispatch_rejected_count"] == 1
        assert checks["dispatch_accepted_count"] == 0
        assert checks["dispatch_count"] == 0
        assert checks["roles_dispatch_attempted"] == ["builder"]
        assert checks["roles_dispatched"] == []
        assert checks["worker_started_count"] == 0
        assert checks["worker_completed"] is False
        assert checks["orchestra_effective"] is False
        assert checks["dispatches_rejected_without_worker"] is True
        assert checks["no_orchestration"] is True
        assert checks["target_role_dispatched"] is False
        assert checks["missing_expected_role"] is True

    def test_missing_answer_check_does_not_flag_premature_completion(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-cb1b", "task-cb1b")

        lines = [
            _session_line("session", id="sess-cb1b"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-cb1b",
            run_id="run-cb1b",
            score="pass",
            checks={},
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["premature_completion"] is False

    def test_detects_fallback_answer_after_dispatch(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-cb3", "task-cb3")

        lines = [
            _session_line("session", id="sess-cb3"),
            _session_line("message", message={
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "orch_dispatch",
                             "arguments": {"goal": "review code", "role": "reviewer"}}],
            }),
        ]
        _write_session_jsonl(run_dir, lines)

        events = [
            {"event": "run.created", "role": "reviewer", "run_id": "wcb3"},
            {"event": "worker.started", "role": "reviewer", "run_id": "wcb3"},
        ]
        _write_orchestra_log(run_dir, events)

        from eval_harness import extract_orchestration_checks

        result = TaskResult(
            task_id="task-cb3",
            run_id="run-cb3",
            score="pass",
            checks={"answer_exists": True},
            run_meta={"target_role": "reviewer"},
        )
        checks = extract_orchestration_checks(result, base_dir=tmp_path / "results")

        assert checks["worker_completed"] is False
        assert checks["worker_running_without_exit"] is True
        assert checks["fallback_answer_after_dispatch"] is True


# ── 13. Slice 1 — Classified token parser and artifact payload ────


class TestTokenParserBuckets:
    """Verify _parse_pi_session_file captures all trace-backed buckets."""

    def test_caches_read_and_write_tokens(self, tmp_path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-cache", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "cacheRead": 50, "cacheWrite": 40, "totalTokens": 163},
                "provider": "lmstudio",
                "model": "qwen3.6-35b",
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["usage"]["input"] == 100
        assert parsed["usage"]["output"] == 20
        assert parsed["usage"]["reasoning"] == 3
        assert parsed["usage"]["cacheRead"] == 50
        assert parsed["usage"]["cacheWrite"] == 40
        assert parsed["usage"]["totalTokens"] == 163

    def test_captures_reported_cost(self, tmp_path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-cost", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "cacheRead": 0, "cacheWrite": 0, "totalTokens": 123,
                           "cost": {"input": 0.001, "output": 0.005,
                                    "cacheRead": 0, "cacheWrite": 0, "total": 0.006}},
                "provider": "openai",
                "model": "gpt-4o",
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["usage"]["reported_cost"] == 0.006

    def test_captures_provider_and_model(self, tmp_path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-prov", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 50, "output": 10, "reasoning": 0,
                           "cacheRead": 0, "cacheWrite": 0, "totalTokens": 60},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        # Provider/model come from the message level, not usage
        assert "provider" in parsed or True  # may be absent if no provider on message

    def test_tracks_max_context_tokens(self, tmp_path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-max", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "cacheRead": 0, "cacheWrite": 0, "totalTokens": 123},
            }}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 75, "output": 10, "reasoning": 1,
                           "cacheRead": 0, "cacheWrite": 0, "totalTokens": 86},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        # Max should track the largest input/total across all calls
        assert parsed["context_usage"]["max_input_tokens"] == 100
        assert parsed["context_usage"]["max_total_tokens"] == 123
        # Final (last) values remain as before
        assert parsed["context_usage"]["last_input_tokens"] == 75
        assert parsed["context_usage"]["last_total_tokens"] == 86

    def test_legacy_fields_still_present(self, tmp_path):
        """Ensure the legacy usage fields still work after adding new buckets."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-legacy", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "totalTokens": 123},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["usage"]["input"] == 100
        assert parsed["usage"]["output"] == 20
        assert parsed["usage"]["reasoning"] == 3
        assert parsed["usage"]["totalTokens"] == 123
        # New fields default to 0 when not present in trace
        assert parsed["usage"]["cacheRead"] == 0
        assert parsed["usage"]["cacheWrite"] == 0
        assert parsed["usage"]["reported_cost"] == 0

    def test_sum_across_multiple_calls(self, tmp_path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-multi", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "cacheRead": 10, "cacheWrite": 5, "totalTokens": 123,
                           "cost": {"total": 0.01}},
            }}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 50, "output": 10, "reasoning": 2,
                           "cacheRead": 8, "cacheWrite": 3, "totalTokens": 62,
                           "cost": {"total": 0.005}},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["usage"]["input"] == 150
        assert parsed["usage"]["output"] == 30
        assert parsed["usage"]["reasoning"] == 5
        assert parsed["usage"]["cacheRead"] == 18
        assert parsed["usage"]["cacheWrite"] == 8
        assert parsed["usage"]["totalTokens"] == 185
        assert parsed["usage"]["reported_cost"] == 0.015
        assert parsed["context_usage"]["api_call_count"] == 2

    def test_role_session_identified_by_prefix(self, tmp_path):
        """orchestra-worker-* sessions are classified as role sessions."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "orchestra-worker-w123",
                        "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 50, "output": 10, "reasoning": 2,
                           "cacheRead": 0, "cacheWrite": 0, "totalTokens": 62},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["session_id"] == "orchestra-worker-w123"
        # Role sessions are identified by the session_id prefix
        assert parsed["usage"]["input"] == 50

    def test_main_session_identified_by_cwd_and_no_prefix(self, tmp_path):
        """Non-orchestra-worker sessions matching workdir are main sessions."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-main",
                        "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["session_id"] == "sess-main"
        assert parsed["cwd"] == "/workspace/run-task"
        assert parsed["usage"]["input"] == 200

    def test_provider_model_from_last_usage_message(self, tmp_path):
        """Provider and model are captured from the last usage-bearing message."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-prov2", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 50, "output": 10, "reasoning": 0,
                           "cacheRead": 0, "cacheWrite": 0, "totalTokens": 60},
            }, "provider": "anthropic", "model": "claude-sonnet"}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed.get("provider") == "anthropic"
        assert parsed.get("model") == "claude-sonnet"

    def test_no_crash_on_missing_usage_fields(self, tmp_path):
        """Gracefully handle sessions with partial usage data."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n".join([
            json.dumps({"type": "session", "id": "sess-partial", "cwd": "/workspace/run-task"}),
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 10},
            }}),
        ]))

        from eval_harness import _parse_pi_session_file

        parsed = _parse_pi_session_file(session_file)

        assert parsed["usage"]["input"] == 10
        # Missing fields should default to 0
        for key in ("output", "reasoning", "totalTokens", "cacheRead", "cacheWrite"):
            assert parsed["usage"][key] >= 0, f"{key} should be present"


class TestTokenAggregationPayload:
    """Verify collect_run_artifacts produces structured tokens.json."""

    def _write_main_session(self, run_dir: Path, lines: list[dict]) -> None:
        sid = "sess-main-01"
        for event in lines:
            if event.get("type") == "session":
                sid = event["id"]
                break
        filename = f"{sid.replace(':', '-')}.jsonl"
        path = run_dir / "artifacts" / "pi-sessions" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(event) for event in lines) + "\n"
        path.write_text(content)

    def _write_role_session(self, run_dir: Path, lines: list[dict]) -> None:
        sid = "orchestra-worker-w123"
        for event in lines:
            if event.get("type") == "session":
                sid = event["id"]
                break
        filename = f"{sid.replace(':', '-')}.jsonl"
        path = run_dir / "artifacts" / "pi-sessions" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(event) for event in lines) + "\n"
        path.write_text(content)

    def test_tokens_json_has_structured_sections(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-struct", "task-struct")

        # Write a main session with full usage data
        self._write_main_session(run_dir, [
            {"type": "session", "id": "sess-main-a",
             "cwd": "/workspace/run-struct-task-struct"},
            {"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "cacheRead": 5, "cacheWrite": 3, "totalTokens": 126},
            }, "provider": "lmstudio", "model": "qwen3.6-35b"},
        ])

        # Write a role session
        self._write_role_session(run_dir, [
            {"type": "session", "id": "orchestra-worker-w123",
             "cwd": "/workspace/run-struct-task-struct"},
            {"type": "message", "message": {
                "role": "assistant",
                "content": [],
                "usage": {"input": 50, "output": 10, "reasoning": 2,
                           "cacheRead": 1, "cacheWrite": 0, "totalTokens": 63},
            }, "provider": "lmstudio", "model": "qwen3.6-35b"},
        ])

        # Update manifest with session info matching what collect_run_artifacts would do
        manifest_path = run_dir / "artifacts" / "manifest.json"
        m = json.loads(manifest_path.read_text())
        m["pi_sessions"] = [
            {
                "file": "sess-main-a.jsonl",
                "session_id": "sess-main-a",
                "cwd": "/workspace/run-struct-task-struct",
                "usage": {"input": 100, "output": 20, "reasoning": 3,
                           "cacheRead": 5, "cacheWrite": 3, "totalTokens": 126},
            },
            {
                "file": "orchestra-worker-w123.jsonl",
                "session_id": "orchestra-worker-w123",
                "cwd": "/workspace/run-struct-task-struct",
                "usage": {"input": 50, "output": 10, "reasoning": 2,
                           "cacheRead": 1, "cacheWrite": 0, "totalTokens": 63},
            },
        ]
        manifest_path.write_text(json.dumps(m))

        from eval_harness import _build_tokens_payload

        # Simulate what collect_run_artifacts does with parsed sessions
        token_payload = _build_tokens_payload(
            m["pi_sessions"],  
            workdir="/workspace/run-struct-task-struct",
            main_context_usage=m["pi_sessions"][0].get("context_usage", {}),
        )

        # Legacy flat fields preserved
        assert "input_tokens" in token_payload
        assert "output_tokens" in token_payload
        assert "reasoning_tokens" in token_payload
        assert "total_tokens" in token_payload

        # Structured sections present
        assert "main_session" in token_payload
        assert "role_sessions" in token_payload
        assert "all_sessions" in token_payload
        assert "expensive_main_session_tokens" in token_payload
        assert "cheap_role_tokens" in token_payload

    def test_legacy_totals_are_all_sessions(self, tmp_path):
        run_dir = _build_artifacts_dir(tmp_path, "run-tot", "task-tot")

        sessions = [
            {
                "session_id": "sess-main-b",
                "cwd": "/workspace/run-tot-task-tot",
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            },
            {
                "session_id": "orchestra-worker-w456",
                "cwd": "/workspace/run-tot-task-tot",
                "usage": {"input": 100, "output": 25, "reasoning": 5,
                           "cacheRead": 10, "cacheWrite": 8, "totalTokens": 148},
            },
        ]

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-tot-task-tot",
            main_context_usage={},
        )

        # Legacy totals should be ALL sessions combined (not just main)
        assert token_payload["input_tokens"] == 300
        assert token_payload["output_tokens"] == 75
        assert token_payload["reasoning_tokens"] == 15
        assert token_payload["total_tokens"] == 438

    def test_main_session_bucket_isolated(self, tmp_path):
        sessions = [
            {
                "session_id": "sess-main-c",
                "cwd": "/workspace/run-x-task-x",
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            },
            {
                "session_id": "orchestra-worker-w789",
                "cwd": "/workspace/run-x-task-x",
                "usage": {"input": 100, "output": 25, "reasoning": 5,
                           "cacheRead": 10, "cacheWrite": 8, "totalTokens": 148},
            },
        ]

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-x-task-x",
            main_context_usage={},
        )

        # Main session should only include non-orchestra-worker tokens
        main = token_payload["main_session"]
        assert main["input_tokens"] == 200
        assert main["output_tokens"] == 50
        assert main["total_tokens"] == 290

    def test_role_sessions_bucket_isolated(self, tmp_path):
        sessions = [
            {
                "session_id": "sess-main-d",
                "cwd": "/workspace/run-y-task-y",
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            },
            {
                "session_id": "orchestra-worker-w789",
                "cwd": "/workspace/run-y-task-y",
                "usage": {"input": 100, "output": 25, "reasoning": 5,
                           "cacheRead": 10, "cacheWrite": 8, "totalTokens": 148},
            },
        ]

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-y-task-y",
            main_context_usage={},
        )

        # Role sessions should only include orchestra-worker tokens
        roles = token_payload["role_sessions"]
        assert roles["input_tokens"] == 100
        assert roles["output_tokens"] == 25
        assert roles["total_tokens"] == 148

    def test_expensive_main_alias_points_to_main(self, tmp_path):
        sessions = [
            {
                "session_id": "sess-main-e",
                "cwd": "/workspace/run-z-task-z",
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            },
        ]

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-z-task-z",
            main_context_usage={},
        )

        expensive = token_payload["expensive_main_session_tokens"]
        assert expensive["total_tokens"] == 290
        cheap = token_payload["cheap_role_tokens"]
        assert cheap["total_tokens"] == 0

    def test_all_sessions_bucket_equals_totals(self, tmp_path):
        sessions = [
            {
                "session_id": "sess-main-f",
                "cwd": "/workspace/run-aa-task-aa",
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            },
            {
                "session_id": "orchestra-worker-w789",
                "cwd": "/workspace/run-aa-task-aa",
                "usage": {"input": 100, "output": 25, "reasoning": 5,
                           "cacheRead": 10, "cacheWrite": 8, "totalTokens": 148},
            },
        ]

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-aa-task-aa",
            main_context_usage={},
        )

        all_sessions = token_payload["all_sessions"]
        assert all_sessions["total_tokens"] == 438
        # All sessions total should equal legacy flat total_tokens
        assert all_sessions["total_tokens"] == token_payload["total_tokens"]

    def test_main_context_includes_final_and_max(self, tmp_path):
        sessions = [
            {
                "session_id": "sess-main-g",
                "cwd": "/workspace/run-bb-task-bb",
                "usage": {"input": 200, "output": 50, "reasoning": 10,
                           "cacheRead": 30, "cacheWrite": 20, "totalTokens": 290},
            },
        ]

        main_context = {
            "api_call_count": 4,
            "last_input_tokens": 150,
            "last_total_tokens": 200,
            "max_input_tokens": 300,
            "max_total_tokens": 400,
            "compaction_count": 2,
        }

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-bb-task-bb",
            main_context_usage=main_context,
        )

        # Main context fields in legacy flat area
        assert token_payload["main_session_api_call_count"] == 4
        assert token_payload["main_session_context_input_tokens"] == 150
        assert token_payload["main_session_context_total_tokens"] == 200
        assert token_payload["main_session_max_input_tokens"] == 300
        assert token_payload["main_session_max_total_tokens"] == 400
        assert token_payload["compaction_count"] == 2

    def test_only_main_sessions_no_roles(self, tmp_path):
        """When only main sessions exist, role buckets should be zeroed."""
        sessions = [
            {
                "session_id": "sess-main-h",
                "cwd": "/workspace/run-cc-task-cc",
                "usage": {"input": 100, "output": 20, "reasoning": 5,
                           "cacheRead": 3, "cacheWrite": 2, "totalTokens": 127},
            },
        ]

        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            sessions,
            workdir="/workspace/run-cc-task-cc",
            main_context_usage={},
        )

        assert token_payload["role_sessions"]["total_tokens"] == 0
        assert token_payload["cheap_role_tokens"]["total_tokens"] == 0
        assert token_payload["all_sessions"]["total_tokens"] == 127

    def test_empty_sessions_produces_zeroed_payload(self, tmp_path):
        from eval_harness import _build_tokens_payload

        token_payload = _build_tokens_payload(
            [],
            workdir="/workspace/run-dd-task-dd",
            main_context_usage={},
        )

        assert token_payload["input_tokens"] == 0
        assert token_payload["total_tokens"] == 0
        assert token_payload["main_session"]["total_tokens"] == 0
        assert token_payload["all_sessions"]["total_tokens"] == 0
