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
from typing import Callable

_ACTIVE_RUNS_RE = re.compile(r"^active_runs:\s*(\d+)\s*/", re.MULTILINE)


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
    """Poll until the session has zero active runs, or the timeout elapses.

    Returns True when no active runs remain (or a query error reports none).
    Unparseable status output is treated as "still unknown" and keeps polling;
    on total timeout it returns False so callers can decide to proceed anyway.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        try:
            active = parse_active_runs(query())
        except Exception:
            active = None  # transient query failure; keep polling until deadline
        if active == 0:
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        sleep_for = poll_interval if deadline is None else min(poll_interval, max(0.1, deadline - time.monotonic()))
        time.sleep(sleep_for)
