# EVALUATION

## 1) Evidence inventory

### Commands run
- `./03-results dash`
- `./03-results runs`
- `./03-results run 20260903T010508`
- `./03-results run 20260903T010424`
- `./03-results run 20260903T010339`
- `./04-debug 20260903T010508 orch`
- `./04-debug 20260903T010424 orch`
- `./04-debug 20260903T010339 orch`
- `./04-debug 20260903T010424 full`
- `./04-debug 20260903T010424 raw`
- read-only `rg/find` inspections noted below

### Artifacts and sources inspected
- `PLAN.md`
- `DECISIONS.md`
- `ARCHITECTURE.md`
- `RESEARCH.md`
- `README.md`
- `bench/cli.py`
- `bench/harnesses/pi_rpc.py`
- `bench/orchestration.py`
- `bench/reporting/debug.py`
- `bench/reporting/formatters.py`
- `bench/reporting/queries.py`
- `bench/reporting/scoring.py`
- `bench/runtime.py`
- `bench/runner.py`
- `tests/unit/test_cli.py`
- `tests/unit/test_reporting.py`
- `tests/unit/test_runner.py`
- `tests/unit/test_scoring.py`
- `tests/unit/test_session_debug.py`
- `tests/unit/test_pi_rpc_harness.py`
- `tests/unit/test_orchestration_settle.py`
- `tests/integration/test_scripts.py`
- `results/20260903T010339-smoke-dependent-setup-chain/result.json`
- `results/20260903T010424-smoke-dependent-setup-chain/result.json`
- `results/20260903T010508-smoke-dependent-setup-chain/result.json`
- `results/20260903T010508-smoke-dependent-setup-chain/artifacts/harness/events.jsonl` via `rg`

### Facts proven
- Three distinct run states are present in existing artifacts:
  - disabled tools mode: `20260903T010339` has `provenance.orchestra=false` and `provenance.orchestra_tools_enabled_by_default=false` in raw `result.json`.
  - skip-`/orch on` contamination mode: `20260903T010424` has `provenance.orchestra=false`, `orchestra_tools_enabled_by_default=null`, contamination populated, and `03-results run` reports contamination.
  - full Orchestra mode: `20260903T010508` has `provenance.orchestra=true`, `auto_gate.reason=settled`, and Orchestra category scoring persisted.
- Computed scoring persists to raw JSON for sampled runs: `score_numeric`, `score_display`, and `category_scores` exist in all three sampled `result.json` files.
- `04-debug` fallback to harness artifacts is implemented and tested (`bench/reporting/session_debug.py`, `tests/unit/test_session_debug.py`, `tests/unit/test_cli.py`), and public command evidence from `./04-debug 20260903T010424 raw` showed harness fallback content.
- Public root commands exist (`01-start`, `02-run`, `03-results`, `04-debug`).

### Facts unproven / evidence gaps
- No public-command evidence was gathered for lifecycle failure, evaluator crash, malformed result JSON, or delete/rescore flows; only source/tests were reviewed.
- No fresh run was allowed, so mode semantics were judged from existing artifacts plus source/tests, not from newly executed `02-run` invocations.
- Existing command output for `./04-debug 20260903T010508 orch` and some `orch` outputs was truncated by harness volume; source plus targeted artifact grep were used to close key questions.

## 2) Issue inventory

### Blocker
1. **Full-Orchestra reporting undercounts returned child work and lowers orchestration score.**
   - Evidence:
     - `results/20260903T010508-smoke-dependent-setup-chain/result.json` records `roles_requested=[builder, verifier]`, `roles_started=[builder, verifier]`, `roles_returned=[builder]`, `child_sessions.completed=1`, orchestration `26.25/35`, total `88/100`.
     - `rg -n "returned done|subagents returned|verifier" results/20260903T010508-smoke-dependent-setup-chain/artifacts/harness/events.jsonl` shows extension/user evidence for two returned roles and a later aggregate return: `verifier ... returned done (2/2)` and `[orchestra: 3 subagents returned]` with both builder and verifier summaries.
   - Why it matters: `03-results`, raw `result.json`, and underlying run evidence disagree on core Orchestra facts; score correctness and reporting truth fail.

### Important
2. **Public UX still exposes unsupported debug flags and documents them as public.**
   - Evidence:
     - `README.md` examples/options include `./04-debug <run-id> full --no-tools`, `--no-tools`, `--no-color`, `--plain`.
     - `bench/cli.py` public help prints `04-debug <run-id> orch|full|raw [--no-tools] [--no-color] [--plain]` and the `04-debug` parser accepts those flags.
     - `tests/unit/test_cli.py` asserts those flags are public.
   - Conflict: `PLAN.md` says `04-debug` should use positional modes only and no unsupported flags.

