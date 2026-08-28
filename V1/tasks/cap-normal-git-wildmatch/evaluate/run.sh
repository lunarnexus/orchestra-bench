#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
from __future__ import annotations

import json
import os
import re
import shlex
from collections import Counter
import shutil
import subprocess as sp
import tempfile
import time
from pathlib import Path

TASK_ID = "cap-normal-git-wildmatch"


def repo_root() -> Path:
    return Path(os.environ.get("BENCH_REPO_ROOT") or Path(__file__).resolve().parents[3]).resolve()


def task_dir() -> Path:
    return repo_root() / "tasks" / TASK_ID


def workspace() -> Path:
    return Path(os.environ.get("BENCH_WORKDIR") or os.getcwd()).resolve()


def run(cmd, cwd: Path, timeout=10):
    try:
        return sp.run(cmd, cwd=cwd, text=True, stdout=sp.PIPE, stderr=sp.PIPE, timeout=timeout)
    except sp.TimeoutExpired as exc:
        return sp.CompletedProcess(
            cmd,
            124,
            stdout=(exc.stdout or ""),
            stderr=((exc.stderr or "") + f"\ntimeout after {timeout}s"),
        )


def evidence_score(ws: Path) -> tuple[dict[str, object], float]:
    checks: dict[str, object] = {}
    total = 0.0
    names = ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]
    anchors = ["wildmatch", "pattern", "pathname", "case", "bracket", "test", "security", "verify"]
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


def logical_lines(path: Path) -> list[str]:
    out: list[str] = []
    buf = ""
    for line in path.read_text(errors="replace").splitlines():
        if buf:
            buf += line
        else:
            buf = line
        if buf.rstrip().endswith("\\"):
            buf = buf.rstrip()[:-1] + " "
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return out


def parse_upstream_match_cases(t3070: Path) -> tuple[list[dict[str, object]], int]:
    """Parse Git t3070 `match ...` lines mechanically.

    Git's helper uses expectation columns:
      1 glob/wildmatch
      2 case-insensitive wildmatch
      3 pathname/pathmatch
      4 case-insensitive pathmatch
    Some lines include four additional filesystem/git-ls-files expectations; those
    are intentionally ignored because this benchmark exercises only the pure
    wildmatch function through a standalone CLI.
    """
    cases: list[dict[str, object]] = []
    skipped_e = 0
    modes = ["wildmatch", "iwildmatch", "pathmatch", "ipathmatch"]
    for lineno, line in enumerate(logical_lines(t3070), 1):
        stripped = line.strip()
        if not stripped.startswith("match "):
            continue
        parts = shlex.split(stripped, posix=True)
        if len(parts) not in (7, 11) or parts[0] != "match":
            raise ValueError(f"cannot parse upstream match line {lineno}: {line!r}")
        expectations = parts[1:5]
        text = parts[-2]
        pattern = parts[-1]
        for mode, expect in zip(modes, expectations):
            if expect == "E":
                skipped_e += 1
                continue
            if expect not in ("0", "1"):
                raise ValueError(f"unexpected upstream expectation {expect!r} on line {lineno}")
            cases.append({"line": lineno, "mode": mode, "text": text, "pattern": pattern, "expected": expect == "1"})
    return cases, skipped_e


def write_reference_workspace(refdir: Path, solved: Path, fixture_main: Path) -> None:
    shutil.copy2(solved / "upstream-wildmatch.c", refdir / "wildmatch.c")
    shutil.copy2(solved / "upstream-wildmatch.h", refdir / "wildmatch.h")
    shutil.copy2(fixture_main, refdir / "main.c")
    # Minimal compatibility shim needed to compile Git's exact wildmatch.c
    # outside the full Git tree. The upstream wildmatch.c file itself is copied
    # byte-for-byte and left unchanged.
    (refdir / "git-compat-util.h").write_text(
        "#ifndef GIT_COMPAT_UTIL_H\n"
        "#define GIT_COMPAT_UTIL_H\n"
        "#include <ctype.h>\n"
        "#include <stddef.h>\n"
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "#include <string.h>\n"
        "static inline int is_glob_special(int c) {\n"
        "    return c == '*' || c == '?' || c == '[' || c == '\\\\';\n"
        "}\n"
        "#endif\n"
    )
    (refdir / "Makefile").write_text(
        """CC ?= cc\nCFLAGS ?= -Wall -Wextra -O2\n\nall: wildmatch-cli\n\nwildmatch-cli: main.o wildmatch.o\n\t$(CC) $(CFLAGS) -o $@ main.o wildmatch.o\n\nmain.o: main.c wildmatch.h\nwildmatch.o: wildmatch.c wildmatch.h git-compat-util.h\n\nclean:\n\trm -f *.o wildmatch-cli\n"""
    )


def feature_hints(text: str, pattern: str) -> list[str]:
    hints: list[str] = []
    if "[" in pattern:
        hints.append("bracket")
    if "**" in pattern:
        hints.append("double_star")
    if "/" in text and any(ch in pattern for ch in "*?["):
        hints.append("pathname_slash")
    if "[:" in pattern:
        hints.append("posix_class")
    if "\\" in pattern:
        hints.append("escape")
    if not hints:
        hints.append("other")
    return hints


def cli_match(binary: Path, mode: str, text: str, pattern: str, cwd: Path, timeout=3) -> tuple[bool | None, int, str]:
    proc = run([str(binary), mode, text, pattern], cwd, timeout=timeout)
    if proc.returncode == 0:
        return True, proc.returncode, proc.stderr
    if proc.returncode == 1:
        return False, proc.returncode, proc.stderr
    return None, proc.returncode, proc.stderr


