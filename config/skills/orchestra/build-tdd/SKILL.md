---
name: build-tdd
description: Implement software changes with focused scope, TDD where practical, minimal green code, and safe refactoring.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, build, tdd, implementation]
    related_skills: [plan-work, systematic-debugging, verify-work]
---

# Build TDD

Use this skill to implement approved software work. Stay inside the assigned scope.

Professional goal: protect behavior while making the smallest working change.

## Before coding

Confirm:
- assigned goal
- in-scope and out-of-scope boundaries
- files/modules allowed
- acceptance criteria
- planned tests/checks
- project instructions
- current branch/worktree expectations

If the task has multiple valid interpretations, ask before editing.

## TDD loop

For new behavior and bug fixes, use Red -> Green -> Refactor when practical:

1. **Red** — write a failing test for one behavior.
2. **Verify Red** — run it and confirm expected failure.
3. **Green** — write minimal code to pass.
4. **Verify Green** — run focused test.
5. **Refactor** — improve structure only after green.
6. **Verify again** — run focused and relevant checks.

If literal test-first is impractical, state why and use the closest safe substitute: characterization test, exact repro, or focused manual check.

## Test design

Good tests are:
- behavior-focused
- one behavior per test
- public-interface oriented when possible
- fast
- independent
- repeatable
- self-validating
- timely

Use real code where practical. Use mocks only when they isolate external systems or hard-to-control boundaries.

## Implementation rules

- Make the smallest working change.
- Prefer existing patterns and helpers.
- Preserve public APIs unless the plan says otherwise.
- Add dependencies only when approved or clearly required by plan.
- Keep refactors scoped and behavior-preserving.
- Remove temporary debug output before finishing.
- Never weaken security checks as unrelated cleanup.

## Refactoring discipline

Refactor after green.

Good refactoring targets:
- duplication
- confusing names
- redundant state
- long or tangled functions
- leaky abstractions
- overly broad reads
- silent failures

Every new abstraction needs a reason for depth.

## If tests fail unexpectedly

Switch to systematic debugging:
- reproduce
- minimize
- isolate
- form a hypothesis
- change one thing
- verify root cause

Do not pile multiple guesses into one patch.

## Handoff output

Return:

```md
## Build Result

Files changed:
- ...

Behavior implemented:
- ...

Tests/checks run:
- command — result

Red/Green evidence:
- ...

Blockers:
- ...

Risks:
- ...
```
