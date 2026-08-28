# Project Decisions

NEVER EVER EDIT THIS FILE WITHOUT THE USER EXPRESSLY SAYING "edit DECISIONS.md".  If you're not sure, ask the user to confirm.  DO NOT ASSUME YOU HAVE APPROVAL, DO NOT INFER APPROVAL, ALWAYS CONFIRM WITH THE USER.

This file is the authoritative record of project decisions made by the project owner. Decisions belong here regardless of size.

Agents must preserve these decisions and must not remove, weaken, reinterpret, or supersede them without explicit owner approval. Suggestions, implications, and inferred design choices are not decisions until the owner approves them.

When code, documentation, or two recorded decisions conflict, identify the conflict and ask the owner for clarification. Do not silently choose one. Retain superseded decisions and identify the decision that replaced them.

`DECISIONS.md` records what the project must do. `PLAN.md` describes the current work plan for implementing and verifying those decisions. Current implementation does not silently supersede this register.

This register currently captures decisions made in the active V2 rebuild session. Later work may scan `PLAN.md`, architecture notes, implementation, reviews, and other project artifacts to backfill older decisions.

## Product and scope

### D-PRODUCT-001 — V2 rebuild, not V1 restore

**Decision:** Rebuild orchestra-bench as a clean V2. `V1/` is reference material only, period. It is read-only and must never be built, executed, imported, mounted, or used as a V2 runtime dependency. It may be consulted only to understand prior operator-facing behavior and recover explicitly approved concepts.

### D-PRODUCT-002 — Multi-harness benchmark

**Decision:** V2 must support multiple agent harnesses. Pi is first, followed by Hermes, OpenCode, and other harnesses through generic harness boundaries.

### D-PRODUCT-003 — Container isolation remains required

**Decision:** Benchmark task/harness execution must be isolated through the benchmark container runtime.

## Operator workflow

### D-UX-001 — Public operator UX is exactly three numbered scripts

**Decision:** The public numbered operator workflow is exactly:

```text
scripts/01-start
scripts/02-run
scripts/03-results
```

No public numbered `03-grade`, `04-suite`, `04-results`, `04-run-suite`, or `05-results` path is part of the standard workflow.

### D-UX-002 — Bare `01-start` performs complete setup

**Decision:** Running `scripts/01-start` with no arguments performs the complete normal build, container replacement/start, and runtime configuration flow. These are implementation stages, not separate public operator actions. The script must work from either the project root or the `scripts/` directory.

### D-UX-003 — `02-run` is the single run surface

**Decision:** `scripts/02-run` is the single operator surface for manual harness commands and automatic benchmark runs.

### D-UX-004 — `03-results` owns results and debugging views

**Decision:** `scripts/03-results` shows grades, results, debug artifacts, and comparisons.

### D-UX-005 — Standalone grading is internal/private

**Decision:** Standalone grading, if exposed, is internal/private. It is not a standard numbered human step.

### D-UX-006 — Preserve useful V1 operator features, not V1 complexity

**Decision:** Examine V1's operator-facing features and preserve useful behavior. Do not preserve V1 implementation complexity, bad features, or complicated workflows merely for compatibility.

### D-UX-007 — Simplification is a primary constraint

**Decision:** Do not overcomplicate or invent new workflow. V2 must reduce complication and streamline the benchmark operator experience.

## Start and configuration workflow

### D-START-001 — Docker caching follows the useful V1 boundary

**Decision:** `01-start` builds the container using the useful V1 caching strategy. The build refreshes Orchestra and Pi plugins while caching Pi, Hermes, and OpenCode installations. Research the V1 build before changing the cache boundary.

### D-CONFIG-004 — Regular config directories provide runtime overrides

**Decision:** Runtime configuration overrides come from the regular project config directories: `config/orchestra/`, `config/pi/`, `config/hermes/`, and `config/opencode/`. Files present in those directories are copied over the corresponding installed defaults inside the container.

## Run and results workflow

### D-RUN-001 — Manual harness sessions run inside the container

**Decision:** `02-run pi <args...>`, `02-run opencode <args...>`, and `02-run hermes <args...>` run the selected harness inside the container. Additional harnesses may be added later.

### D-RUN-002 — Automatic targets run and score through one command

**Decision:** `02-run --auto <test-or-suite>` runs the selected test or suite automatically inside the container and scores it when execution completes.

### D-RUN-003 — Harness configuration commands use the same passthrough

