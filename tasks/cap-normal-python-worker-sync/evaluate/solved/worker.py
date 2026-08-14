from __future__ import annotations

import argparse
import json

import sync_core


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued sync jobs")
    parser.add_argument("--once", action="store_true", help="process at most one available job")
    parser.add_argument("--drain", action="store_true", help="keep processing until no work remains")
    args = parser.parse_args()

    result = sync_core.run_worker(drain=args.drain, max_jobs=None if args.drain else 1)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
