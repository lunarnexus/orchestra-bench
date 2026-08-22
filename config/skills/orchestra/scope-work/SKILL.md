---
name: scope-work
description: Clarify a software request into scope, success criteria, constraints, exclusions, and open questions before research, planning, or coding.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, scope, requirements, planning]
    related_skills: [research-first, plan-work]
---

# Scope Work

Use this skill at intake. Convert a request into a clear engineering target before research, planning, or implementation.

Professional goal: reduce ambiguity early so later agents do not invent scope.

## When to use

Use for:
- new feature requests
- bug reports with unclear expected behavior
- refactors or cleanup requests
- multi-file or multi-step work
- requests that include tradeoffs, constraints, or hidden decisions

For tiny obvious edits, do a compact scope pass in your head and report the scope briefly.

## Inputs to inspect

Read only what is needed to clarify the request:
- user request
- project instructions such as `AGENTS.md`
- existing plan/artifact docs if present
- nearby README/docs/issues when they define expected behavior
- current code/tests only if required to understand scope

## Scope fields

Produce or update:

```md
## Scope

Goal:
- <one-sentence outcome>

In scope:
- <included behavior/work>

Out of scope:
- <excluded item> — <reason>

Success criteria:
- <observable result>

Constraints:
- <compatibility/security/performance/API/deadline/etc.>

Assumptions:
- <assumption and why it is reasonable>

Open questions:
1. <question that blocks planning or implementation>
```

## Method

1. Restate the user outcome in plain language.
2. Identify the actor or system that observes the change.
3. Separate **what/why** from **how**.
4. List in-scope work.
5. List out-of-scope work with a short reason.
6. Convert vague goals into observable success criteria.
7. Identify constraints and risks.
8. Record assumptions only when they are safe and reversible.
9. Ask numbered questions for blockers.
10. Map each in-scope item to a future research item, spike, plan slice, or explicit deferral.

## Requirement deltas

For changed behavior, use deltas when helpful:

- `ADDED`: new behavior
- `MODIFIED`: changed behavior, with before/after
- `REMOVED`: deleted behavior
- `RENAMED`: name/API/UI change

Example:

```md
MODIFIED: `/orch roles ROLE enabled VALUE`
Before: accepted only `true` or `false`.
After: accepts `true/false`, `yes/no`, `y/n`, `1/0`, `on/off`.
```

## Decision rule

If two or more valid interpretations exist, ask for a decision before planning or coding.

If the only ambiguity is low-risk and reversible, state the assumption and proceed to research or planning.

## Output

Return:
- scoped goal
- in scope
- out of scope
- success criteria
- constraints
- assumptions
- numbered open questions
- recommended next step: research, spike, plan, or implement
