# Architecture

## Boundary

`orchestra-bench` runs benchmark tasks and harnesses inside a Docker container. The host provides operator commands and developer tests; benchmark execution happens in the container.

Public commands:

```bash
01-start
02-run
03-results
04-debug
```

## Host/container layout

The container sees the repo as `/bench` and uses mounted result/artifact/config paths.

Important paths:

- host `tasks/` -> container task material
- host `results/` -> run result directories
- host `artifacts/` -> runtime/operator artifacts
- container `/workspace/` -> active harness workspaces and run-scoped Pi homes

## Runtime config sync

`01-start` builds/recreates the container and syncs runtime config.

Runtime config sources:

- `config/orchestra/`
- `config/pi/`
- `config/hermes/`
- `config/opencode/`

Runtime sync records provenance outside public `results/` so result listings contain run dirs only.

Pi uses run-scoped HOME directories:

```text
/workspace/.pi/home/<run-id>
```

`PI_CODING_AGENT_DIR` must equal:

```text
$HOME/.pi/agent
```

This invariant prevents split runtime state.

## Run modes

### Manual

```bash
02-run pi <task-id>
```

Manual task session flow:

1. prepare run workspace
2. sync runtime config for the chosen run id
3. launch harness inside the container workspace
4. copy final container workspace back into the run result workspace
5. collect Pi session artifacts
6. grade final workspace
7. normalize run-tree ownership to the host user

Harness startup failure is a benchmark/runtime error and skips grading.

### Automatic

```bash
02-run --auto <task-or-suite>
```

Auto flow re-enters `bench.cli` inside the container and should use one run id for runtime HOME, result path, and command re-entry. Auto output still needs operator UX cleanup: default should show brief milestones; verbose should be proven to stream useful detail.

## Results and scoring

`03-results` owns reporting:

- dashboard
- single-run details
- filters
- comparisons
- deletion/rescore management where supported

V2 scoring separates:

- `result`: `pass|fail|error`
- `score`: numeric display such as `89/100`
- `category_scores`: only the `functionality` category, computed solely from canonical boolean checks in `details.functionality.checks`. No weighted categories are persisted.
- diagnostics outside correctness scoring: Orchestra behavior (Pi sessions/Orchestra artifacts) lives in `orchestra`, run/evidence health in `reliability`, and tokens/context/elapsed time/compactions in their dedicated fields. These never contribute to the score.

Functionality comes from task evaluator checks.

Pre-scoring result dirs are stale data and should be ignored, deleted, or rerun.

## Debug

`04-debug` owns trace inspection for one run at a time:

```bash
04-debug <run-id> orch
04-debug <run-id> full
04-debug <run-id> raw
```

- `orch`: parent/orchestrator session
- `full`: parent + children sessions
- `raw`: raw session/debug artifacts

Debug views can expose sensitive prompts, model outputs, tool outputs, and filesystem paths. Treat run artifacts as sensitive.

## Task model

Tasks live under `tasks/<task-id>/` and normally include:

- `task.yaml`
- `Prompt.md`
- `PRD.md`
- fixture/source files
- `evaluate/run.sh`

Task metadata may declare scoring expectations:

```yaml
scoring:
  expected_orchestra: true
  required_roles: [builder, verifier]
```

Roles are task-specific. Do not require every role for every task.

## Trust boundaries

- Task fixtures are untrusted benchmark input.
- Evaluators are benchmark-owned and hidden from the task workspace until grading.
- Raw debug artifacts may contain sensitive data.
- Runtime config and extension overlays are trusted local inputs.
- Docker image build currently uses current tool installs rather than pinned historical versions, by owner preference. This favors testing current harness behavior over reproducible frozen tool versions.

## Ownership

Container-created run files must be host-deleteable. Ownership normalization uses the host UID/GID where available after result writes, workspace copy-back, evaluator artifacts, and session artifact collection.
