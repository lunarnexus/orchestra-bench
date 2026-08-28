---
name: research-first
description: Gather evidence from code, docs, tests, APIs, and prior art before designing or implementing software changes.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, research, prior-art, evidence]
    related_skills: [scope-work, spike, plan-work]
---

# Research First

Use this skill before planning or implementation when facts are uncertain. The goal is to replace assumptions with evidence.

Professional goal: reuse what exists, verify APIs, and reduce implementation risk before coding.

## Research questions

Start with one clear question:

```md
Question: <the fact or decision this research must answer>
Scope: <exact files/directories/docs/web topic>
Sources: repo/docs/web/API/tests/examples
Enough evidence: <what would make the answer reliable>
```

Prefer one question or one tight file cluster per research pass.

## Source order

Use relevant sources in this order:

1. Project instructions such as `AGENTS.md`.
2. Existing code and nearby patterns.
3. Existing tests and fixtures.
4. Project docs and architecture notes.
5. Build, package, and CI configuration.
6. Official external docs.
7. Local cached dependency source or API definitions.
8. Web search for ecosystem/prior-art context.

## Prior-art outcome matrix

Classify what you find:

- **adopt** — use an existing solution as-is.
- **extend** — build on an existing solution.
- **compose** — combine existing pieces.
- **build** — implement because no suitable path exists.

## API and dependency checks

Before planning dependency or API integration:
- verify the actual API shape
- quote at least one concrete signature, option, config field, or example
- check version-specific behavior
- prefer official docs/source over memory
- inspect local cached source when available and relevant

## Method

1. Confirm the research question.
2. Bound the scope tightly.
3. Inspect requested sources.
4. Record concrete evidence with file refs or URLs.
5. Separate facts from interpretation.
6. Note conflicts or stale evidence.
7. Answer the question directly.
8. Recommend adopt/extend/compose/build when prior art matters.
9. Identify remaining unknowns.
10. Recommend next step: more research, spike, plan, or implement.

## Dispatch guidance for sub-research

When delegating research:
- read-only by default
- one topic or one tight file cluster
- exact files/directories/topic
- expected return shape
- rough size limit for lookup/triage
- ask for sources, confidence, gaps, blockers, risks

If a researcher times out, retry with a smaller slice. If the same topic times out again, split to one topic, use main-session tools, or stop.

## Output

Return:

```md
## Research Result

Answer:
- <direct answer>

Evidence:
- `<file:line>` or URL — <fact>

Prior-art outcome:
- adopt / extend / compose / build — <reason>

Confidence:
- high / medium / low

Gaps:
- <unknowns>

Risks:
- <risk if this evidence is wrong or incomplete>

Recommended next step:
- research / spike / plan / implement
```
