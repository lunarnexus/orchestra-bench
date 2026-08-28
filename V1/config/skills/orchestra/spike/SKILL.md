---
name: spike
description: Run a timeboxed throwaway experiment to answer feasibility or tradeoff questions that research cannot settle.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, spike, feasibility, prototype]
    related_skills: [research-first, plan-work]
---

# Spike

A spike is a timeboxed disposable experiment. Use it to reduce uncertainty before committing to a production plan.

Professional goal: answer feasibility questions with evidence while avoiding accidental production code.

## When to spike

Use a spike when:
- research cannot answer feasibility
- two approaches need practical comparison
- API/integration behavior is uncertain
- performance or compatibility risk needs proof
- planning without evidence would be risky

Use research instead when docs/code can answer the question. Use planning when production work is already clear.

## Spike contract

A spike must define:

```md
Question:
- <main uncertainty>

Timebox:
- <duration or effort cap>

Feasibility questions:
1. Given ..., when ..., then ...?
2. ...

Allowed experiment scope:
- <files/scratch area/commands>

Evidence to collect:
- <measurements, output, API behavior, screenshots, etc.>

Promotion rule:
- <what evidence would justify production implementation>
```

## Method

1. State the uncertainty.
2. Decompose into 2-5 feasibility questions.
3. Order questions by risk.
4. Do minimal research first.
5. Build the smallest disposable experiment.
6. Capture evidence.
7. Compare approaches if relevant.
8. Stop when the question is answered or the timebox ends.
9. Mark any spike code as disposable.
10. Return a verdict.

## Verdicts

Use one:

- **VALIDATED** — evidence supports the approach.
- **PARTIAL** — approach may work but has unresolved risk.
- **INVALIDATED** — evidence rejects the approach.

## Evidence standards

Good evidence includes:
- exact command/output
- code snippet or file ref
- API response or docs quote
- measurement method
- screenshots or logs when relevant
- clear limitations

## Production boundary

Spike code is not production code by default. If it should be kept, plan a production implementation slice that reviews, tests, simplifies, and integrates it intentionally.

## Output

```md
## Spike Result

Question:
- ...

Verdict:
- VALIDATED / PARTIAL / INVALIDATED

Evidence:
- ...

Findings:
- ...

Tradeoffs:
- ...

Remaining unknowns:
- ...

Recommendation:
- research / plan / implement / reject approach
```
