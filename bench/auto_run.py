"""Pi RPC-backed benchmark auto runner.

Replaces one-shot `pi -p` for --auto runs: the parent Pi process stays under
benchmark control, and grading is allowed to proceed only after Pi has settled
AND (when Orchestra was used) no active Orchestra runs remain for the session.

Prompt text is read from stdin so the bash wrapper keeps prompt selection.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from bench.pi_rpc_runner import PiRpcRunner
from bench.orchestration_gate import docker_status_query, wait_for_settled as gate_wait_for_settled

ORCH_ON_TIMEOUT = 300.0        # /orch on preflight should be quick
PI_SETTLE_TIMEOUT = 4 * 3600.0  # generous for local-model capability tasks
GATE_TIMEOUT = 3 * 3600.0      # workers must finish before we grade


def build_pi_rpc_command(container: str, workdir: str, model: str) -> list[str]:
    model_arg = f" --model {model}" if model else ""
    return [
        "docker", "exec", "-i", container,
        "sh", "-c", f"cd {workdir} && exec pi --mode rpc{model_arg}",
    ]


def _fetch_orchestrator_skill(container: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", "-i", container, "orchestra", "_orchestrator-skill"],
        capture_output=True, text=True,
    )
    return (proc.stdout or "").strip()


def _events_contain(events: list[dict], needle: str) -> bool:
    return any(needle in json.dumps(e, default=str) for e in events)


def run_auto(
    args: argparse.Namespace,
    prompt_text: str,
    command_override: list[str] | None = None,
    skill_fetcher=None,
    gate=None,  # callable(session_id) -> "settled"|"timeout"; injectable for tests
) -> int:
    events_path = Path(args.events_path) if args.events_path else None
    runner = PiRpcRunner(
        command_override or build_pi_rpc_command(args.container, args.workdir, args.model),
        workdir=None,  # cd happens inside the container command
        event_log_path=events_path,
    )

    pi_exit: int | None = None
    session_id = ""
    orch_on_ok = True
    gate_result = "skipped"
    try:
        runner.start()

        if args.orch_on:
            runner.send({"type": "prompt", "message": "/orch on"})
            settled = runner.wait_for_settled(timeout=ORCH_ON_TIMEOUT)
            orch_on_ok = settled and _events_contain(runner.events, "Orchestra orchestrator skill refreshed")
            if not orch_on_ok:
                print("[bench] /orch on preflight failed", file=sys.stderr)
                return 1

        prompt_text = prompt_text.strip()
        if args.orch_on:
            fetch = skill_fetcher or (lambda: _fetch_orchestrator_skill(args.container))
            skill = fetch()
            if skill:
                prompt_text = f"{skill}\n\n---\n\n{prompt_text}"

        runner.send({"type": "prompt", "message": prompt_text})
        settled = runner.wait_for_settled(timeout=PI_SETTLE_TIMEOUT)
        if not settled:
            print("[bench] warning: Pi did not report agent_settled before timeout; proceeding to grade", file=sys.stderr)

        # Capture the parent session id for status queries and artifacts.
        runner.send({"type": "get_state"})
        while True:
            event = runner.read_line(timeout=10.0)
            if event is None or (event.get("type") == "response" and event.get("command") == "get_state"):
                break
        data = (event or {}).get("data") or {}
        session_id = str(data.get("sessionId") or "")

        if args.orch_on and session_id:
            default_gate = lambda sid: (
                "settled" if gate_wait_for_settled(
                    docker_status_query(args.container, sid),
                    timeout=GATE_TIMEOUT, poll_interval=10.0,
                ) else "timeout"
            )
            gate_result = (gate or default_gate)(session_id)
            print(f"[bench] orchestra gate: {gate_result} (session={session_id})", file=sys.stderr)

        pi_exit = runner.stop() or 0
    finally:
        if runner.running:
            runner.stop()

    summary = {"pi_exit": pi_exit, "orch_on_ok": orch_on_ok, "session_id": session_id, "gate_result": gate_result}
    if args.summary_out:
        out = Path(args.summary_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    return int(pi_exit or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pi RPC-backed benchmark auto runner")
    parser.add_argument("--container", required=True)
    parser.add_argument("--workdir", required=True, help="in-container task workdir")
    parser.add_argument("--model", default="", help="pi --model value; empty uses Pi default")
    parser.add_argument("--orch-on", action="store_true", help="run /orch on preflight first")
    parser.add_argument("--events-path", default="", help="JSONL artifact for RPC events (host path)")
    parser.add_argument("--summary-out", default="", help="write JSON summary to this host path")
    args = parser.parse_args(argv)

    prompt_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not prompt_text.strip():
        print("[bench] no prompt text on stdin", file=sys.stderr)
        return 2
    return run_auto(args, prompt_text)


if __name__ == "__main__":
    raise SystemExit(main())