**Decision:** `02-run pi config` runs `pi config` inside the container. Hermes and OpenCode configuration and testing commands use the same passthrough model.

### D-RESULTS-001 — Results support management and comparison

**Decision:** `03-results` displays and compares results, supports filtering for sorting/display/comparison, re-scores when requested, and can delete results selected by filters.

### D-ORCHESTRA-001 — Known Orchestra bugs inform lifecycle behavior

**Decision:** Review `~/workspace/orchestra/KNOWN_BUGS.md` when implementing or testing Orchestra lifecycle, settle, and scoring behavior.

## Container execution semantics

### D-RUNTIME-001 — Benchmark task/harness execution is container-only

**Decision:** All benchmark task and harness execution must happen inside the benchmark container. Host-side `02-run` is an operator shim only; it must not run Pi, OpenCode, Hermes, or benchmark tasks on the host.

### D-RUNTIME-002 — Developer pytest may run on host

**Decision:** Normal developer `pytest` verification may run on the host. Only tests that specifically exercise container behavior need to run against or inside the container.

### D-RUNTIME-003 — Harness passthrough docker-execs inside the container

**Decision:** `02-run` supports harness passthrough commands that docker-exec into the running benchmark container:

```bash
scripts/02-run pi <args...>
scripts/02-run opencode <args...>
scripts/02-run hermes <args...>
```

For example, `scripts/02-run pi config` must run `pi config` inside the container.

### D-RUNTIME-004 — Harness passthrough args are opaque

**Decision:** When the first non-option token is a known harness name, `02-run` treats the remaining argv as opaque harness arguments and passes them to that harness inside the container.

### D-RUNTIME-005 — Automatic benchmark execution uses only `02-run --auto`

**Decision:** Automatic benchmark execution uses one form:

```bash
scripts/02-run --auto <target>
```

`<target>` may identify a task or suite. `--suite` is redundant and is not part of the operator UX. Auto runs execute inside the benchmark container.

### D-RUNTIME-006 — Host paths are mapped to container paths

**Decision:** Host-facing arguments such as `config/orchestra/agent-catalog.yaml` must be mapped to their container paths before in-container automation runs.

### D-RUNTIME-007 — Run workspaces are isolated per run

**Decision:** Each benchmark run gets an isolated task workspace created/used through the container-backed runtime.

## Output and artifacts

### D-OUTPUT-001 — Default output is concise

**Decision:** Default operator output should be short status/progress, not full harness transcript spam.

### D-OUTPUT-002 — `--verbose` shows full harness session output

**Decision:** `--verbose` shows or streams the full harness session output for both manual harness passthrough and automatic benchmark runs.

### D-OUTPUT-003 — Full transcripts are always recorded

**Decision:** Full harness stdout, stderr, and session transcript must be recorded as run artifacts whether or not `--verbose` is used.

### D-OUTPUT-004 — Fake/dry-run success is not proof

**Decision:** Fake harness runs, dry runs, wrapper-call tests, and debug rendering for failed evaluator crashes are not proof that the benchmark works. Acceptance requires the actual container-backed operator flow and a real evaluator result or an exact real blocker.

## Catalog and model selection

### D-CONFIG-001 — Benchmark catalog source

**Decision:** The project-local benchmark catalog is copied from `~/workspace/orchestra/agent-catalog.yaml`.

### D-CONFIG-002 — Use regular project config, do not edit source

**Decision:** Copy the source catalog once into the regular project config path `config/orchestra/agent-catalog.yaml` and reuse that local project config copy. Do not modify `~/workspace/orchestra/agent-catalog.yaml`. Do not repeatedly recopy unless the source catalog changes again by owner action.

### D-CONFIG-003 — Current benchmark model

**Decision:** The current expected local model for benchmark runs is `lmstudio/qwen/qwen3.8-27b`, already loaded in LM Studio and configured for local Orchestra.

## Build/review sequencing

### D-PROCESS-001 — Freeze semantics before implementation

**Decision:** Operator semantics must be clarified and recorded before implementation proceeds. Do not rush ahead from partial or ambiguous worker findings.

### D-PROCESS-002 — Real dogfood blocks later feature claims

**Decision:** The V2 operator flow is not accepted until the real container-backed dogfood flow works or returns an exact real blocker.

### D-PROCESS-003 — AppSec is deferred until planned build steps complete

**Decision:** AppSec/security review is deferred until all planned build steps are complete, unless the owner explicitly requests an earlier security review.
