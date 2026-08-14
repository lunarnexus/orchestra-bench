# ARCHITECTURE

## Runtime shape

### Host-owned assets
The host repo owns:
- benchmark tasks
- benchmark results
- benchmark artifacts
- benchmark-local Orchestra config snapshot
- numbered operator scripts plus internal implementation helpers

Recommended repo shape:

```text
config/orchestra/
  config.yaml
  prompts.yaml
  agent-catalog.yaml

config/pi/
  lmstudio.json
  settings.json

config/skills/
  # benchmark-local Pi skills copied into the container image

docker/
  Dockerfile
  entrypoint.sh

tasks/
results/
artifacts/
scripts/
```

### Container-owned runtime
The shared container must contain:
- Node 22+
- Pi coding agent
- Orchestra installed from source
- LM Studio Pi plugin installed via official Pi plugin install flow
- CodeGraph Pi plugin installed via official Pi plugin install flow
- benchmark-local skills from `config/skills/` copied into `~/.pi/agent/skills/`
- initialized Pi/Orchestra runtime under `~/.pi/agent/`
- workspace root for per-run task workdirs

## Container contract

### Mounts
The container should mount:
- `results/` → writable result output
- `artifacts/` → writable run artifacts
- `config/orchestra/` → read-only benchmark-local Orchestra config source

Task definitions and evaluator files are intentionally **not** mounted during agent runs. Public scripts copy only agent-visible materials into the workdir, and evaluator code is copied into a temporary in-container path only during grading.

Example intended mount shape:

```text
/bench/results
/bench/artifacts
/bench/orchestra-config
/workspace
```

### In-container config application
On runtime init:
1. copy `/bench/orchestra-config/*.yaml` into Pi's Orchestra runtime dir
2. run `orchestra init pi --copy --force`
3. ensure final runtime config is inspectable under Pi's live config path

This copy step is deliberate: benchmark runs should use local editable files from this repo, but the running Pi/Orchestra environment should consume copied runtime config inside the container.

Pi runtime config is stored under benchmark-local Pi config, not Orchestra config:
- `config/pi/lmstudio.json` is copied into `~/.pi/agent/lmstudio.json` during runtime init.
- `config/pi/settings.json` is merged into `~/.pi/agent/settings.json` before plugin install, so benchmark-owned settings such as `enableInstallTelemetry: false` take effect without clobbering unrelated Pi defaults.
- `config/skills/` is copied into `~/.pi/agent/skills/` during image build, so benchmark-local skills can be versioned with the benchmark and loaded by Pi inside the container.

## Model resolution

### Source of truth
Model provenance must come from the copied `agent-catalog.yaml`.
Expected resolution path:
1. read `default_role`
2. resolve that role in `roles`
3. read `roles.<role>.model`
4. record that model in run metadata

Role-focused benchmark tasks have a `target_role`, but Pi itself should still start as the parent/coordinator using the default parent model. The parent prompt asks Orchestra to dispatch the target role when Orchestra is enabled. The harness should not pretend that invoking Pi with a role-specific model is the same as exercising Orchestra role dispatch.

### Baseline runs without Orchestra
For Orchestra-off comparisons, the benchmark should still use the same catalog-derived model so the comparison stays fair.

## Runtime lifecycle

### Desired commands
Keep the operator surface simple, but with clear semantics:
- `scripts/01-start start` builds the image and recreates the benchmark container so mounts/config are fresh
- `scripts/01-start stop` removes the benchmark container cleanly
- task isolation comes from a fresh per-run workdir created by `scripts/02-open-pi <task-id>`
- `scripts/02-open-pi <task-id> --auto` uses the same prep path, runs `/orch on` through `pi -p`, then continues the same Pi session with `Prompt.md` non-interactively and exits
- role-focused tasks keep the Pi session as the parent/coordinator and ask it to dispatch the target role through Orchestra when Orchestra is enabled; the harness records `target_role` separately instead of running Pi as the worker role
- `scripts/03-collect-results` grades all prepared/ungraded runs idempotently
- `scripts/04-run-suite <suite>` runs each suite task through `02-open-pi --auto`, then grades it; `--no-orchestra` passes through for baseline/no-Orchestra suite runs

## Operator flow

The intended manual flow is:

```text
start/recreate container
-> open Pi for one or more tasks (auto-prepares each run), or run a whole suite via `04-run-suite <suite>`
-> collect/grade all prepared ungraded runs
-> inspect historical results/tokens/traces
```

The flow should stay thin. It is not a separate orchestration system.

## Task artifact shape

Preferred per-task artifact shape:

```text
tasks/<task-id>/
  PRD.md
  Prompt.md
  kb/           # or kb.md for very small tasks
  fixture/
  evaluate/     # grader-only, not copied into agent-visible workspace
  task.yaml
```

