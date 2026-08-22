# TEST CREATION

This document is the benchmark authoring guide for `orchestra-bench`.

It exists for future agents and humans who need to create, replace, or redesign benchmark tasks — especially capability tasks.

Capability tasks should borrow from SWE-bench, SaaSBench, and mature open-source projects: real code snapshots or realistic app fixtures, detailed end-state requirements, source changes where appropriate, and live end-to-end verification.

For process/orchestration benchmarking, mature open-source slices are especially valuable. We are not primarily testing whether a model can invent a novel implementation; we are testing whether the agent system can research, decompose, implement, verify, review, and integrate a well-specified behavior. Existing mature code and tests provide a high-quality oracle and comparison target.

The goal is not just to add more tests. The goal is to add tests that meaningfully answer:

> Does this agent setup produce better results?
>
> If so, in what ways?

---

## 1. What the benchmark is trying to measure

The benchmark is for evaluating **agent systems**, not just raw model coding ability.

That means we care about four distinct things:

1. **Intelligence**
   - Did the agent understand the requirements?
   - Did it build the correct thing?
   - Did it handle edge cases and hidden traps?
   - Did it make good technical decisions?

2. **Speed**
   - How quickly did it get to a correct answer?
   - Faster is better when correctness is preserved.

3. **Efficiency**
   - How many tokens did it consume?
   - Fewer tokens are better when correctness is preserved.

4. **Process / Orchestration**
   - Did planning, research, review, verify, and appsec activity improve outcomes?
   - Did the agent coordinate work well?
   - Did the orchestration overhead pay for itself?

Top-level **pass/fail** should remain simple:

- **Pass** = the task produced what we asked for and it works correctly.
- **Fail** = it did not.

Pass/fail is not the same thing as ranking quality. Ranking quality comes from category scores.

---

## 2. Design principles for new tests

### 2.1 Outcome-first
The benchmark should primarily measure whether the final product works.

Do not create tasks that mainly reward writing plans, buzzwords, or ceremonial workflow artifacts.

### 2.2 Orchestration should be naturally useful
Do not force orchestration just so dispatch events happen.

Instead, create tasks where orchestration *helps* because the work is:
- multi-step
- multi-surface
- stateful
- security-sensitive
- full of edge cases
- easier to decompose than to brute-force in one pass

### 2.3 Real product patterns beat toy tasks
Prefer tasks that look like small SaaS/app problems:
- public + admin split
- browser surface + API surface
- persistence + reporting
- background job + retry + recovery
- audit/history
- imports/exports
- security boundaries

### 2.4 Difficulty should come from coordination and correctness, not random obscurity
Good difficulty:
- hidden edge cases
- state transitions
- idempotency
- persistence correctness
- multi-step flows
- safe handling of hostile input
- recovery after restart or failure

Bad difficulty:
- vague specs
- arbitrary trick wording
- missing required information
- dependency chaos unrelated to the product behavior
- giant unbounded scope

### 2.5 Tests should separate models
A useful benchmark should produce visibly different outcomes for different model/system strengths.

If two clearly different agents routinely tie on a task, the task may be too easy, too binary, or too shallow.

---

## 3. What makes a capability task good

A strong capability task should usually have most of these properties:

- **A real live surface** that can be exercised end-to-end: browser UI, HTTP API, CLI, worker, or file-processing command
- **Durable persistence** when the product behavior implies state (file-backed, SQLite, Postgres, etc.)
- **Several related endpoints or actions**
- **Nontrivial state transitions**
- **A few important invariants**
- **At least one security-sensitive area**
- **At least one failure/recovery edge case**
- **Multiple surfaces that must agree**
  - browser
  - API
  - worker
  - CLI
  - export/report
- **Enough scope that planning/research/review/verify/appsec can matter**

A weak capability task tends to be:
- one file
- one endpoint family
- one happy path
- no persistence hazards
- no retry/conflict/state traps
- no meaningful security concerns

### 3.1 Canonical capability task shape

New capability tasks should combine three benchmark traditions:

- **SWE-bench style:** real code snapshot, issue/feature request, source changes, regression checks.
- **SaaSBench style:** detailed end-state requirements, stateful product workflow, live verifier.
- **orchestra-bench style:** workflow evidence, orchestration diagnostics, category scores, token/time/process reporting.

The preferred task is:

> Given a real or realistic app snapshot and a detailed product requirement, modify/build the app so a live end-to-end workflow works correctly.

The evaluator should:

