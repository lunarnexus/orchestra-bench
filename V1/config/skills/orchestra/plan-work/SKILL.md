---
name: plan-work
description: Convert scoped, researched software work into executable slices with files, tests, risks, verification, and dependency markers.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, planning, slices, architecture]
    related_skills: [scope-work, research-first, spike, verify-work]
---

# Plan Work

Use this skill after scope and research are clear. Produce an executable plan that a smaller builder model can follow without inventing scope.

Professional goal: turn decisions and evidence into small, verifiable implementation units.

## Planning guardrail

Planning is not implementation. Use read-only inspection and research as needed, then stop with a plan.

## Plan shape

```md
# Plan

## Goal

## Acceptance Criteria

## Context / Assumptions

## Files to Change

## Design Notes

## Task Breakdown

## Tests to Add or Update

## Verification

## Risks

## Open Questions
```

## Scope-work -> slice-tasks -> plan-work

1. Confirm scope and success criteria.
2. Confirm research evidence and unresolved unknowns.
3. Decide whether a spike is needed.
4. Create vertical slices.
5. Add files, tests, risks, and verification.
6. Mark dependencies.
7. Identify reviewer/security checkpoints.

## Vertical slices

Prefer thin end-to-end slices that produce observable behavior.

A good first slice is often a **tracer bullet**: the smallest real path through the system that proves integration points.

Avoid broad horizontal layers unless the work is explicitly foundation, migration, or infrastructure.

## Slice template

```md
- [ ] Slice N — sequential|parallel-safe|blocked — <verb + narrow goal>
  Scope: <exact files/modules/behavior>
  Stop when: <observable stop condition>
  Verify: <command or inspection>
  Risk: P0|P1|P2|P3 — <why>
```

Risk tiers:
- **P0**: critical data/security/production path; strongest verification.
- **P1**: important user-visible behavior; tests and review required.
- **P2**: normal feature/internal change; focused tests and relevant checks.
- **P3**: low-risk docs/config/small cleanup; lightweight verification.

## Dependency markers

- **sequential** — depends on prior work.
- **parallel-safe** — can run with other work because files/modules are separate and no output dependency exists.
- **blocked** — needs answer, decision, evidence, or artifact first.

Parallel-safe excludes shared schemas, migrations, public APIs, global config, broad refactors, and tests depending on unwritten implementation.

## TDD-ready planning

For behavior changes and bug fixes, include:
- expected failing test or repro
- focused test file
- behavior/public interface under test
- Red -> Green -> Refactor sequence
- regression test for bug fixes

## Verification planning

Each implementation slice needs a verify path. Use focused checks first, broader checks at useful boundaries.

Plan reviewer/security gates:
- verifier after behavior exists
- reviewer after step/phase
- security after security-sensitive work or before ship

## Output

Return:
- artifacts changed or plan drafted
- summary of approach
- slices with dependency markers
- open questions/blockers
- recommended next action
