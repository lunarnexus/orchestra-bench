"""Orchestra settle gate.

After the parent Pi session settles, benchmark auto mode must not grade while
tracked Orchestra workers/reports are still active. The gate polls
`orchestra status --session-id <sid>` and reports how many runs are active for
the session lineage.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

_ACTIVE_RUNS_RE = re.compile(r"^active_runs:\s*(\d+)\s*/", re.MULTILINE)
_STATUS_BOOL_RE = {
    "descendants_terminal": re.compile(r"^descendants_terminal:\s*(yes|no)\s*$", re.MULTILINE),
    "session_report_available": re.compile(r"^session_report_available:\s*(yes|no)\s*$", re.MULTILINE),
    "session_report_delivered": re.compile(r"^session_report_delivered:\s*(yes|no)\s*$", re.MULTILINE),
}


@dataclass
class GateStatus:
    active_runs: int | None = None
    descendants_terminal: bool | None = None
    session_report_available: bool | None = None
    session_report_delivered: bool | None = None


def parse_status_details(status_text: str) -> GateStatus:
    """Parse compact Orchestra session status fields used by the bench gate."""
    status = GateStatus(active_runs=parse_active_runs(status_text))
    for key, pattern in _STATUS_BOOL_RE.items():
        match = pattern.search(status_text)
        if match:
            setattr(status, key, match.group(1) == "yes")
    return status


def parse_active_runs(status_text: str) -> int | None:
    """Return the session-scoped active run count, or None if unparseable."""
    match = _ACTIVE_RUNS_RE.search(status_text)
    return int(match.group(1)) if match else None


StatusQuery = Callable[[], str]


def docker_status_query(container_name: str, session_id: str) -> StatusQuery:
    """Build a status query that runs `orchestra status` inside the container."""

    def query() -> str:
        proc = subprocess.run(
            [
                "docker", "exec", "-i", container_name,
                "sh", "-c", f"orchestra status --session-id {session_id} 2>&1 || true",
            ],
            capture_output=True,
            text=True,
        )
        return (proc.stdout or "") + (proc.stderr or "")

    return query


def wait_for_settled(
    query: StatusQuery,
    timeout: float | None = None,
    poll_interval: float = 5.0,
) -> bool:
    """Backward-compatible bool gate."""
    return wait_for_gate_status(query, timeout=timeout, poll_interval=poll_interval).result == "settled"


@dataclass
class GateWaitResult:
    result: str
    status: GateStatus


def wait_for_gate_status(
    query: StatusQuery,
    timeout: float | None = None,
    poll_interval: float = 5.0,
) -> GateWaitResult:
    """Poll until the session has zero active runs, or the timeout elapses."""
    deadline = None if timeout is None else time.monotonic() + timeout
    last_status = GateStatus()
    while True:
        try:
            last_status = parse_status_details(query())
        except Exception:
            last_status = GateStatus()  # transient query failure; keep polling until deadline
        if last_status.active_runs == 0:
            return GateWaitResult("settled", last_status)
        if deadline is not None and time.monotonic() >= deadline:
            return GateWaitResult("timeout", last_status)
        sleep_for = poll_interval if deadline is None else min(poll_interval, max(0.1, deadline - time.monotonic()))
        time.sleep(sleep_for)
