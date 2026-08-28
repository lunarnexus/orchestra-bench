"""Orchestra settle status parsing and gating helpers."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

_ACTIVE_RUNS_RE = re.compile(r"^active_runs:\s*(\d+)\s*/", re.MULTILINE)
_STATUS_BOOL_RE = {
    "descendants_terminal": re.compile(r"^descendants_terminal:\s*(yes|no)\s*$", re.MULTILINE),
    "session_report_available": re.compile(r"^session_report_available:\s*(yes|no)\s*$", re.MULTILINE),
    "session_report_delivered": re.compile(r"^session_report_delivered:\s*(yes|no)\s*$", re.MULTILINE),
}
_TERMINAL_STATES = frozenset({"settled", "timeout", "failed"})


@dataclass(frozen=True)
class OrchestrationStatusSnapshot:
    session_id: str = ""
    raw_text: str = ""
    active_runs: int | None = None
    descendants_terminal: bool | None = None
    session_report_available: bool | None = None
    session_report_delivered: bool | None = None
    state: str = "missing"
    parsed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrchestrationSettleResult:
    safe_to_grade: bool
    reason: str
    harness_status: str = ""
    session_id: str = ""
    snapshots: tuple[OrchestrationStatusSnapshot, ...] = ()


@runtime_checkable
class StatusProvider(Protocol):
    def __call__(self, session_id: str) -> Any:
        ...



def parse_status_text(status_text: str, *, session_id: str = "") -> OrchestrationStatusSnapshot:
    raw_text = status_text or ""
    active_runs = parse_active_runs(raw_text)
    parsed = active_runs is not None
    state = "unparseable"
    if parsed:
        state = "settled" if active_runs == 0 else "running"
    details: dict[str, Any] = {}
    for key, pattern in _STATUS_BOOL_RE.items():
        match = pattern.search(raw_text)
        if match:
            value = match.group(1) == "yes"
            details[key] = value
        else:
            value = None
        details.setdefault(key, value)
    return OrchestrationStatusSnapshot(
        session_id=session_id,
        raw_text=raw_text,
        active_runs=active_runs,
        descendants_terminal=details.get("descendants_terminal"),
        session_report_available=details.get("session_report_available"),
        session_report_delivered=details.get("session_report_delivered"),
        state=state,
        parsed=parsed,
        details=details,
    )



def parse_active_runs(status_text: str) -> int | None:
    """Return the session-scoped active run count, or None if unparseable."""
    match = _ACTIVE_RUNS_RE.search(status_text or "")
    return int(match.group(1)) if match else None



def coerce_status_snapshot(session_id: str, value: Any) -> OrchestrationStatusSnapshot:
    if isinstance(value, OrchestrationStatusSnapshot):
        if value.session_id:
            return value
        return OrchestrationStatusSnapshot(
            session_id=session_id,
            raw_text=value.raw_text,
            active_runs=value.active_runs,
            descendants_terminal=value.descendants_terminal,
            session_report_available=value.session_report_available,
            session_report_delivered=value.session_report_delivered,
            state=value.state,
            parsed=value.parsed,
            details=dict(value.details),
        )
    if value is None:
        return OrchestrationStatusSnapshot(session_id=session_id, state="missing")
    if isinstance(value, str):
        return parse_status_text(value, session_id=session_id)
    if isinstance(value, dict):
        raw_text = str(value.get("raw_text") or value.get("text") or value.get("status_text") or "")
        state = str(value.get("state") or "") or "missing"
        parsed = bool(value.get("parsed"))
        active_runs = value.get("active_runs")
        if active_runs is not None:
            try:
                active_runs = int(active_runs)
                parsed = True
            except (TypeError, ValueError):
                active_runs = None
        if not raw_text and active_runs is None and state not in {"timeout", "failed", "missing", "unparseable"}:
            raw_text = ""
        if not parsed and raw_text:
            parsed_snapshot = parse_status_text(raw_text, session_id=session_id)
            details = dict(parsed_snapshot.details)
            for key in _STATUS_BOOL_RE:
                if key in value:
                    details[key] = value.get(key)
            return OrchestrationStatusSnapshot(
                session_id=session_id,
                raw_text=parsed_snapshot.raw_text,
                active_runs=active_runs if active_runs is not None else parsed_snapshot.active_runs,
                descendants_terminal=details.get("descendants_terminal"),
                session_report_available=details.get("session_report_available"),
                session_report_delivered=details.get("session_report_delivered"),
                state=state if state else parsed_snapshot.state,
                parsed=True,
                details=details,
            )
        details = {
            key: value.get(key)
            for key in ("descendants_terminal", "session_report_available", "session_report_delivered")
            if key in value
        }
        return OrchestrationStatusSnapshot(
            session_id=session_id,
            raw_text=raw_text,
            active_runs=active_runs,
            descendants_terminal=value.get("descendants_terminal"),
            session_report_available=value.get("session_report_available"),
            session_report_delivered=value.get("session_report_delivered"),
            state=state,
            parsed=parsed,
            details=details,
        )
    return OrchestrationStatusSnapshot(session_id=session_id, raw_text=str(value), state="unparseable")



def wait_for_orchestration_settle(
    session_id: str,
    status_provider: StatusProvider | Callable[[str], Any],
    *,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float = 5.0,
    accept_terminal_states: frozenset[str] = _TERMINAL_STATES,
) -> OrchestrationSettleResult:
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    snapshots: list[OrchestrationStatusSnapshot] = []
    while True:
        try:
            snapshot = coerce_status_snapshot(session_id, status_provider(session_id))
        except Exception as exc:
            snapshot = OrchestrationStatusSnapshot(session_id=session_id, state="missing", details={"error": f"{type(exc).__name__}: {exc}"})
        snapshots.append(snapshot)
        if snapshot.state in accept_terminal_states:
            if snapshot.state == "settled" and snapshot.active_runs not in {None, 0}:
                pass
            else:
                return OrchestrationSettleResult(
                    safe_to_grade=True,
                    reason=snapshot.state,
                    session_id=session_id,
                    snapshots=tuple(snapshots),
                )
        if snapshot.state == "missing":
            return OrchestrationSettleResult(
                safe_to_grade=False,
                reason="missing_status",
                session_id=session_id,
                snapshots=tuple(snapshots),
            )
        if snapshot.state == "unparseable":
            return OrchestrationSettleResult(
                safe_to_grade=False,
                reason="unparseable_status",
                session_id=session_id,
                snapshots=tuple(snapshots),
            )
        if snapshot.active_runs == 0:
            return OrchestrationSettleResult(
                safe_to_grade=True,
                reason="settled",
                session_id=session_id,
                snapshots=tuple(snapshots),
            )
        if deadline is not None and time.monotonic() >= deadline:
            return OrchestrationSettleResult(
                safe_to_grade=False,
                reason="timeout",
                session_id=session_id,
                snapshots=tuple(snapshots),
            )
        if deadline is not None:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return OrchestrationSettleResult(
                    safe_to_grade=False,
                    reason="timeout",
                    session_id=session_id,
                    snapshots=tuple(snapshots),
                )
            time.sleep(min(poll_interval_seconds, remaining))
        elif poll_interval_seconds > 0:
            time.sleep(poll_interval_seconds)