3. **`03-results` still has a `debug` subcommand path, which conflicts with the public split between results and debug.**
   - Evidence: `bench/cli.py` defines `results_subparsers.add_parser("debug", ...)` while `DECISIONS.md` says `03-results` owns results and `04-debug` owns traces.
   - Impact: product surface is muddier than specified even if hidden from help.

4. **Run detail prints a `sessions` path as if present even when `pi-sessions` does not exist.**
   - Evidence:
     - `./03-results run 20260903T010424` and `./03-results run 20260903T010508` print `sessions : /home/james/workspace/orchestra-bench/results/.../artifacts/pi-sessions`.
     - `find .../artifacts/pi-sessions` for both run dirs returned `No such file or directory`.
   - Conflict: `PLAN.md` requires missing evidence to appear as unavailable/warning/error rather than being silently implied present.

5. **Test suite contains stale/conflicting public UX expectations.**
   - Evidence:
     - `tests/unit/test_cli.py` expects current help: `usage: 03-results [command] [run-id]` and rejects `03-results debug` in help.
     - `tests/integration/test_scripts.py` still expects old help text: `usage: 03-results [dashboard|runs|run|tokens|timing|debug|compare|rescore|delete]` and strings `delete-preview` / `delete-confirmation`.
   - Impact: operator-facing CLI tests are not a trustworthy acceptance signal.

6. **Full-Orchestra evidence fields are internally inconsistent.**
   - Evidence: `results/20260903T010508.../result.json` has `auto_gate.snapshots[0].session_report_available=false` and `session_report_delivered=true`; same file records evidence `pi_sessions=false` even though the run was graded from Orchestra-related harness evidence and reports sessions path.
   - Impact: debug usefulness/reliability scoring is harder to trust.

### Minor
7. **Terminology is inconsistent between requirements and implementation (`dash` vs `dashboard`).**
   - Evidence: current public help uses `dash`; stale integration tests still expect `dashboard` in usage. This is mainly a cleanup/consistency problem once stale tests are fixed.

### No-action
8. **Three-mode semantics are materially represented in current artifacts and source.**
   - Evidence: sampled `result.json` files plus `bench/cli.py`, `bench/runtime.py`, `bench/harnesses/pi_rpc.py`, `tests/unit/test_cli.py`, `tests/unit/test_pi_rpc_harness.py` show distinct disabled-tools, skip-`/orch on`, and full-Orchestra handling.

### Unknown
9. **Failure-path public UX completeness remains partially unproven.**
   - Evidence gap only: no allowed fresh runs for lifecycle/evaluator/malformed-JSON cases; source/tests exist but no public-command proof was gathered in this pass.

## 3) End-state requirement judgment
- Three Orchestra modes: **partial pass** — semantics exist in code/artifacts; no fresh run proof this pass.
- Reporting truth: **fail** — full-Orchestra run facts undercount returns; missing session paths printed without missing-state labeling.
- Public UX: **fail** — public docs/help/tests still expose unsupported `04-debug` flags; `03-results debug` still exists in code.
- Test value: **fail** — stale/conflicting CLI expectations reduce trust.
- Known problem history: **mixed**
  - `/orch on` wait-for-settle: pass in source/tests.
  - contamination vs orchestration success: pass in source/artifacts.
  - score persistence to raw JSON: pass in sampled artifacts.
  - `04-debug` fallback: pass in source/tests and one public raw fallback check.
  - settled full-Orchestra stale active children: pass for sampled run (`active=0`, `inferred_active=0`).
  - full-Orchestra metric persistence/category availability: pass in sampled raw JSON.
  - public docs unsupported flags/commands: fail.
  - full-Orchestra return/accounting correctness: fail.
- Score correctness: **fail** — orchestration score for sampled full-Orchestra run is based on undercounted returned roles/children.
- Report consistency: **fail** — harness event evidence, raw result, and summary outputs disagree.
- Debug usefulness: **partial pass** — fallback exists and raw output is helpful; truth issues remain.
- Contamination handling: **pass** for sampled contamination run.
- Settlement: **partial fail** — settle gate exists and sampled active counts are zero, but persisted return accounting is incomplete for full-Orchestra evidence.
- Failure paths: **unknown/partial** — source/tests cover them; public-command proof incomplete.
- Benchmark value: **fail for acceptance** — benchmark is close, but misleading Orchestra metrics and stale UX/tests reduce operator trust.

## 4) Overall verdict
- **Verdict: fail**
- Primary reason: current benchmark outputs are not fully trustworthy for full-Orchestra runs, and public command/test surface still contradicts the stated end-state UX.
