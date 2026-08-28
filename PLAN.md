# V2 Rebuild Plan

`DECISIONS.md` is authoritative. This plan describes how to bring the current worktree into conformance with those decisions. If this plan conflicts with `DECISIONS.md`, stop and ask the owner; do not infer a resolution.

## Goal

Deliver a streamlined, container-isolated benchmark with exactly three public operator scripts:

```text
scripts/01-start
scripts/02-run
scripts/03-results
```

Normal workflow:

```bash
scripts/01-start
scripts/02-run pi                         # interactive harness session
scripts/02-run pi config                  # harness command inside container
scripts/02-run --auto <test-or-suite>     # automatic run and scoring
scripts/03-results ...                    # inspect/manage results
```

V1 is read-only reference material. Preserve useful operator-facing behavior and proven Docker caching ideas, not V1 implementation complexity.

## Non-negotiable constraints

- Never edit `DECISIONS.md` without the user's express instruction to edit it.
- Do not add public numbered scripts beyond `01-start`, `02-run`, and `03-results`.
- Bare `01-start` performs the complete normal setup. Build/start/recreate/configure are internal stages, not public actions.
- All benchmark tasks and harness sessions run inside the benchmark container.
- Normal developer pytest may run on the host; container-specific tests run against or inside the container.
- Automatic execution has one form: `02-run --auto <target>`. There is no `--suite` UX.
- Runtime overrides come from `config/orchestra/`, `config/pi/`, `config/hermes/`, and `config/opencode/`.
- Default output is concise. `--verbose` shows the full session. Full transcripts are always retained.
- Fake harnesses, dry runs, wrapper tests, and evaluator-crash rendering are contract/diagnostic evidence only, never acceptance proof.
- AppSec is deferred until all planned build work is complete unless the owner requests it earlier.
- Do not import `V1/eval_harness.py` or other V1 runtime code into V2.
- V2 has exactly one active Dockerfile: `docker/Dockerfile`. Any Dockerfile under `V1/` is read-only reference material and is never built or used by V2.

## Plan maintenance rules

- Update slice status only from returned command/artifact evidence.
- A blocked, failed, fake, or dry run is not completion evidence.
- Rewrite obsolete future instructions as soon as implementation or an owner decision invalidates them.
- Keep historical details in verification/review artifacts, not repeated checkpoints in this plan.
- Do not change operator semantics during implementation. Stop and ask the owner.
- Keep slices small and sequential where dependencies exist.

## Current state

### Plan evidence status

- [x] Slice 1.1 — V1 operator-feature, cache, and config inventory. `RESEARCH.md` records separated evidence, current mismatches, source-to-destination config mapping, cache findings, and genuine owner questions; reviewer `7975c0b25ea4` passed the re-review.
- [~] Slice 1.2 — worktree and cleanup boundary inventory complete; owner approval is required before deletion, migration, staging, or checkpointing. `RESEARCH.md` records the explicit keep/reference/migrate/remove/defer boundary and checkpoint proposal.

### Proven

- A real container-backed Pi command-harness task completed successfully:
  - run: `s17r20260828T173608-smoke-dependent-setup-chain`
  - model: `lmstudio/qwen/qwen3.8-27b`
  - harness: ok
  - evaluator: ok
  - outcome: pass
  - transcript, manifest, and evaluator artifacts present
- Evaluator environment inheritance, omitted evaluator status normalization, and host-readable result files were fixed and unit-tested.
- Public wrappers can locate the repository when invoked from `scripts/`.
- `config/orchestra/agent-catalog.yaml` has been used successfully inside the container.

### Not accepted / known drift

- `01-start` still exposes internal actions and does not implement the one-command setup decision.
- Runtime configuration is incomplete and inconsistent. The current `init` path can run host-side while using container-default paths.
- The Docker build/config flow does not implement all regular override directories or the decided cache boundary.
- Obsolete numbered wrappers were removed; the public surface is `scripts/01-start`, `scripts/02-run`, `scripts/03-results`.
- Results now route through `scripts/03-results` only.
- Default and `--verbose` output behavior does not match decisions.
- `03-results` lacks the complete filtering, comparison, rescoring, and filtered deletion workflow.
- Root `tasks/` is absent; runtime falls back to `V1/tasks`, conflicting with V1's reference-only role.
- Pi RPC exists in code/tests but is not wired into the operator flow. Orchestra settle has no production status provider/session provenance.
- `02-run --auto pi` can be confused with manual Pi passthrough because wrapper parsing is shell-based.
- The V2 replacement worktree is largely uncommitted and mixed with broad deletions.
- Stale config variants, compatibility helpers, old artifacts, and editor/workspace residue need review before removal.

