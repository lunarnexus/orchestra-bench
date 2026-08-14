# FOUNDATION

## Goal
Build a lightweight, SaaSBench-inspired benchmark for **Orchestra itself** that answers the practical question:

> Can Orchestra build great things?

The benchmark is outcome-first. Process evidence matters, but only as secondary evidence for understanding why a run succeeded or failed.

## Stable principles

### 1. Runtime validity is mandatory
The benchmark is only valid if it runs the real stack the user cares about:
- Pi runs **inside** the benchmark container
- Orchestra is installed from the user's Gitea source pattern
- the LM Studio Pi plugin is installed from the user's Gitea source pattern
- `orchestra init pi --copy --force` is run inside the container
- local editable Orchestra config files are copied into the container runtime

If those are missing, the benchmark is not testing the real system.

### 2. Agent catalog is the primary source of truth
- `agent-catalog.yaml` is the most important configuration artifact
- model selection must come from the copied local `agent-catalog.yaml`
- `PI_MODEL` is **not** the benchmark truth source
- the default role in the catalog, typically `builder`, is the starting place for model resolution unless a run explicitly targets another role

### 3. Config must be local and editable
The benchmark must use benchmark-local editable config files, copied into the container:
- `config.yaml`
- `prompts.yaml`
- `agent-catalog.yaml`

These should live in this repo as benchmark-owned config snapshots, not be generated ad hoc at run time.

The LM Studio runtime config should also live in the project config area, but separately from Orchestra config since it is Pi/plugin runtime config, not Orchestra config. Do not copy it directly from `~/.pi/agent/` during runtime setup.

### 4. Pi and Orchestra run inside one reusable container
- use one shared benchmark image and one long-lived benchmark container by default
- do **not** rebuild/recreate the container for every tiny test
- task workspaces inside the container must still reset between runs
- explicit rebuild/recreate/reset operations are acceptable and expected when needed for cleanliness or runtime changes

### 5. Simple operator flow
The operator flow should stay simple and scripts-first.
Use numbered scripts as the public UX, with `open-pi.sh` exempt if kept.
Do not present a user-facing CLI in the main documentation.

Target flow:
1. setup runtime/container
2. open Pi for one or more tasks; task runs auto-prepare isolated workdirs
3. collect/grade prepared runs
4. inspect results/reporting

Avoid unnecessary modes and ceremony.

### 6. Outcome first, orchestration second
The benchmark should measure whether Orchestra helps deliver strong end results.
- do **not** force subagent usage just to prove orchestration happened
- if a task does not require research, not using `researcher` is acceptable
- if a task does not require planning, not using `planner` is acceptable
- process traces, dispatch counts, role usage, and token breakdowns are useful diagnostics, not the primary score

### 7. Tasks should invite orchestration naturally
Even smoke tests should be real enough that a capable model might choose to use planning, research, review, verification, or security help when useful.
Do not build trivial toy tasks whose only purpose is to force one role.

### 8. Batch structure over role-isolation obsession
The benchmark should be organized into a few batches, not many modes.
Current intended batch philosophy:
- `smoke` — 6 real end-to-end tasks: 3 compact runtime smokes plus 3 workflow smokes that require research/planning/build/verify/review/security evidence
- `role-focused` — 3 tasks each for planner, researcher, verifier, reviewer, builder, and appsec
- `capability-easy` — restored straightforward, passable, real-app E2E tasks across varied stacks
- `capability-normal` — restored more involved SaaSBench-style E2E tasks with seeded conflicts/traps
- `capability-advanced` — larger full-app tasks such as ShortLink Desk

Old standalone `contract` tasks are not public benchmark suites; container/workdir invariants belong in harness/container checks. Capability tasks are the exception to the normal outcome-first/no-forced-roles principle: they intentionally score full Orchestra workflow evidence across planner, researcher, builder, verifier, reviewer, and appsec. That workflow evidence is required as task material but scored, not an automatic pass/fail gate.

Smoke E2E tests should be inspired by SaaSBench-style product patterns:
- dependent setup chain -> one core action
- public entrypoint -> authenticated/admin confirmation
- interactive action -> immediate progression/feedback
- metering/invoicing -> signed webhook
- public upload -> admin approval under security constraints
- migration -> rollback/release evidence without secret leakage

### 9. Preserve comparison value
Keep support for:
- repeated trials
- per-run artifacts
- config snapshots / hashes
- model and catalog provenance
- Orchestra on/off comparisons
- comparison across catalog / prompt / skill changes
- baseline/no-Orchestra suite runs with `04-run-suite --no-orchestra`

### 10. Task material should borrow from SaaSBench
Task structure and benchmark wisdom should be borrowed from SaaSBench where useful:
- agent-facing requirement artifact(s)
- bounded knowledge/research artifact(s)
- fixture/workspace seed
- grader/evaluator materials

Use markdown for human-facing requirement and knowledge artifacts.

Current preferred mapping:
- `PRD.md` — product requirements document / authoritative spec
- `Prompt.md` — agent-facing run prompt / instructions
- `kb.md` or `kb/` markdown files — bounded knowledge / clarifications
- `fixture/` — starting workspace
- `evaluate/` — grader-only materials kept outside the agent-visible workspace
- runtime copies of PRD/prompt/KB into the task work folder are part of the normal benchmark flow

### 11. Reference sources and install rules
Use these user-specified runtime sources:
- Orchestra: `http://git.lunarnexus.local:3000/james/orchestra`
- LM Studio plugin: `http://git.lunarnexus.local:3000/james/pi-lmstudio`

Install rules:
- install Orchestra using its `README.md`
- install the LM Studio plugin using the official `pi` plugin install command

## Capability-suite decisions
- Delete old flawed capability task IDs rather than keep them in public inventory.
- Use `capability-easy`, `capability-normal`, and `capability-advanced` as separate suites.
- Rebuild each capability suite with 3 tasks when replacement tasks are ready.
- Use varied languages, frameworks, dependencies, app types, and DB/storage types.
- Preinstall task platform dependencies in the benchmark image/container where practical so agents are not tested on boring package setup.
- Use bundled local `kb/` docs instead of live web access for capability research; web surfing availability is not what these tasks test.
- Prefer real app dependencies when they are part of the behavior being evaluated, including Redis/Postgres when stable inside the existing benchmark container.
- Do not create extra service containers for capability dependencies; install/start services inside the existing benchmark container when needed.
- Use lightweight substitutes only when they preserve the same app behavior and failure modes being evaluated.
- Each capability task should produce a real working app and test functionality, security, performance, and workflow artifacts where relevant.
- Capability tasks must be browser-routable working applications, not API-only slices. A valid capability app needs at least one usable `GET /` or equivalent HTML/browser entrypoint that lets a human inspect and exercise the core workflow on a routable host/port. API endpoints can still be primary grading targets, but the first browser experience must not be a bare 404 or docs-only page.

## Authoring guide

Detailed task-creation methodology lives in `TEST_CREATION.md`. Use it when creating or replacing capability tasks, designing evaluators, calibrating difficulty, or teaching future agents how to author benchmark tasks.

## Non-goals
- reproducing full SaaSBench complexity
- optimizing for forced role activation over delivered outcome
- rebuilding the whole environment for each tiny run
- treating process metrics as the benchmark's only truth
