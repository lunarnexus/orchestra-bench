---
name: systematic-debugging
description: Debug failures by reproducing, isolating, forming falsifiable hypotheses, fixing root cause, and adding regression protection.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, debugging, rca, bug-fix]
    related_skills: [build-tdd, verify-work]
---

# Systematic Debugging

Use this skill for failing tests, bug reports, regressions, flaky behavior, or unclear runtime failures.

Professional goal: fix root cause, not symptoms.

## Debugging flow

1. Reproduce the failure.
2. Capture the exact red command, input, or scenario.
3. Minimize the reproduction.
4. Check recent changes.
5. Trace data flow across boundaries.
6. Compare working and failing examples.
7. Form ranked falsifiable hypotheses.
8. Test one hypothesis at a time.
9. Identify root cause.
10. Add or update a regression test.
11. Fix minimally.
12. Verify focused and broader checks.

## Reproduction

Capture:
- command or steps
- expected result
- actual result
- relevant logs/output
- environment assumptions
- whether it is deterministic or flaky

If reproduction is unavailable, focus first on building one.

## Minimize

Reduce the failure to the smallest case that still fails:
- smallest input
- narrowest test
- fewest components
- shortest command
- simplest fixture

A minimal repro makes hypotheses cheaper to test.

## Hypotheses

Write hypotheses as falsifiable statements:

```md
H1: The CLI rejects `yes` because role toggles use a strict true/false parser.
Test: run role toggle command with `yes`; inspect parser call path.
```

Rank by likelihood and cheapness to test.

## One variable at a time

Change one thing, test, record result. This prevents accidental passing changes that hide the real cause.

## RCA output

Root Cause Analysis should identify:
- root cause
- contributing factors
- why existing tests/checks missed it
- corrective action
- preventive action or regression test

## Rule of three

After three failed fix attempts, pause and question assumptions, architecture, reproduction, or ownership. Escalate or replan instead of continuing random patches.

## Debug logs

Temporary debug logs should be uniquely tagged so they can be found and removed.

Example tag: `DEBUG_ORCH_BOOL_PARSE_20260803`.

## Output

```md
## Debugging Result

Repro:
- ...

Root cause:
- ...

Hypotheses tested:
- H1 — result
- H2 — result

Fix:
- ...

Regression protection:
- ...

Verification:
- command — result

Remaining risk:
- ...
```