## Execution order

Work is sequential unless a slice explicitly says otherwise. Do not start later feature work while an earlier operator-flow gate is red.

---

## Phase 1 — Research the operator contract and establish a safe boundary

### Slice 1.1 — V1 operator-feature, cache, and config inventory

Research only. Inspect V1 from the user's perspective:

- build/start behavior and Docker cache-break placement
- what must refresh versus remain cached
- configuration override behavior and destination paths
- interactive Pi/Hermes/OpenCode use
- automatic test and suite execution
- scoring and rescoring
- results filters, comparison, deletion, and debug navigation

Also inspect:

- `~/workspace/orchestra/KNOWN_BUGS.md`
- the single active V2 Dockerfile (`docker/Dockerfile`) and V1 Dockerfile/build scripts as read-only reference material
- current config directories and intended override files

Deliverable:
- compact keep/drop/simplify inventory with exact references
- proposed Docker stages and invalidation boundary
- config source-to-destination map
- known Orchestra lifecycle constraints relevant to automatic scoring

Gate:
- reviewer confirms the inventory describes operator behavior rather than proposing V1 code restoration

### Slice 1.2 — Worktree and cleanup boundary

Inventory only:

- intended V2 files, including the single active `docker/Dockerfile`
- V1 reference tree, including any reference-only Dockerfile
- deleted legacy root files
- untracked V2 replacements
- generated artifacts and editor residue
- config variants and whether they are intentional experiments

Deliverable:
- explicit keep/remove/migrate list
- proposed V1/V2 deletion boundary
- recoverable checkpoint proposal

Gate:
- owner approves uncertain deletions and checkpoint boundary

### Slice 1.3 — Establish a recoverable V2 checkpoint

After owner approval:

- remove only confirmed residue
- preserve uncertain experiment configs and historical material
- establish the approved V1/V2 boundary
- create a recoverable commit or equivalent checkpoint before further implementation

Stop when:
- the current V2 work can be recovered independently of later edits
- no swap, generated scratch, or accidental result files are included

---

## Phase 2 — Implement unified configuration before `01-start`

### Slice 2.1 — Implement regular config overrides

Implement one generic override mechanism for:

```text
config/orchestra/
config/pi/
config/hermes/
config/opencode/
```

Rules:
- files override corresponding installed defaults inside the container
- absent optional directories/files do not invent defaults
- source project config remains operator-editable
- runtime snapshots record effective config provenance
- catalog remains `config/orchestra/agent-catalog.yaml`
- configuration is applied inside the container, never host-side using container paths

Stop when:
- focused tests prove representative overrides for every supported harness
- real container inspection confirms effective files and provenance

### Slice 2.2 — Rewrite `01-start` as one normal command

V2 build rule: use only `docker/Dockerfile`. Do not copy, build, or maintain a second V2 Dockerfile; consult `V1/docker/Dockerfile` only to recover useful cache and install behavior.

Required behavior:

```bash
scripts/01-start
```

From project root or `scripts/`, it must:

1. build using the approved V1-derived cache boundary
2. refresh Orchestra and Pi plugins while retaining cached Pi/Hermes/OpenCode installs
3. replace/start the container in a known-good state
4. apply runtime configuration inside the container
5. print a concise success/status summary

Remove from public UX:
- `build`
- `start`
- `recreate`
- `init`
- internal `start start` shapes

Implementation rules:
- shell wrapper stays thin
- one Python function owns the internal setup stages
- no host-side runtime initialization using container paths

Verification:
- works from root and `scripts/` without PYTHONPATH
- Docker cache-stage contract checks
- container recreated/running
- Pi, Hermes, and OpenCode commands installed
- all config override checks pass inside container
- one real bare `scripts/01-start` succeeds

### Slice 2.3 — Reduce public scripts to exactly three

