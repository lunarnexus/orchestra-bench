# Plan

## Goal

Replace the current one-shot `pi -p` auto runner with an RPC-backed Pi auto runner so benchmark automation stays alive while asynchronous Orchestra workers finish and return reports. Preserve interactive Pi behavior and keep `--no-orchestra` baseline runs comparable.

## Acceptance Criteria

- `scripts/02-open-pi <task-id> --auto` can run through a Pi RPC client instead of exiting after the first `agent_settled`.
- In Orchestra-enabled auto runs, grading does not begin until:
  - Pi has emitted `agent_settled`,
  - no tracked Orchestra runs for the parent session are active,
  - and no pending Orchestra session report remains undelivered when detectable.
- Real Orchestra worker reports are delivered back into the parent session; no fake repeated "wait" prompts are injected.
- `--auto --no-orchestra` still works and exits after normal Pi settle.
- Artifacts include the RPC event stream and enough lifecycle evidence to debug settle/worker timing.
- Batch runs no longer produce `worker_running_without_exit=true` merely because one-shot Pi exited before async workers finished.
- Focused tests cover RPC runner command construction, event parsing, settle/active-run wait logic, and `02-open-pi` integration without requiring real model calls.

## Context / Assumptions

- Current failing Batch07/Batch08 behavior is caused by one-shot Pi exiting after model settle while Orchestra worker processes are still running.
- This is mostly a benchmark automation problem because interactive Pi sessions remain alive and can receive asynchronous auto-return reports.
- Nested worker dispatch is currently disabled/unused, so the top-level parent session is the main lifecycle owner in the benchmark.
- Pi RPC mode keeps the host process alive under benchmark control and emits `agent_settled` events.
- Pi docs define `agent_settled` as the point where Pi will not continue through retry, compaction retry, or queued follow-up messages by itself.
- Orchestra already has CLI/state primitives for run/session report waiting, but the exact most reliable command mix should be validated in a tracer-bullet slice.

## Files to Change

- `scripts/02-open-pi`
- New helper, likely `scripts/pi-rpc-runner` or `scripts/_pi-rpc-runner`
- `scripts/04-run-suite` only if option/help text needs to expose runner mode
- `eval_harness.py` only if artifact collection/manifest needs RPC event metadata
- `scripts/05-results` only if new RPC artifact summaries should be displayed
- Tests:
  - `tests/test_operator_flow.py`
  - new or existing RPC runner tests, e.g. `tests/test_pi_rpc_runner.py`
  - `tests/test_orchestration_extraction.py` if manifest fields change
- Docs:
  - `README.md`
  - `ARCHITECTURE.md`
  - `RESEARCH.md`

## Design Notes

- Keep the parent Pi session in RPC mode for auto runs:
  1. start `pi --mode rpc --model "$BENCH_MODEL"` in the task workdir,
  2. send `/orch on` when Orchestra is enabled,
  3. wait for `/orch on` `agent_settled`,
  4. send the task prompt,
  5. listen for `agent_settled`, `turn_*`, tool, and message events,
  6. after each settle, query Orchestra activity for the parent session,
  7. exit only when Pi is settled and Orchestra has no active/pending work for that session.
- Store raw RPC JSONL under `results/<run>-<task>/artifacts/pi-rpc/events.jsonl` or equivalent before grading.
- Avoid fake follow-up keepalive prompts. They consume extra model turns and can loop.
- Prefer using real auto-return delivery from the Orchestra Pi extension. If RPC does not deliver reports reliably, add a narrow benchmark-side resume strategy as a fallback, not as the primary design.
- `--no-orchestra` can still use RPC for consistency, but its completion condition is only Pi `agent_settled` because there are no expected Orchestra workers.
- Keep one-shot `pi -p` available only as a legacy/debug path if useful, not the default for benchmark auto runs.

## Task Breakdown

- [ ] Slice 1 — sequential — RPC tracer bullet
  Scope: create a minimal local/container RPC client helper that starts Pi RPC, sends one prompt, logs events, and exits on `agent_settled` for a no-Orchestra prompt.
  Stop when: a test or dry-run demonstrates event parsing and clean shutdown without real benchmark grading.
  Verify: focused unit tests for JSONL event parsing plus one harmless container smoke if available.
  Risk: P1 — changes auto-run execution path.

