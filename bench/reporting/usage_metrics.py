"""Shared token, context, and compaction extraction for benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def _empty_bucket() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "api_calls": 0,
        "final_context_tokens": None,
        "max_context_tokens": None,
        "compactions": 0,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return events
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _usage_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _usage_total(usage: dict[str, Any]) -> int:
    total = usage.get("totalTokens")
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        return int(total)
    return (
        _usage_int(usage.get("input"))
        + _usage_int(usage.get("output"))
        + _usage_int(usage.get("cacheRead"))
        + _usage_int(usage.get("cacheWrite"))
        + _usage_int(usage.get("cacheWrite1h"))
    )


def _add_call(bucket: dict[str, Any], usage: dict[str, Any], *, update_context: bool = True) -> None:
    input_tokens = _usage_int(usage.get("input"))
    output_tokens = _usage_int(usage.get("output"))
    cache_read = _usage_int(usage.get("cacheRead"))
    cache_write = _usage_int(usage.get("cacheWrite")) + _usage_int(usage.get("cacheWrite1h"))
    bucket["input_tokens"] += input_tokens
    bucket["output_tokens"] += output_tokens
    bucket["reasoning_tokens"] += _usage_int(usage.get("reasoning"))
    bucket["cached_input_read_tokens"] += cache_read
    bucket["cache_write_tokens"] += cache_write
    bucket["total_tokens"] += _usage_total(usage)
    bucket["api_calls"] += 1
    if update_context:
        context_tokens = input_tokens
        bucket["final_context_tokens"] = context_tokens
        current_max = bucket["max_context_tokens"]
        bucket["max_context_tokens"] = context_tokens if current_max is None else max(current_max, context_tokens)


def _merge_bucket(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_read_tokens", "cache_write_tokens", "total_tokens", "api_calls", "compactions"):
        target[key] += source[key]
    if source["final_context_tokens"] is not None:
        target["final_context_tokens"] = source["final_context_tokens"]
    if source["max_context_tokens"] is not None:
        current = target["max_context_tokens"]
        target["max_context_tokens"] = source["max_context_tokens"] if current is None else max(current, source["max_context_tokens"])


def _session_id(events: Iterable[dict[str, Any]], fallback: str) -> str:
    for event in events:
        if event.get("type") == "session" and event.get("id"):
            return str(event["id"])
    return fallback


def _is_child_session(path: Path, session_id: str) -> bool:
    text = f"{path.name} {session_id}".lower()
    return "orchestra-worker" in text or "worker" in text or "child" in text


def _event_usage(event: dict[str, Any]) -> dict[str, Any] | None:
    usage = event.get("usage")
    if isinstance(usage, dict):
        return usage
    message = event.get("message")
    if isinstance(message, dict):
        usage = message.get("usage")
        if isinstance(usage, dict):
            return usage
    assistant_event = event.get("assistantMessageEvent")
    if isinstance(assistant_event, dict):
        usage = assistant_event.get("usage")
        if isinstance(usage, dict):
            return usage
    return None


def _usage_has_tokens(usage: dict[str, Any]) -> bool:
    return any(_usage_int(usage.get(key)) > 0 for key in (
        "input",
        "output",
        "reasoning",
        "cacheRead",
        "cacheWrite",
        "cacheWrite1h",
        "totalTokens",
    ))


def _flush_usage(bucket: dict[str, Any], usage: dict[str, Any] | None) -> None:
    if usage is not None:
        _add_call(bucket, usage)


def _message_role(event: dict[str, Any]) -> str:
    message = event.get("message")
    return str(message.get("role") or "") if isinstance(message, dict) else ""


def _bucket_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    bucket = _empty_bucket()
    pending_usage: dict[str, Any] | None = None

    for event in [*events, {}]:
        event_type = event.get("type")
        usage = _event_usage(event)
        role = _message_role(event)

        if event_type == "compaction":
            _flush_usage(bucket, pending_usage)
            pending_usage = None
            if isinstance(usage, dict) and _usage_has_tokens(usage):
                _add_call(bucket, usage, update_context=False)
            bucket["compactions"] += 1
            continue

        if event_type == "branch_summary":
            _flush_usage(bucket, pending_usage)
            pending_usage = None
            if isinstance(usage, dict) and _usage_has_tokens(usage):
                _add_call(bucket, usage, update_context=False)
            continue

        if role == "toolResult":
            _flush_usage(bucket, pending_usage)
            pending_usage = None
            continue

        if event_type == "message_end" and role == "assistant":
            if isinstance(usage, dict) and _usage_has_tokens(usage):
                # A final message usage replaces the stream snapshots for this
                # lifecycle, so count it once and use it for context metrics.
                _add_call(bucket, usage)
            else:
                _flush_usage(bucket, pending_usage)
            pending_usage = None
            continue

        if isinstance(usage, dict) and _usage_has_tokens(usage):
            # Pi emits one usage snapshot per stream update. Keep the final
            # snapshot for that lifecycle instead of counting every update.
            pending_usage = usage
            continue

        _flush_usage(bucket, pending_usage)
        pending_usage = None

    return bucket


def _bucket_from_session_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return _bucket_from_events(events)


def _bucket_from_harness_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return _bucket_from_events(events)


def _child_activity_observed(events: Iterable[dict[str, Any]]) -> bool:
    for event in events:
        if (
            event.get("type") == "tool_execution_end"
            and event.get("toolName") == "orch_dispatch"
            and not event.get("isError")
        ):
            return True
    return False


def extract_usage_metrics(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    sessions_dir = root / "artifacts" / "pi-sessions"
    harness_events_path = root / "artifacts" / "harness" / "events.jsonl"

    # One bucket per session id: duplicate evidence for the same session is
    # counted once so parent/children/all stay deduplicated.
    session_buckets: dict[str, dict[str, Any]] = {}
    is_child_by_sid: dict[str, bool] = {}

    if sessions_dir.is_dir():
        for path in sorted(sessions_dir.rglob("*.jsonl")):
            events = _read_jsonl(path)
            if not events:
                continue
            sid = _session_id(events, path.stem)
            if sid in session_buckets:
                continue
            session_buckets[sid] = _bucket_from_session_events(events)
            is_child_by_sid[sid] = _is_child_session(path, sid)

    parent_ids = [sid for sid, child in is_child_by_sid.items() if not child]
    child_ids = [sid for sid, child in is_child_by_sid.items() if child]
    saw_parent = bool(parent_ids)
    saw_child = bool(child_ids)
    used_harness_parent = False

    all_bucket = _empty_bucket()
    parent_bucket = _empty_bucket()
    child_bucket = _empty_bucket()

    harness_events = _read_jsonl(harness_events_path) if harness_events_path.is_file() else []
    child_activity_observed = _child_activity_observed(harness_events)

    if not saw_parent and harness_events:
        bucket = _bucket_from_harness_events(harness_events)
        if bucket["api_calls"] or bucket["compactions"]:
            used_harness_parent = True
            sid = "harness-events"
            for event in harness_events:
                if event.get("command") == "get_state" and isinstance(event.get("data"), dict) and event["data"].get("sessionId"):
                    sid = str(event["data"]["sessionId"])
                    break
            if sid not in session_buckets:
                session_buckets[sid] = bucket
                is_child_by_sid[sid] = False
                parent_ids.append(sid)
                saw_parent = True

    for sid, bucket in session_buckets.items():
        if is_child_by_sid[sid]:
            _merge_bucket(child_bucket, bucket)
        else:
            _merge_bucket(parent_bucket, bucket)
        _merge_bucket(all_bucket, bucket)

    if not session_buckets:
        return {}
    unavailable_reasons: dict[str, str] = {}
    all_unavailable = False
    if child_activity_observed and not saw_child:
        # Child sessions were expected but are missing or unreadable; the
        # parent-only total must not be presented as the run total.
        unavailable_reasons["children"] = "child activity observed but no readable child pi sessions"
        unavailable_reasons["all"] = "total needs both parent and child session evidence; child sessions are missing or unreadable"
        all_unavailable = True
    elif not saw_child:
        # No child activity occurred, so all may equal parent. Record the
        # explicit evidence basis for that claim.
        unavailable_reasons["children"] = (
            "no child activity observed in harness events"
            if harness_events_path.is_file()
            else "no child session files or harness events available"
        )

    return {
        "total": None if all_unavailable else all_bucket["total_tokens"],
        "sources": {
            "parent": "harness_events" if used_harness_parent else ("pi_session" if saw_parent else None),
            "children": "pi_sessions" if saw_child else None,
        },
        "unavailable_reasons": unavailable_reasons,
        "session_ids": list(session_buckets),
        "parent_session_ids": parent_ids,
        "child_session_ids": child_ids,
        "subagent_session_ids": child_ids,
        "all_sessions": None if all_unavailable else all_bucket,
        "parent_session": parent_bucket if saw_parent else None,
        "main_session": parent_bucket if saw_parent else None,
        "children_sessions": child_bucket if saw_child else None,
        "subagent_sessions": child_bucket if saw_child else None,
    }