Completed cleanup:
- removed `scripts/03-grade`
- removed `scripts/04-suite`
- removed `scripts/05-results`
- removed alias-only `scripts/_collect-results`

Public surface remains `scripts/01-start`, `scripts/02-run`, `scripts/03-results`.

Stop when:
- directory inventory and help output expose only the intended numbered workflow

---

## Phase 3 — Simplify `02-run` and prove Pi passthrough

### Slice 3.1 — Move dispatch parsing into Python

Required forms:

```bash
scripts/02-run pi <args...>
scripts/02-run opencode <args...>
scripts/02-run hermes <args...>
scripts/02-run --auto <test-or-suite>
```

Requirements:
- shell wrapper only locates the repository and invokes Python
- Python distinguishes passthrough from `--auto`
- harness args remain opaque
- `02-run --auto pi` is an automatic target, not passthrough
- no host-local benchmark fallback
- no `--suite`

### Slice 3.2 — Implement real interactive Pi passthrough

Requirements:
- execute inside the running container
- attach stdin
- allocate a TTY when the caller has one
- propagate signals and command exit status reasonably
- preserve all opaque arguments exactly
- `02-run pi config` runs `pi config` inside the container
- default display is concise where applicable
- `--verbose` exposes the full session
- retain the complete session transcript as an artifact

Stop when:
- focused parser/process tests pass
- real `02-run pi <approved-smoke-args>` works from root and `scripts/`
- real `02-run pi config` reaches in-container Pi configuration

---

## Phase 4 — Unify workspace and migrate live tasks

### Slice 4.1 — Unify workspace/runtime model

Resolve competing workspace paths and dead runtime initialization helpers.

Requirements:
- one run-scoped workspace model inside the container
- catalog `{workdir}` expansion points to the real workspace
- evaluator remains hidden until grading
- run artifacts remain host-readable
- Pi/Orchestra runtime directories are run-scoped where required

Stop when:
- workspace/evaluator boundary tests pass
- a real task confirms paths reported in provenance and artifacts

### Slice 4.2 — Move live tasks out of V1

Create root `tasks/` by migrating the minimum smoke tasks first.

Requirements:
- no V2 runtime dependency on `V1/tasks`
- preserve task assets and evaluator behavior without importing V1 harness code
- migrate additional tasks only after smoke contracts pass

Stop when:
- container mounts root `tasks/`
- one migrated smoke task passes real execution and grading

---

## Phase 5 — Automatic task and suite execution

### Slice 5.1 — Automatic single-task flow

Required command:

```bash
scripts/02-run --auto <test>
```

Requirements:
- entire run and grading occur inside the container
- default output is concise status/progress
- `--verbose` streams the full harness session
- full stdout, stderr, transcript, and lifecycle summary are always retained
- result JSON remains compact and references artifacts

Stop when:
- focused output/lifecycle tests pass
- one real migrated task proves concise default output
- one real verbose run proves full live output and retained transcript

### Slice 5.2 — Automatic suite targets

Required command:

```bash
scripts/02-run --auto <suite>
```

Requirements:
- task/suite resolution is unambiguous
- serial execution by default
- continue/fail policy and summary return code are explicit
- each task has independent workspace, results, and artifacts
- no separate suite command or flag

Stop when:
- one real smoke suite completes and scores through the container-backed operator flow

---

## Phase 6 — Complete `03-results`

Use the approved Slice 1.1 V1 inventory; do not repeat the research.

### Slice 6.1 — Display, filtering, and comparison

Required capabilities:
- list and display runs
- detailed run and debug views
- filters for sorting and display
- comparisons using filters
- token and timing summaries where data exists

### Slice 6.2 — Rescoring and safe filtered deletion

Requirements:
- explicit rescoring
- prior result preserved until replacement succeeds
- deletion supports filters
- deletion always previews the exact selected runs
- destructive execution requires explicit confirmation
- unsafe or unexpectedly broad deletion is refused unless explicitly confirmed

Verification:
- deletion tests use temporary/copied results, not valued accepted runs
- a real accepted run proves filtering, comparison, and rescoring without being deleted

Stop when:
- one canonical `03-results` surface satisfies all decided management workflows

---

## Phase 7 — Pi lifecycle backend and Orchestra settle

### Slice 7.1 — Research and approve backend selection