def main():
    ws = workspace()
    root = repo_root()
    solved = root / "solved"
    if not solved.is_dir():
        solved = root / "tasks" / TASK_ID / "evaluate" / "solved"
    t3070 = solved / "upstream-t3070-wildmatch.sh"
    checks: dict[str, object] = {}
    details: dict[str, object] = {}

    cases, skipped_e = parse_upstream_match_cases(t3070)
    checks["upstream_t3070_loaded"] = len(cases) >= 700
    details["upstream_cases_loaded"] = len(cases)
    details["upstream_E_cases_skipped"] = skipped_e

    build = run(["make", "clean", "all"], ws, timeout=20)
    checks["builds"] = build.returncode == 0 and (ws / "wildmatch-cli").exists()
    details["build_stdout"] = build.stdout[-2000:]
    details["build_stderr"] = build.stderr[-2000:]

    reference_built = False
    reference_build_stderr = ""
    reference_build_stdout = ""
    failed_cases: list[dict[str, object]] = []
    failed_by_mode: Counter[str] = Counter()
    failed_by_feature_hint: Counter[str] = Counter()
    compared = matched_reference = matched_upstream_expectations = 0

    with tempfile.TemporaryDirectory(prefix="wildmatch-ref-") as tmp:
        refdir = Path(tmp)
        write_reference_workspace(refdir, solved, ws / "main.c")
        ref_build = run(["make", "clean", "all"], refdir, timeout=20)
        reference_built = ref_build.returncode == 0 and (refdir / "wildmatch-cli").exists()
        reference_build_stdout = ref_build.stdout[-2000:]
        reference_build_stderr = ref_build.stderr[-2000:]

        if checks["builds"] and reference_built:
            candidate_bin = ws / "wildmatch-cli"
            reference_bin = refdir / "wildmatch-cli"
            for case in cases:
                compared += 1
                mode = str(case["mode"])
                text = str(case["text"])
                pattern = str(case["pattern"])
                upstream_expected = bool(case["expected"])
                cand, cand_rc, cand_err = cli_match(candidate_bin, mode, text, pattern, ws)
                ref, ref_rc, ref_err = cli_match(reference_bin, mode, text, pattern, refdir)
                if ref == upstream_expected:
                    matched_upstream_expectations += 1
                if cand == ref:
                    matched_reference += 1
                else:
                    failed_by_mode[mode] += 1
                    hints = feature_hints(text, pattern)
                    for hint in hints:
                        failed_by_feature_hint[hint] += 1
                    failed_cases.append({
                        "line": case["line"],
                        "mode": mode,
                        "text": text,
                        "pattern": pattern,
                        "feature_hints": hints,
                        "candidate": cand,
                        "candidate_rc": cand_rc,
                        "reference": ref,
                        "reference_rc": ref_rc,
                        "upstream_expected": upstream_expected,
                        "candidate_stderr": cand_err[-500:],
                        "reference_stderr": ref_err[-500:],
                    })

            start = time.monotonic()
            proc = run([str(candidate_bin), "wildmatch", "a" * 58 + "b", "*a*a*a*a*a*a*a*a*a*a*a*a*a*a*a*a"], ws, timeout=3)
            elapsed = time.monotonic() - start
            checks["performance_guard"] = elapsed < 2.5 and proc.returncode in (0, 1)
        else:
            checks["performance_guard"] = False

    checks["reference_builds"] = reference_built
    checks["reference_matches_upstream_expectations"] = matched_upstream_expectations == compared and compared > 0
    checks["wildmatch_matches_reference"] = matched_reference == compared and compared > 0
    checks["wildmatch_vectors"] = checks["wildmatch_matches_reference"]
    details["reference_build_stdout"] = reference_build_stdout
    details["reference_build_stderr"] = reference_build_stderr
    details["cases_compared"] = compared
    details["cases_matching_reference"] = matched_reference
    details["reference_cases_matching_upstream_expectations"] = matched_upstream_expectations
    details["failed_total"] = len(failed_cases)
    details["failed_by_mode"] = dict(sorted(failed_by_mode.items()))
    details["failed_by_feature_hint"] = dict(sorted(failed_by_feature_hint.items()))
    details["failed_cases"] = failed_cases[:30]

    ev_checks, ev_quality = evidence_score(ws)
    checks.update(ev_checks)

    if compared:
        reference_ratio = matched_reference / compared
    else:
        reference_ratio = 0.0
    functional = (
        (0.10 if checks["builds"] else 0)
        + (0.10 if checks["reference_builds"] and checks["upstream_t3070_loaded"] else 0)
        + (0.65 * reference_ratio)
        + (0.05 if checks["performance_guard"] else 0)
    )
    workflow = 0.10 * ev_quality
    raw_score_numeric = round(functional + workflow, 6)
    pass_core = (
        checks["builds"]
        and checks["reference_builds"]
        and checks["upstream_t3070_loaded"]
        and checks["reference_matches_upstream_expectations"]
        and checks["wildmatch_matches_reference"]
        and checks["performance_guard"]
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
            "functional": {
                "score": round(functional, 6),
                "max": 0.9,
                "checks": {k: checks[k] for k in [
                    "builds",
                    "reference_builds",
                    "upstream_t3070_loaded",
                    "reference_matches_upstream_expectations",
                    "wildmatch_matches_reference",
                    "performance_guard",
                ]},
            },
            "workflow": {"score": round(workflow, 6), "max": 0.1},
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
PY
