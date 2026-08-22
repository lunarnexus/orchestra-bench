---
name: commit-clean
description: Prepare clean commits or PR handoffs after implementation, verification, review, and security checks are complete.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, git, commit, pr]
    related_skills: [verify-work, review-code, security-review]
---

# Commit Clean

Use this skill at the end of a change before commit, push, or PR.

Professional goal: preserve a clean, factual, reviewable history.

## Preconditions

Before committing, confirm:
- implementation is complete
- focused verification passed
- relevant broader checks passed or failures are disclosed
- review completed for non-trivial work
- security reviewed when relevant
- no unapproved scope creep remains
- no secrets/debug output/temporary files are staged

Explicit WIP commits are allowed only when requested.

## Diff inspection

Inspect:
- `git status`
- staged/unstaged diff
- new/deleted files
- generated files
- config or lockfile changes
- secrets/tokens
- debug logs/prints
- commented-out code
- accidental formatting churn

## Commit grouping

Prefer small coherent commits:
- one feature/fix/doc change per commit
- tests with the behavior they verify
- migrations with related model/schema changes when practical
- avoid mixing unrelated cleanup with behavior changes

## Conventional commit style

Use project convention. If no convention is known, conventional commits are a good default:

```text
type(scope): imperative summary
```

Common types:
- `feat`
- `fix`
- `docs`
- `test`
- `refactor`
- `chore`
- `perf`
- `build`
- `ci`

Examples:

```text
feat(skills): add planner methodology terms
fix(cli): parse boolean toggles consistently
docs: move backlog items to roadmap
```

Keep the summary short, factual, and imperative.

## PR / handoff summary

Include:
- what changed
- why
- tests/checks run
- review/security notes
- migrations or config changes
- known risks or follow-ups

## Final checklist

```md
Implementation: complete
Verification: <commands/results>
Review: <done/skipped with reason>
Security: <done/not relevant/reason>
Diff inspected: yes
Commit message: <message>
Residual risk: <risk or none identified>
```

## Output

Return:

```md
## Commit Prep

Status:
- ready / not ready

Diff summary:
- ...

Checks:
- ...

Review/security:
- ...

Commit message:
- ...

PR summary:
- ...

Blockers:
- ...
```
