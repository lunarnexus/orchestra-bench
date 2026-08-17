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

Straightforward source/app-inspired end-to-end tasks:

| Task | Stack | Description |
|------|-------|-------------|
| `cap-easy-express-inventory` | Node / Express / JSON persistence | Build an inventory API with stock adjustments, low-stock reports, ledger history, and workflow evidence |
| `cap-easy-fastapi-helpdesk` | Python / FastAPI / SQLite | Build a helpdesk API with ticket creation, admin triage, audit log, and workflow evidence |
| `cap-easy-django-reports` | Python / Django / SQLite | Build a reporting app with grouped summaries, exports, report history, and workflow evidence |

### capability-normal — integrated end-to-end tasks

More involved app/system tasks restored from the prior hard suite:

| Task | Stack | Description |
|------|-------|-------------|
| `cap-normal-python-worker-sync` | Python / FastAPI / SQLite worker | Build a document sync API plus worker with durable jobs, retries, conflict handling, stale recovery, and audit history |
| `cap-normal-ruby-billing-ledger` | Ruby / Sinatra / SQLite | Build a billing ledger with idempotency, reconciliation, refunds, exports, and workflow evidence |
| `cap-normal-ts-approval-queue` | TypeScript / Node | Build a moderation queue with approval workflow, attachment path safety, visibility rules, XSS-safe rendering, and audit history |

### capability-advanced — larger integrated end-to-end tasks

Full app/system tasks intended for longer multi-role orchestration:

| Task | Stack | Description |
|------|-------|-------------|
| `cap-advanced-url-shortener-review` | Python / FastAPI / SQLite | Build ShortLink Desk: URL shortening, redirects, stats, suspicious-link review, admin decisions, audit history, URL safety checks, and live E2E grading |

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
- `Prompt.md` is the complete agent-facing run prompt — concise instructions for the agent, including any dispatch/role/artifact requirements. The harness does not prepend role/workflow instructions.
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

Lists tasks with `--list`, grouped by suite and role. Use `config` to open Pi's package/resource config TUI inside the benchmark container. For a task run, it prepares an isolated per-run workdir inside the container, copies only agent-visible task materials into it, resolves the parent model from `config/orchestra/agent-catalog.yaml`, and writes `.bench_run.json` in `results/<run_id>-<task_id>/`. By default it prints `Prompt.md` and starts Pi interactively. With `--auto`, it first runs `/orch on` through `pi -p`, then continues the same Pi session with `Prompt.md` non-interactively. With `--auto --no-orchestra`, it skips only that automatic `/orch on` preflight and sends `Prompt.md` as-is; if Orchestra tools are available, the model may still dispatch when the task prompt asks it to. Role-focused dispatch instructions belong in the task's `Prompt.md`; the harness records `target_role` separately for diagnostics instead of injecting prompt text or running Pi as that worker role. Evaluator files are not mounted during this session. After interactive use, exit normally (Ctrl+D).

### `03-collect-results [task-id]`

With no task id, grades every prepared/ungraded run under `results/` and captures run artifacts. Already-graded runs are skipped so repeated collection is safe. With a task id, grades the latest prepared run for that task. Use `--force` to re-grade or `--splits` for dev/holdout summary. Use `scripts/05-results` explicitly for dashboards, filtering, and comparison reporting.

For each graded run, the result folder contains:
- `result.json` — score, checks, metadata, token totals, Pi session ids
- `artifacts/pi-sessions/` — copied Pi JSONL session files for that workdir
- `artifacts/pi-sessions.json` — session id summary
- `artifacts/tokens.json` — token totals parsed from Pi usage fields
- `elapsed_seconds` in `result.json` — wall-clock time from task open/prep to grading
- `artifacts/orchestra-debug/debug/` — full `orchestra debug --session-id ...` output for each Pi session; zero Orchestra runs is not an error
- `artifacts/orchestra-debug/` — additional Orchestra doctor/state/log artifacts when present