Do not add a public harness-selection flag without owner approval.

Research:
- current `PiRpcHarness` implementation and gaps
- Pi RPC behavior in the installed version
- catalog/role-driven backend selection options
- implications for later Hermes/OpenCode backends

Deliverable:
- minimal internal backend-selection proposal
- owner decision before implementation

### Slice 7.2 — Wire the approved Pi lifecycle backend

After owner approval:
- make the selected Pi lifecycle backend reachable through production resolution
- preserve generic harness boundaries
- record the backend in provenance

Stop when:
- one real no-Orchestra Pi lifecycle smoke emits events, settles, and grades successfully

### Slice 7.3 — Implement Orchestra settle provider

Research `~/workspace/orchestra/KNOWN_BUGS.md` before implementation.

Requirements:
- production status provider and session identity provenance
- no grading while relevant workers/reports remain active
- clear timeout/failure classification
- raw status snapshots and lifecycle events retained
- known Orchestra bugs handled or explicitly reported

Stop when:
- active-worker test blocks grading
- terminal-worker test allows grading
- one real Orchestra-enabled smoke completes without premature grading

Gate:
- owner review before automatic Orchestra reliability is declared

---

## Phase 8 — Prove Hermes and OpenCode

Use the generic `02-run` interface already implemented in Phase 3.

Verify inside the container:

```bash
scripts/02-run hermes <approved-smoke-args>
scripts/02-run opencode <approved-smoke-args>
```

Requirements:
- interactive stdin/TTY behavior matches the generic contract
- opaque arguments and exit status are preserved
- full session transcripts are retained
- do not force Pi lifecycle semantics onto other harnesses

Stop when:
- both installed harnesses complete approved real smoke commands

---

## Phase 9 — Cleanup, verification, and handoff

### Slice 9.1 — Remove confirmed dead code and stale artifacts

Candidates, only after impact review:
- legacy environment aliases
- unused compatibility config helpers
- stale catalog variants not approved for retention
- dead runtime/workspace model
- stale `.workspace`, swap files, and generated residue

Do not delete uncertain experiment configs without owner approval.

### Slice 9.2 — Full verification

Run:
- compile/import checks
- full V2 unit suite
- integration tests
- container contract tests
- real bare `01-start`
- real Pi, Hermes, and OpenCode passthrough
- real automatic task
- real automatic suite
- `03-results` display/filter/compare/rescore/delete safety checks
- mandatory real Orchestra settle gate after Slice 7.3

Distinguish baseline/environment failures from regressions.

### Slice 9.3 — Final review and AppSec

After all build slices are complete:
- independent code review
- independent verification
- AppSec review
- fix material findings and repeat affected gates

### Slice 9.4 — Clean commit and operator handoff

Before committing:
- ensure no editor swap/generated scratch files are staged
- ensure real results remain ignored unless intentionally retained
- produce a concise operator README matching the three-script workflow
- create a clean final commit/handoff from the established V2 boundary

## Acceptance checklist

V2 is complete only when all are true:

- [ ] Bare `scripts/01-start` performs complete cached build/start/configure from root and `scripts/`.
- [ ] Exactly three public numbered scripts remain.
- [ ] Pi, Hermes, and OpenCode passthrough execute interactively inside the container.
- [ ] `scripts/02-run --auto <test>` runs and scores a real task.
- [ ] `scripts/02-run --auto <suite>` runs and summarizes a real suite.
- [ ] No benchmark execution falls back to the host.
- [ ] Regular config overrides work for Orchestra, Pi, Hermes, and OpenCode.
- [ ] Runtime no longer depends on `V1/tasks`.
- [ ] Default output is concise; `--verbose` is full; transcripts are always retained.
- [ ] `03-results` supports display, filtering, comparison, rescoring, and safe filtered deletion.
- [ ] Orchestra automatic grading does not occur while relevant work remains active.
- [ ] Fake/dry-run tests are not cited as end-to-end acceptance.
- [ ] Full verification, review, and final AppSec gates pass.
- [ ] The V2 worktree has a clean, recoverable, reviewable commit history.

## Immediate next action

Proceed with **Slice 1.2 — worktree and cleanup boundary inventory**. Do not delete uncertain files or rewrite implementation until the boundary inventory is reviewed and the owner approves uncertain cleanup.
