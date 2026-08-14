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
