"""Pi RPC-backed benchmark auto runner.

Replaces one-shot `pi -p` for --auto runs: the parent Pi process stays under
benchmark control, and grading is allowed to proceed only after Pi has settled
AND (when Orchestra was used) no active Orchestra runs remain for the session.

Prompt text is read from stdin so the bash wrapper keeps prompt selection.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from bench.pi_rpc_runner import PiRpcRunner

ORCH_ON_TIMEOUT = 300.0        # /orch on preflight should be quick
PI_SETTLE_TIMEOUT = 4 * 3600.0  # generous for local-model capability tasks
STATUS_SETTLE_TIMEOUT = 300.0
HUMAN_CONTROL_TIMEOUT = 4 * 3600.0
HUMAN_STATUS_INTERVAL = 30.0


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


class SessionDebugRenderer:
    """Render Pi RPC events as a readable parent-session transcript."""

    def __init__(self) -> None:
        self._open_stream = False

    def sent_prompt(self, message: str) -> None:
        self._newline()
        print(f"\n>>> {message}\n", file=sys.stderr, flush=True)

    def event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "message_update":
            delta = ((event.get("assistantMessageEvent") or {}).get("delta") or "")
            if delta:
                print(delta, end="", file=sys.stderr, flush=True)
                self._open_stream = True
            return
        if event_type == "message_end":
            text = _message_text(event.get("message") or {})
            if text and not self._open_stream:
                self._newline()
                print(text, file=sys.stderr, flush=True)
            self._newline()
            return
        if event_type == "tool_execution_start":
            self._newline()
            print(f"\n[tool:start] {event.get('toolName') or event.get('name') or ''}", file=sys.stderr, flush=True)
            return
        if event_type == "tool_execution_end":
            self._newline()
            result = event.get("result") or event.get("content") or ""
            print(f"\n[tool:end] {event.get('toolName') or event.get('name') or ''}", file=sys.stderr, flush=True)
            if result:
                print(str(result), file=sys.stderr, flush=True)
            return
        if event_type == "entry_appended":
            entry = event.get("entry") or {}
            data = entry.get("data") or {}
            text = str(data.get("text") or "")
            custom_type = entry.get("customType") or entry.get("type") or "entry"
            if text:
                self._newline()
                print(f"\n[{custom_type}]\n{text}", file=sys.stderr, flush=True)
            return
        if event_type in {"agent_start", "agent_end", "agent_settled"}:
            self._newline()
            print(f"\n[{event_type}]", file=sys.stderr, flush=True)
            return

    def _newline(self) -> None:
        if self._open_stream:
            print(file=sys.stderr, flush=True)
            self._open_stream = False


def _message_text(message: dict) -> str:
    parts: list[str] = []
    for item in message.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


def _events_contain(events: list[dict], needle: str) -> bool:
    return any(needle in json.dumps(e, default=str) for e in events)


def _assistant_text(events: list[dict], start_index: int = 0) -> str:
    parts: list[str] = []
    for event in events[start_index:]:
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        text = _message_text(message)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parent_done(text: str) -> bool:
    lowered = text.lower()
    if any(word in lowered for word in ("waiting for", "waiting on", "subagent is dispatched", "will auto-return")):
        return False
    return bool(re.search(r"\b(done|finished|complete|completed|final summary)\b", lowered))


def _orch_status_clear(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"active_runs:\s*0\b", lowered):
        return True
    if "no active" in lowered or "all clear" in lowered:
        return True
    return False


def _send_prompt_and_wait(runner: PiRpcRunner, message: str, timeout: float, debug: SessionDebugRenderer | None = None) -> tuple[bool, str]:
    start = len(runner.events)
    if debug is not None:
        debug.sent_prompt(message)
    runner.send({"type": "prompt", "message": message})
    settled = runner.wait_for_settled(timeout=timeout)
    return settled, _assistant_text(runner.events, start)


def _orch_status_text(events: list[dict], start_index: int = 0) -> str:
    parts: list[str] = []
    for event in events[start_index:]:
        entry = event.get("entry") or {}
        data = entry.get("data") or {}
        if entry.get("customType") == "orchestra-output":
            parts.append(str(data.get("text") or ""))
    return "\n".join(parts)


def _send_orch_status_and_wait(runner: PiRpcRunner, timeout: float, debug: SessionDebugRenderer | None = None) -> tuple[bool, str]:
    start = len(runner.events)
    if debug is not None:
        debug.sent_prompt("/orch status")
    runner.send({"type": "prompt", "message": "/orch status"})
    deadline = time.monotonic() + timeout
    saw_response = False
    while time.monotonic() < deadline:
        event = runner.read_line(timeout=min(1.0, max(0.0, deadline - time.monotonic())))
        if event is None:
            if not runner.running:
                break
            continue
        if event.get("type") == "response" and event.get("command") == "prompt":
            saw_response = bool(event.get("success", True))
        text = _orch_status_text(runner.events, start)
        if text:
            return True, text
        if saw_response:
            return True, ""
    return False, _orch_status_text(runner.events, start)


def _get_session_id(runner: PiRpcRunner) -> str:
    runner.send({"type": "get_state"})
    while True:
        event = runner.read_line(timeout=10.0)
        if event is None:
            return ""
        if event.get("type") == "response" and event.get("command") == "get_state":
            data = event.get("data") or {}
            return str(data.get("sessionId") or "")


def run_auto(
    args: argparse.Namespace,
    prompt_text: str,
    command_override: list[str] | None = None,
    skill_fetcher=None,
    gate=None,  # callable(session_id) -> "settled"|"timeout"; injectable for tests
) -> int:
    events_path = Path(args.events_path) if args.events_path else None
    debug_renderer = SessionDebugRenderer() if getattr(args, "debug", False) else None
    runner = PiRpcRunner(
        command_override or build_pi_rpc_command(args.container, args.workdir, args.model),
        workdir=None,  # cd happens inside the container command
        event_log_path=events_path,
        event_callback=debug_renderer.event if debug_renderer is not None else None,
    )

    pi_exit: int | None = None
    session_id = ""
    orch_on_ok = True
    gate_result = "skipped"
    gate_status: dict[str, object] = {}
    rpc_agent_settled_seen = False
    rpc_summary_written = False
    result_code = 0
    runner_error = ""
    try:
        runner.start()

        if result_code == 0:
            prompt_text = prompt_text.strip()
            if args.orch_on:
                settled, orch_text = _send_prompt_and_wait(runner, "/orch on", ORCH_ON_TIMEOUT, debug_renderer)
                rpc_agent_settled_seen = rpc_agent_settled_seen or runner.agent_settled_seen
                orch_on_ok = settled and (
                    "orchestra" in orch_text.lower()
                    or _events_contain(runner.events, "Orchestra orchestrator skill refreshed")
                )
                if not orch_on_ok:
                    print("[bench] /orch on did not complete cleanly", file=sys.stderr)
                    result_code = 1

            if result_code != 0:
                raise RuntimeError("orchestra preflight failed")

            completion_hint = (
                "\n\n## Auto-run completion instruction\n"
                "When the task is fully finished, say clearly that you are done."
            )
            settled, parent_text = _send_prompt_and_wait(
                runner,
                f"{prompt_text}{completion_hint}" if args.orch_on else prompt_text,
                PI_SETTLE_TIMEOUT,
                debug_renderer,
            )
            rpc_agent_settled_seen = rpc_agent_settled_seen or runner.agent_settled_seen
            if not settled:
                print("[bench] warning: Pi did not report agent_settled before timeout; proceeding to cleanup", file=sys.stderr)
                result_code = 1

            session_id = _get_session_id(runner)

            if args.orch_on and result_code == 0:
                deadline = time.monotonic() + HUMAN_CONTROL_TIMEOUT
                parent_is_done = _parent_done(parent_text)
                status_text = ""
                while time.monotonic() < deadline:
                    settled, status_text = _send_orch_status_and_wait(runner, STATUS_SETTLE_TIMEOUT, debug_renderer)
                    rpc_agent_settled_seen = rpc_agent_settled_seen or runner.agent_settled_seen
                    status_clear = settled and _orch_status_clear(status_text)
                    gate_result = "settled" if status_clear else "waiting"
                    gate_status = {"active_runs": 0 if status_clear else None}
                    print(
                        f"[bench] orchestra status: {gate_result} "
                        f"(parent_done={parent_is_done}, session={session_id})",
                        file=sys.stderr,
                    )
                    if parent_is_done and status_clear:
                        break
                    if not status_clear:
                        time.sleep(HUMAN_STATUS_INTERVAL)
                    if not parent_is_done:
                        # Human-style: keep the session open and give Pi a chance
                        # to continue after returned workers/status output.
                        settled, parent_text = _send_prompt_and_wait(
                            runner,
                            "Continue when ready. If the task is fully finished, say that you are done.",
                            PI_SETTLE_TIMEOUT,
                            debug_renderer,
                        )
                        parent_is_done = _parent_done(parent_text)
                        if not settled:
                            break
                else:
                    gate_result = "timeout"
                    result_code = 1

            pi_exit = runner.stop() or 0
            if result_code == 0:
                result_code = int(pi_exit or 0)
    except Exception as exc:
        runner_error = f"{type(exc).__name__}: {exc}"
        print(f"[bench] RPC auto runner error: {runner_error}", file=sys.stderr)
        result_code = 1
    finally:
        if runner.running:
            stopped_exit = runner.stop()
            if pi_exit is None:
                pi_exit = stopped_exit
        rpc_agent_settled_seen = rpc_agent_settled_seen or runner.agent_settled_seen

        summary = {
            "pi_exit": pi_exit if pi_exit is not None else result_code,
            "orch_on_ok": orch_on_ok,
            "session_id": session_id,
            "gate_result": gate_result,
            "rpc_runner_used": True,
            "rpc_agent_settled_seen": rpc_agent_settled_seen,
            "rpc_gate_result": gate_result,
            "rpc_summary_written": False,
            "rpc_event_count": len(runner.events),
            "rpc_tools_done": sum(1 for e in runner.events if e.get("type") == "tool_execution_end"),
            "rpc_agent_start_count": sum(1 for e in runner.events if e.get("type") == "agent_start"),
            "rpc_agent_end_count": sum(1 for e in runner.events if e.get("type") == "agent_end"),
            "rpc_agent_settled_count": sum(1 for e in runner.events if e.get("type") == "agent_settled"),
            "rpc_gate_active_runs": gate_status.get("active_runs"),
            "rpc_gate_descendants_terminal": gate_status.get("descendants_terminal"),
            "rpc_gate_session_report_available": gate_status.get("session_report_available"),
            "rpc_gate_session_report_delivered": gate_status.get("session_report_delivered"),
        }
        if runner_error:
            summary["rpc_error"] = runner_error
        if args.summary_out:
            out = Path(args.summary_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                out.write_text(json.dumps({**summary, "rpc_summary_written": True}, indent=2) + "\n")
            except Exception as exc:
                summary["rpc_summary_written"] = False
                print(f"[bench] warning: failed to write RPC summary to {out}: {exc}", file=sys.stderr)
            else:
                rpc_summary_written = True
        summary["rpc_summary_written"] = rpc_summary_written
        print(json.dumps(summary))
    return result_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pi RPC-backed benchmark auto runner")
    parser.add_argument("--container", required=True)
    parser.add_argument("--workdir", required=True, help="in-container task workdir")
    parser.add_argument("--model", default="", help="pi --model value; empty uses Pi default")
    parser.add_argument("--orch-on", action="store_true", help="run /orch on preflight first")
    parser.add_argument("--events-path", default="", help="JSONL artifact for RPC events (host path)")
    parser.add_argument("--summary-out", default="", help="write JSON summary to this host path")
    parser.add_argument("--debug", action="store_true", help="mirror the parent Pi session to stderr while running")
    args = parser.parse_args(argv)

    prompt_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not prompt_text.strip():
        print("[bench] no prompt text on stdin", file=sys.stderr)
        return 2
    return run_auto(args, prompt_text)


if __name__ == "__main__":
    raise SystemExit(main())
