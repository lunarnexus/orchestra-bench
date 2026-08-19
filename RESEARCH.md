# RESEARCH

## Purpose
This file records evidence-backed findings, recovered requirements, and benchmark design conclusions for `orchestra-bench`.

---

## 1. User requirements recovered from this project thread

### Runtime requirements
The benchmark must:
- run Pi **inside** the benchmark container
- install Orchestra from the user's Gitea/source pattern
- install the LM Studio Pi plugin from the user's Gitea/source pattern
- run `orchestra init pi --copy --force` inside the container
- use local editable Orchestra config files copied into the container runtime

### Config / model requirements
- `agent-catalog.yaml` is the critical artifact
- `PI_MODEL` must **not** be the source of truth
- model selection must be derived from local `agent-catalog.yaml`
- the default role, usually `builder`, is the normal role to inspect for model provenance

### Workflow requirements
- keep one reusable benchmark container by default
- do not require rebuilding for every tiny run
- still allow resets/rebuilds when needed for cleanliness
- keep the operator flow simple
- keep artifact capture and repeated comparison support

### Runtime sources explicitly provided by the user
- Orchestra source: `http://git.lunarnexus.local:3000/james/orchestra`
- LM Studio Pi plugin source: `http://git.lunarnexus.local:3000/james/pi-lmstudio`

### Install rules explicitly provided by the user
- install Orchestra using its `README.md`
- install the LM Studio plugin using the official `pi` plugin install command

### Exact install commands confirmed by focused research
LM Studio plugin official Pi install pattern:
```bash
pi install http://git.lunarnexus.local:3000/james/pi-lmstudio
```
Optional forms also confirmed:
```bash
pi install -l http://git.lunarnexus.local:3000/james/pi-lmstudio
pi install http://git.lunarnexus.local:3000/james/pi-lmstudio@<tag-or-commit>
```

