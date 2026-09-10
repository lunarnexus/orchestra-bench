"""Orchestra behavior extraction from Pi sessions and Orchestra artifacts."""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .session_debug import classify_session

_ORCH_SUMMARY_RE = re.compile(r"^\[orchestra:\s*(?P<body>.+?)\]$")
_WAIT_RE = re.compile(r"\b(waiting|awaiting|do not poll while waiting|still waiting)\b", re.IGNORECASE)
_INTEGRATED_RE = re.compile(r"\b(integrat|advance the plan|final readiness summary|all acceptance criteria confirmed|synthesiz)\b", re.IGNORECASE)
_FINALIZED_RE = re.compile(r"\b(final summary|final readiness summary|done\.|returning compact schema|all acceptance criteria confirmed)\b", re.IGNORECASE)
_STATUS_TOKENS = {"success", "error", "blocker", "blocked", "fail", "failed", "timeout", "timed", "timed_out", "reconciled", "complete"}


_FAILURE_STATUSES = {"error", "fail", "failed", "timeout", "timed", "timed_out"}
_NO_CHILD_REASON = "no reason recorded"


@dataclass(frozen=True)
class _SummaryEvent:
    role: str
    status: str
    timestamp: datetime | None
    text: str
    child_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class _SessionEvidence:
    kind: str
    path: Path
    session_id: str
    timestamps: tuple[datetime, ...]
    # Paired dispatch records: role/goal/task_label/tool_call_id + result ("", "accepted", or "rejected").
    dispatches: tuple[dict[str, str], ...]
    started_roles: tuple[str, ...]
    return_events: tuple[_SummaryEvent, ...]
    waiting_signals: tuple[datetime, ...]
    integration_signals: tuple[datetime, ...]
    finalization_signals: tuple[datetime, ...]


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return events
    except OSError:
        return events
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except (TypeError, ValueError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        item_type = str(item.get("type") or "")
        if item_type == "text":
            text = str(item.get("text") or "")
            if text:
                parts.append(text)
            continue
        text = item.get("text") or item.get("thinking") or item.get("content")
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts)


def _summary_reason_after(lines: list[str], start_index: int) -> str:
    """Capture the reason line that follows a non-success child return summary."""
    for follow in lines[start_index + 1 :]:
        stripped = follow.strip()
        if not stripped or _ORCH_SUMMARY_RE.match(stripped):
            break
        value = re.sub(r"^(?:summary|reason)\s*[:\-]\s*", "", stripped, flags=re.IGNORECASE).strip()
        return " ".join(value.split())[:160]
    return ""


_PASS_OVERRIDE_STATUS_RE = re.compile(r"^status\s*[:\-]\s*(done|complete|success)\b", re.IGNORECASE)
_PASS_LINE_KEY_RE = re.compile(r"^(verdict|summary)\s*[:\-]", re.IGNORECASE)
_PASS_WORD_RE = re.compile(r"\bpass\b")


def _return_block_pass_override(lines: list[str], start_index: int) -> bool:
    """True when a failure header's return block reports `status: done` plus a pass verdict/summary.

    The bracket header can lag the child's actual terminal state (e.g. `[orchestra: verifier <id> fail]`
    followed by `verdict: **pass** ... status: done`). That contradiction is not a real failure."""
    saw_done = False
    saw_pass = False
    for follow in lines[start_index + 1 :]:
        stripped = follow.strip()
        if not stripped or _ORCH_SUMMARY_RE.match(stripped):
            break
        if _PASS_OVERRIDE_STATUS_RE.match(stripped):
            saw_done = True
        elif _PASS_LINE_KEY_RE.match(stripped) and _PASS_WORD_RE.search(stripped):
            saw_pass = True
    return saw_done and saw_pass


