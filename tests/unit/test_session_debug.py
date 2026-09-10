from __future__ import annotations

import json
from pathlib import Path

from bench.reporting.session_debug import discover_session_transcripts, format_session_debug, format_session_raw


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_harness_fallback_artifacts(run_dir: Path) -> tuple[Path, Path]:
    harness_dir = run_dir / "artifacts" / "harness"
    events_path = harness_dir / "events.jsonl"
    transcript_path = harness_dir / "transcript.txt"
    _write_jsonl(
        events_path,
        [
            {"type": "session", "id": "harness-session", "cwd": "/workspace/run"},
            {"type": "custom", "customType": "orchestra-command", "data": {"text": "enable orchestra tools"}},
            {"type": "custom", "customType": "orch_dispatch", "data": {"text": "dispatch builder"}},
            {"type": "custom", "customType": "orch_status", "data": {"text": "children active"}},
            {"type": "custom", "customType": "orch_return", "data": {"text": "child returned"}},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Read PRD.md"}]}},
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Working"},
                        {"type": "toolCall", "name": "read", "arguments": {"path": "PRD.md"}},
                        {"type": "text", "text": "Done"},
                    ],
                },
            },
            {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "tool raw output"}]}},
            {"type": "tool_execution_start", "tool": "read", "path": "PRD.md"},
            {"type": "tool_execution_end", "tool": "read", "result": "ok"},
        ],
    )
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        "prompt: enable orchestra tools\n"
        '{"message": "enable orchestra tools", "type": "prompt"}\n'
        "prompt: # Run Prompt\n"
        "Read `PRD.md`, inspect the fixture, implement the requested behavior, and leave the workspace in a runnable state.\n"
        "Dispatch and proceed until finished.\n",
        encoding="utf-8",
    )
    return events_path, transcript_path


def test_discover_session_transcripts_classifies_main_and_workers_in_filename_order(tmp_path: Path) -> None:
    session_dir = tmp_path / "artifacts" / "pi-sessions"
    _write_jsonl(
        session_dir / "2026-08-30T03-58-59-347Z_main.jsonl",
        [{"type": "session", "id": "main-session", "cwd": "/workspace/run"}],
    )
    _write_jsonl(
        session_dir / "2026-08-30T03-59-47-784Z_worker-id.jsonl",
        [{"type": "session", "id": "orchestra-worker-abc", "cwd": "/workspace/run"}],
    )
    _write_jsonl(
        session_dir / "2026-08-30T04-01-33-806Z_orchestra-worker-file.jsonl",
        [{"type": "session", "id": "plain-session", "cwd": "/workspace/run"}],
    )

    full = discover_session_transcripts(session_dir, view="full")
    orch = discover_session_transcripts(session_dir, view="orch")

    assert [transcript.path.name for transcript in full] == [
        "2026-08-30T03-58-59-347Z_main.jsonl",
        "2026-08-30T03-59-47-784Z_worker-id.jsonl",
        "2026-08-30T04-01-33-806Z_orchestra-worker-file.jsonl",
    ]
    assert [transcript.kind for transcript in full] == ["main", "worker", "worker"]
    assert [transcript.session_id for transcript in full] == ["main-session", "orchestra-worker-abc", "plain-session"]
    assert [transcript.path.name for transcript in orch] == ["2026-08-30T03-58-59-347Z_main.jsonl"]


def test_discover_session_transcripts_falls_back_to_harness_artifacts_when_pi_sessions_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "results" / "20260902T225856-smoke-dependent-setup-chain"
    session_dir = run_dir / "artifacts" / "pi-sessions"
    events_path, transcript_path = _write_harness_fallback_artifacts(run_dir)

    full = discover_session_transcripts(session_dir, view="full")
    orch = discover_session_transcripts(session_dir, view="orch")

    assert [transcript.path for transcript in full] == [events_path, transcript_path]
    assert [transcript.kind for transcript in full] == ["parent", "harness"]
    assert [transcript.path for transcript in orch] == [events_path]


