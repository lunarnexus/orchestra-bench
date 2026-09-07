# Orchestra Bench V2 — Completion Plan

## Goal and Invariants

Deliver three reliable Pi auto-run modes with one correctness-only grading path.

### Required modes

1. `--no-orchestra --no-orch-on`
   - Orchestra tools are disabled.
   - `/orch on` is skipped.
   - No Orchestra dispatch is expected.

2. `--no-orch-on`
   - Orchestra tools remain available.
   - `/orch on` is skipped.
   - If dispatches occur, all descendants and the parent must settle before grading.

3. `--orchestra`
   - `/orch on` completes before the task prompt.
   - If dispatches occur, all descendants and the parent must settle before grading.

### Correctness scoring

- Correctness comes only from `evaluation.details.functionality.checks`.
- Score is `passed required checks / total required checks`.
- Pass means every required functionality check is true.
- Reliability, orchestration behavior, usage, context, timing, and performance are diagnostics only.
- Diagnostics must not increase or reduce correctness score.
- Contradictory evaluator verdicts are unscored.

### Lifecycle protocol

- Orchestrated auto prompts require the parent to finish with the explicit marker:

  ```text
  BENCH_PARENT_DONE
  ```

- Accepted marker forms are case-insensitive and may use spaces, underscores, or hyphens.
- Fuzzy completion words such as `done`, `complete`, `finished`, or `ready for grading` are not enough.
- The marker must occur after the latest relevant Orchestra boundary.
- Direct child-return notifications do not prove all descendants are terminal.
- The consolidated returned-children prompt is the fallback descendant-completion signal when no authoritative status source is available.
- A later successful dispatch invalidates an earlier consolidated-return signal.
- After apparent completion, the harness waits through a quiet window so late dispatches can be observed.
- The benchmark must not send synthetic continuation prompts.
- If the parent never emits the marker before the completion timeout, grading is skipped and the result must say so clearly.

### Constraints

- V1 is read-only.
- Public commands are root commands: `01-start`, `02-run`, `03-results`, `04-debug`.
- `03-results` subcommands are `dash`, `runs`, and `run`.
- Do not validate Orchestra-owned catalog schema in the benchmark.
- Do not change public tasks, suites, commands, fixtures, or timeouts without explicit approval.
- Do not pin Docker package or tool versions.
- Do not edit `DECISIONS.md` without explicit authorization.
- Do not edit `/home/james/workspace/orchestra/BAD_BEHAVIOR.md` without explicit authorization.
- Inspect live run artifacts directly in the main session; do not delegate artifact inspection.

## Completed Tasks

- [x] Remove role-focused V2 tasks from the active inventory.
- [x] Keep 13 active V2 tasks: 6 smoke, 3 capability-easy, 3 capability-normal, 1 capability-advanced.
- [x] Make all active task evaluators emit non-empty boolean `details.functionality.checks`.
- [x] Stage shared evaluator helpers via `bench/evaluator.py`.
- [x] Implement correctness-only scoring.
- [x] Persist correctness-only `category_scores.functionality` for new results.
- [x] Keep diagnostics separate from correctness.
- [x] Preserve explicit run-mode provenance.
- [x] Separate configured tool availability from observed tool execution.
- [x] Skip `/orch on` in both no-`/orch on` modes.
- [x] Run `/orch on` before the task prompt in full Orchestra mode.
- [x] Replace disabled-tools prompt wording with `Proceed until finished.`.
- [x] Append `BENCH_PARENT_DONE` completion instructions to auto prompts.
- [x] Require explicit completion marker instead of fuzzy done-ish text.
- [x] Use a separate child-wait budget.
- [x] Use a separate parent-finalization budget.
- [x] Use a quiet-period settle window after apparent completion.
- [x] Invalidate stale consolidated-return evidence after later dispatches.
- [x] Fail closed when children, descendants, or parent completion are not proven settled.
- [x] Persist Orchestra diagnostics and observed execution on lifecycle failure.
- [x] Collect parent and child Pi sessions for auto runs.
- [x] Persist explicit session-collection status or unavailable reason.
- [x] Compute parent, children, and all-session usage separately.
- [x] Deduplicate repeated usage/session evidence.
- [x] Avoid labelling parent-only usage as `all` when child evidence is required but unavailable.
- [x] Deduplicate dispatch evidence across parent sessions and harness events.
- [x] Count child terminal/active states consistently.
- [x] Surface child role, provider, model, terminal status, and failure reason in debug evidence when available.
- [x] Preserve child terminal-success precedence over intermediate tool errors.
- [x] Fix import-time test leakage in reporting management.
- [x] Keep `03-results dash`, `03-results runs`, and `03-results run` naming unchanged.