def _orchestra_summary_events(text: str, *, timestamp: datetime | None) -> list[_SummaryEvent]:
    lines = text.splitlines()
    events: list[_SummaryEvent] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        match = _ORCH_SUMMARY_RE.match(line)
        if not match:
            continue
        body = match.group("body").strip()
        if not body:
            events.append(_SummaryEvent(role="", status="", timestamp=timestamp, text=line))
            continue
        tokens = body.split()
        if len(tokens) == 1 and tokens[0].isdigit():
            events.append(_SummaryEvent(role="", status="", timestamp=timestamp, text=line))
            continue
        status = tokens[-1].lower().replace(" ", "_")
        if status not in _STATUS_TOKENS:
            # Header/bare role-only lines are not return evidence; keep scanning.
            continue
        role = ""
        child_id = ""
        if len(tokens) >= 3 and re.fullmatch(r"[0-9a-fA-F-]{6,}", tokens[-2]):
            role = tokens[0]
            child_id = tokens[-2]
        elif len(tokens) >= 2:
            role = tokens[0]
        if status in _FAILURE_STATUSES and _return_block_pass_override(lines, index):
            # Header says fail but the return block reports done + pass: count as a success.
            status = "complete"
        reason = _summary_reason_after(lines, index) if status in _FAILURE_STATUSES else ""
        events.append(_SummaryEvent(role=role, status=status, timestamp=timestamp, text=line, child_id=child_id, reason=reason))
    return events


def _dispatch_key(record: dict[str, str]) -> tuple[str, str, str]:
    return (
        record.get("role", "").strip().lower(),
        record.get("goal", "").strip().lower(),
        record.get("task_label", "").strip().lower(),
    )


_CONCRETE_REJECTION_REASONS = (
    ("global concurrency limit exceeded", re.compile(r"\bglobal\s+concurrency limit exceeded\b")),
    ("per-session concurrency limit exceeded", re.compile(r"\bper[- ]?session\s+concurrency limit exceeded\b")),
    ("model concurrency limit exceeded", re.compile(r"\bmodel\s+concurrency limit exceeded\b")),
)


def _rejection_reason(text: str) -> str:
    """Pick the most specific rejection reason present in an orch_dispatch result.

    Concrete reasons (e.g. `model concurrency limit exceeded`) win over the generic
    `dispatch was not accepted` marker; otherwise the leading detail segment before the
    marker is preserved, and only then does the generic label apply.
    """
    lowered = " ".join(text.lower().split())
    for reason, pattern in _CONCRETE_REJECTION_REASONS:
        if pattern.search(lowered):
            return reason
    marker_index = None
    for marker in ("dispatch was not accepted", "not accepted"):
        index = lowered.find(marker)
        if index != -1 and (marker_index is None or index < marker_index):
            marker_index = index
    if marker_index is not None:
        prefix = " ".join(text.split())[:marker_index].strip(" ;,:-").strip()
        if 3 <= len(prefix) <= 80:
            return prefix
    return "dispatch was not accepted"


def _classify_dispatch_result_text(normalized: str, text: str) -> tuple[str, str]:
    if "orchestra dispatched:" in normalized or "subagent will auto-return" in normalized:
        return ("accepted", "")
    if any(phrase in normalized for phrase in ("dispatch was not accepted", "model concurrency limit exceeded", "not accepted", "rejected")):
        return ("rejected", _rejection_reason(text))
    return ("", "")


def _pair_dispatch_records(
    attempts: list[dict[str, str]], results: list[dict[str, str]]
) -> tuple[dict[str, str], ...]:
    records = [{**attempt, "result": "", "reason": ""} for attempt in attempts]
    used = [False] * len(records)

    def find_by_id(tool_call_id: str) -> int | None:
        if not tool_call_id:
            return None
        for index, record in enumerate(records):
            if not used[index] and record["tool_call_id"] == tool_call_id:
                return index
        return None

    fifo = 0
    for result in results:
        target = find_by_id(result["tool_call_id"])
        if target is None and not result["tool_call_id"]:
            while fifo < len(records) and used[fifo]:
                fifo += 1
            if fifo < len(records):
                target = fifo
        if target is None:
            # Result without a matching attempt in this source: keep it as dispatch evidence.
            records.append(
                {
                    "role": "",
                    "goal": "",
                    "task_label": "",
                    "tool_call_id": result["tool_call_id"],
                    "result": result["result"],
                }
            )
        else:
            used[target] = True
            records[target]["result"] = result["result"]
            records[target]["reason"] = str(result.get("reason") or "")
    return tuple(records)


