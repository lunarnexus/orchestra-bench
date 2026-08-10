# PLAN

## Goal
Turn `orchestra-bench` into a valid, lightweight, SaaSBench-inspired benchmark for Orchestra that answers:

> Can Orchestra build great things?

The immediate priority is **runtime validity**. The benchmark is not acceptable until it runs the real Pi + Orchestra + LM Studio plugin stack inside the container using benchmark-local editable config.

## Current status
- shared harness/task/result skeleton exists
- runtime is valid for the intended benchmark
- reporting/comparison support exists
- task artifacts now use `PRD.md` + `Prompt.md` consistently
- current task inventory has 6 smoke tasks, 18 role-focused tasks, 1 contract task, and 3 capability tasks
- smoke tasks include the original three compact E2E patterns plus three workflow smokes requiring research/planning/build/verify/review/security evidence
- remaining benchmark-design work is to run the new smoke batch end-to-end and harden task quality based on observed failures

## Stable constraints
- Pi runs inside the benchmark container
- install Orchestra from `http://git.lunarnexus.local:3000/james/orchestra`
- install LM Studio plugin from `http://git.lunarnexus.local:3000/james/pi-lmstudio`
- install Orchestra using its `README.md`
- install LM Studio plugin using the official `pi` plugin install command
- use benchmark-local editable config files copied into the container runtime:
  - Orchestra config under `config/orchestra/`:
    - `config.yaml`
    - `prompts.yaml`
    - `agent-catalog.yaml`
  - Pi/plugin config under `config/pi/`:
    - `lmstudio.json`
- `agent-catalog.yaml` is the source of truth for model provenance
- `PI_MODEL` is not the source of truth
- keep a reusable container by default
- keep the operator flow simple
- preserve artifact capture and repeated comparison support
- benchmark should be organized by **batches** and judged **outcome-first**

## Batch direction
Target benchmark batches:
1. `smoke` — 6 real end-to-end tasks that build/test something real and collectively exercise the core Orchestra workflow
2. `role-focused` — 3 tasks each for planner, researcher, verifier, reviewer, builder, and appsec
3. `contract` — runtime/workdir and anti-fake-success checks
4. `capability` — integrated SaaSBench-inspired tasks, split later only if needed

Retired construction bucket:
- `capability-raw-material` is no longer part of the task inventory.

## Public UX direction
- no user-facing CLI
- README exposes the operator flow as three numbered steps:
  - `scripts/01-start start|stop`
  - `scripts/02-open-pi <task-id>` (auto-prepares the run)
  - `scripts/03-collect-results`
- `scripts/_prepare-task-run` may remain as an internal compatibility helper, but operators should not need to run it
- non-numbered helper scripts or internals may exist, but should not be the documented operator surface

Notes:
- smoke tasks should be real enough to naturally invite orchestration where useful
- role-focused tasks are intentionally narrower and help isolate value/behavior by role
- contract tasks protect against unsafe or fake-success behavior
- current role-focused fixtures can remain as raw material until the dedicated role-focused batch is assembled

## Execution plan

### Slice 1 — runtime source install contract (`sequential`, complete)
Scope:
- `docker/Dockerfile`
- `docker/entrypoint.sh`
- `scripts/build-env`
- `scripts/start-env`
- `.env.example`
- `README.md`

Build:
- install Pi in the container
- install Orchestra from the Gitea repo using its README instructions
- install LM Studio Pi plugin from the Gitea repo using the official `pi` plugin install command
- expose `pi` and `orchestra` on `PATH`

Stop when:
- a fresh container has working `pi` and `orchestra`
- the LM Studio plugin is installed in Pi's runtime

Verify:
- `scripts/01-start start`
- runtime troubleshooting checks in `ARCHITECTURE.md` confirm `pi` and `orchestra` are on PATH inside the container

### Slice 2 — benchmark-local config snapshot (`sequential`, complete)
Scope:
- new `config/orchestra/`
- `docker/entrypoint.sh`
- `scripts/start-env`
- `scripts/_prepare-task-run`
- `README.md`

Build:
- add committed benchmark-local config files:
  - `config/orchestra/config.yaml`
  - `config/orchestra/prompts.yaml`
  - `config/orchestra/agent-catalog.yaml`
- mount them into the container read-only
- copy them into Pi's live Orchestra runtime dir inside the container

Stop when:
- container runtime contains copied benchmark-local config under Pi's Orchestra config path