def test_format_session_debug_hides_tools_and_keeps_textual_events(tmp_path: Path) -> None:
    session_dir = tmp_path / "artifacts" / "pi-sessions"
    _write_jsonl(
        session_dir / "2026-08-30T03-58-59-347Z_main.jsonl",
        [
            {"type": "session", "id": "main-session", "cwd": "/workspace/run"},
            {"type": "model_change", "provider": "lmstudio", "modelId": "qwen/qwen3.8-27b"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Read PRD.md"}]}},
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Working"},
                        {"type": "toolCall", "name": "read", "arguments": {"path": "PRD.md"}},
                        {"type": "text", "text": "Done"},
                    ],
                },
            },
            {"type": "custom", "customType": "orchestra-output", "data": {"text": "orchestra status: active"}},
            {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "tool raw output"}]}},
        ],
    )
    _write_jsonl(
        session_dir / "2026-08-30T03-59-47-784Z_orchestra-worker-0adf.jsonl",
        [
            {"type": "session", "id": "orchestra-worker-0adf", "cwd": "/workspace/run"},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "worker text"}]}},
        ],
    )

    full = format_session_debug(session_dir, view="full", no_tools=True, no_color=True)
    orch = format_session_debug(session_dir, view="orch", no_tools=True, no_color=True)

    assert "=== session transcripts (full) ===" in full
    assert "╭─ session main" in full
    assert "Read PRD.md" in full
    assert "Working" in full
    assert "Done" in full
    assert "orchestra status: active" in full
    assert "tool-call" not in full
    assert "tool-result" not in full
    assert "worker text" in full

    assert "=== session transcripts (orch) ===" in orch
    assert "worker text" not in orch
    assert "Read PRD.md" in orch


def test_format_session_debug_uses_harness_fallback_for_orch_and_full_views(tmp_path: Path) -> None:
    run_dir = tmp_path / "results" / "20260902T225856-smoke-dependent-setup-chain"
    session_dir = run_dir / "artifacts" / "pi-sessions"
    _write_harness_fallback_artifacts(run_dir)

    full = format_session_debug(session_dir, view="full", no_tools=False, no_color=True)
    orch = format_session_debug(session_dir, view="orch", no_tools=True, no_color=True)

    assert "no session transcripts found" not in full
    assert "no session transcripts found" not in orch
    assert "╭─ session parent" in full
    assert "╭─ session harness" in full
    assert "enable orchestra tools" in full
    assert "orch_dispatch" in full
    assert "orch_status" in full
    assert "Read PRD.md" in full
    assert "tool-call" in full
    assert "toolResult" in full
    assert "worker text" not in full

    assert "╭─ session harness" not in orch
    assert "enable orchestra tools" in orch
    assert "orch_dispatch" in orch
    assert "orch_status" in orch
    assert "Read PRD.md" in orch


def test_format_session_raw_emits_jsonl_text_verbatim(tmp_path: Path) -> None:
    session_dir = tmp_path / "artifacts" / "pi-sessions"
    _write_jsonl(
        session_dir / "2026-08-30T03-58-59-347Z_main.jsonl",
        [
            {"type": "session", "id": "main-session", "cwd": "/workspace/run"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Read PRD.md"}]}},
        ],
    )

    raw = format_session_raw(session_dir)

    assert raw.startswith("=== session transcripts (raw) ===\n")
    assert "path: " in raw
    assert "2026-08-30T03-58-59-347Z_main.jsonl" in raw
    assert '"type": "session"' in raw
    assert '"text": "Read PRD.md"' in raw
    assert "╭─" not in raw


def test_format_session_raw_falls_back_to_harness_artifacts_when_pi_sessions_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "results" / "20260902T225856-smoke-dependent-setup-chain"
    session_dir = run_dir / "artifacts" / "pi-sessions"
    events_path, transcript_path = _write_harness_fallback_artifacts(run_dir)

    raw = format_session_raw(session_dir)

    assert raw.startswith("=== session transcripts (raw) ===\n")
    assert f"path: {events_path}" in raw
    assert f"path: {transcript_path}" in raw
    assert '"customType": "orchestra-command"' in raw
    assert "prompt: enable orchestra tools" in raw
    assert '"type": "get_state"' not in raw
