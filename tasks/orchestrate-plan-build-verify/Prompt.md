# Task: Plan, Build, Verify Stats Module

Add `mean()` and `median()` functions to the stats module. Read the code first, then follow all three steps below.

## Steps (all required)

### 1. Plan
Write a plan to **`plan.md`** in the current directory with Goal, Changes (at least 1 file), and Acceptance criteria (at least 2 items). The plan should mention the code file, the test file, and the verification command you will use.

### 2. Implement
Add `mean()` and `median()` to `src/stats.py` following the same patterns as `count()` and `total()`:
- `mean(values: list[float]) -> float` — arithmetic mean, rounded to 2 decimal places. Raise `ValueError` on empty input.
- `median(values: list[float]) -> float` — median value, rounded to 2 decimal places. For even-length lists, average the two middle values. Raise `ValueError` on empty input.

Constraints: modify only `src/stats.py`, use Python stdlib only, keep existing functions unchanged.

### 3. Verify
Run the test suite with `python3 -m pytest tests/test_stats.py` from the workdir root. All tests must pass.
