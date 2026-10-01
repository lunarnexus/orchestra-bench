# Plan

## Goal
Automate testing `orchestra-bench` against a selected Orchestra branch/ref, ensuring the Orchestra CLI/package and Pi extension come from the same checkout before runtime initialization.

## Finished Successfully
`./scripts/01-start` can be run with an Orchestra ref/branch setting, switches the in-container Orchestra checkout before `orchestra init pi --copy --force`, uses the matching Pi extension from that same checkout, and records the effective Orchestra ref/branch/SHA in runtime/run metadata.

## Acceptance Criteria
- `01-start` applies the Orchestra ref inside the container before runtime config sync; the default ref is the `test` branch, with `BENCH_ORCHESTRA_REF` as an optional override.
- Startup order is:
  1. build/install Orchestra in image,
  2. recreate container,
  3. fetch/switch or checkout `/opt/orchestra/src` to `BENCH_ORCHESTRA_REF` (default: `test` branch),
  4. reinstall editable package if needed,
  5. use Pi extension from `/opt/orchestra/src/extensions/pi/orchestra`,
  6. run `orchestra init pi --copy --force`.
- Avoid mixed-version tests: CLI/package and Pi extension must come from the same Orchestra checkout/ref.
- Runtime summary/run metadata records Orchestra source dir, requested ref, branch, SHA, and dirty state.
- In-container runs always switch to the effective ref (default `test`); host-side runs with `BENCH_ORCHESTRA_REF` unset remain unchanged (no git ops, empty `orchestra_provenance`).

## Scope
In scope:
- Startup/runtime code in `bench/runtime.py` and CLI/start flow as needed.
- Dockerfile/build args only if needed for repeatable branch installation.
- Tests for startup ordering, extension source selection, and metadata.

Out of scope:
- Changing benchmark tasks.
- Changing model/provider config.
- Manual branch switching in the running container.

## Context / Evidence
- Current Dockerfile clones Orchestra into `/opt/orchestra/src` and installs it editable into `/opt/orchestra/.venv`.
- `sync_runtime_config()` runs `orchestra init pi --copy --force` from container `PATH`.
- Current extension source may be `/bench/orchestra-extension`, mounted from host `../orchestra/extensions/pi/orchestra`.
- If only `/opt/orchestra/src` is switched, the CLI/package and extension can come from different branches.

## Task Breakdown
- [x] Slice 1 — sequential — Design branch/ref configuration
  Reference: PLAN.md Slice 1
  Scope: choose exact env/build arg names and default behavior.
  Stop when: implementation interface is clear and preserves current unset behavior.
  Verify: inspect startup flow and tests to update.
  Risk: P2 — startup semantics affect every benchmark run.
  Gates: user approval before code changes.
  Note: env `BENCH_ORCHESTRA_REF` is an optional override; in-container default is the `test` branch (host-side unset = no switch).

- [x] Slice 2 — sequential — Apply Orchestra ref before runtime init
  Reference: PLAN.md Slice 2
  Scope: container-side git fetch/switch/checkout and editable reinstall before `_sync_runtime_config_inside_container()`.
  Stop when: `orchestra init pi --copy --force` runs after the checkout step.
  Verify: focused startup/runtime tests.
  Risk: P1 — wrong ordering gives mixed or stale Orchestra runtime.
  Gates: build/test verification.
  Note: `_apply_orchestra_ref()` runs at the top of `sync_runtime_config()` (in-container), before `orchestra init pi --copy --force`; ref passed into the container via `container_exec` env.

- [x] Slice 3 — sequential — Align Pi extension source with checked-out ref
  Reference: PLAN.md Slice 3
  Scope: ensure runtime config copies extension from `/opt/orchestra/src/extensions/pi/orchestra` when a ref is configured, avoiding host-mounted branch mismatch.
  Stop when: CLI/package and extension source are guaranteed same checkout.
  Verify: runtime summary and test assertions.
  Risk: P1 — mixed extension/package versions invalidate benchmarks.
  Gates: test verification.
  Note: `_require_orchestra_extension_source(..., prefer_checkout=True)` forces the checkout extension dir when a ref is set.

- [x] Slice 4 — sequential — Record Orchestra provenance
  Reference: PLAN.md Slice 4
  Scope: include source dir, requested ref, current branch, SHA, and dirty state in runtime summary/run metadata.
  Stop when: results show effective Orchestra provenance.
  Verify: unit tests plus one startup metadata inspection.
  Risk: P2 — missing provenance makes comparisons ambiguous.
  Gates: test verification.
  Note: `orchestra_provenance` added to the runtime-config-sync summary (and thus run metadata); `{}` when unset.

- [x] Slice 5 — sequential — End-to-end validation
  Reference: PLAN.md Slice 5
  Note: default-ref behavior covered by focused tests; Docker smoke validation is the user's next step.
  Scope: run focused tests, then `./scripts/01-start` with test ref, then smoke benchmark.
  Stop when: smoke has lifecycle ok, evaluation ok, no evaluator leakage, and recorded Orchestra ref matches requested ref.
  Verify: `python3 -m pytest tests -q` if practical, plus smoke run.
  Risk: P2 — container startup path is integration-heavy.
  Gates: user approval before running benchmark smoke.

## Parallelization Check
Sequential. Startup ordering and extension-source alignment are coupled; do not split implementation across overlapping runtime/startup files.

## Tests to Add or Update
- Startup/runtime test that branch/ref checkout happens before runtime config sync.
- Test that configured ref uses `/opt/orchestra/src/extensions/pi/orchestra` rather than host-mounted `/bench/orchestra-extension`.
- Metadata test for requested ref, branch, SHA, and dirty state.
- Existing runtime contract tests should remain green.

## Verification
- Focused tests for runtime/startup flow.
- Full tests if practical: `python3 -m pytest tests -q`.
- Manual validation:
  ```bash
  ./scripts/01-start
  ./scripts/02-run --auto smoke-dependent-setup-chain --no-orchestra --notes "orchestra test-branch smoke" --verbose
  ```
- Confirm metadata records requested ref `test` (or the override) and effective SHA.

## Risks
- Mixed branch sources if extension remains host-mounted while package is switched in container.
- Dependency changes on branch may require Docker build-time ref checkout, not only runtime checkout.
- Detached SHA/tag checkout needs `git checkout`, not `git switch`.
- Network/fetch failures should fail startup clearly.

## Open Questions
- None; default is `test`, `BENCH_ORCHESTRA_REF` remains an optional override.
