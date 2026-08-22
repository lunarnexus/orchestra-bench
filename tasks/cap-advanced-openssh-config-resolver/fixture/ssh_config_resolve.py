#!/usr/bin/env python3
"""Standalone OpenSSH-style client config resolver.

TODO: implement the behavior described in PRD.md.
"""

from __future__ import annotations

import argparse
import json


def resolve_config(config_path: str, host: str) -> dict:
    return {
        "host": host,
        "hostname": host,
        "user": None,
        "port": 22,
        "identityfile": [],
        "proxycommand": None,
        "forwardagent": None,
        "compression": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    print(json.dumps(resolve_config(args.config, args.host), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
