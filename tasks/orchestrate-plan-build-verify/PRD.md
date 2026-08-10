# Orchestrate: Plan, Build, Verify

## Goal
Add `mean()` and `median()` functions to the stats module, write a plan, implement the functions, and verify the module end to end.

## Context
A small Python stats module is provided in `src/` with two working functions (`count`, `total`). Tests exist in `tests/test_stats.py` and cover `count`, `total`, `mean`, and `median`.

## Implementation spec
Add `mean()` and `median()` to `src/stats.py` following the same patterns as `count()` and `total()`:

- `mean(values: list[float]) -> float` — return arithmetic mean, rounded to 2 decimal places. Raise `ValueError` on empty input (matching existing convention).
- `median(values: list[float]) -> float` — return median value, rounded to 2 decimal places. For even-length lists, average the two middle values. Raise `ValueError` on empty input.

## Constraints
- Modify only `src/stats.py` (do not edit tests)
- Use Python stdlib only
- Keep existing `count()` and `total()` functions unchanged

## Plan requirements
Write a plan to **`plan.md`** in the current directory. The plan must include:
- **Goal** — one-sentence description of what is being built
- **Changes** — which file(s) you will modify and how (at least 1 file listed with details)
- **Acceptance criteria** — at least 2 testable pass/fail items

## Acceptance criteria for grading
1. `plan.md` exists with Goal, Changes (≥1 file), and Acceptance criteria (≥2 items) sections
2. `src/stats.py` contains working `mean()` and `median()` functions
3. `python3 -m pytest tests/test_stats.py` passes from the workdir root
4. `mean([1, 2, 2]) == 1.67`, `median([1, 2, 3, 4]) == 2.5`, and empty input raises `ValueError`
