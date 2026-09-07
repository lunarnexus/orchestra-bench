"""Readable Pi session transcript discovery and rendering."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class SessionTranscript:
    path: Path
    session_id: str
    kind: str  # main | worker | parent | harness
    events: tuple[dict[str, Any], ...]


def _sort_key(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_worker_session(session_id: str, path: Path) -> bool:
    haystacks = (session_id, path.name)
    return any("orchestra-worker" in value for value in haystacks if value)


def _parse_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            events.append({"type": "raw", "line": raw_line})
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            events.append({"type": "raw", "value": event})
    return tuple(events)


def _parse_raw_text(path: Path) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        events.append({"type": "raw", "line": raw_line})
    return tuple(events)


def _session_id_from_events(events: Iterable[dict[str, Any]], fallback: str) -> str:
    for event in events:
        if event.get("type") == "session" and event.get("id"):
            return str(event.get("id") or "")
    return fallback


def classify_session(path: Path, *, session_id: str = "") -> str:
    return "worker" if _is_worker_session(session_id, path) else "main"


def _discover_pi_session_transcripts(session_dir: Path) -> tuple[SessionTranscript, ...]:
    root = Path(session_dir)
    if not root.is_dir():
        return ()

    transcripts: list[SessionTranscript] = []
    for path in sorted(root.rglob("*.jsonl"), key=lambda item: _sort_key(item, root)):
        events = _parse_jsonl(path)
        session_id = _session_id_from_events(events, path.stem)
        kind = classify_session(path, session_id=session_id)
        transcripts.append(SessionTranscript(path=path, session_id=session_id, kind=kind, events=events))
    return tuple(transcripts)


def _discover_harness_transcripts(session_dir: Path) -> tuple[SessionTranscript, ...]:
    root = Path(session_dir)
    harness_dir = root.parent / "harness"
    if not harness_dir.is_dir():
        return ()

    transcripts: list[SessionTranscript] = []
    events_path = harness_dir / "events.jsonl"
    if events_path.is_file():
        events = _parse_jsonl(events_path)
        transcripts.append(
            SessionTranscript(
                path=events_path,
                session_id=_session_id_from_events(events, events_path.stem),
                kind="parent",
                events=events,
            )
        )
    transcript_path = harness_dir / "transcript.txt"
    if transcript_path.is_file():
        transcripts.append(
            SessionTranscript(
                path=transcript_path,
                session_id=transcript_path.stem,
                kind="harness",
                events=_parse_raw_text(transcript_path),
            )
        )
    return tuple(transcripts)


def discover_session_transcripts(session_dir: Path, *, view: str = "full") -> tuple[SessionTranscript, ...]:
    transcripts = _discover_pi_session_transcripts(session_dir)
    if not transcripts:
        transcripts = _discover_harness_transcripts(session_dir)

    if view == "full":
        return transcripts
    if view == "orch":
        return tuple(transcript for transcript in transcripts if transcript.kind in {"main", "parent"})
    raise ValueError(f"unknown session transcript view: {view}")


def _shorten(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _fmt_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    return _shorten(text)


def _summary_from_mapping(mapping: dict[str, Any], *, skip: set[str] | None = None, limit: int = 4) -> str:
    skip = skip or set()
    parts: list[str] = []
    for key, value in mapping.items():
        if key in skip:
            continue
        parts.append(f"{key}={_fmt_value(value)}")
        if len(parts) >= limit:
            break
    return " ".join(parts)


def _split_lines(text: str) -> list[str]:
    lines = text.splitlines()
    return lines or [""]


def _indent(lines: Iterable[str], prefix: str) -> list[str]:
    return [f"{prefix}{line}" if line else prefix.rstrip() for line in lines]


def _block(title: str, lines: Iterable[str], *, plain: bool) -> list[str]:
    rendered = list(lines)
    if plain:
        body = [f"[{title}]"]
        body.extend(rendered or ["(empty)"])
        return body
    body = [f"╭─ {title}"]
    if rendered:
        body.extend(_indent(rendered, "│ "))
    else:
        body.append("│ (empty)")
    body.append("╰─")
    return body


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _render_header(transcript: SessionTranscript, *, plain: bool, color: bool) -> list[str]:
    title = f"session {transcript.kind}"
    if not plain:
        title = _color(title, "1", color)
    header = [
        f"file: {transcript.path.name}",
        f"session_id: {transcript.session_id or 'n/a'}",
    ]
    return _block(title, header, plain=plain)


def _render_message_content(message: dict[str, Any], *, no_tools: bool, plain: bool) -> list[str]:
    role = str(message.get("role") or "message")
    content = message.get("content") or []
    lines: list[str] = []

    if role.lower().startswith("tool") and no_tools:
        return []
    if not isinstance(content, list):
        summary = _fmt_value(content)
        if summary:
            lines.append(f"content: {summary}")
        return _block(role, lines, plain=plain) if lines else []

    for item in content:
        if not isinstance(item, dict):
            if not no_tools:
                lines.extend(_split_lines(_shorten(str(item))))
            continue
        item_type = str(item.get("type") or "")
        if item_type == "text":
            text = str(item.get("text") or "")
            if text:
                lines.extend(_split_lines(text))
            continue
        if item_type == "thinking":
            text = str(item.get("thinking") or item.get("text") or "")
            if text:
                lines.extend(_indent(_split_lines(text), "thinking: "))
            continue
        if item_type in {"toolCall", "tool_call", "toolResult", "tool_result"}:
            if no_tools:
                continue
            label = "tool-call" if "Call" in item_type or "call" in item_type else "tool-result"
            payload = item.get("arguments") if "Call" in item_type or "call" in item_type else item.get("content")
            if isinstance(payload, dict):
                summary = _summary_from_mapping(payload)
            elif isinstance(payload, list):
                summary = _shorten(" ".join(_fmt_value(value) for value in payload))
            else:
                summary = _fmt_value(payload)
            name = item.get("name") or item.get("toolName") or item.get("tool") or ""
            prefix = f"{label}: {name}".rstrip()
            lines.append(f"{prefix} {summary}".rstrip())
            continue
        if no_tools and _shorten(item_type).startswith("tool"):
            continue
        lines.append(f"{item_type}: {_summary_from_mapping(item)}".rstrip())

    if not lines:
        return []
    return _block(role, lines, plain=plain)


def _render_custom_event(event: dict[str, Any], *, no_tools: bool, plain: bool, color: bool) -> list[str]:
    custom_type = str(event.get("customType") or event.get("type") or "custom")
    if no_tools and "tool" in custom_type.lower():
        return []
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    text = str(data.get("text") or "") if isinstance(data, dict) else ""
    if text:
        lines = _split_lines(text)
    elif isinstance(data, dict):
        summary = _summary_from_mapping(data)
        lines = [summary] if summary else ["(empty)"]
    else:
        lines = [_fmt_value(data)]
    title = custom_type
    if not plain:
        title = _color(title, "35", color)
    return _block(title, lines, plain=plain)


def _render_event(event: dict[str, Any], *, no_tools: bool, plain: bool, color: bool) -> list[str]:
    event_type = str(event.get("type") or "")
    if event_type == "session":
        session_id = str(event.get("id") or event.get("session_id") or "")
        cwd = str(event.get("cwd") or "")
        lines = [f"session_id: {session_id or 'n/a'}"]
        if cwd:
            lines.append(f"cwd: {cwd}")
        return _block("session", lines, plain=plain)
    if event_type == "model_change":
        lines = [
            f"provider: {_fmt_value(event.get('provider'))}",
            f"model: {_fmt_value(event.get('modelId') or event.get('model'))}",
        ]
        return _block("model_change", lines, plain=plain)
    if event_type == "thinking_level_change":
        return _block("thinking_level_change", [f"thinkingLevel: {_fmt_value(event.get('thinkingLevel'))}"], plain=plain)
    if event_type == "message":
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        if not message:
            return _block("message", [_summary_from_mapping(event, skip={"type", "id", "parentId", "timestamp", "message"})], plain=plain)
        rendered = _render_message_content(message, no_tools=no_tools, plain=plain)
        if rendered:
            return rendered
        return []
    if event_type in {"tool_execution_start", "tool_execution_end", "agent_start", "agent_end", "agent_settled"}:
        if no_tools and "tool" in event_type:
            return []
        return _block(event_type, [_summary_from_mapping(event, skip={"type", "id", "parentId", "timestamp"})], plain=plain)
    if event_type == "custom":
        return _render_custom_event(event, no_tools=no_tools, plain=plain, color=color)
    if event_type == "raw":
        if "line" in event:
            return _block("raw", [_shorten(str(event.get("line") or ""), 160)], plain=plain)
        return _block("raw", [_fmt_value(event.get("value"))], plain=plain)

    summary = _summary_from_mapping(event, skip={"type", "id", "parentId", "timestamp"})
    if not summary:
        summary = "(unrenderable event)"
    return _block(event_type or "event", [summary], plain=plain)


def render_session_transcript(
    transcript: SessionTranscript,
    *,
    no_tools: bool = False,
    plain: bool = False,
    color: bool = False,
) -> str:
    lines = _render_header(transcript, plain=plain, color=color)
    for event in transcript.events:
        rendered = _render_event(event, no_tools=no_tools, plain=plain, color=color)
        if rendered:
            lines.append("")
            lines.extend(rendered)
    return "\n".join(lines).rstrip() + "\n"


def format_session_debug(
    session_dir: Path,
    *,
    view: str = "orch",
    no_tools: bool = False,
    plain: bool = False,
    no_color: bool = False,
    isatty: bool | None = None,
) -> str:
    transcripts = discover_session_transcripts(session_dir, view="full")
    if view == "orch":
        transcripts = tuple(transcript for transcript in transcripts if transcript.kind in {"main", "parent"})
    elif view != "full":
        raise ValueError(f"unknown session transcript view: {view}")

    use_color = bool(isatty if isatty is not None else sys.stdout.isatty()) and not no_color and not plain
    body = [f"=== session transcripts ({view}) ==="]
    if not transcripts:
        body.append("no session transcripts found")
        return "\n".join(body) + "\n"

    for index, transcript in enumerate(transcripts):
        if index:
            body.append("")
        body.extend(render_session_transcript(transcript, no_tools=no_tools, plain=plain, color=use_color).rstrip().splitlines())
    return "\n".join(body).rstrip() + "\n"


def format_session_raw(session_dir: Path) -> str:
    transcripts = discover_session_transcripts(session_dir, view="full")
    body = ["=== session transcripts (raw) ==="]
    if not transcripts:
        body.append("no session transcripts found")
        return "\n".join(body) + "\n"

    for index, transcript in enumerate(transcripts):
        if index:
            body.append("")
        body.append(f"path: {transcript.path}")
        try:
            raw_text = transcript.path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            body.append("(missing)")
            continue
        raw_lines = raw_text.rstrip("\n").splitlines()
        body.extend(raw_lines or ["(empty)"])
    return "\n".join(body).rstrip() + "\n"


__all__ = [
    "SessionTranscript",
    "classify_session",
    "discover_session_transcripts",
    "format_session_debug",
    "format_session_raw",
    "render_session_transcript",
]