Orchestra README development install flow confirmed:
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
orchestra init pi
```

Important ordering:
1. install Orchestra first
2. ensure `orchestra` is on `PATH`
3. run `orchestra init pi` only after the install is complete
4. benchmark runtime should still use `orchestra init pi --copy --force` per user requirement, even though README shows the base init command

### LM Studio runtime config confirmed by focused research
Current local file:
```json
{"url":"http://192.168.1.209:1234"}
```

Source:
- `~/.pi/agent/lmstudio.json`

Important conclusions:
- the benchmark runtime needs a benchmark-local copy of `lmstudio.json`
- the expected container target should be `~/.pi/agent/lmstudio.json`
- the benchmark-local source should live in the project Pi config area, preferably `config/pi/lmstudio.json`
- do not copy it directly from `~/.pi/agent/` during runtime setup
- the file contains no credential, but it does expose environment-specific private network location data

---

## 2. What we learned from the existing SaaSBench-Orchestra harness

### Stable harness decisions already validated there
From the prior harness work in `~/workspace/SaasBench-Orchestra`:
- local editable Orchestra config files were preferred and used
- `PI_MODEL` was removed from the source-of-truth path
- model was read from `agent-catalog.yaml`
- Pi had to run inside the application/task container
- artifacts and evaluation were consolidated into one run folder
- `orchestra init pi --copy --force` replaced symlink-style init so copied config/plugin artifacts were real files
- token usage was available from Pi session JSONL logs
- one run folder per benchmark execution was less confusing than split folders

### Relevant SaaSBench-Orchestra bootstrap pattern
The working SaaSBench bootstrap flow included:
- clone/copy Orchestra source into container
- install Python 3.12 with `uv`
- create Orchestra venv and install Orchestra there
- install Node 22 via `nvm`
- install Pi globally
- install LM Studio plugin from the Gitea repo
- run `orchestra init pi --copy --force`
- copy local `config.yaml` and `agent-catalog.yaml` into Pi's Orchestra config dir
- validate with `orchestra doctor`
- validate Pi/Orchestra integration with a direct command

### Concrete bootstrap evidence from `bootstrap-container.sh`
Observed working steps in the existing harness:
- install Orchestra in a venv from repo source
- install Pi in the container
- clone the LM Studio plugin repo and install/copy it
- run `orchestra init pi --copy --force`
- copy benchmark-local `config.yaml` and `agent-catalog.yaml` into `/root/.pi/agent/orchestra/`
- verify with `orchestra doctor`
- verify Pi model execution in container

Conclusion:
This is the correct runtime pattern to carry into `orchestra-bench`.

---

## 3. What we learned from SaaSBench itself

### SaaSBench workflow shape
SaaSBench's value comes from a disciplined end-to-end workflow:
- prepare a clean workspace/container
- provide task prompt / PRD and supporting knowledge
- let the coding system build the app or feature
- evaluate with an external scripted grader

This strongly influenced the benchmark direction for `orchestra-bench`.

### Concrete SaaSBench artifact shape
Focused inspection found these canonical task artifacts:

Agent-facing canonical artifacts:
- `task/task.md` — authoritative task requirements / PRD
- `kb/knowledge_base.json` — supplemental clarifications / bounded knowledge

Agent-facing runtime copies:
- workspace copy of `task.md`
- workspace copy of `knowledge_base.json`
- in SaaSBench these are copied into the candidate workspace before the run

Grader-only materials:
- `check/<task>/prepare_workspace.sh`
- `check/<task>/prompt_for_model.md`
- `check/<task>/test_model_output.sh`
- evaluator dependency files such as `check/${TASK}_e/evaluate/requirements.txt`

Important design lesson:
- task requirements and bounded knowledge are distinct artifacts
- the benchmark should preserve that distinction
- human-facing task materials should be markdown where practical
- keep `PRD.md` and `Prompt.md` as separate artifacts
- runtime copies into the task work folder are part of the normal benchmark flow
- grader/evaluator materials should stay outside the agent-visible workspace to avoid contamination

### Key properties worth borrowing
From the earlier SaaSBench investigation and task materials:
- task-per-folder organization
- clean or resettable workspace per run
- authoritative task prompt / product requirements
- support docs / knowledge base when needed
- hidden or partially hidden grading where possible
- finished runnable state matters, not just patch text
- outcome and process should be reported separately

### What SaaSBench-style tasks test for
Across the inspected task materials, the useful pattern is not just raw code editing. Good tasks tend to require some combination of:
- understanding a real spec
- choosing among implementation options
- handling multi-file changes
- preserving prior behavior while adding features
- resolving ambiguity sensibly
- integrating with APIs, infra, or data models
- leaving the application or output in a valid finished state

This is the right north star for `orchestra-bench`.

### Important implication for Orchestra benchmarking
If the task does not actually require research, planning, review, or verification, then not using those roles is acceptable.
The benchmark should judge the final result first, then use process evidence to explain the outcome.

---

## 4. What we learned from `~/workspace/orchestra/evals/`

### Existing eval suite philosophy
The prior Orchestra eval suites already use a useful benchmark split:
- smoke
- contract/regression
- capability/dev
- later holdout / qualification ideas

### Specific evidence from role eval READMEs
- `planner` suite explicitly separates smoke, contract regression, capability/dev, and qualification study
- `researcher` suite explicitly uses smoke, contract, and capability/dev and warns not to combine them into one leaderboard score
- `builder`, `reviewer`, `verifier`, and `appsec` eval docs emphasize:
  - realistic fixtures
  - hidden grading
  - repeated runs
  - separate reporting of outcome, process, scope, policy, and handoff

### Design conclusion
`orchestra-bench` should follow that higher-level structure, but in a lighter-weight, simpler benchmark form.

---

## 5. Token tracking findings for expensive-main / cheap-role model comparisons

### User direction
The benchmark is shifting toward using a more expensive/online model in the main Pi session and cheaper/local models for Orchestra role/subagent sessions. Reporting must therefore separate main-session context and token usage from role-session totals.

### Trace-backed fields currently available
Focused inspection of current `results/*/artifacts/pi-sessions/*.jsonl` found 980 usage events. Every sampled usage event contained:

```text
input
output
cacheRead
cacheWrite
reasoning
totalTokens
cost
```

Every sampled `cost` object contained:

```text
input
output
cacheRead
cacheWrite
total
```

Pi session messages also include `provider` and `model`. Existing local/OAuth/local-model runs report cost fields, but sampled costs are `0`, so they are useful schema evidence but not real spend evidence.

### Computable benchmark fields
From current traces and logs the harness can compute:
- all-session input/output/reasoning/cache-read/cache-write/total token buckets
- main-session-only token buckets
- role-session-only token buckets
- main-session API call count
- role-session API call count
- final main-session context size from the last usage-bearing event
- max main-session context size from max usage-bearing event
- compaction count from Pi `type == "compaction"` events
- worker role attribution by joining Pi session id to Orchestra log `worker_session_id` when present

### Unsupported or optional fields
The following should not be first-class required fields until traces or config support them:
- tool-use tokens
- search request counts or search line-item costs
- batch/flex/priority pricing mode
- real dollar estimates for OAuth/plan/local runs

### Provider pricing research summary
Public provider documentation supports a provider-neutral schema with optional provider-specific fields:
- input tokens
- output tokens
- cached input/cache-read tokens
- cache-write tokens
- reasoning/thinking tokens, safest as an output subcategory unless provider documents otherwise
- optional tool/search costs or request counts
- optional pricing mode such as batch/flex/priority

Design conclusion: keep all-session `total_tokens` only as a convenience scalar, add classified `main_session`, `role_sessions`, and `all_sessions` token sections, and use structured main-session tokens as the expensive-model cost proxy. Historical flat-only results are disposable and should be deleted or regenerated rather than used as fallback data.

---

## 6. Current state of `orchestra-bench`

Implemented pieces that can mostly be kept:
- shared container/task harness structure
- runtime-valid Pi + Orchestra + LM Studio plugin install path
- benchmark-local config snapshot copied into the container runtime
- catalog-derived model provenance, with `PI_MODEL` removed as benchmark truth
- reusable shared container semantics
- numbered operator flow
- task discovery and grading flow
- results schema, result collection, and split/provenance reporting
- repeated-trial aggregation/reporting
- `PRD.md` + `Prompt.md` task artifact model

Current gaps:
1. the new smoke batch should be run through the numbered operator flow with the real Pi/Orchestra stack
2. task/evaluator quality should be tightened based on observed model failures and adjudication traces
3. holdout-quality tasks still need review before using the suite for final comparisons

Conclusion:
The runtime foundation and suite inventory are now valid enough to support real benchmark runs. The main remaining risk is task/evaluator quality, not runtime bootstrapping or suite shape.

---

## 6. Verified runtime repair sequence

The runtime repair sequence was:
1. install Pi, Orchestra, and LM Studio plugin in the container
2. add benchmark-local editable config snapshot and mount/copy it
3. run `orchestra init pi --copy --force` inside the container
4. derive model from `agent-catalog.yaml`, remove `PI_MODEL` as truth source
5. preserve reusable-container semantics
6. repair the operator flow on top of the valid runtime
7. keep and extend reporting metadata as needed

This remains useful historical context. Future work should focus on SaaSBench-quality task design rather than redoing the runtime foundation.

---

## 7. Benchmark philosophy decisions reached after review

### Outcome-first benchmark
The benchmark question is:

> Can Orchestra build great things?

Therefore:
- do not over-focus on proving that a specific subagent was used
- do not force researcher/planner/reviewer usage unless the test is explicitly about a behavioral contract
- use process traces as secondary evidence

### Smoke batch should still be real
The user explicitly rejected trivial toy smoke tests.
Smoke tasks should be:
- small
- fast
- but complex enough that Orchestra might naturally choose to plan, research, review, verify, or security-check if helpful

### Better organization is by batch, not by a huge set of modes
Current agreed direction after capability cleanup:
- `smoke`
- `role-focused`
- `capability-easy`
- `capability-normal`

Old standalone `contract` tasks are retired from the public benchmark inventory. Runtime/workdir contract checks belong in harness/container tests or startup health checks.

### Desired task character
Even the smaller tasks should create natural pressure for some mix of:
- planning
- ambiguity resolution
- research from docs or local knowledge
- review/verification
- real end-state correctness

But grading should remain focused on the delivered outcome.

---

## 8. Current task set and status

Current implemented public task inventory:
- `smoke`: 6 real smoke/workflow tasks.
- `role-focused`: 18 per-role tasks, 3 each for planner, researcher, verifier, reviewer, builder, and appsec.
- `capability-easy`: 3 integrated app-building tasks.
- `capability-normal`: 3 harder integrated app-building tasks.

Retired task IDs:
- `smoke` legacy contract task
- `plan-bounded-feature`
- `research-api-integration`
- `orchestrate-plan-build-verify`

Research conclusion:
The old capability tasks were useful scaffolding but are not good enough for final capability benchmarking: two were pre-solved, one had an invalid verification contract, and none required/scored full Orchestra workflow evidence. They should be replaced with real app-building capability suites.

---

## 9. Open decisions and likely defaults

### Config location
Likely default:
- commit benchmark-local config under `config/orchestra/`

### Non-Orchestra baseline model selection
Likely default:
- still use the same catalog-derived model for fair Orchestra on/off comparisons

### Batching work next
Current benchmark-level design step:
- build `capability-easy` and `capability-normal` tasks
- score, rather than hard-fail, full workflow evidence across planner/researcher/builder/verifier/reviewer/appsec
- keep old contract checks out of public suite inventory

---

## 10. Smoke E2E patterns learned from SaaSBench samples

Three strong small-E2E patterns emerged from the inspected sample tasks:

1. **Dependent setup chain -> one core action**
- create prerequisite entities/settings
- perform one primary workflow action
- verify list/detail/derived state

2. **Public entrypoint -> authenticated/admin confirmation**
- unauthenticated/public submission or action
- sign in as operator/admin
- verify visible state handoff and controllability

3. **Interactive action -> immediate progression/feedback**
- create one personal object/task/item
- perform the main interaction
- verify counters/status/progress/notifications changed visibly

These are good templates for the 3 smoke E2E tests.

## 11. Pi one-shot auto mode and asynchronous Orchestra workers

Batch07 and Batch08 exposed a benchmark lifecycle failure rather than a task-specific implementation failure. In the failed runs, the parent Pi session dispatched a builder, Pi reached settle in one-shot `pi -p` mode, the host process exited, and grading began while Orchestra logs still showed the worker as `running` with no `worker.exited`/`done` event. Interactive Pi is less exposed to this problem because the TUI process remains alive and can receive real auto-return reports.

Pi documentation confirms a useful distinction:
- `agent_settled` means Pi has no automatic retry, compaction retry, or queued follow-up left.
- RPC mode keeps a process-level client connected and streams lifecycle events such as `agent_settled`.
- Extension follow-up messages can trigger new turns, but fake "still waiting" follow-ups are not a principled keepalive because they can burn extra model turns or loop.

Research conclusion:
For benchmark automation, `--auto` should move from one-shot `pi -p` to a Pi RPC runner. The runner should keep the host process alive after Pi settle, query Orchestra state for the parent session, and only grade once Pi is settled and expected Orchestra workers/reports are terminal or explicitly failed. This preserves asynchronous Orchestra behavior while fixing benchmark premature grading.

## 12. Summary conclusions

1. The current harness framework is partially useful, but runtime-valid benchmarking is not complete.
2. The agent catalog is central and must become the benchmark's real source of truth.
3. The benchmark must copy benchmark-local Orchestra config into the container and run the real Pi+Orchestra runtime there.
4. The benchmark should be organized around batches inspired by existing Orchestra evals and SaaSBench methodology.
5. The benchmark should be judged outcome-first: whether Orchestra delivers strong finished results, not whether it merely exercised every role.
