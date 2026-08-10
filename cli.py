#!/usr/bin/env python3
"""cli — Command-line entry point for orchestra-bench harness."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on path so eval_harness can be imported
_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    """Dispatch to the harness CLI."""
    # Import here so we don't pollute __main__ namespace at import time
    from eval_harness import main as _harness_main  # noqa: E402

    return _harness_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