def _summarize_session(path: Path) -> _SessionEvidence:
    events = _read_jsonl_events(path)
    session_id = path.stem
    if events:
        session_id = str(events[0].get("id") or session_id)

    kind = classify_session(path, session_id=session_id)
    timestamps: list[datetime] = []
    dispatch_attempts: list[dict[str, str]] = []
    dispatch_results: list[dict[str, str]] = []
    started_roles: list[str] = []
    pending_dispatch_roles: list[str] = []
    seen_dispatch_tool_ids: set[str] = set()
    seen_dispatch_result_ids: set[str] = set()
    seen_return_texts: set[str] = set()
    return_events: list[_SummaryEvent] = []
    waiting_signals: list[datetime] = []
    integration_signals: list[datetime] = []
    finalization_signals: list[datetime] = []

    for event in events:
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is not None:
            timestamps.append(timestamp)
        event_type = str(event.get("type") or "")
        if event_type in {"message", "message_end", "turn_end"}:
            raw_message = event.get("message")
            if isinstance(raw_message, dict):
                message = raw_message
            elif isinstance(raw_message, str) and raw_message.startswith("{"):
                try:
                    parsed_message = ast.literal_eval(raw_message)
                except (ValueError, SyntaxError):
                    parsed_message = {}
                message = parsed_message if isinstance(parsed_message, dict) else {}
            else:
                message = {}
        else:
            if event_type == "tool_execution_start" and str(event.get("toolName") or "") == "orch_dispatch":
                # Harness events: the start carries the attempt; pair it with tool_execution_end below.
                arguments = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
                if not arguments:
                    raw_args = event.get("args")
                    arguments = raw_args if isinstance(raw_args, dict) else {}
                tool_call_id = str(event.get("toolCallId") or "")
                if tool_call_id and tool_call_id in seen_dispatch_tool_ids:
                    continue
                if tool_call_id:
                    seen_dispatch_tool_ids.add(tool_call_id)
                dispatch_attempts.append(
                    {
                        "role": str(arguments.get("role") or "").strip(),
                        "goal": str(arguments.get("goal") or "").strip(),
                        "task_label": str(arguments.get("taskLabel") or arguments.get("task_label") or "").strip(),
                        "tool_call_id": tool_call_id,
                    }
                )
                continue
            if event_type == "tool_execution_end" and str(event.get("toolName") or "") == "orch_dispatch":
                tool_call_id = str(event.get("toolCallId") or "")
                if not tool_call_id or tool_call_id not in seen_dispatch_result_ids:
                    if tool_call_id:
                        seen_dispatch_result_ids.add(tool_call_id)
                    text = _message_text(event.get("result") if isinstance(event.get("result"), dict) else {})
                    normalized = " ".join(text.lower().split())
                    classified, reason = _classify_dispatch_result_text(normalized, text)
                    if not classified and event.get("isError"):
                        classified, reason = "rejected", _rejection_reason(text)
                    if classified:
                        dispatch_results.append({"tool_call_id": tool_call_id, "result": classified, "reason": reason})
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            text = ""
            if isinstance(data, dict):
                text = str(data.get("text") or "")
            if text and _WAIT_RE.search(text):
                if timestamp is not None:
                    waiting_signals.append(timestamp)
            if text and _INTEGRATED_RE.search(text):
                if timestamp is not None:
                    integration_signals.append(timestamp)
            if text and _FINALIZED_RE.search(text):
                if timestamp is not None:
                    finalization_signals.append(timestamp)
            continue
        if not message:
            continue
        role = str(message.get("role") or "")
        text = _message_text(message)
        if role == "assistant":
            content = message.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("type") or "") != "toolCall":
                        continue
                    if str(item.get("name") or "") != "orch_dispatch":
                        continue
                    arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                    if not isinstance(arguments, dict):
                        continue
                    tool_call_id = str(item.get("id") or item.get("toolCallId") or "")
                    if tool_call_id and tool_call_id in seen_dispatch_tool_ids:
                        continue
                    if tool_call_id:
                        seen_dispatch_tool_ids.add(tool_call_id)
                    dispatch_attempts.append(
                        {
                            "role": str(arguments.get("role") or "").strip(),
                            "goal": str(arguments.get("goal") or "").strip(),
                            "task_label": str(arguments.get("taskLabel") or arguments.get("task_label") or "").strip(),
                            "tool_call_id": tool_call_id,
                        }
                    )
                    pending_dispatch_roles.append(str(arguments.get("role") or "").strip())
                    if timestamp is not None and _WAIT_RE.search(text):
                        waiting_signals.append(timestamp)
        if role == "toolResult" and str(message.get("toolName") or "") == "orch_dispatch":
            tool_call_id = str(message.get("toolCallId") or "")
            normalized = " ".join(text.lower().split())
            if not tool_call_id or tool_call_id not in seen_dispatch_result_ids:
                if tool_call_id:
                    seen_dispatch_result_ids.add(tool_call_id)
                classified, reason = _classify_dispatch_result_text(normalized, text)
                if classified:
                    dispatch_results.append({"tool_call_id": tool_call_id, "result": classified, "reason": reason})
            if timestamp is not None and _WAIT_RE.search(text):
                waiting_signals.append(timestamp)
        summaries = _orchestra_summary_events(text, timestamp=timestamp)
        for summary in summaries:
            if summary.text in seen_return_texts:
                continue
            seen_return_texts.add(summary.text)
            if summary.status in {"success", "complete"}:
                return_events.append(summary)
                if timestamp is not None and _INTEGRATED_RE.search(text):
                    integration_signals.append(timestamp)
                if timestamp is not None and _FINALIZED_RE.search(text):
                    finalization_signals.append(timestamp)
            elif summary.status in {"error", "fail", "failed"}:
                return_events.append(summary)
            elif summary.status in {"blocker", "blocked"}:
                return_events.append(summary)
            elif summary.status in {"timeout", "timed", "timed_out"}:
                return_events.append(summary)
            elif summary.status == "reconciled":
                return_events.append(summary)
        if summaries:
            continue
        if timestamp is not None:
            if _WAIT_RE.search(text):
                waiting_signals.append(timestamp)
            if _INTEGRATED_RE.search(text):
                integration_signals.append(timestamp)
            if _FINALIZED_RE.search(text):
                finalization_signals.append(timestamp)

    return _SessionEvidence(
        kind=kind,
        path=path,
        session_id=session_id,
        timestamps=tuple(timestamps),
        dispatches=_pair_dispatch_records(dispatch_attempts, dispatch_results),
        started_roles=tuple(started_roles),
        return_events=tuple(return_events),
        waiting_signals=tuple(waiting_signals),
        integration_signals=tuple(integration_signals),
        finalization_signals=tuple(finalization_signals),
    )


