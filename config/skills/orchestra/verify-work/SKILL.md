---
name: verify-work
description: Verify software changes with risk-scaled checks, real command evidence, baseline-failure distinction, and clear residual risk.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, verification, testing, quality]
    related_skills: [build-tdd, review-code, security-review]
---

# Verify Work

Use this skill after implementation or debugging. Produce evidence about whether the work satisfies the target behavior.

Professional goal: make readiness factual.

## Verification source order

Find commands/checks from:

1. `AGENTS.md`
2. CI config
3. README/contributor docs
4. package/build config
5. nearby test conventions
6. project history or common framework defaults

## Risk-scaled verification

Scale checks to risk:

- **P0 critical**: data/security/production path. Run focused tests, broad relevant suite, migration/security validation, and smoke/UAT where useful.
- **P1 important**: user-visible or core behavior. Run focused tests plus relevant suite/review gate.
- **P2 normal**: internal feature/fix. Run focused tests and relevant lint/type checks.
- **P3 low-risk**: docs/config/small cleanup. Inspect output or run lightweight check.

## Verification method

1. Identify acceptance criteria.
2. Identify changed files and risk tier.
3. Choose focused check first.
4. Run relevant broader checks.
5. Distinguish baseline failures from new failures.
6. Record commands and exact outcomes.
7. Note missing checks and why.
8. State verdict and residual risk.

## Baseline failures

If a check was already failing before the change:
- report it as baseline
- explain how you know
- do not hide it
- block only on new failures unless project policy says otherwise

## Human-runnable smoke tests

For manual smoke tests, include:
- command/steps
- expected result
- actual result
- reason manual/scripting was used

## Terminal verdict evidence

When practical, include at least one real command result from a contiguous run.

## Output

```md
## Verification Report

Verdict:
- pass / fail / blocked / pass with notes

Acceptance criteria checked:
- ...

Commands run:
- `<command>` — pass/fail — <summary>

Baseline failures:
- ...

New failures:
- ...

Missing checks:
- <check> — <reason>

Residual risk:
- ...

Readiness:
- ready / not ready / ready after listed fixes
```

Do not claim a check passed unless it was run successfully.
