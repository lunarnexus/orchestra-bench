"""Tests for bench.auto_run using a fake pi RPC process (no docker)."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from bench.auto_run import run_auto  # noqa: E402


def _write_fake_pi(tmp_path: Path, orch_on_text: str) -> Path:
    script = tmp_path / "fake_pi.py"
    script.write_text(f"""
import json, sys
for line in sys.stdin:
    cmd = json.loads(line)
    t = cmd.get("type")
    if t == "prompt":
        print(json.dumps({{"type": "response", "command": "prompt", "success": True}}), flush=True)
        msg = {{
            "role": "assistant",
            "content": [{{"type": "text", "text": {json.dumps(orch_on_text)}}}],
        }}
        print(json.dumps({{"type": "message_end", "message": msg}}), flush=True)
        if cmd.get("message") == "/orch on":
            pass
        else:
            print(json.dumps({{"type": "agent_start"}}), flush=True)
        print(json.dumps({{"type": "agent_settled"}}), flush=True)
    elif t == "get_state":
        print(json.dumps({{
            "type": "response", "command": "get_state", "success": True,
            "data": {{"sessionId": "fake-sid-123", "isStreaming": False}},
        }}), flush=True)
""")
    return script


def _args(tmp_path: Path) -> Namespace:
    return Namespace(
        container="unused", workdir="/workspace/x", model="", orch_on=False,
        events_path=str(tmp_path / "events.jsonl"), summary_out=str(tmp_path / "summary.json"),
    )


def test_no_orchestra_run_settles_and_writes_artifacts(tmp_path):
    fake = _write_fake_pi(tmp_path, "done")
    code = run_auto(_args(tmp_path), "task prompt here", command_override=[sys.executable, str(fake)])
    assert code == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["session_id"] == "fake-sid-123"
    assert summary["gate_result"] == "skipped"
    events = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert any(e.get("type") == "agent_settled" for e in events)


def test_orch_on_preflight_failure_fails_run(tmp_path):
    fake = _write_fake_pi(tmp_path, "something else happened")
    args = _args(tmp_path)
    args.orch_on = True
    code = run_auto(args, "task prompt here", command_override=[sys.executable, str(fake)])
    assert code == 1


def test_orch_on_success_uses_injected_skill_and_gate(tmp_path):
    fake = _write_fake_pi(tmp_path, "Orchestra orchestrator skill refreshed")

    args = _args(tmp_path)
    args.orch_on = True
    code = run_auto(
        args, "task prompt here",
        command_override=[sys.executable, str(fake)],
        skill_fetcher=lambda: "SKILL-TEXT",
        gate=lambda sid: "settled" if sid == "fake-sid-123" else "timeout",
    )
    assert code == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["orch_on_ok"] is True
    assert summary["gate_result"] == "settled"
