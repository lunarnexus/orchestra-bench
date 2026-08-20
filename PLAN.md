# Plan

## Goal

Refactor the benchmark harness around the actual operator workflow, then implement the Pi RPC auto runner. The outcome should be a less clunky, more reproducible loop for overnight Orchestra experiments:

```text
runtime sync -> run suite --auto -> integrated grade -> inspect with 05-results/debug
```

The refactor should remove benchmark ownership of Orchestra `config.yaml`/`prompts.yaml`, reduce Dockerfile/plugin hand-edits, preserve local editable experiment inputs, and fix one-shot Pi premature grading by using RPC lifecycle control.

## Acceptance Criteria

### Runtime/config ergonomics
- `config/orchestra/config.yaml` and `config/orchestra/prompts.yaml` are not required by the benchmark; runtime setup uses the installed Orchestra defaults for both.
- `agent-catalog.yaml` remains benchmark-local and hand-editable.
- auxiliary skills under `config/skills/` are synced into the container runtime predictably.
- Pi plugin selection stays as commented install lines in `docker/Dockerfile` (operator's chosen mechanism); no extra profile machinery.
- run metadata captures enough provenance to know which prompt source, catalog, skills, Orchestra version/rev, and enabled plugins were used.

### RPC auto runner
- `scripts/02-open-pi <task-id> --auto` uses a Pi RPC runner or has a controlled rollout flag for it.
- Auto grading does not begin until Pi is settled and tracked Orchestra workers/reports are terminal or explicitly failed/abandoned.
- `--auto --no-orchestra` remains comparable and exits on normal Pi settle.
- Raw RPC events are saved as artifacts.
- Batch runs no longer fail with `worker_running_without_exit=true` solely because one-shot Pi exited early.

### Debug/results ergonomics
- `05-results` remains the bread-and-butter interface.
- `05-results debug <run>` becomes a guided trace navigator: result summary, lifecycle warnings, relevant artifact paths, Pi session snippets, RPC events, Orchestra logs/debug/state summaries.
- Missing/empty traces are called out explicitly rather than silently looking like no activity.

### Refactor quality
- Core path/artifact/result logic moves toward importable Python modules instead of growing `eval_harness.py`, `02-open-pi`, and `05-results` further.
- Focused tests cover modules directly without needing large subprocess/script copies for every behavior.
- Existing operator commands remain available.

## Context / Assumptions

- The benchmark currently works, but the operator has to perform too many manual steps: rebuild/start, hand-copy prompt/catalog files, adjust plugins through Pi config or Dockerfile comments, run suites, then manually dig through traces.
- `config.yaml` and `prompts.yaml` are Orchestra-owned in practice; the simplest fix is to stop carrying them in benchmark config and let the installed Orchestra version provide them.
- `agent-catalog.yaml` and `config/skills/` are experiment-owned and should stay local/editable.
- Batch07/Batch08 proved that one-shot `pi -p` is not a valid Orchestra async lifecycle runner for benchmark auto mode.
- Pi RPC mode gives the benchmark a process that can stay alive across `agent_settled` and wait for Orchestra workers/reports.
- The user is willing to let a small model work overnight, so slices must be explicit, bounded, and testable.

## Target Architecture

Add/extend modules incrementally; do not perform a giant rewrite first.

```text
bench/
  run_paths.py          # RunDirectory / artifact paths (built)
  pi_rpc_runner.py      # JSONL RPC client, settle loop, event artifacts (built)
  orchestration_gate.py # active-run detection around RPC settle (built)
  auto_run.py           # --auto driver: preflight, prompt, settle gate; used by 02-open-pi (built)
  results_cli.py        # future extraction target for scripts/05-results
  debug_views.py        # future trace summarization helpers

scripts/
  01-start              # calls runtime sync during start/init
  02-open-pi            # thin operator wrapper; auto path delegates to Python runner
  04-run-suite          # unchanged UX; benefits from 02-open-pi
  05-results            # keep UX, gradually move internals to modules
```

Keep public script names stable.

## Files Likely to Change

- `FOUNDATION.md`, `ARCHITECTURE.md`, `README.md`, `RESEARCH.md`, `PLAN.md`
- `scripts/01-start`
- `scripts/02-open-pi`
- `scripts/04-run-suite` if runner flags are exposed
- `scripts/05-results`
- `eval_harness.py` only as needed; prefer moving new code into modules
- new `bench/` package modules
- `docker/entrypoint.sh` for runtime sync hooks if needed
- `config/pi/settings.json` only as needed
- tests under `tests/`, ideally with shared helpers/fixtures

## Design Notes

### Runtime sync
- Treat Orchestra `config.yaml` and `prompts.yaml` as Orchestra-owned. Remove benchmark requirements for both and let `orchestra init pi --copy --force` install the matching defaults.
- Keep the catalog local. Do not overwrite `config/orchestra/agent-catalog.yaml` during sync unless explicitly requested.
- Sync `config/skills/` into runtime on start/init so auxiliary skill edits are applied without image rebuild when possible.
- Pi plugin selection stays as commented install lines in `docker/Dockerfile`. No profile mechanism.

### RPC runner
- Start Pi with `--mode rpc --model "$BENCH_MODEL"` in the task workdir.
- Send `/orch on` first when enabled; wait for `agent_settled`.
- Send task prompt; watch RPC events.
- On settle, query Orchestra state for the parent session/run ids.
- Keep process alive if active expected workers/reports remain.
- Exit only when settled + no active expected descendants/pending reports.
- Save all RPC lines to `artifacts/pi-rpc/events.jsonl`.
- Do not use fake repeated wait prompts.

### Debug views
- Prefer concise summaries first, with paths/commands to inspect deeper.
- Show lifecycle chain: dispatch -> worker started -> worker exited/done -> report delivered/consumed.
- Show mismatches: worker running at grade time, missing worker session JSONL, empty debug output, no role tokens despite dispatch, pending report not delivered.
- Keep raw artifacts; do not duplicate large logs into result JSON.
- RPC event traces are benchmark-runner artifacts, not Orchestra debug artifacts. `orchestra debug` does not automatically capture the raw Pi RPC event stream, so the runner should write it alongside other run artifacts under `artifacts/pi-rpc/`.
- Keep `result.json` stable. Do not add bulky RPC event data. If needed, store only compact booleans/status in existing `orchestration_checks`; otherwise let `05-results debug` read RPC summary/events directly from artifacts.

## Status (overnight fork, 2026-08-19)

Slices 1-8 complete and live-verified. Slices 9-10 deferred as planned.

Live E2E evidence (container `orchestra-bench-runner`, model lmstudio/qwen/qwen3.8-27b):
- Run A: `researcher-summarize-release-notes --auto --no-orchestra --auto-runner rpc`
  → PASS, pi_exit 0, session captured, events.jsonl with agent_settled, debug section renders.
- Run B: `cap-easy-express-inventory --auto` (Orchestra on; RPC default)
  → /orch on preflight OK; gate result "settled" before exit; `worker_running_without_exit=False`;
  graded after settle. Task score=fail is a genuine local-model capability failure
  (incomplete app.js), not a harness lifecycle issue.
- Default `--auto` flipped to RPC after the live pass. Legacy print runner should be removed completely.

## Task Breakdown

- [x] Slice 1 — sequential — Extract `RunDirectory` path helper
  Scope: add `bench/run_paths.py` and replace a small set of repeated run/artifact path constructions in tests or non-risky code.
  Stop when: tests can use `RunDirectory` for result/artifact paths.
  Verify: focused path/helper tests.
  Risk: P2 — foundation for later refactor.

- [x] Slice 2 — sequential — Simplify runtime config sync (verified live: container keeps installed Orchestra config.yaml/prompts.yaml; only agent-catalog.yaml + skills overlaid)
  Scope: stop requiring/copying benchmark `config.yaml` and `prompts.yaml`; preserve local `agent-catalog.yaml`; sync `config/skills/`; keep runtime config/prompts from installed Orchestra defaults.
  Stop when: `config/orchestra/config.yaml` and `config/orchestra/prompts.yaml` can both be absent and `scripts/01-start start` / runtime init still succeeds without overwriting the local catalog.
  Verify: unit tests or script tests with temp config/runtime dirs plus a container init smoke.
  Risk: P1 — config provenance and accidental overwrite risk.

- [x] Slice 3 — dropped — Plugin profiles
  Decision (operator): keep commented `pi install` lines in `docker/Dockerfile` as the plugin selection mechanism. Simple and sufficient; no profile machinery.

- [x] Slice 4 — sequential — RPC runner tracer bullet
  Scope: implement minimal `bench/pi_rpc_runner.py` that starts Pi RPC, sends one prompt, logs events, and exits on `agent_settled` for no-Orchestra mode.
  Stop when: mocked process tests pass and a harmless container smoke can run without grading.
  Verify: `tests/test_pi_rpc_runner.py` for JSONL protocol/event parsing.
  Risk: P1 — new execution path.

- [x] Slice 5 — sequential — Orchestra-aware settle gate (live: Run B gate result "settled")
  Scope: add active-run/report detection around RPC settle; use existing Orchestra CLI/state outputs where possible.
  Stop when: mocked tests cover active worker preventing exit and terminal worker allowing exit.
  Verify: mocked Orchestra CLI outputs and synthetic RPC events.
  Risk: P1 — prevents premature grading.

- [x] Slice 6 — sequential — Wire `02-open-pi --auto` to RPC runner (default now rpc)
  Scope: keep existing prep, metadata, cleanup, artifact collection, grading integration; replace one-shot auto path. Follow-up cleanup: remove the legacy print runner path and public `--auto-runner` option completely.
  Stop when: operator-flow tests prove command construction and cleanup/grade sequencing.
  Verify: `pytest -q tests/test_operator_flow.py tests/test_pi_rpc_runner.py --tb=short`.
  Risk: P1 — public workflow.

- [x] Slice 7 — sequential — RPC artifacts and debug navigation (verified on real runs)
  Scope: save RPC events under run artifacts; extend manifest/debug view to summarize RPC/Pi/Orchestra trace availability and lifecycle chain.
  Stop when: `scripts/05-results debug <run>` shows useful trace guidance on synthetic fixtures.
  Verify: reporting/debug tests.
  Risk: P2 — operator diagnostics.

- [x] Slice 8 — sequential, MANDATORY FINAL GATE — Live end-to-end verification (passed; see Status above)
  Scope: after all other slices land and unit tests pass, run at least one no-Orchestra task AND one Orchestra-enabled task in the real container through `--auto`.
  Stop when (all required):
  - both runs produce a graded result.json with sane tokens/orchestration fields,
  - RPC events artifact exists (`artifacts/pi-rpc/events.jsonl`) and shows agent_settled before exit,
  - Orchestra run has no false `worker_running_without_exit` from early one-shot exit,
  - `scripts/05-results debug <run-id>` renders the new trace guidance on a real run.
  Verify:
  ```bash
  scripts/01-start start   # only if container is stale/recreated for mounts
  scripts/02-open-pi <small-smoke-task> --auto --no-orchestra --notes "RPC live e2e"
  scripts/02-open-pi <small-role-or-capability-task> --auto --notes "RPC live e2e orchestra"
  scripts/05-results run <run-id>
  scripts/05-results debug <run-id>
  ```
  If the live run fails, fix and re-run before declaring the plan complete. LM Studio concurrency==1 means runs serialize with any other local model use — acceptable.
  Risk: P1 — real runtime integration.

- [ ] Slice 9 — parallel-safe after core stabilizes — Start decomposing `05-results`
  Scope: move pure aggregation/formatting helpers into importable modules without changing CLI output.
  Stop when: existing reporting tests still pass and new direct module tests cover moved logic.
  Verify: `pytest -q tests/test_reporting.py --tb=short`.
  Risk: P2.

- [ ] Slice 10 — parallel-safe after core stabilizes — Test fixture cleanup
  Scope: consolidate repeated result/artifact/session builders into shared test helpers.
  Stop when: at least RPC/debug/reporting tests use shared helpers and total duplication drops.
  Verify: focused test suite.
  Risk: P3.

## Execution Guidance (overnight fork, qwen3.8-27b)

Keep every slice minimal — simple over clever. No security scans. Commit at milestones, do not push.

Order:
1. Slices 1-4: foundation + RPC tracer bullet with mocked tests.
2. Slice 5: settle gate with mocked Orchestra outputs.
3. Slice 6: wire `02-open-pi --auto` to RPC, dogfood it, then remove the legacy print runner path.
4. Slice 7-8: RPC artifact wiring + debug view + real end-to-end runs (one no-Orchestra, one Orchestra).
5. Slices 9-10 are deferred until the RPC path has stabilized in real use; do not start them opportunistically.

Constraints:
- Do not rewrite `05-results` or split all of `eval_harness.py` this pass.
- Do not overwrite local `agent-catalog.yaml` automatically.
- Remove legacy one-shot print runner UX after RPC live verification; `--auto` should mean RPC only.
- Do not delete existing result artifacts.
- LM Studio is concurrency==1; live dogfood runs serialize with the operator session — that is acceptable, no special handling.

## Verification Commands

Focused unit checks as slices land:
```bash
pytest -q tests/test_operator_flow.py tests/test_reporting.py tests/test_orchestration_extraction.py --tb=short
```

Focused tests for the built modules:
```bash
pytest -q tests/test_run_paths.py tests/test_pi_rpc_runner.py tests/test_orchestration_gate.py tests/test_auto_run.py --tb=short
```

Runtime dogfood after wiring:
```bash
scripts/01-start start
scripts/02-open-pi cap-easy-django-reports --auto --notes "RPC runner smoke"
scripts/05-results run <run-id>
scripts/05-results debug <run-id>
```

## Risks

- Accidentally overwriting hand-edited `agent-catalog.yaml`; sync must be safe by default.
- RPC mode may expose trust/extension loading differences from print/TUI mode.
- Orchestra session id mapping may be wrong; event artifacts and state queries must make this debuggable.
- Adding refactor and RPC at once can destabilize the harness; keep slices vertical and small.

## Open Questions

- None for Orchestra `config.yaml`/`prompts.yaml`: they come from installed Orchestra, not benchmark config.
- Closed: RPC event details belong in artifacts and `05-results debug`, not in `result.json`; only compact status fields may be added to existing `orchestration_checks` if they materially help filtering/comparison.