1. grade the current rubric/check structure,
2. score workflow/process evidence as secondary evidence,
3. run static/source checks where useful,
4. start the app/CLI/service for real,
5. exercise it through browser, HTTP, subprocess, worker, or file fixtures,
6. verify persisted state and hidden invariants.

For web apps, use Playwright or equivalent browser automation when practical. For CLI apps, use subprocess golden-output tests. For APIs/services, use local HTTP fixtures. For workers, seed jobs/state and run the worker process.

### 3.2 Mature open-source slice tasks

A strong task may be a small, well-bounded slice of a mature open-source project rather than a complete app. Good sources include Git, OpenSSH, rsync, curl, SQLite, and similarly old, heavily tested projects.

Use this pattern when the mature project already gives us better behavior and tests than we can invent quickly:

1. choose a stable subsystem boundary, such as a parser, matcher, CLI mode, file-tree operation, or protocol-free helper;
2. record upstream provenance: project, license, URL, commit or release, source files, and test files;
3. keep evaluator-only reference code or oracle invocations outside `fixture/`;
4. write a PRD that describes the required behavior, not the solved implementation;
5. allow equivalent implementations, but keep a comparison note against upstream code for diagnosis;
6. run end-to-end tests through the same public surface the agent is asked to provide.

Good mature-OSS slices:
- Git `wildmatch`: compact glob/path matcher with rich mature test vectors.
- OpenSSH client config resolution: realistic parser/precedence behavior, oracle-checkable with `ssh -G -F` where available.
- rsync filter/exclude behavior: filesystem E2E semantics and strong regression tests.
- curl-style transfer/test harness slices: useful, but often higher infra cost.

Avoid deleting a giant subsystem from a full app unless the build and test loop remains reliable. A trimmed fixture with the target implementation removed is usually the first choice. Full-repo deletion/rebuild variants can be added later when the smaller benchmark proves useful.

Mature-OSS tasks must still follow the normal benchmark rules:
- behavior dominates source similarity;
- hidden tests check invariants, not arbitrary implementation style;
- workflow evidence remains secondary process evidence;
- evaluator-only upstream code/tests must not be visible in the run workspace;
- license/provenance must be documented.

---

## 4. Target suite shape

Current public inventory philosophy:

- `smoke`
  - real but compact end-to-end tasks
  - runtime sanity + workflow sanity
- `role-focused`
  - narrower tasks to isolate planner / researcher / verifier / reviewer / builder / appsec behavior
- `capability-easy`
  - straightforward integrated app tasks
- `capability-normal`
  - more difficult integrated tasks
- future `capability-hard`
  - truly difficult tasks where orchestration should help noticeably

Important:

- `capability-easy` is for calibration.
- `capability-normal` should differentiate stronger models.
- `capability-hard` should stress decomposition, recovery, coordination, and tradeoffs.

If easy/normal capability tasks are replaced wholesale, preserve at least one small calibration tier somewhere.

---

## 5. Anatomy of a task

Preferred task layout:

```text
tasks/<task-id>/
  PRD.md
  Prompt.md
  kb.md or kb/
  fixture/
  evaluate/
  task.yaml
```

When adapting from SWE-bench or SaaSBench, record source provenance in the PRD or task metadata:

```yaml
source_benchmark:
  name: SWE-bench|SaaSBench
  task_or_instance_id: <id>
  repo_or_url: <url when applicable>
  commit: <sha when applicable>
  adaptation_notes: <short note>
```

The agent-visible fixture may be a copied real snapshot, a trimmed snapshot, or a realistic fixture derived from the benchmark task. Keep evaluator-only reference data outside the fixture.

### `PRD.md`
Authoritative product requirements.

Should specify:
- runtime shape
- required routes/commands
- persistence expectations
- browser expectations
- validation/status behavior
- security constraints
- done condition

### `Prompt.md`
The complete run prompt used by the agent.

Should be short and operational, not the full spec duplicated. Put all task-specific execution instructions here, including:
- `Dispatch and proceed until finished.` when dispatch is desired
- role-focused instructions such as asking the parent session to dispatch the target role
- required workflow evidence files such as `RESEARCH.md`, `PLAN.md`, `VERIFY.md`, `REVIEW.md`, `SECURITY.md`, `APPSEC.md`, or `answer.md`

The harness must not prepend hidden role/workflow instructions. `--auto` may run `/orch on` as a separate preflight unless `--no-orchestra` is used, but the task prompt itself is still exactly `Prompt.md`.

### `kb.md` or `kb/`
Bounded research material.

Use this when the task should reward reading and synthesis rather than live web search.

### `fixture/`
The starting workspace.