- [ ] Slice 2 — sequential — Orchestra-aware settle gate
  Scope: add logic that maps the Pi session id to Orchestra session id, detects dispatched run ids, polls Orchestra status/report state after `agent_settled`, and keeps RPC alive until descendants are terminal.
  Stop when: synthetic tests cover active worker -> no exit, terminal worker -> exit.
  Verify: unit tests with mocked RPC events and mocked Orchestra CLI outputs.
  Risk: P1 — lifecycle correctness.

- [ ] Slice 3 — sequential — Wire `02-open-pi --auto`
  Scope: replace the current `pi -p` auto path with the RPC runner; keep existing preparation, notes, metadata, cleanup, artifact collection, and grading behavior.
  Stop when: `02-open-pi --auto --no-orchestra` and Orchestra-enabled command construction are covered by tests.
  Verify: `pytest -q tests/test_operator_flow.py ...` focused tests.
  Risk: P1 — operator workflow.

- [ ] Slice 4 — sequential — Artifact and result diagnostics
  Scope: persist RPC event logs and manifest pointers; optionally extract settle/active-worker timing into existing diagnostics if straightforward.
  Stop when: `result.json`/manifest points to RPC artifacts and `05-results debug` can lead operators to them or existing debug paths remain sufficient.
  Verify: artifact collection tests and a `scripts/05-results debug <run>` smoke on a synthetic result.
  Risk: P2 — debugging/reporting only.

- [ ] Slice 5 — sequential — Container dogfood
  Scope: run one tiny no-Orchestra auto task and one Orchestra-enabled capability/smoke task through the RPC runner in the real benchmark container.
  Stop when: grading waits for terminal workers and no longer reports `worker_running_without_exit=true` for a run whose worker completed.
  Verify: `scripts/05-results run <id>` evidence: worker completed, role sessions captured when worker ran, RPC artifacts present.
  Risk: P1 — real runtime behavior can differ from unit tests.

- [ ] Slice 6 — sequential — Review and cleanup
  Scope: review changed scripts/docs/tests, remove legacy dead code only if safe, and document any fallback flags.
  Stop when: focused tests and a small operator-flow smoke pass; reviewer signs off.
  Verify: `pytest -q tests/test_operator_flow.py tests/test_orchestration_extraction.py tests/test_reporting.py --tb=short` plus targeted runner tests.
  Risk: P2.

## Tests to Add or Update

- RPC JSONL parser handles responses, `agent_settled`, tool events, malformed lines, and process EOF.
- Runner exits on plain Pi settle when Orchestra is disabled.
- Runner does not exit on settle while mocked Orchestra active count is nonzero.
- Runner exits after mocked active count reaches zero and pending report delivery is complete/absent.
- `scripts/02-open-pi --auto` invokes the RPC runner and still performs cleanup/artifact collection/grading.
- `scripts/04-run-suite` still passes shared options across suites.

## Verification

Focused:
```bash
pytest -q tests/test_operator_flow.py tests/test_orchestration_extraction.py tests/test_reporting.py --tb=short
```

After implementation adds runner tests, include them explicitly:
```bash
pytest -q tests/test_pi_rpc_runner.py tests/test_operator_flow.py --tb=short
```

Runtime dogfood:
```bash
scripts/02-open-pi cap-easy-django-reports --auto --notes "RPC runner smoke"
scripts/05-results run <run-id>
```

Success evidence should include no premature `worker_running_without_exit` when workers complete, and RPC event artifacts present.

## Risks

- RPC protocol details may require a small Node/Python client rather than shell-only scripting.
- Mapping Pi session ids to Orchestra session ids must be exact or the settle gate can wait on the wrong scope.
- If Pi RPC mode does not load extensions or trust resources like print mode, startup flags/settings may need adjustment.
- If Orchestra auto-return cannot inject into an RPC session, a fallback resume/report-injection path may be needed.
- Long-running failed workers need timeouts and clear failure artifacts so CI does not hang indefinitely.

## Open Questions

- Should `--auto` always use RPC once implemented, or should a temporary `--auto-runner rpc|print` flag exist during rollout?
- Which Orchestra CLI command is most reliable for pending session reports in the bench container: status/history/debug, `_await-session-report`, or a new explicit status command?
- What timeout should the runner enforce per task/suite, and should it come from task metadata?
- Should RPC event summaries be elevated into `result.orchestration_checks`, or kept as debug artifacts only at first?
