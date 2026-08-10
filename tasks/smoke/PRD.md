# Contract Task — Container Contract Verification

## Goal
Create a file `output.txt` in the current working directory containing exactly:

```
BENCH_OK
```

This validates that:
- The container workdir is clean (no leftover files from previous runs)
- We can write output inside the container
- Reset clears prior state so re-runs are contamination-free

## Acceptance criteria
1. `output.txt` exists in the task workdir and contains `BENCH_OK\n`
2. No other files exist in the workdir (except what we create)
3. After reset + re-run, output is identical with no leftover artifacts from run 1
