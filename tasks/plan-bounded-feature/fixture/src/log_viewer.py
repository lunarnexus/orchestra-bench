#!/usr/bin/env python3
"""log-viewer — read JSON-lines log files and print entries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MISSING = object()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="log-viewer",
        description="View JSON-lines log files.",
    )
    parser.add_argument("logfile", help="Path to JSON-lines log file")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Limit output to N entries (default: all)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="FIELD:VALUE",
        help="Only show entries where the field path matches the value. May be repeated.",
    )
    return parser.parse_args(argv)


def parse_filter_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError(f"invalid filter spec {spec!r}; expected FIELD:VALUE")
    field_path, expected = spec.split(":", 1)
    if not field_path:
        raise ValueError(f"invalid filter spec {spec!r}; field path cannot be empty")
    return field_path, expected


def resolve_field_path(entry: object, field_path: str):
    current = entry
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def read_entries(path: Path, count: int | None = None):
    """Yield parsed JSON objects from a .jsonl file."""
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            yield json.loads(line), i + 1
            if count and i + 1 >= count:
                break


def format_entry(entry: dict, lineno: int) -> str:
    """Return a readable string for one log entry."""
    ts = entry.get("timestamp", "?")
    level = entry.get("level", "—").upper()
    msg = entry.get("message", "")
    return f"[{lineno}] {ts}  {level:5s}  {msg}"


def entry_matches_filters(entry: dict, filters: list[tuple[str, str]], lineno: int) -> bool:
    for field_path, expected in filters:
        actual = resolve_field_path(entry, field_path)
        if actual is MISSING:
            print(f"Warning: missing field path {field_path!r} on line {lineno}", file=sys.stderr)
            return False
        if str(actual) != expected:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.logfile)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    try:
        filters = [parse_filter_spec(spec) for spec in args.filter]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    for entry, lineno in read_entries(path, count=args.count):
        if filters and not entry_matches_filters(entry, filters, lineno):
            continue
        print(format_entry(entry, lineno))
    return 0


if __name__ == "__main__":
    sys.exit(main())