### `04-run-suite <suite>`

Runs every task in a suite through `scripts/02-open-pi <task-id> --auto`, grades each run, then prints the result summary. This is the dogfood batch path for suite-level checks. Use `--no-orchestra` for baseline runs that skip automatic `/orch on` skill loading while leaving the task prompt unchanged. Use `scripts/04-run-suite --list` to see suites. To grade already prepared runs without opening Pi, use `scripts/03-collect-results`.

### `05-results [view]`

Read-only historical reporting. Default `dashboard` shows overview, per-suite breakdown, per-test breakdown, token/time metrics, and orchestration behavior summaries. Common views:

- `scripts/05-results runs --limit 50` — recent graded runs
- `scripts/05-results run <run-id-or-run-folder>` — one run detail
- `scripts/05-results debug <run-id-or-run-folder>` — one run detail plus captured Orchestra debug markdown and recent Pi session trace events
- `scripts/05-results tasks` — per-test aggregate breakdown
- `scripts/05-results timeline [--task <task-id>]` — run history
- `scripts/05-results tokens` — token usage
- `scripts/05-results timing` — elapsed time
- `scripts/05-results configs` — discovered result configurations, assigned ids like `C01`
- `scripts/05-results compare --group-by model,orchestra,plugins,skills` — compare grouped configurations

Filters are composable and mostly substring/list based:

```bash
scripts/05-results runs --suite smoke --model 35b
scripts/05-results runs --plugins pi-codegraph
scripts/05-results runs --plugins pi-codegraph,!orchestra
scripts/05-results runs --skills research-first,!build-tdd
scripts/05-results runs --no-orchestra
scripts/05-results compare --suite smoke --group-by model,orchestra,plugins --per-task
scripts/05-results compare --configs C01,C02 --per-task
```

Notes remain available via `--notes <substring>`, but they are free-form operator notes, not the primary way to identify configuration. Prefer metadata filters/config ids for comparisons.

Filter semantics:
- `--model <text>` matches the actual parent run model by substring, so long model names can be shortened. It does not match other role-specific model entries from the catalog.
- `--plugins <list>` filters Pi plugins/extensions/packages captured in run metadata. Separate by comma or space. Prefix a term with `!` or `-` to exclude it, e.g. `--plugins pi-codegraph,!orchestra`.
- `--skills <list>` filters auxiliary, non-Orchestra skills. Prefix with `!` or `-` to exclude.
- `--no-orchestra` filters runs with no actual Orchestra dispatch/activity. Use `--group-by orch_on,orchestra,plugins` to distinguish `/orch on` intent from opportunistic tool use when the plugin is enabled.

### Run metadata capture

Every run persists:
- **role** — parent Pi role/model selector, normally `builder`
- **target_role** — role-focused task target when applicable; the parent session should dispatch this role through Orchestra when enabled
- **model** / **role_models_summary** — catalog-derived parent model and role-model summary; role models may differ
- **catalog_path** / **catalog_sha256** — source catalog path and snapshot hash, kept for provenance but not normally needed as a report filter
- **orchestra** — whether the run used the automatic `/orch on` preflight; this is harness intent, not proof of actual dispatch
- **pi_enabled_plugins** / **pi_enabled_plugins_summary** — actually enabled Pi plugins, used by `05-results --plugins`; installed extensions/packages are captured separately for provenance
- **extra_skills** / **aux_skills_summary** — additional non-Orchestra skills, used by `05-results --skills`
- **notes** — free-form operator notes; useful for human labels, but config comparison should prefer metadata filters/config ids

These fields are stored in `.bench_run.json` when a task run is opened and merged into `result.run_meta` during evaluation, so results can be compared across runs later without depending on brittle notes strings.

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

## Test creation guide

See `TEST_CREATION.md` for the benchmark authoring guide: capability task goals, difficulty calibration, evaluator rules, scoring intent, anti-patterns, and checklist for future test-creating agents.

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
