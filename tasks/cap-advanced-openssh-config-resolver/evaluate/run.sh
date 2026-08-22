#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
import tempfile
from collections import Counter
from pathlib import Path

TASK_ID = "cap-advanced-openssh-config-resolver"
COMPARE_KEYS = ["hostname", "user", "port", "identityfile", "proxycommand", "forwardagent", "compression"]


def workspace() -> Path:
    return Path(os.environ.get("BENCH_WORKDIR") or os.getcwd()).resolve()


def run(cmd, cwd: Path, timeout=10):
    return sp.run(cmd, cwd=cwd, text=True, stdout=sp.PIPE, stderr=sp.PIPE, timeout=timeout)


def call_tool(ws: Path, cfg: Path, host: str):
    proc = run(["python3", "ssh_config_resolve.py", "--config", str(cfg), "--host", host], ws)
    if proc.returncode != 0:
        return proc, None
    try:
        data = json.loads(proc.stdout)
        return proc, normalize_candidate(data, host)
    except Exception:
        return proc, None


def bool_or_none(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.lower()
        if low in {"yes", "true", "on", "1"}:
            return True
        if low in {"no", "false", "off", "0"}:
            return False
    return value


def normalize_candidate(data: dict, host: str) -> dict:
    out = {"host": data.get("host", host)}
    for key in COMPARE_KEYS:
        val = data.get(key)
        if key == "port" and val is not None:
            try:
                val = int(val)
            except Exception:
                pass
        elif key in {"forwardagent", "compression"}:
            val = bool_or_none(val)
        elif key == "identityfile":
            val = list(val or [])
        out[key] = val
    return out


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


def oracle(ssh_bin: str, ws: Path, cfg: Path, host: str):
    proc = run([ssh_bin, "-G", "-F", str(cfg), host], ws)
    if proc.returncode != 0:
        return proc, None
    return proc, parse_ssh_g(proc.stdout, host)


def evidence_score(ws: Path) -> tuple[dict[str, object], float]:
    checks: dict[str, object] = {}
    total = 0.0
    names = ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]
    anchors = ["openssh", "ssh -g", "host", "include", "precedence", "config", "parse", "test", "security"]
    for name in names:
        p = ws / name
        present = p.exists()
        text = p.read_text(errors="replace") if present else ""
        words = len(text.split())
        relevant = present and words >= 25 and sum(a in text.lower() for a in anchors) >= 2
        checks[f"{name[:-3].lower()}_present"] = present
        checks[f"{name[:-3].lower()}_relevant"] = relevant
        total += 1.0 if relevant else 0.0
    return checks, total / len(names)


def compare_dict(candidate: dict, expected: dict) -> list[str]:
    errors: list[str] = []
    if candidate.get("host") != expected.get("host"):
        errors.append(f"host: expected {expected.get('host')!r}, got {candidate.get('host')!r}")
    for key in COMPARE_KEYS:
        if candidate.get(key) != expected.get(key):
            errors.append(f"{key}: expected {expected.get(key)!r}, got {candidate.get(key)!r}")
    return errors