Verify:
- `docker exec orchestra-bench-runner test -f /root/.pi/agent/orchestra/agent-catalog.yaml`
- `docker exec orchestra-bench-runner test -f /root/.pi/agent/orchestra/config.yaml`
- `docker exec orchestra-bench-runner test -f /root/.pi/agent/orchestra/prompts.yaml`

### Slice 3 — runtime initialization (`sequential`, complete)
Scope:
- `docker/entrypoint.sh`
- `scripts/start-env`
- maybe `scripts/init-runtime`

Build:
- run `orchestra init pi --copy --force` inside the container after config is present
- copy benchmark-local LM Studio runtime config from the Pi config area (preferably `config/pi/lmstudio.json`) into `~/.pi/agent/lmstudio.json` after plugin install and before doctor checks
- ensure the benchmark-local catalog does not require unavailable harness executables during runtime doctor checks, or install the required executables if they are intentionally part of the benchmark contract
- make runtime initialization idempotent and rerunnable without rebuilding the image

Stop when:
- `orchestra doctor` works in container
- `/orch doctor` works from Pi inside container
- LM Studio runtime config is copied from a benchmark-local file into the container

Verify:
- `docker exec orchestra-bench-runner bench-entrypoint init-runtime`
- `docker exec orchestra-bench-runner orchestra doctor`
- `docker exec orchestra-bench-runner pi --no-approve -p "/orch doctor"`

### Slice 4 — remove `PI_MODEL` truth path, derive model from catalog (`sequential`, complete)
Scope:
- `scripts/_prepare-task-run`
- `scripts/02-open-pi`
- `scripts/run-task`
- `eval_harness.py`
- `__init__.py`
- `.env.example`
- `README.md`
- relevant tests

Build:
- resolve run model from `agent-catalog.yaml`
- inspect `default_role` and role model, defaulting normally to `builder`
- persist catalog-derived model/config provenance in run metadata
- remove `PI_MODEL` as operator truth source

Stop when:
- runs work without needing `PI_MODEL`
- `.bench_run.json` records catalog-derived model provenance

Verify:
- prepare one run without setting `PI_MODEL`
- inspect `.bench_run.json`
- grep docs/scripts/tests for authoritative `PI_MODEL` usage

### Slice 5 — reusable container semantics (`sequential`, complete)
Scope:
- `scripts/build-env`
- `scripts/start-env`
- `README.md`
- tests

Build:
- default `start` reuses an existing valid container
- explicit recreate/restart path exists when needed
- workspace reset remains available between runs
- runtime reinit remains available after config changes

Stop when:
- repeated `start` does not recreate the container by default

Verify:
- compare container IDs across repeated starts

### Slice 6 — operator flow repair (`sequential`, complete)
Scope:
- `scripts/_prepare-task-run`
- `scripts/02-open-pi`
- `scripts/03-collect-results`
- `scripts/eval-task`
- `scripts/run-task`
- `README.md`
- operator-flow tests

Build:
- keep a thin flow: build/start -> prepare -> open Pi -> eval+collect
- ensure eval uses the existing workdir rather than recreating it
- preserve metadata and artifact collection

Stop when:
- one smoke task can be prepared, opened in Pi, evaluated, and summarized using the valid runtime without rebuilding the image

Verify:
- one end-to-end smoke run through the operator flow

### Slice 7 — reporting metadata cleanup (`parallel-safe`, complete)
Scope:
- `eval_harness.py`
- `__init__.py`
- tests
- `README.md`

Build:
- keep existing reporting/aggregation
- group comparisons by catalog-derived provenance rather than stale env settings
- extend metadata as needed: role, model, catalog hash, config hash, image/container IDs

Stop when:
- result comparison clearly distinguishes config/catalog revisions

Verify:
- reporting tests
- compare output on multiple runs with different config provenance

### Slice 8 — batch restructuring and task triage (`sequential`, complete)
Scope:
- `tasks/`
- batch metadata/layout
- `README.md`
- `PLAN.md`
- possible new batch runner helpers

Build:
- classify current tasks into `smoke`, `contract`, `capability`, and `capability-raw-material` buckets where practical
- keep `smoke` as real small implementation work; keep `smoke` task as a contract/harness check
- preserve useful raw material instead of deleting everything that is role-shaped
- define a small set of batch-oriented benchmark runs
- promote/rewrite the strongest raw material into a credible smoke batch and at least one stronger capability batch