Runtime copies into the task work folder include only the agent-visible materials:
- `PRD.md`
- `Prompt.md`
- `kb/` or `kb.md`
- `fixture/`

Grader/evaluator materials are not mounted for the agent session. During grading, the host copies the evaluator into a temporary in-container path, runs it against the existing workdir, then removes the temporary evaluator copy.

## Benchmark organization

### Primary unit: task batches
The benchmark should group tasks by batch, not by abstract tooling mode.

Target batch structure:
- `smoke` — 6 real end-to-end tasks: 3 compact runtime smokes plus 3 workflow smokes that require role evidence
- `role-focused` — exactly 3 tasks each for planner, researcher, verifier, reviewer, builder, and appsec
- `capability-easy` — integrated end-to-end tasks: restored prior easy tasks plus rebuilt ShortLink Desk
- `capability-normal` — integrated end-to-end tasks: restored prior normal/hard tasks

`capability-raw-material` was a temporary construction bucket and should not appear in the final task inventory.
The old monolithic `capability` suite is retired; Slice 1 removes its flawed placeholder tasks before new normal/hard tasks are added.

### Smoke batch
Small but legitimate end-to-end tasks.
Purpose:
- prove runtime validity
- prove Orchestra can complete real small tasks
- allow orchestration to emerge naturally when helpful

### Role-focused batch
Narrower per-role tasks.
Purpose:
- isolate behavior/value for planner, researcher, verifier, reviewer, builder, and appsec
- keep 3 tasks per role
- grade outcomes and role-specific deliverables without turning the whole benchmark into forced role activation

### Capability-normal batch
Straightforward SaaSBench-inspired real-app tasks.
Purpose:
- test whether Orchestra improves outcomes on meaningful but passable work
- cover varied languages, frameworks, storage choices, and app shapes
- score workflow evidence without making it the only source of truth

### Capability-hard batch
Harder SaaSBench-inspired real-app tasks with seeded conflicts, edge cases, and hidden checks.
Purpose:
- test planning, research, build, verification, review, and AppSec coordination under realistic friction
- include state/idempotency/security/performance checks where appropriate
- remain passable, but not easy

### Internal container/harness checks
Runtime/workdir contract checks are not a public benchmark suite. They belong in harness/container tests or startup health checks, not in `04-run-suite` task inventory.

## Result model

Each run should persist:
- task id
- batch
- run id
- role target if applicable
- catalog-derived model
- Orchestra on/off
- config/catalog hashes or snapshot identifiers
- image/container identifiers when useful
- elapsed time
- token summaries when available
- evaluator outcome
- optional process diagnostics: role usage, dispatch counts, parent/worker token breakdown
- when present, soft process penalties that adjust `score_numeric`/rubric for orchestration or efficiency issues without changing the evaluator's top-level pass/fail field

## Validation and testing process

Unit tests protect harness behavior, but they are not sufficient for changes to operator scripts, runtime setup, task packaging, result collection, artifact capture, or reporting. Those changes must also be dogfooded through Pi inside the benchmark container.

### Runtime validity checks
A valid runtime should be able to demonstrate:
- `pi` exists in container
- `orchestra` exists in container
- LM Studio plugin is installed in Pi
- `orchestra doctor` passes
- `/orch doctor` works from Pi inside the container
- one smoke task can be prepared, run, graded, and summarized without rebuilding the image

### Required dogfood integration check
For harness or task changes, the preferred real integration check is:

```bash
scripts/02-open-pi smoke-dependent-setup-chain --auto
scripts/03-collect-results
scripts/05-results run <run-id>
```

`--auto` must use the same preparation path as interactive runs. By default it first runs `/orch on` through `pi -p`, then continues the same Pi session with `Prompt.md` inside the per-run workdir. This proves the operator flow, orchestrator-skill loading, Pi session capture, grading, token capture, timing, and result display against the actual benchmark path. Use `--no-orchestra` only for intentional baseline/debug runs.

### Verification expectations
When dogfooding a run, verify:
- the expected `results/<run-id>-<task-id>/result.json` exists
- `.bench_run.json` contains catalog-derived model metadata and start timing
- `result.json` has the correct `task_id`, `run_id`, score, checks, run metadata, tokens when available, and elapsed time for new runs
- `artifacts/pi-sessions.json` contains at least one Pi session id for actual Pi runs
- `artifacts/orchestra-debug/debug/` contains `orchestra debug` output; `runs: 0` is valid when Orchestra was not used
- `scripts/05-results` and `scripts/05-results run <run-id>` display the run without counting test junk or invalid no-session runs as ordinary benchmark results

### Test hygiene
Tests and ad hoc checks must not leave fake benchmark history in `results/`. If a test intentionally creates result directories, it must use a temporary results directory or clean up any generated `results/<run-id>-<task-id>/` folders before finishing.
