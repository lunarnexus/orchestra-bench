---
name: review-code
description: Independently review code changes for correctness, scope, maintainability, simplification, tests, and material risks.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, review, quality, maintainability]
    related_skills: [verify-work, security-review, commit-clean]
---

# Review Code

Use this skill after implementation and verification evidence exist. Review independently with fresh context.

Professional goal: catch material issues before commit, merge, push, or ship.

## Inputs

Read what matters:
- user request / scope
- plan and acceptance criteria
- changed files or diff
- tests/checks already run
- project instructions
- nearby code conventions
- relevant research/design notes

## Review checks

Check:
- correctness
- acceptance criteria
- scope control
- test quality
- edge cases that matter now
- error handling
- maintainability
- reuse of existing helpers/patterns
- unnecessary abstraction
- duplication
- dead code
- hidden public contract changes
- overcomplication

## Evidence discipline

Search codebase evidence before judging. Use file/line refs, diff hunks, command output, or project conventions.

Apply Chesterton's Fence before recommending removal: understand why the code exists.

Skip nits and style churn unless the project explicitly requires them.

## Simplification triage

Classify cleanup ideas:

- **SAFE** — low-risk, clear benefit.
- **CAREFUL** — useful but needs tests/context.
- **RISKY** — may change behavior; defer unless scoped.

Conflict priority:

1. correctness
2. requested scope/focus
3. readability and reuse
4. micro-performance

## Common agent-code smells

- redundant state
- parameter sprawl
- copy-paste-with-variation
- leaky abstractions
- stringly typed logic
- pass-through wrappers
- commented-out code
- redundant casts/assertions
- debug prints
- silent failures
- broad refactor outside scope
- tests of implementation details only

## Findings

Each finding needs:
- severity: HIGH / MEDIUM / LOW
- file:line when available
- evidence
- suggested fix

Severity:
- **HIGH**: wrong behavior, regression, major missing check, security issue.
- **MEDIUM**: relevant edge case, weak test, maintainability problem.
- **LOW**: non-blocking cleanup or future improvement.

## Output

```md
## Code Review Report

Verdict:
- pass / fail / pass with notes

Blocking findings:
- HIGH/MEDIUM — `file:line` — problem — evidence — fix

Non-blocking findings:
- LOW — `file:line` — issue — suggestion

Checks/evidence inspected:
- ...

Missing evidence:
- ...

Readiness:
- ready / not ready / ready after fixes
```
