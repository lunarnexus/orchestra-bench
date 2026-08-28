"""Tests for bench.pi_rpc_runner using a fake pi RPC process."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from bench.pi_rpc_runner import PiRpcRunner  # noqa: E402


def _write_fake_pi(tmp_path: Path, hang_after_settle: bool) -> Path:
    script = tmp_path / "fake_pi.py"
    settle_line = '{"type": "agent_settled"}'
    tail = (
        'import time\nwhile True:\n    time.sleep(0.2)\n' if hang_after_settle else ''
    )
    script.write_text(
        f"""
import json, sys
for line in sys.stdin:
    cmd = json.loads(line)
    if cmd.get("type") == "prompt":
        print(json.dumps({{"type": "response", "command": "prompt", "success": True}}), flush=True)
        print(json.dumps({{"type": "agent_start"}}), flush=True)
        print(json.dumps({{"type": "turn_end", "message": {{"role": "assistant"}}}}), flush=True)
        print(json.dumps({{"type": "agent_end", "willRetry": False}}), flush=True)
        print('{settle_line}', flush=True)
{tail}"""
    )
    return script


def test_settles_and_logs_events(tmp_path):
    fake = _write_fake_pi(tmp_path, hang_after_settle=False)
    log = tmp_path / "events.jsonl"
    runner = PiRpcRunner([sys.executable, str(fake)], event_log_path=log)
    try:
        runner.start()
        runner.send({"type": "prompt", "message": "hello"})
        assert runner.wait_for_settled(timeout=10) is True
        types = [e.get("type") for e in runner.events]
        assert "response" in types and "agent_settled" in types
        logged = [json.loads(line) for line in log.read_text().splitlines()]
        assert any(e.get("type") == "agent_settled" for e in logged)
    finally:
        runner.stop()


def test_timeout_when_never_settles(tmp_path):
    fake = tmp_path / "silent_pi.py"
    fake.write_text("import time\ntime.sleep(30)\n")
    runner = PiRpcRunner([sys.executable, str(fake)])
    try:
        runner.start()
        assert runner.wait_for_settled(timeout=1.0) is False
    finally:
        code = runner.stop(grace_seconds=2)
    assert code != 0  # killed


def test_stop_returns_exit_code(tmp_path):
    fake = tmp_path / "quick_pi.py"
    fake.write_text("import sys\nsys.exit(3)\n")
    runner = PiRpcRunner([sys.executable, str(fake)])
    runner.start()
    assert runner.stop() == 3
