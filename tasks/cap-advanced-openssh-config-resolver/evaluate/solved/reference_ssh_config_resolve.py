#!/usr/bin/env python3
"""Evaluator-only reference for cap-advanced-openssh-config-resolver.

This is not agent-visible. It delegates the supported subset to the exact
OpenSSH oracle used by the evaluator: `ssh -G -F CONFIG HOST`, then normalizes
that output into the task JSON contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess as sp
import sys

COMPARE_KEYS = ["hostname", "user", "port", "identityfile", "proxycommand", "forwardagent", "compression"]


def parse_ssh_g(stdout: str, host: str) -> dict:
    result: dict[str, object] = {
        "host": host,
        "hostname": None,
        "user": None,
        "port": None,
        "identityfile": [],
        "proxycommand": None,
        "forwardagent": None,
        "compression": None,
    }
    for raw in stdout.splitlines():
        if not raw.strip() or " " not in raw:
            continue
        key, value = raw.split(" ", 1)
        key = key.lower()
        if key not in COMPARE_KEYS:
            continue
        if key == "identityfile":
            result["identityfile"].append(value)
        elif key == "port":
            result["port"] = int(value)
        elif key in {"forwardagent", "compression"}:
            result[key] = value.lower() == "yes"
        elif key == "proxycommand":
            result[key] = None if value.lower() == "none" else value
        else:
            result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    ssh = shutil.which("ssh")
    if not ssh:
        print("ssh not found", file=sys.stderr)
        return 127
    proc = sp.run([ssh, "-G", "-F", args.config, args.host], text=True, stdout=sp.PIPE, stderr=sp.PIPE)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    print(json.dumps(parse_ssh_g(proc.stdout, args.host), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