## Local Verification

Run before rebuilding or live proof:

```bash
PYTHONPATH=. pytest -q tests/unit tests/integration/test_scripts.py
```

Current local status:

- [x] `295 passed`

## Remaining Tasks

### 1. Rebuild/sync runtime

Status: pending.

Run:

```bash
./01-start
```

Accept when:

- command exits 0;
- container is ready;
- runtime uses the current checked-out benchmark code.

### 2. Mode 1 live proof

Status: pending for current completion protocol.

Run once:

```bash
./02-run --auto pi smoke-dependent-setup-chain --no-orchestra --no-orch-on
```

Inspect directly:

```bash
./03-results run <run-id>
./04-debug <run-id> full
```

Accept when:

- command exits 0;
- evaluator runs;
- all required functionality checks pass;
- score is `100/100`;
- Orchestra tools are disabled;
- `/orch on` is skipped;
- no successful Orchestra dispatch occurs;
- session collection is collected or explicitly unavailable with reason;
- usage buckets are truthful;
- raw result, `03-results`, and `04-debug` agree materially.

### 3. Mode 2 live proof

Status: pending.

Run once:

```bash
./02-run --auto pi smoke-dependent-setup-chain --no-orch-on
```

Inspect directly:

```bash
./03-results run <run-id>
./04-debug <run-id> full
```

Accept when:

- command exits 0;
- evaluator runs;
- all required functionality checks pass;
- score is `100/100`;
- `/orch on` is skipped;
- observed tool execution is recorded if dispatch occurs;
- every observed child/descendant is terminal before grading;
- parent integrates returned children;
- parent final response includes the accepted completion marker;
- no active child remains at grading;
- session collection preserves parent and child evidence or explicit unavailable reasons;
- parent, children, and all usage buckets are truthful and deduplicated;
- child terminal/active counts are internally consistent;
- raw result, `03-results`, and `04-debug` agree materially.

### 4. Mode 3 live proof

Status: pending.

Run once:

```bash
./02-run --auto pi smoke-dependent-setup-chain --orchestra
```

Inspect directly:

```bash
./03-results run <run-id>
./04-debug <run-id> full
```

Accept when all Mode 2 checks pass, plus:

- `/orch on` activation completes before the task prompt;
- full-mode orchestration diagnostics are present when applicable.

### 5. Final result views

Status: pending.

Run after all three live proofs pass:

```bash
./03-results dash
./03-results runs
```

Accept when:

- all three modes are visible;
- run summaries match raw result files;
- correctness display is based only on functionality checks;
- diagnostics remain diagnostics.

### 6. Close plan

Status: pending.

Close only after:

- local regression is green;
- runtime has been rebuilt with current code;
- all three live modes pass their acceptance checks;
- final `03-results` views agree with raw evidence.

## Verification Matrix

| Case | Expected result |
|---|---|
| Empty check map | evaluator error; no score |
| Non-boolean check | evaluator error; no score |
| Contradictory verdict/checks | evaluator error; no score |
| Partial required checks | fail with proportional correctness score |
| All required checks | pass, `100/100` |
| Workflow or reliability diagnostics change | no correctness-score change |
| Harness-only usage | populate when evidence exists; otherwise explicit unavailable reason |
| Parent plus children | exact separate buckets and deduplicated aggregate |
| Duplicate parent session/harness dispatch | count once |
| Compaction event | counted once according to usage semantics |
| Direct child notification only | keep waiting; do not grade |
| Consolidated return without parent marker | fail closed |
| Consolidated return followed by later dispatch | earlier return no longer clears descendants |
| Consolidated return plus parent marker and settle | safe to grade when descendants are terminal |
| Lifecycle failure | evaluator not run; diagnostics still persisted |
| Active child at grading boundary | no grading |
| Tool use without `/orch on` | visible diagnostic; no correctness impact |
| Raw/result/debug views | same material facts |