def _empty_metrics() -> dict[str, Any]:
    return {
        "dispatch_attempts": None,
        "dispatch_accepted": None,
        "dispatch_rejected": None,
        "dispatch_rejection_reasons": None,
        "roles_requested": None,
        "roles_started": None,
        "roles_returned": None,
        "duplicate_same_slice_dispatches": None,
        "same_slice_dispatches": None,
        "child_returns": {"ok": None, "error": None, "blocker": None},
        "child_sessions": {"completed": None, "failed": None, "timed_out": None, "reconciled": None, "active": None, "inferred_active": None},
        "child_failure_reasons": None,
        "parent": {"waited": None, "integrated": None, "finalized_before_children": None},
        "dispatch": {"attempts": None, "accepted": None, "rejected": None, "rejection_reasons": None},
        "roles": {"requested": None, "started": None, "returned": None},
        "children": {"returns": {"ok": None, "error": None, "blocker": None}, "sessions": {"completed": None, "failed": None, "timed_out": None, "reconciled": None, "active": None, "inferred_active": None}, "failure_reasons": None},
        "evidence": {"pi_sessions": False, "orchestra_debug": False},
    }


def _finalize_list(value: list[str], *, seen: bool) -> list[str] | None:
    if not seen:
        return None
    return value


def _finalize_count(value: int, *, seen: bool) -> int | None:
    if not seen:
        return None
    return value


