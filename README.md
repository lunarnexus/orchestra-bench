# orchestra-bench

Lightweight SaaSBench-style benchmark suite for evaluating [Orchestra](https://github.com/lunarnexus/orchestra) itself.

## Why this exists

Official SaaSBench is excellent methodology, but too large and integration-heavy for tuning Orchestra skills on small models. We want the same discipline with much smaller tasks and much faster iteration.

## What we measure

Can Orchestra:
- build a small app end-to-end
- research APIs/docs correctly and only when useful
- plan at the right depth
- dispatch the right roles at the right time
- review, verify, and recover from blockers meaningfully
- use small models efficiently

Also record: score/pass rate, elapsed time, token usage, model/catalog/config used, and Orchestra logs/traces.

## Suite structure

The benchmark is organized into four first-class suites.

### smoke — 6 real end-to-end tasks

Small but real implementation tasks based on SaaSBench-style product patterns. The first three are compact runtime E2E checks; the added workflow smokes require research, planning, building, verification, review, and security evidence files.

| Task | Pattern | Description |
|------|---------|-------------|
| `smoke-dependent-setup-chain` | dependent setup chain → one core action | Create prerequisite data, perform checkout, and verify derived order state |
| `smoke-public-admin-handoff` | public entrypoint → admin confirmation | Record a public support request and expose it for admin triage |
| `smoke-interactive-progress` | interactive action → immediate feedback | Complete lesson answer progression with immediate scoring feedback |
| `smoke-billing-webhook-lifecycle` | metering → invoice → signed webhook | Deduplicate usage, invoice totals, and sign webhook payloads safely |
| `smoke-public-admin-upload` | public upload → admin approval | Accept safe uploads, reject traversal/disallowed files, and approve records |
| `smoke-migration-release-check` | migration → rollback → release note | Preserve compatibility, rollback data, and avoid secret leakage in notes |

### role-focused — 18 per-role tasks

Narrower tasks that isolate value/behavior by role: 3 tasks each for planner, researcher, verifier, reviewer, builder, and appsec.

| Role | Tasks |
|------|-------|
| planner | `planner-plan-api-boundary`, `planner-plan-migration`, `planner-plan-risk-review` |
| researcher | `researcher-choose-storage-api`, `researcher-summarize-release-notes`, `researcher-compare-auth-options` |
| verifier | `verifier-validate-bugfix`, `verifier-check-release-evidence`, `verifier-decide-test-coverage` |
| reviewer | `reviewer-review-inventory`, `reviewer-review-api-diff`, `reviewer-review-error-handling` |
| builder | `builder-add-endpoint`, `builder-fix-seeded-bug`, `builder-implement-parser` |
| appsec | `appsec-vulnerable-diff`, `appsec-review-upload-flow`, `appsec-secrets-config-audit` |

### capability-easy — integrated end-to-end tasks

Straightforward SaaSBench-inspired real-app tasks:

| Task | Stack | Description |
|------|-------|-------------|
| `cap-normal-django-reports` | Python / Django / SQLite | Build a reporting app with sales/refund ingest, grouped summary exports, report history, permissions, and workflow evidence scoring |
| `cap-normal-express-inventory` | Node / Express-style / file-backed | Build an inventory API with product CRUD, stock adjustments, low-stock reporting, ledger history, and workflow evidence scoring |
| `cap-normal-fastapi-helpdesk` | Python / FastAPI / SQLite | Build a helpdesk API with public ticket intake, admin triage, audit log, pagination, and workflow evidence scoring |

### capability-normal — integrated end-to-end tasks

Harder SaaSBench-inspired real-app tasks with more realistic conflicts and traps.

| Task | Stack | Description |
|------|-------|-------------|
| `cap-hard-python-worker-sync` | Python / FastAPI / SQLite worker | Build a document sync API plus background worker with durable SQLite jobs, retries, stale-job recovery, conflict handling, audit history, pagination, and workflow evidence scoring |
| `cap-hard-ruby-billing-ledger` | Ruby / Sinatra / SQLite | Build a billing ledger API + CLI with invoices, payments, refunds/credits, durable idempotency, reconciliation, CSV export, and workflow evidence scoring |
| `cap-hard-ts-approval-queue` | TypeScript / Node / file-backed | Build a moderation queue with durable submissions, approval/rejection flow, attachment path safety, XSS-safe public rendering, audit history, pagination, and workflow evidence scoring |

## Task artifact model

Each task folder contains:

```
tasks/<task-id>/
  PRD.md          — product requirements / authoritative spec (copied into workdir)
  Prompt.md       — agent-facing run prompt / instructions (printed by 02-open-pi)
  kb/             — bounded knowledge / reference docs (markdown, copied into workdir)
  fixture/        — starting workspace seed
  evaluate/       — grader materials (kept outside agent-visible workspace)
  task.yaml       — batch metadata and scoring config
```

- `PRD.md` is the authoritative product spec, copied into the task workdir so the agent can reference it.
- `Prompt.md` is what `02-open-pi` prints to kick off the session — concise instructions for the agent.
- `kb/` or `kb.md` provides bounded knowledge / clarifications (markdown only).
- `evaluate/` contains grader materials. These are not mounted during the agent session; grading copies them into the container only temporarily.

## Operator flow (manual benchmark runs)

The operator interface uses numbered scripts only:

```
scripts/01-start   →  scripts/02-open-pi <task-id>   →  scripts/03-collect-results
                         ↘  scripts/04-run-suite <suite>
                            scripts/05-results [view]
```

Task definitions are not mounted during agent runs. `02-open-pi` automatically creates a fresh run id and isolated per-run workdir, then copies only agent-visible materials before opening Pi.

### Step-by-step

```bash
# 1. Build and recreate the shared container
scripts/01-start start

# 2. Optional: adjust Pi package/resource config inside the container
scripts/02-open-pi config

# 3. List tasks, then open Pi for one task
scripts/02-open-pi --list
scripts/02-open-pi <task-id>
# Or run Prompt.md non-interactively and exit
scripts/02-open-pi <task-id> --auto
# For a baseline/debug run without automatic /orch on:
scripts/02-open-pi <task-id> --auto --no-orchestra

# 4. After completing one or more tasks in Pi, grade all ungraded runs
scripts/03-collect-results

# Optional: run every task in a suite via --auto, then grade/report it
scripts/04-run-suite <suite>

# Optional: inspect historical results, task breakdowns, timelines, and tokens
scripts/05-results
scripts/05-results run <run-id>
scripts/05-results timeline
scripts/05-results tokens
scripts/05-results timing
```

### `01-start [start|stop]`

`start` builds the shared benchmark image, then recreates the long-lived container so mounts/config are fresh. Because the build is fast, this is the normal startup command. `stop` stops and removes the benchmark container cleanly while leaving the image, results, and artifacts intact.

### `02-open-pi <task-id>`

Lists tasks with `--list`, grouped by suite and role. Use `config` to open Pi's package/resource config TUI inside the benchmark container. For a task run, it prepares an isolated per-run workdir inside the container, copies only agent-visible task materials into it, resolves the parent model from `config/orchestra/agent-catalog.yaml`, and writes `.bench_run.json` in `results/<run_id>-<task_id>/`. By default it prints `Prompt.md` and starts Pi interactively. With `--auto`, it first runs `/orch on` through `pi -p`, then continues the same Pi session with `Prompt.md` non-interactively. Use `--auto --no-orchestra` only for baseline/debug runs that intentionally skip Orchestra preflight. For role-focused tasks, the parent Pi session is instructed to dispatch the target role through Orchestra when Orchestra is enabled; the harness records `target_role` separately instead of running Pi as that worker role. Evaluator files are not mounted during this session. After interactive use, exit normally (Ctrl+D).

### `03-collect-results [task-id]`

With no task id, grades every prepared/ungraded run under `results/`, captures run artifacts, and then shows the historical dashboard. Already-graded runs are skipped so repeated collection is safe. With a task id, grades the latest prepared run for that task. Use `--force` to re-grade, `--splits` for dev/holdout summary, or `--compare` for provenance grouping (role/model/catalog hash/path/orchestra).

For each graded run, the result folder contains:
- `result.json` — score, checks, metadata, token totals, Pi session ids
- `artifacts/pi-sessions/` — copied Pi JSONL session files for that workdir
- `artifacts/pi-sessions.json` — session id summary
- `artifacts/tokens.json` — token totals parsed from Pi usage fields
- `elapsed_seconds` in `result.json` — wall-clock time from task open/prep to grading
- `artifacts/orchestra-debug/debug/` — full `orchestra debug --session-id ...` output for each Pi session; zero Orchestra runs is not an error
- `artifacts/orchestra-debug/` — additional Orchestra doctor/state/log artifacts when present

### `04-run-suite <suite>`

Runs every task in a suite through `scripts/02-open-pi <task-id> --auto`, grades each run, then prints the result summary. This is the dogfood batch path for suite-level checks. Use `--no-orchestra` for baseline/no-Orchestra suite runs. Use `scripts/04-run-suite --list` to see suites. To grade already prepared runs without opening Pi, use `scripts/03-collect-results`.

### `05-results [view]`

Read-only historical reporting. Default `dashboard` shows overview, recent runs, task breakdown, and token summary. Other views:
- `scripts/05-results runs --limit 50`
- `scripts/05-results run <run-id-or-run-folder>`
- `scripts/05-results tasks`
- `scripts/05-results timeline [--task <task-id>]`
- `scripts/05-results tokens`
- `scripts/05-results timing`

### Run metadata capture

Every run persists:
- **role** — parent Pi role/model selector, normally `builder`
- **target_role** — role-focused task target when applicable; the parent session should dispatch this role through Orchestra when enabled
- **model** — catalog-derived model used for the run
- **catalog_path** / **catalog_sha256** — source catalog path and snapshot hash
- **orchestra** — optional metadata field; use Pi's `/config` inside the session for runtime toggles
- **extra_skills** — list of additional skills loaded for this run
- **notes** — free-form operator notes about config, catalog version, etc.

These fields are stored in `.bench_run.json` when a task run is opened and merged into `result.run_meta` during evaluation, so results can be compared across runs later.

## Testing changes

For harness, task, collector, artifact, or reporting changes, unit tests are only the first check. Also dogfood the real Pi path:

```bash
scripts/02-open-pi smoke-dependent-setup-chain --auto
scripts/03-collect-results
scripts/05-results run <run-id>
```

The dogfood run should produce a real Pi session, result JSON, token/timing artifacts when available, and `orchestra debug` output. By default `--auto` runs `/orch on` before the task prompt so the orchestrator skill is loaded for the session. Tests and ad hoc checks should not leave fake result history in `results/`; use temporary result dirs or clean generated runs afterward.

## Runtime contract

The numbered scripts handle the normal workflow. Use `scripts/01-start start` to build and recreate the container with fresh mounts/config, or `scripts/01-start stop` to stop and remove the container cleanly.

Runtime internals and troubleshooting checks live in `ARCHITECTURE.md` so the README stays focused on the operator flow. The container installs the LM Studio and CodeGraph Pi plugins during image build, and copies `config/skills/` into Pi's in-container skills directory.

## Methodology rules

- Keep outcome and process separate. Outcome is primary; process traces are diagnostic.
- Use development vs holdout splits.
- Run repeated trials per model/config.
- Keep fixtures deterministic where possible.
- Prefer hidden grading for final outcome.
- Capture traces for adjudication, not just scores.
- Design tasks so weak models can still reveal orchestration quality.

## Metrics

Report separately:
- **outcome**: pass/fail, evaluator score
- **process**: which roles were used, in what order, how many times
- **cost**: total tokens, parent tokens, worker tokens, elapsed time
- **efficiency**: passes per token, passes per minute
- **policy**: read-only compliance, scope compliance, proper blocking
- **quality**: review findings, verifier correctness, residual defects
- **stability**: repeatability across 3+ trials

## Repo layout

```
orchestra-bench/
  config/orchestra/     — benchmark-local Orchestra config (catalog, prompts, config)
  config/pi/            — Pi/plugin runtime config (lmstudio.json, settings.json)
  config/skills/        — benchmark-local Pi skills copied into the container image
  docker/               — Dockerfile and entrypoint for the shared container
  scripts/              — numbered operator scripts
  tasks/<task-id>/      — task definitions with fixture/, evaluate/, task.yaml
  results/              — per-run result artifacts (.bench_run.json, scores)
  artifacts/            — captured session logs and traces
```