def main():
    ws = workspace()
    checks: dict[str, object] = {}
    details: dict[str, object] = {"failed_cases": []}

    ssh_bin = shutil.which("ssh")
    checks["openssh_client_available"] = bool(ssh_bin)

    syntax = run(["python3", "-m", "py_compile", "ssh_config_resolve.py"], ws)
    checks["syntax_ok"] = syntax.returncode == 0
    details["syntax_stderr"] = syntax.stderr[-2000:]

    passed = total = oracle_ok = 0
    failed_by_case_type: Counter[str] = Counter()
    failed_by_key: Counter[str] = Counter()
    if ssh_bin:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            incdir = t / "inc"
            incdir.mkdir()
            (incdir / "10-extra.conf").write_text("""
Host *.include.test
    User include-user
    Compression yes
Host included-special
    HostName special.internal
    Port 2201
""".strip() + "\n")
            (incdir / "20-forward.conf").write_text("""
Host forwarded.include.test
    ForwardAgent yes
""".strip() + "\n")
            cfg = t / "main.conf"
            cfg.write_text(f"""
Include {incdir}/*.conf
User global-user

Host exact.example
    HostName exact.internal
    User exact-user
    Port 2200
    IdentityFile ~/.ssh/exact-one
    IdentityFile ~/.ssh/exact-two
    ProxyCommand "ssh -W %h:%p bastion-%r"

Host *.example !blocked.example
    HostName %h.corp
    User wildcard-user
    Port 2222
    ForwardAgent yes

Host bracket[0-9].example
    HostName bracketed.internal
    Compression yes

Host quoted
    HostName quoted.internal
    User "quoted-user"
    Port=2202
    ProxyCommand "ssh -q jump.example nc %h %p"

Host *
    HostName default-%h
    User default-user
    Port 2022
    Compression no
""".strip() + "\n")
            hosts = [
                "exact.example",
                "api.example",
                "blocked.example",
                "foo.include.test",
                "included-special",
                "forwarded.include.test",
                "bracket7.example",
                "quoted",
                "plainhost",
            ]
            for host in hosts:
                total += 1
                oproc, expected = oracle(ssh_bin, ws, cfg, host)
                if expected is not None:
                    oracle_ok += 1
                proc, got = call_tool(ws, cfg, host)
                errs = []
                if expected is None:
                    errs.append(f"ssh -G oracle failed: rc={oproc.returncode} stderr={oproc.stderr[-500:]}")
                if proc.returncode != 0 or got is None:
                    errs.append(f"candidate failed: rc={proc.returncode} stdout={proc.stdout[-500:]} stderr={proc.stderr[-500:]}")
                if expected is not None and got is not None:
                    errs.extend(compare_dict(got, expected))
                if not errs:
                    passed += 1
                else:
                    failed_by_case_type["positive"] += 1
                    for err in errs:
                        failed_by_key[err.split(":", 1)[0]] += 1
                    details["failed_cases"].append({"host": host, "case_type": "positive", "errors": errs, "expected": expected, "candidate": got})

            negative_cases = []
            bad = t / "bad.conf"
            bad.write_text("Host *\n    Port 70000\n")
            negative_cases.append(("invalid_port", bad, "badhost", "port"))
            a = t / "a.conf"; b = t / "b.conf"
            a.write_text(f"Include {b}\nHost *\n User a\n")
            b.write_text(f"Include {a}\n")
            negative_cases.append(("include_cycle", a, "cycle", "recursive"))
            malformed = t / "malformed.conf"
            malformed.write_text("Host *\n    Port\n")
            negative_cases.append(("malformed_option", malformed, "malformed", "port"))

            for name, cfg_path, host, stderr_hint in negative_cases:
                total += 1
                oproc, expected = oracle(ssh_bin, ws, cfg_path, host)
                proc, got = call_tool(ws, cfg_path, host)
                oracle_failed = oproc.returncode != 0
                candidate_failed = proc.returncode != 0
                if oracle_failed:
                    oracle_ok += 1
                if oracle_failed and candidate_failed and stderr_hint.lower() in (proc.stderr or "").lower():
                    passed += 1
                else:
                    failed_by_case_type["negative"] += 1
                    failed_by_key[name] += 1
                    details["failed_cases"].append({
                        "negative": name,
                        "case_type": "negative",
                        "errors": ["candidate did not fail like ssh -G oracle"],
                        "oracle_rc": oproc.returncode,
                        "oracle_stderr": oproc.stderr[-500:],
                        "candidate_rc": proc.returncode,
                        "candidate_stdout": proc.stdout[-500:],
                        "candidate_stderr": proc.stderr[-500:],
                    })

    checks["oracle_cases"] = oracle_ok == total and total > 0
    checks["config_cases"] = passed == total and total > 0
    details["case_passed"] = passed
    details["case_total"] = total
    details["oracle_cases_ok"] = oracle_ok
    details["failed_total"] = total - passed
    details["failed_by_case_type"] = dict(sorted(failed_by_case_type.items()))
    details["failed_by_key"] = dict(sorted(failed_by_key.items()))
    details["compare_keys"] = COMPARE_KEYS

    ev_checks, ev_quality = evidence_score(ws)
    checks.update(ev_checks)

    ratio = passed / total if total else 0.0
    functional = (
        (0.05 if checks["openssh_client_available"] else 0)
        + (0.05 if checks["syntax_ok"] else 0)
        + (0.10 if checks["oracle_cases"] else 0)
        + (0.70 * ratio)
    )
    workflow = 0.10 * ev_quality
    raw_score_numeric = round(functional + workflow, 6)
    pass_core = (
        checks["openssh_client_available"]
        and checks["syntax_ok"]
        and checks["oracle_cases"]
        and checks["config_cases"]
    )
    score_numeric = raw_score_numeric if pass_core else min(raw_score_numeric, 0.849)
    score = "pass" if pass_core and score_numeric >= 0.85 else "fail"

    result = {
        "task_id": TASK_ID,
        "run_id": os.environ.get("BENCH_RUN_ID", "manual"),
        "score": score,
        "score_numeric": score_numeric,
        "checks": checks,
        "details": json.dumps(details, sort_keys=True),
        "rubric": {
            "functional": {"score": round(functional, 6), "max": 0.9, "checks": {k: checks[k] for k in ["openssh_client_available", "syntax_ok", "oracle_cases", "config_cases"]}},
            "workflow": {"score": round(workflow, 6), "max": 0.1},
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
PY