Should contain:
- enough real code to feel grounded
- enough missing/broken pieces to require reasoning
- no evaluator-only hints

### `evaluate/`
Grader-only materials.

Not visible during the agent run.

Should include:
- evaluator script
- any hidden checks
- solved reference if needed for authoring/tests

### `task.yaml`
Task metadata.

Should define:
- `task_id`
- `batch`
- `family`
- `description`
- `timeout_minutes`
- `scoring_type`

Do not use prompt-control metadata such as `expected_workflow`; workflow/role/artifact requirements belong in `Prompt.md` and evaluator logic.

---

## 6. How to make tests harder in the right way

### 6.1 Add statefulness
Examples:
- state must survive restart
- data written by one surface must be visible in another
- stale work must be reclaimed
- old queued work must conflict instead of corrupting state

### 6.2 Add idempotency and deduplication
Examples:
- repeated request must not double-apply
- duplicate webhook must return original outcome
- retried background work must not fork state

### 6.3 Add multi-phase workflow
Examples:
- create → approve → publish → export
- enqueue → run worker → poll result → inspect history
- submit → review → reconcile → download audit/export

### 6.4 Add security boundaries
Examples:
- public vs admin views
- token/header auth
- path traversal rejection
- XSS-safe rendering
- secret leakage checks
- filesystem path exposure checks

### 6.5 Add failure and recovery behavior
Examples:
- transient upstream failures
- stale locks/jobs
- conflict resolution
- retries with bounded attempts
- crash-safe persistence

### 6.6 Add hidden evaluator checks
Examples:
- deterministic ordering
- pagination correctness
- newest-first histories
- restart consistency
- CLI/API parity
- multi-request state invariants

### 6.7 Add cross-surface parity
Examples:
- homepage references routes that actually work
- CLI reconcile matches API reconcile
- worker updates are visible in admin history
- export matches ledger/report contents

---

## 7. Difficulty calibration rubric for authors

Use this when deciding whether a task is easy, normal, advanced, or hard.

Harder should mean **less implementation help and more system responsibility**, not a vaguer product spec. End-state behavior should stay clear at every tier.

| Tier | Target task shape | Author help level | Expected agent behavior |
| --- | --- | --- | --- |
| Easy | Small app/utility slice, often 5–10 minutes | Heavy help: detailed PRD, examples, stack constraints, likely file layout, maybe internal design notes | Execute a clear reproduction task well |
| Normal | Longer app slice, often 15–30+ minutes | Strong end-state spec, fewer architecture hints, more hidden checks | Plan and build a realistic slice |
| Advanced | Multi-surface or strongly stateful slice | Mostly product behavior and constraints, little internal design help | Infer architecture, coordinate implementation, handle edge cases |
| Hard | Friction-heavy real-app task | Minimal implementation guidance; end-state clarity only | Own strategy, decomposition, recovery, verification, and tradeoffs |

### Easy
- small app, utility, CLI, API, or web slice
- target roughly 5–10 minutes for a strong agent
- lots of author help is allowed
- fixture may be close to done
- tests should still run end-to-end
- one or two meaningful invariants are enough

### Normal
- multiple interacting behaviors
- meaningful edge cases
- less internal design guidance
- at least one recovery/conflict/security concern
- enough scope that strong models should separate from weaker ones

### Advanced
- multiple surfaces or larger codebase slice
- richer state transitions
- hidden invariants matter more
- agent must infer more structure from product behavior

### Hard
- multiple components or roles naturally help
- strong state/retry/recovery invariants
- meaningful hidden checks
- multiple surfaces must stay aligned
- should expose differences in planning, decomposition, and verification quality

If a task can be solved reliably by brute-force single-pass coding with little reflection, it is probably not hard.

---

## 8. Evaluator authoring rules

### 8.1 Evaluators must test behavior, not prose performance alone
Workflow evidence matters, but working behavior matters more.

### 8.2 Evaluators should check real runtime behavior
Prefer live end-to-end checks:
- Playwright/browser actions against the running web app
- HTTP requests against the running API/service
- subprocess commands for CLI apps
- real persistence artifacts
- restart checks
- worker/job behavior
- import/export file fixtures

Over:
- regex-only grading on generated text
- static-only checks when runtime behavior is practical

### 8.3 Hidden checks are good when they test invariants
Good hidden checks:
- ordering
- duplicate suppression
- stale-job reclaim
- persistence after restart
- history completeness
- escaping/sanitization

