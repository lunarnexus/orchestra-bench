# Plan — Capability Normal/Hard Suite Redesign

## Goal
Replace the flawed old capability tasks with two real end-to-end capability suites:

- `capability-normal`: 3 straightforward, passable app-building tasks.
- `capability-hard`: 3 passable but difficult SaaSBench-style tasks with conflicts/traps.

Authoritative decisions live in `FOUNDATION.md`.

## Design Corrections
- Preinstall common task platform dependencies in the benchmark image/container where practical; do not make agents spend task time on boring package setup.
- Use bundled local `kb/` docs instead of live web access; internet research is not the target capability here.
- Use real app dependencies when they matter to the behavior under test. Redis/Postgres are acceptable if stable inside the existing benchmark container.
- Do not create extra service containers; install/start any services inside the existing benchmark container.
- Use lightweight substitutes only when they preserve the same app behavior and failure modes.
- Workflow evidence is expected and scored, not an automatic pass/fail gate. Missing workflow artifacts should reduce score substantially, but a functionally excellent result may still pass depending on task rubric.
- Capability-normal tasks must include a browser-routable `GET /` HTML entrypoint. API-only completion is no longer sufficient for a "working application" benchmark.

## Target Tasks

### capability-normal
1. `cap-normal-fastapi-helpdesk`
   - Python FastAPI API + SQLite/Postgres-style persistence.
   - Public ticket intake, admin triage, audit log, pagination/status codes.

2. `cap-normal-express-inventory`
   - Node/Express API + SQLite/Postgres-style persistence.
   - Inventory reservation, release, commit workflow, seeded SKUs.

3. `cap-normal-django-reports`
   - Django app + SQLite.
   - Date filters, grouped aggregates, CSV export, permission checks, performance budget.

### capability-hard
1. `cap-hard-ruby-billing-ledger`
   - Ruby Sinatra/Rack app + durable SQLite ledger.
   - Customers, invoices, payments, refunds/credits, idempotency traps, reconciliation, CSV export, and CLI/API parity.

2. `cap-hard-ts-approval-queue`
   - TypeScript/Node app, simple server/build, SQLite/file store.
   - Submission moderation, public visibility, upload/path/XSS traps.

3. `cap-hard-python-worker-sync`
   - Python API + background worker + SQLite jobs; Redis if stable in the existing container.
   - External sync, retries, polling, stale jobs, conflicting local docs.

## Shared Scoring Direction
- Functional outcome: about 70%.
- Workflow evidence: about 20%.
- Verification/review/security artifacts: about 10%.
- Workflow evidence should be scored for relevance and consistency with actual files/tests, not just file existence.

