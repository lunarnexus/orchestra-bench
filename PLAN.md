# Plan

## Goal
Fix the current container build failure where `docker build -f docker/Dockerfile ...` stops at `gem install --no-document sinatra sqlite3 rack-test minitest` because the Ruby `sqlite3` native extension requires `pkg-config`.

## Acceptance Criteria
- The benchmark image build reaches/passes the Ruby gem install step without the `sqlite3`/`pkg-config` failure.
- The fix stays limited to the runtime/build path and directly affected tests/docs.
- Existing source URLs, Pi/Orchestra install flow, plugin install flow, task logic, evaluators, and benchmark scoring behavior are unchanged.

## Context / Evidence
- `docker/Dockerfile` installs Ruby task dependencies via `RUN gem install --no-document sinatra sqlite3 rack-test minitest`, and installs OS packages in the earlier apt layer: `git curl ca-certificates python3 python3-pip python3-venv ruby ruby-dev build-essential libsqlite3-dev`.
- The reported failure is in the Docker build at the Ruby `sqlite3` gem native extension, requiring `pkg-config`; the minimal OS-level build dependency is the missing `pkg-config` package in the same apt layer.
- `scripts/01-start` builds the image with `docker build -f "$ROOT/docker/Dockerfile" -t "$IMAGE_NAME" "$ROOT"`, then recreates and initializes the shared container.
- `tests/test_slice1_runtime_contract.py` already protects Dockerfile runtime install contracts and is the narrowest existing test location for this dependency assertion.
- `FOUNDATION.md` and `ARCHITECTURE.md` require a valid container runtime with preinstalled practical task dependencies; this fix supports that existing architecture without changing it.

## Research Used
- Planner-owned local evidence: `docker/Dockerfile`, `scripts/01-start`, `tests/test_slice1_runtime_contract.py`, `FOUNDATION.md`, `RESEARCH.md`, `ARCHITECTURE.md`.

## Research Still Needed
- None.

## Files to Change
- `docker/Dockerfile`
- `tests/test_slice1_runtime_contract.py`
- Optional only if implementation exposes an operator-facing note gap: `ARCHITECTURE.md` runtime dependency wording. Default: no docs update.

## Design Notes
- Add `pkg-config` to the existing apt install list in `docker/Dockerfile`; do not pin or upgrade Ruby gems.
- Keep `libsqlite3-dev`, `ruby-dev`, and `build-essential`; `pkg-config` complements these native-extension build deps.
- Do not alter task dependencies, gem names, repository URLs, Pi plugin installs, entrypoint behavior, task fixtures, evaluators, or result collection.
- Artifact update decision: `PLAN.md` updated for active work; `FOUNDATION.md`, `RESEARCH.md`, `ARCHITECTURE.md`, and `ROADMAP.md` do not require updates unless a builder finds the actual build failure differs from the reported `pkg-config` absence.

## Task Breakdown
- [ ] Slice 1 — sequential — Add missing native-extension build dependency
  Scope: `docker/Dockerfile` apt package list only.
  Interfaces: Docker image build environment for Ruby `sqlite3` gem native extension.
  Stop when: `pkg-config` appears in the apt install list in the runtime deps layer and no unrelated Dockerfile changes are made.
  Verify: `docker build -f docker/Dockerfile -t orchestra-bench-env .` or `BENCH_IMAGE_NAME=orchestra-bench-env scripts/01-start start`.
  Risk: P2 — container build path blocks benchmark runtime, but change is a narrow OS package addition.
  Gates: verifier after build evidence; reviewer optional due narrow config-only fix.

- [ ] Slice 2 — sequential — Protect the dependency contract
  Scope: `tests/test_slice1_runtime_contract.py`.
  Interfaces: Existing Dockerfile text-based runtime contract tests.
  Stop when: a focused assertion fails without `pkg-config` in `docker/Dockerfile` and passes with it present.
  Verify: `pytest -q tests/test_slice1_runtime_contract.py`.
  Risk: P3 — test-only coverage for a build dependency.
  Gates: none.

- [ ] Slice 3 — sequential — Full runtime smoke verification
  Scope: Docker build/start path only: `scripts/01-start start` and runtime verification it already performs.
  Interfaces: Built image, recreated `orchestra-bench-runner`, `bench-entrypoint init-runtime`, `which pi`, `which orchestra`, `orchestra doctor`, `pi list`.
  Stop when: the command completes or any remaining failure is captured as a separate non-`pkg-config` blocker.
  Verify: `scripts/01-start start`.
  Risk: P2 — validates the real shared benchmark runtime.
  Gates: verifier required if Docker is available in the environment.

## Tests to Add or Update
- Update `tests/test_slice1_runtime_contract.py` to assert `pkg-config` is present in `docker/Dockerfile`.
- No task/evaluator tests should change.

## Verification
- Focused: `pytest -q tests/test_slice1_runtime_contract.py`
- Build: `docker build -f docker/Dockerfile -t orchestra-bench-env .`
- End-to-end runtime path: `scripts/01-start start`
- If Docker is unavailable locally, record that as an environment limitation and provide the focused pytest result plus the exact unrun Docker command.

## Risks
- `apt` package name could vary only on non-Debian bases; current base is `node:22-slim`, so Debian package `pkg-config` is appropriate.
- Docker build may reveal a later unrelated network/source/plugin failure after the `sqlite3` step; treat that as out of scope unless directly caused by the new package addition.
- Build cache may mask the fix; verifier should use `--no-cache` if the failing layer is cached unexpectedly.

## Open Questions
- None.
