
## Slice 1.2 — Worktree and cleanup boundary inventory

This inventory is read-only evidence. It does not authorize deletion, migration, staging, or committing.

### Current worktree evidence

- Tracked deletions: 320 total, including 265 task files, 34 tests, 8 scripts, and 4 bench files.
- Untracked paths: 415 total, including the 347-path `V1/` reference tree, 22 V2 `bench/` files, 19 V2 tests, 6 scripts, and 16 `.workspace` paths.
- Tracked modifications include `PLAN.md`, `RESEARCH.md`, `docker/Dockerfile`, `docker/entrypoint.sh`, `pytest.ini`, `scripts/01-start`, `scripts/03-results`, and `config/orchestra/agent-catalog.yaml`.
- Generated/ignored outputs include caches, `results/`, and `artifacts/`.

### Keep as current V2

- `bench/**`
- `docker/Dockerfile`
- `docker/entrypoint.sh`
- `scripts/01-start`, `scripts/02-run`, `scripts/03-results`
- `config/orchestra/agent-catalog.yaml`
- `config/pi/{lmstudio.json,settings.json}`
- `config/skills/**`
- `tests/unit/**`, `tests/integration/**`
- `DECISIONS.md`, `PLAN.md`, `RESEARCH.md`, `pytest.ini`

### Keep as reference-only

- `V1/**`, including `V1/docker/Dockerfile`, `V1/scripts/**`, `V1/tasks/**`, and `V1/tests/**`.

V1 must not be built, executed, imported, mounted, or used as a V2 runtime dependency. It currently cannot be removed safely because V2 task discovery still falls back to `V1/tasks` and current task tests assert that behavior. That dependency must be removed before deleting the reference tree.

### Migrate later

- deleted root `tasks/**` into the future V2 root `tasks/**`
- deleted flat root tests into `tests/unit/**` and `tests/integration/**`
- legacy runtime files into their reviewed V2 replacements
- old operator scripts into the three-script surface only where behavior is explicitly retained

### Remove candidates after impact review

- `.pytest_cache/`, `.ruff_cache/`, `.codegraph/`, Python `__pycache__/`
- generated `artifacts/`, `results/`, `V1/artifacts/`, and `V1/results/`
- empty `docs/`

### Cleanup applied

- Removed stale `.bench-dogfood/` residue.
- Removed obsolete numbered wrappers `scripts/03-grade`, `scripts/04-suite`, `scripts/05-results`.
- Removed alias-only `scripts/_collect-results`.
- Preserved `V1/**`, `config/orchestra` variant files, and `.workspace/`.

### Proposed recoverable checkpoint boundary

Before further implementation, checkpoint the current V2 source, tests, documentation, Docker files, config, and complete `V1/` reference tree together. Exclude generated outputs, caches, editor residue, and unapproved scratch material. Do not finalize tracked deletions or delete uncertain config variants until the owner approves the boundary.

### Mismatches requiring planned work

- V2 still has a runtime dependency on `V1/tasks`.
- The regular `config/hermes/` and `config/opencode/` directories do not exist.
- Deprecated numbered wrappers removed.
- The stale `.bench-dogfood` residue was removed; it was not a valid project config path.
- The V2 replacement/deletion boundary is not yet committed or otherwise checkpointed.

### Slice 1.2 conclusion

The inventory is complete, but its gate is intentionally pending owner approval for uncertain deletions and the recoverable checkpoint boundary. No cleanup or checkpoint should proceed until that approval is given.
