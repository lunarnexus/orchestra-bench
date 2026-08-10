# Capability Task — Add Bounded CLI Filtering

## Goal
Plan, implement, and verify `--filter <field>:<value>` support for the `log-viewer` CLI in `src/log_viewer.py`.

## Context
A small codebase is provided in `src/` and a sample log file is provided as `sample.log.jsonl`.

## Feature spec
- Flag: `--filter <field>:<value>` (example: `--filter level:info`)
- Supports dot notation for nested fields: `--filter user.name:Alice`
- Multiple flags are allowed and must use AND logic
- Invalid or missing field paths must print a warning and skip the entry without crashing

## Deliverables
- `plan.md` in the workdir root
- an updated `src/log_viewer.py`
- `sample.log.jsonl` may be updated if needed to exercise nested-field cases

## Planning requirements
Your `plan.md` must include:
1. **Goal**
2. **Scope**
3. **Changes**
4. **Acceptance criteria**
5. **Risks or edge cases**

The plan should reference real fixture files by name, including `src/log_viewer.py` and `sample.log.jsonl`.

## Acceptance criteria for grading
- `plan.md` exists and contains all 5 required sections
- the CLI supports `--filter <field>:<value>` with dot notation
- multiple filters are combined with AND logic
- invalid or missing field paths warn without crashing
- the evaluator can run the CLI directly against `sample.log.jsonl`