def _finalize_bool(value: bool | None) -> bool | None:
    return value


def _store_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def _coerce_orchestra_flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value in {"true", "True", "1"}:
            return True
        if value in {"false", "False", "0"}:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    return None


def _load_orchestra_mode(run_root: Path) -> bool | None:
    for candidate in (run_root / "result.json", run_root / ".bench_run.json"):
        payload = _read_json(candidate)
        if not payload:
            continue
        sources = [payload]
        for key in ("details", "provenance", "config"):
            source = payload.get(key)
            if isinstance(source, dict):
                sources.append(source)
                nested = source.get("provenance")
                if isinstance(nested, dict):
                    sources.append(nested)
        for source in sources:
            if not isinstance(source, dict):
                continue
            flag = _coerce_orchestra_flag(source.get("orchestra"))
            if flag is not None:
                return flag
    return None


def extract_orchestra_metrics(run_dir: Path | str) -> dict[str, Any]:
    run_root = Path(run_dir)
    sessions_dir = run_root / "artifacts" / "pi-sessions"
    debug_dir = run_root / "artifacts" / "orchestra-debug"

    metrics = _empty_metrics()
    dispatch_reasons: Counter[str] = Counter()
    role_started: list[str] = []
    role_returned: list[str] = []
    role_requested: list[str] = []
    child_completed = child_failed = child_timed_out = child_reconciled = child_active = child_inferred_active = 0
    # Stable identity per child run: (role, session id token); line text is the fallback for
    # malformed summaries that carry neither, so they keep counting like before.
    seen_return_identities: set[tuple[str, str]] = set()
    child_failure_reasons: Counter[str] = Counter()
    child_returns_ok = child_returns_error = child_returns_blocker = 0
    dispatch_attempts = 0
    dispatch_accepted = 0
    dispatch_rejected = 0
    duplicate_same_slice_dispatches = 0
    saw_dispatch_evidence = False
    saw_child_evidence = False
    saw_return_evidence = False
    saw_parent_evidence = False
    parent_waited = None
    parent_integrated = None
    parent_finalized_before_children = None

    if sessions_dir.is_dir():
        metrics["evidence"]["pi_sessions"] = True
        session_evidence = [_summarize_session(path) for path in sorted(sessions_dir.rglob("*.jsonl"))]
    else:
        session_evidence = []
    harness_events = run_root / "artifacts" / "harness" / "events.jsonl"
    if harness_events.is_file():
        metrics["evidence"]["harness_events"] = True
        session_evidence.append(_summarize_session(harness_events))

    if debug_dir.is_dir():
        metrics["evidence"]["orchestra_debug"] = True

    orchestra_mode = _load_orchestra_mode(run_root)
    child_return_timestamps: list[datetime | None] = []
    parent_finalization_times: list[datetime | None] = []

    # Global dedup: one nonempty tool_call_id is one dispatch; a keyless role/goal/task
    # repeat from another source (e.g. copied pi-session vs harness events) counts once.
    seen_tool_call_ids: set[str] = set()
    dispatch_key_owners: dict[tuple[str, str, str], Path] = {}
    same_source_keys: dict[Path, set[tuple[str, str, str]]] = defaultdict(set)

    for evidence in session_evidence:
        if evidence.kind == "worker":
            saw_child_evidence = True
        else:
            saw_parent_evidence = True

        source_seen_keys = same_source_keys[evidence.path]
        for record in evidence.dispatches:
            tool_call_id = str(record.get("tool_call_id") or "")
            role = str(record.get("role") or "")
            dispatch_key = _dispatch_key(record)

            if tool_call_id:
                if tool_call_id in seen_tool_call_ids:
                    continue
                seen_tool_call_ids.add(tool_call_id)
            else:
                owner = dispatch_key_owners.get(dispatch_key)
                if owner is not None and owner != evidence.path:
                    continue
            dispatch_key_owners.setdefault(dispatch_key, evidence.path)

            saw_dispatch_evidence = True
            dispatch_attempts += 1
            _store_unique(role_requested, role)
            # Same-source repeats of the same slice are real attempts; flag them as duplicates.
            if all(dispatch_key) and dispatch_key in source_seen_keys:
                duplicate_same_slice_dispatches += 1
            source_seen_keys.add(dispatch_key)

            result = str(record.get("result") or "")
            if result == "accepted":
                dispatch_accepted += 1
                _store_unique(role_started, role)
            elif result == "rejected":
                dispatch_rejected += 1
                reason = str(record.get("reason") or "").strip() or "dispatch was not accepted"
                dispatch_reasons[reason] += 1

        if evidence.return_events:
            saw_return_evidence = True
        if evidence.waiting_signals:
            parent_waited = True
        if evidence.integration_signals:
            parent_integrated = True
        if evidence.finalization_signals:
            parent_finalized_before_children = parent_finalized_before_children or False

        # Prefer explicit child return summaries and derive started/returned roles from them.
        for summary in evidence.return_events:
            role = summary.role.strip()
            if role:
                _store_unique(role_returned, role)
                _store_unique(role_started, role)
            child_return_timestamps.append(summary.timestamp)
            identity = (
                (summary.role.strip().lower(), summary.child_id.lower())
                if (summary.role or summary.child_id)
                else ("", summary.text)
            )
            # Duplicated terminal return evidence across copied sources is one child run, not several.
            if identity in seen_return_identities:
                continue
            seen_return_identities.add(identity)
            if summary.status in {"success", "complete"}:
                child_returns_ok += 1
                child_completed += 1
            elif summary.status in {"error", "fail", "failed"}:
                child_returns_error += 1
                child_failed += 1
                reason = str(summary.reason or "").strip() or _NO_CHILD_REASON
                child_failure_reasons[reason] += 1
            elif summary.status in {"blocker", "blocked"}:
                child_returns_blocker += 1
                child_reconciled += 1
            elif summary.status in {"timeout", "timed", "timed_out"}:
                child_timed_out += 1
                reason = str(summary.reason or "").strip() or _NO_CHILD_REASON
                child_failure_reasons[reason] += 1
            elif summary.status == "reconciled":
                child_reconciled += 1

        # If there was an accepted dispatch but no explicit return evidence, treat the child as still active.
        if evidence.kind == "worker" and not evidence.return_events:
            child_active += 1

    # Terminal states are mutually exclusive by construction: each stable child identity lands in
    # exactly one bucket above. A worker session without its own return evidence is only still active
    # if accepted-dispatch evidence leaves room for it, so a terminal child is never also counted active.
    terminal_children = child_completed + child_failed + child_timed_out + child_reconciled
    active_gap = max(dispatch_accepted - terminal_children, 0)
    if dispatch_accepted > 0:
        child_active = min(child_active, active_gap)
    child_inferred_active = active_gap

    if parent_waited is None:
        parent_waited = True if any(saw_dispatch_evidence and evidence.kind == "main" and evidence.waiting_signals for evidence in session_evidence) else None
    if parent_integrated is None:
        parent_integrated = True if any(evidence.kind == "main" and evidence.integration_signals for evidence in session_evidence) else None

    if parent_finalized_before_children is None:
        parent_finalization_times = [
            ts
            for evidence in session_evidence
            if evidence.kind == "main"
            for ts in evidence.finalization_signals
        ]
        if parent_finalization_times and child_return_timestamps:
            earliest_parent_final = min(parent_finalization_times)
            latest_child_return = max(ts for ts in child_return_timestamps if ts is not None)
            parent_finalized_before_children = earliest_parent_final < latest_child_return

    dispatch_reasons_dict = dict(dispatch_reasons) if dispatch_reasons else None
    if not dispatch_reasons_dict and dispatch_rejected:
        dispatch_reasons_dict = {"dispatch was not accepted": dispatch_rejected}
    child_failure_reasons_dict = dict(child_failure_reasons) if child_failure_reasons else (None if child_failed == 0 and child_timed_out == 0 else {_NO_CHILD_REASON: child_failed + child_timed_out})

    if dispatch_attempts or dispatch_accepted or dispatch_rejected or duplicate_same_slice_dispatches or role_requested or role_started or role_returned or child_completed or child_failed or child_timed_out or child_reconciled or child_active or child_inferred_active or parent_waited is not None or parent_integrated is not None or parent_finalized_before_children is not None:
        metrics["dispatch_attempts"] = dispatch_attempts
        metrics["dispatch_accepted"] = dispatch_accepted
        metrics["dispatch_rejected"] = dispatch_rejected
        metrics["dispatch_rejection_reasons"] = dispatch_reasons_dict or {}
        metrics["roles_requested"] = role_requested
        metrics["roles_started"] = role_started if role_started else []
        metrics["roles_returned"] = role_returned
        metrics["duplicate_same_slice_dispatches"] = duplicate_same_slice_dispatches
        metrics["same_slice_dispatches"] = duplicate_same_slice_dispatches
        metrics["child_returns"] = {"ok": child_returns_ok, "error": child_returns_error, "blocker": child_returns_blocker}
        metrics["child_failure_reasons"] = child_failure_reasons_dict
        metrics["child_sessions"] = {
            "completed": child_completed,
            "failed": child_failed,
            "timed_out": child_timed_out,
            "reconciled": child_reconciled,
            "active": child_active,
            "inferred_active": child_inferred_active,
        }
        metrics["parent"] = {
            "waited": parent_waited,
            "integrated": parent_integrated,
            "finalized_before_children": parent_finalized_before_children,
        }
        metrics["dispatch"] = {
            "attempts": dispatch_attempts,
            "accepted": dispatch_accepted,
            "rejected": dispatch_rejected,
            "rejection_reasons": dispatch_reasons_dict or {},
        }
        metrics["roles"] = {
            "requested": role_requested,
            "started": role_started if role_started else ([] if dispatch_accepted else None),
            "returned": role_returned,
        }
        metrics["children"] = {
            "returns": metrics["child_returns"],
            "sessions": metrics["child_sessions"],
            "failure_reasons": child_failure_reasons_dict,
        }
    else:
        return metrics

    if orchestra_mode is False and (saw_dispatch_evidence or saw_child_evidence or saw_return_evidence):
        metrics["tool_activity"] = {
            "detected": True,
            "reason": "dispatch/child activity observed while orchestration was disabled",
            "dispatch_attempts": dispatch_attempts,
            "dispatch_accepted": dispatch_accepted,
            "dispatch_rejected": dispatch_rejected,
            "roles_requested": role_requested,
            "roles_started": role_started,
            "roles_returned": role_returned,
            "child_sessions": metrics["child_sessions"],
            "inferred_active": child_inferred_active,
        }

    # Normalize nested aliases when values are absent.
    metrics["dispatch"]["rejection_reasons"] = metrics["dispatch_rejection_reasons"]
    metrics["roles"]["requested"] = metrics["roles_requested"]
    metrics["roles"]["started"] = metrics["roles_started"]
    metrics["roles"]["returned"] = metrics["roles_returned"]
    metrics["children"]["returns"] = metrics["child_returns"]
    metrics["children"]["sessions"] = metrics["child_sessions"]
    return metrics


__all__ = ["extract_orchestra_metrics"]