Bad hidden checks:
- arbitrary wording expectations unrelated to correctness
- exact labels or headings that were not requested, such as `Finding:`, `Risk:`, `Command:`, `Result:`, `Source:`, `Decision:`, `Tradeoff:`, `Threat:`, or `Mitigation:`
- code-symbol requirements that are not visible in the task and are not necessary for the product behavior
- scoring weights for evidence details the prompt never asked for, such as changed-file mentions, unless the requirement is surfaced in `Prompt.md`/`PRD.md`

### 8.4 Don’t overfit to one exact implementation
Allow multiple valid implementations when behavior is equivalent.

### 8.5 Keep pass/fail strict and simple
Pass/fail should answer:
- Did the final system do what the test asked?
- Does it work correctly?

Category scores can be richer than pass/fail.

---

## 9. Workflow evidence philosophy

Capability tasks currently require:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

These should be treated as **secondary evidence**:
- useful for category scoring
- useful for process diagnosis
- useful for later orchestration analysis

They should not become the main source of truth for whether the app works.

### 9.1 Workflow evidence must not become hidden template compliance

If a prompt only asks for “relevant content,” the evaluator must not require a hidden prose template. Do not require exact labels, headings, command formatting, or phrase choices unless those exact requirements are visible in `Prompt.md` or `PRD.md`.

Valid review/security/verification evidence can be written in many styles:
- A review that finds **no blocking issues** is still relevant when it explains what was reviewed, which requirements were checked, and any residual risks or trade-offs.
- Verification can be relevant without literal `Command:` / `Result:` labels if it clearly states what was run or checked and what passed.
- Research can be relevant without `Source:` / `Decision:` / `Tradeoff:` labels if it cites task materials or fixture facts and explains design choices.
- AppSec can be relevant without `Threat:` / `Mitigation:` labels if it discusses the actual security boundaries, inputs, persistence, auth, or injection/XSS/file risks in the task.

The evaluator may reward clear structure, but it must not fail otherwise-substantive evidence only because the model chose different section names.

### 9.2 What workflow scoring should check

Workflow scoring should be a **junk filter plus coarse task-specific evidence check**, not a writing-format exam.

Good workflow evidence checks:
- artifact exists when requested
- enough substantive prose to distinguish evidence from a placeholder
- mentions task-visible concepts: routes, commands, files, persistence, auth, validation, state transitions, tests, or user workflows
- for verification, describes real checks, commands, or observed behavior
- for review/security, discusses requirements, trade-offs, no-blocker findings, risks, or residual concerns

Bad workflow evidence checks:
- exact hidden headings or labels
- exact endpoint-template spelling when a natural equivalent is fine
- exact implementation symbol names unless they are visible or behaviorally required
- “must mention changed files” scoring unless the prompt explicitly asks for it
- requiring review/security to find an issue; “no blocking issues found” is valid when substantiated

### 9.3 Anti-padding still matters

Do reject:
- missing files
- one-line placeholders
- keyword lists / token salad
- generic filler that could apply to any task
- benchmark-gaming prose such as “these terms are listed here” without real evidence
- artifacts that name workflow roles but do not connect to the actual app behavior

The goal is to prevent nonsense from getting credit while allowing honest, concise, non-template evidence.

### 9.4 Scoring decisions from the workflow-evidence audit

Lessons from the cap-easy and cap-normal workflow-evidence fixes:
- Functional behavior remains dominant; workflow evidence changes numeric score, not functional pass/fail.
- Workflow prompts should ask for “substantive, task-specific evidence; do not use keyword lists or filler” when artifact quality is scored.
- Hidden label requirements should not appear in evaluators.
- Hidden changed-file mention scoring should not affect numeric rubrics unless the prompt asks for it; changed-file coverage can remain diagnostic.
- Required-term coverage should not be all-or-nothing, but the default should not be so loose that one generic anchor passes. Use a meaningful default and override explicitly only when justified.
- Task-specific evidence terms must come from visible task requirements or direct fixture facts, not solved-reference prose style.
- Solved references are examples, not hidden contracts.
- Batch-result rescoring is sufficient when only evaluator scoring changes and old workspaces/artifacts still exist; rerun the benchmark only when implementation behavior or runtime collection changed.

When designing future tasks:
- require workflow evidence only when it helps explain process quality
- do not let superficial artifact stuffing dominate scores
- prefer graded quality/coverage over brittle existence-only checks
- make every scored workflow requirement either visible in the prompt/PRD or broad enough to be naturally implied by the task

---

## 10. Category scoring guidance

The same test evidence can feed multiple category scores.

That is desirable.