Stop when:
- smoke batch is credible and no longer centered on the toy `smoke` benchmark
- at least one advanced capability batch is defined with multiple stronger outcome-first tasks
- task organization matches the benchmark philosophy

### Slice 9 — suite expansion requirements (`sequential`, complete)
Scope:
- `FOUNDATION.md`
- `PLAN.md`
- `README.md`
- later task rewrite plan

Build:
- lock the new suite requirement that smoke is exactly 3 real E2E tasks
- lock the new suite requirement that there are 3 role-focused tasks each for planner, researcher, verifier, reviewer, builder, and appsec
- keep `contract` and `capability` as first-class benchmark suites, not deferred away
- record that human-facing task materials should be markdown and should borrow SaaSBench artifact structure where useful
- record the preferred task artifact mapping: `PRD.md`, `Prompt.md`, markdown KB, `fixture/`, `evaluate/`
- state that grader/evaluator materials stay outside the agent-visible workspace
- state that README should show numbered scripts only, with `open-pi.sh` exempt if retained
- use SaaSBench examples to guide smoke E2E task choices:
  - dependent setup chain -> one core action
  - public entrypoint -> authenticated/admin confirmation
  - interactive action -> immediate progression/feedback

Stop when:
- requirements/docs clearly reflect the new suite structure and SaaSBench-inspired task material expectations, including separate `PRD.md` and `Prompt.md` and keeping grader materials outside the agent-visible workspace

### Slice 10 — task artifact migration (`sequential`, complete)
Scope:
- task folders
- runtime copy logic
- operator scripts/docs/tests as needed

Build:
- remove legacy `task.md` as the canonical task artifact
- migrate tasks to consistent `PRD.md` + `Prompt.md` (+ `kb/` or `kb.md` where applicable)
- ensure only agent-visible artifacts are copied into task work folders
- keep evaluator materials outside the agent-visible workspace
- update operator/runtime code and docs to use the new artifact names consistently

Stop when:
- current tasks no longer rely on `task.md`
- runtime/operator flow uses `PRD.md` and `Prompt.md` consistently
- docs and task layouts are aligned

Verify:
- `python3 -m pytest tests/test_task_artifacts.py -v`
- batch inventory review confirms no task depends on legacy `task.md`
- one batch run path documented and executable

### Slice 11 — SaaSBench-pattern smoke + role-focused suite (`sequential`, complete)
Scope:
- `tasks/`
- `task.yaml` metadata
- docs/tests affected by task inventory

Build:
- keep the original 3 compact smoke tasks aligned with the three SaaSBench-inspired patterns:
  1. dependent setup chain -> one core action
  2. public entrypoint -> authenticated/admin confirmation
  3. interactive action -> immediate progression/feedback
- build the full `role-focused` suite: 3 tasks each for planner, researcher, verifier, reviewer, builder, and appsec
- retire `capability-raw-material` by promoting useful fixtures into `role-focused` or `capability`, or deleting weak leftovers
- keep task artifacts in the current `PRD.md` + `Prompt.md` + optional markdown KB shape
- keep `evaluate/` grader materials outside agent-visible workdirs
- preserve `contract` and `capability` as first-class suites

Stop when:
- README task tables show only final suites: `smoke`, `role-focused`, `contract`, and `capability`
- there are 6 smoke tasks and exactly 18 role-focused tasks
- no task is categorized as `capability-raw-material`
- smoke tasks demonstrably map to the three SaaSBench-inspired E2E patterns

Verify:
- task inventory script/check asserts batch counts
- at least one smoke task runs through `01-start start` -> `02-open-pi <task-id>` -> `03-collect-results`
- role-focused fixtures have hidden or grader-only outcome checks

## What can be kept
- current harness/result framework as scaffolding
- current result schema and comparison support
- artifact capture direction
- many existing task fixtures as raw material

## Known invalid assumptions to remove
- npm-latest-only runtime install is sufficient
- `PI_MODEL` controls the benchmark model
- normal start should always recreate the container
- role-isolated toy tasks are enough to measure Orchestra well

## Risks
- some current tasks may still be too toy to keep unchanged
- config provenance mistakes would invalidate comparison claims
- overemphasis on process metrics could distort the benchmark away from end results
- capability batches still need stronger rewritten tasks, not just regrouping

## Recommended next action
Run the new smoke batch through the simplified operator flow (`01-start start` -> `02-open-pi <task-id>` -> `03-collect-results`), inspect real Pi/Orchestra traces and grader results, then tighten individual tasks/evaluators based on observed failures.