Expected/scored workflow artifacts per task:
- `PLAN.md`
- `RESEARCH.md`
- implementation files
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`
- final summary/answer

## Implementation Slices
1. [done] Cleanup old capability tasks and update inventory/docs/tests.
2. [done] Build shared capability workflow-evidence evaluator helper.
3. [done] Build 3 `capability-normal` tasks with unsolved fixtures and reference-solution validation.
4. [done] Build 3 `capability-hard` tasks with stateful correctness, security, validation, persistence, and edge-case checks.
5. [done] Update docs fully.
6. [done] Dogfood representative normal/hard tasks, then full suites.

## Current Status
- Public task inventory is now 30 tasks: 6 smoke, 18 role-focused, 3 `capability-normal`, and 3 `capability-hard`.
- Capability task directories, fixtures, evaluators, solved references, and focused tests are present.
- Workflow evidence scoring is relevance-based and now includes spoof-resistance checks for keyword/token-salad and prose-shaped boilerplate where reviewer feedback found gaps.
- Root test collection is constrained to harness tests with `pytest.ini`, so task fixture/evaluator tests are exercised through focused harness tests rather than accidentally collected from every task workspace.
- Capability tasks now require and grade browser-routable `GET /` HTML entrypoints; API-only completion is no longer sufficient for capability tasks.
- Current final verification: `pytest -q` passed with `648 passed, 5 skipped`.
- `results/` contains graded dogfood/suite evidence with Pi session ids, token totals, elapsed timing, and Orchestra debug artifacts. Latest failed capability runs were reviewed as valid model signal, not evaluator defects.

## Unfinished Issues
1. [done] Fixed `cap-hard-python-worker-sync` workflow spoofing before dogfood. Verifier `7555e2cd56a1` reproduced prose-shaped boilerplate scoring `pass` / `0.86`; builder `b60be852aa30` added exact regression coverage and task-local evaluator tightening; verifier `d23aded3bbe6` confirmed spoof score `0.72` with all workflow relevance checks false, solved score `1.0`, and missing-workflow score `0.7`.
2. [done] Fixed only `cap-normal-django-reports` representative dogfood grading trust issues before further dogfood: reviewer `d315721a6a9d` found evaluator workflow checks were too implementation-specific and final-summary scoring was impossible because no final answer is passed into `evaluate_workflow_evidence`. Builder `81e84cc6a61d` relaxed workflow evidence to accept semantic equivalents and made missing final answer neutral; verifier `a559277e87df` confirmed focused tests `19 passed`, solved score `1.0`, filler/spoof regressions still fail, and `final_summary.max == 0.0` when no final answer is provided. The dogfood app's date-range/history-shape failures are legitimate model misses and should remain detected/scored/reported, not fixed in the run or hidden by evaluator changes.
3. [done] Converted capability-normal tasks from API-only slices to browser-routable working apps. Planner `44a77ca68b9f` found all three normal tasks lacked a graded `GET /` UI; FastAPI verifier `b9e0a2c80f24`, Express verifier `83a445627d4b`, and Django verifier `9c5ef9310287` confirmed solved references expose `200 text/html` browser entrypoints and focused checks pass.
4. [done] Applied the same browser-routable working-app requirement to capability-hard tasks before final dogfood/full suites, because `FOUNDATION.md` applies this principle to all capability tasks. Python worker sync verifier `81b7504f1c6f`, Ruby billing verifier `d32628d8f032`, and TS approval verifier `201d262a93de` confirmed `GET /` browser entrypoints and focused checks.
5. [done] Ran real Pi dogfood for one representative normal task and one representative hard task through `scripts/02-open-pi <task-id> --auto` and `scripts/03-collect-results`: `cap-normal-fastapi-helpdesk` run `20260812T001855` passed with `functional_browser_homepage=true`; `cap-hard-python-worker-sync` run `20260812T002218` passed with `functional_browser_homepage=true`.
6. [done] Ran full `capability-normal` and `capability-hard` suites through `scripts/04-run-suite` after focused verification and representative dogfood. Latest suite evidence: normal suite ran all three tasks with `cap-normal-django-reports` failing and `cap-normal-express-inventory`/`cap-normal-fastapi-helpdesk` passing; hard suite ran all three tasks with `cap-hard-python-worker-sync` passing and `cap-hard-ruby-billing-ledger`/`cap-hard-ts-approval-queue` failing. These failures need triage as benchmark signal vs evaluator/task issue before final handoff.
7. [done] Fixed evaluator-contract mismatches found by reviewer `31578af2350c` before final handoff: Django reports evaluator now accepts semantic row-count aliases while preserving invalid date-range failure; TS approval evaluator accepts equivalent safe upload/history wrapper shapes while preserving missing-admin-route failure. Builder `2584a8b7cb54` and verifier `0bdd8ce38129` confirmed focused tests `21 passed` and negative checks still fail.
8. [done] Reran affected dogfood tasks after evaluator-contract fixes (`cap-normal-django-reports`, `cap-hard-ts-approval-queue`) because old failed workdirs were gone and could not be regraded. Latest failures were triaged by reviewer `6e3deb8b4b1b` as valid model signal, not evaluator defects.
9. [done] Inspected `scripts/05-results` and representative failed/passed run views for score, timing, token, Pi session, and Orchestra debug artifacts. Latest dashboard has graded dogfood/suite results with expected pass/fail signal and captured Pi sessions/tokens/timing/debug artifacts.
10. [done] Cleaned temporary/ad hoc root artifacts: removed `$tmp`, `tmp-verifier-evidence`, `undefined`, `__pycache__`, `tests/__pycache__`, and `.pytest_cache`.
11. [done] Re-ran final verification after dogfood and elapsed-efficiency fix: `pytest -q` passed with `648 passed, 5 skipped`.
12. [sequential] Prepare final non-security review and commit handoff. Security review was explicitly skipped by user request.
