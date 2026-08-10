# Task: Add Bounded CLI Filtering

Plan, implement, and verify `--filter <field>:<value>` support for the `log-viewer` CLI in `src/log_viewer.py`.

This is a plan + implement + verify task:
1. First write a plan to `plan.md` with Goal, Scope, Changes, Acceptance criteria, and Risks or edge cases sections. Reference real fixture files by name.
2. Then implement the feature. The flag supports dot notation for nested fields (`--filter user.name:Alice`), multiple flags use AND logic, and invalid field paths warn without crashing.
3. Then verify the CLI against the provided `sample.log.jsonl`.

Verification examples:
- no filter still prints all entries
- a nested-field filter works
- multiple filters combine with AND logic
- an invalid/missing field path warns but does not crash