### Intelligence
Can use:
- functional correctness
- hidden behavioral checks
- robustness under edge cases
- quality of review/appsec/verify outputs
- correctness of data model and transitions

### Speed
Can use:
- elapsed wall time
- later: time-to-first-pass, time-to-first-correct-state

### Efficiency
Can use:
- total tokens
- input/output/reasoning tokens
- later: cost proxy

### Process / Orchestration
Can use:
- dispatch quality
- role coverage when relevant
- worker completion / integration
- retries/timeouts
- compactions
- redundancy / churn
- whether orchestration helped or merely added overhead
- presence and usefulness of requested workflow evidence

Process scoring should distinguish useful coordination from ceremony. Five workflow files full of generic text should not beat task-specific artifacts plus working code, and a no-issues review should not be penalized merely because no issue was found.

Do not require each check to belong to exactly one category.

---

## 11. What future hard tasks should look like

Strong candidates for future `capability-hard` tasks:

1. **Multi-stage approval/release systems**
   - browser + API + worker + audit + export
   - retries and stale-state handling

2. **Sync / reconciliation systems**
   - local truth vs upstream truth
   - conflict handling
   - idempotent replay
   - restart-safe queues

3. **Admin/public boundary apps**
   - safe rendering
   - secure uploads/attachments
   - reporting/export correctness
   - role-gated operations

4. **Migration / backfill / compatibility tasks**
   - old state to new state
   - rollback-safe logic
   - derived summaries remain correct

5. **Small distributed-workflow simulations**
   - job queues
   - status polling
   - retries
   - history/audit
   - dedupe

Hard tasks should feel like realistic product slices with operational friction, not academic puzzles.

---

## 12. Anti-patterns for test authors

Avoid:
- toy one-endpoint tasks dressed up as capability tests
- requirements that are only hard because they are vague
- evaluators that reward one exact implementation style
- giant setup burden unrelated to the benchmark goal
- making web access necessary when the task is supposed to test local reasoning
- scoring that overweights prose artifacts vs runtime correctness
- web-app tasks with no meaningful browser entrypoint
- CLI/API tasks with no live subprocess or HTTP execution
- tasks with no meaningful state or no persistence requirements
- “security” requirements that never actually get tested

---

## 13. Task creation checklist

Before merging a new capability task, confirm:

- [ ] The task is a real product slice, not a toy
- [ ] The fixture is incomplete but grounded
- [ ] The task has a meaningful live surface: browser, API, CLI, worker, or file command
- [ ] Web tasks have a meaningful `GET /` or equivalent browser entrypoint
- [ ] Persistence is real and tested when state is required
- [ ] At least one security-sensitive behavior is tested
- [ ] At least one edge case / failure mode is tested
- [ ] Hidden checks test invariants, not arbitrary phrasing
- [ ] Every scored workflow requirement is visible in `Prompt.md`/`PRD.md` or naturally implied by the task
- [ ] Workflow evidence scoring rejects placeholders/filler without requiring hidden labels or exact prose templates
- [ ] Review/security evidence can pass when it finds no blocking issues but explains what was checked and why residual risk is acceptable
- [ ] Multiple valid implementations are possible
- [ ] The evaluator starts/runs the app or command and measures runtime behavior end-to-end
- [ ] The task can plausibly benefit from planning/research/review/verify/appsec
- [ ] The task is difficult for the intended suite tier
- [ ] The task is likely to separate stronger vs weaker agents
- [ ] Workflow evidence is useful but not the sole truth source
- [ ] Unit tests for the evaluator/task were added
- [ ] The task was dogfooded through the real benchmark flow: prepare a run workspace with `scripts/02-open-pi` or `scripts/_prepare-task-run`, grade with `scripts/03-collect-results <task-id> --run-id <run-id> --force`, confirm `results/<run-id>-<task-id>/result.json` exists, and confirm `scripts/05-results` reports it. Direct evaluator runs or direct `eval_harness.grade()` calls are smoke checks only and do not satisfy this requirement.

---

## 14. Replacement policy for current capability tasks

If the current capability-easy and capability-normal suites are replaced from scratch:

- preserve the philosophy in this document
- keep at least one calibration tier
- create tasks that are explicitly better at separating:
  - model intelligence
  - speed
  - token efficiency
  - orchestration/process quality
- reserve `capability-hard` for tasks that are genuinely hard, not merely renamed

---

## 15. Final rule for future test-creating agents

When creating new benchmark tasks, optimize for this question:

> If two different agent systems run this task, will this task help us understand which one is better, why, and in what category?

If the answer is no, the task is probably not benchmark-worthy yet.
