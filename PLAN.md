# V2 Rebuild Plan

`DECISIONS.md` is authoritative for semantics. This plan describes the path to the finished product.

## The product

A container-isolated benchmark with exactly three public scripts:

```bash
scripts/01-start                        # complete setup: build, start, configure
scripts/02-run pi|hermes|opencode ...   # interactive harness session inside the container
scripts/02-run --auto <task-or-suite>   # automatic run and scoring
scripts/03-results ...                  # inspect, compare, rescore, delete results
```

Operator experience:
- Bare `01-start` from root or `scripts/` leaves a running, fully configured container and prints a concise summary.
- Harness sessions feel native: TTY, stdin, opaque args, exit status all preserved.
- `--auto` runs default to concise progress output; `--verbose` streams the full session; complete transcripts are always retained as artifacts.
- Config overrides come from `config/orchestra/`, `config/pi/`, `config/hermes/`, `config/opencode/` and apply to both interactive and automatic runs, with effective-config provenance recorded per run.
- Tasks live in root `tasks/`. Everything benchmark-related executes inside the container; the host runs only pytest.
- `V1/` remains a read-only reference library of proven behavior to recreate.

## Done (proven)

- [x] V1 research inventory, cleanup boundary, recoverable checkpoint (`699d23c723b0e35d3c63a4d804d7c058f0d8fcd0`).
- [x] Task migration contract: root `tasks/` mount + real graded smoke run `s17r20260828T173608-smoke-dependent-setup-chain` (pass, real evaluator score).
- [x] Hermes/OpenCode official installs and config layouts (`RESEARCH.md`).
- [x] Slice 2.1 regular config overrides: mounts, in-container propagation to `/root/.pi/agent`, persisted provenance — verified in a rebuilt container.
- [x] Public surface reduced to the three scripts; results route through `03-results` only.
- [x] Pi, Hermes, OpenCode installed and passthrough-checked inside the container.

## Remaining slices

Work sequentially. Each slice ships with focused tests plus one real container check as its own acceptance evidence.

### Slice 2.2 — Bare `01-start` — done
`scripts/01-start` with no arguments now performs the whole setup: build (cached, one Dockerfile at `docker/Dockerfile`), refresh Orchestra + Pi plugins while keeping cached harness installs, recreate the container, apply runtime config inside it, print a concise summary. Shell wrapper stays thin; Python owns the setup stages. Evidence: builder `a6273635cbe4`; focused tests passed; real `bash scripts/01-start` passed.

### Slice 3.1 — Python dispatch for `02-run` — done
Move argument parsing from shell into Python: passthrough (`pi|hermes|opencode <opaque args>`) versus `--auto <target>`; `--auto pi` is an automatic target. Evidence: focused parser/wrapper tests passed; real `scripts/02-run --help` worked from root and `scripts/`.

### Slice 3.2 — Interactive TTY passthrough — done
Attach stdin, allocate a TTY when the caller has one, propagate signals and exit status, retain the session transcript. `02-run pi config` reaches the configured in-container Pi settings. Evidence: builder `72fd8ff662c6`; focused tests passed; real root and `scripts/` TTY smokes started `pi config` in-container and retained transcripts.

### Slice 4.1 — One workspace model — done
Single run-scoped workspace inside the container; catalog `{workdir}` expands to it; evaluator stays hidden until grading; run artifacts host-readable; runtime snapshot includes the effective per-harness config overlay. Evidence: builders `784018c69d48` and `613ca13ca473`; focused workspace/provenance tests passed; real smoke provenance confirmed run-scoped workspace. The smoke harness failure was model availability (`Model "lmstudio/qwen/qwen3.8-27b" not found`), not workspace/provenance.

### Slice 5.1/5.2 — Automatic task and suite runs — implementation done, real acceptance blocked
`02-run --auto <task>` runs and grades entirely in the container with concise default output and always-retained artifacts. `02-run --auto <suite>` resolves suites, runs serially, summarizes per-task results with an explicit return code. Evidence: builder `25bbcfc4dae2`; focused auto/task/suite tests passed and compact output/artifact behavior implemented. Real operator acceptance is blocked by external Pi/LM Studio runtime model resolution: runs `20260829T203030` and `20260829T203524` failed before scoring with `Error: Model "lmstudio/qwen/qwen3.8-27b" not found`, while `pi --list-models` later lists the model. Rerun one task and one smoke suite after runtime/model state is stable.

### Slice 6 — `03-results` complete — done
List/display runs, detail and debug views, filters, comparisons via filters, token/timing summaries, explicit rescoring (prior result preserved until replacement succeeds), filtered deletion with preview + confirmation. Evidence: builders `91d3b00be8fe` and `ef81a4fdcb6b`; focused CLI/reporting/integration tests and ruff passed; deletion safety covered with copied/temp results.

### Slice 7 — Hermes/OpenCode proof — done
Real interactive smokes for both through the generic `02-run` interface, transcripts retained. Evidence: verifier `984c015d8a9d`; Hermes `--help` and OpenCode `--version` passed from root and `scripts/`, transcripts retained under `artifacts/02-run/`.

### Slice 8 — Pi lifecycle backend + Orchestra settle (final feature phase)
Research current `PiRpcHarness` and `~/workspace/orchestra/KNOWN_BUGS.md`, propose minimal backend selection, get owner approval, wire it, record backend in provenance. Then production Orchestra settle provider: session identity, grading waits for relevant workers to finish, timeouts classified, status snapshots retained. Acceptance: real Pi lifecycle smoke settles and grades; active-worker test blocks grading, terminal-worker test allows it.

### Slice 9 — Final polish
Remove confirmed dead code (legacy env aliases, unused compat helpers, stale workspace residue). Full verification pass across unit/integration/container-contract tests plus one end-to-end operator run of all three scripts. Concise operator README for the three-script workflow. Clean commit.

## Acceptance checklist

- [x] Bare `scripts/01-start` performs complete cached setup from root and `scripts/`.
- [x] Exactly three public numbered scripts.
- [x] Pi, Hermes, OpenCode interactive passthrough inside the container with TTY and transcripts.
- [ ] `--auto <task>` runs and scores a real task; `--auto <suite>` summarizes a real suite.
- [x] Config overrides effective for all four config dirs, provenance recorded.
- [ ] Concise default output; `--verbose` full; transcripts always retained.
- [x] `03-results` delivers display, filtering, comparison, rescoring, safe deletion.
- [ ] Orchestra grading waits for active work.
- [ ] Clean commit history from the established V2 boundary.

## Immediate next action

Finish the `01-start` progress-output fix currently in flight, then simplify public CLI help by hiding/removing leaked internal `--root` options from operator-facing `01-start`, `02-run`, and `03-results` usage. Wrappers already resolve the repo root automatically; keep root plumbing internal only where tests/functions need it.

After that, proceed with Slice 8.1 — research Pi lifecycle backend and Orchestra settle proposal for owner approval.
