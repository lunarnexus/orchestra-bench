# orchestra-bench

Container-isolated benchmark for comparing agent harnesses and measuring whether Orchestra improves parent/child agent work.

## Public commands

Use the root commands:

```bash
./01-start
./02-run
./03-results
./04-debug
```

The `scripts/` directory contains compatibility wrappers for the same commands.

## Start

```bash
./01-start
```

Builds/recreates the benchmark container and syncs runtime config for Pi/Orchestra and other harnesses.

## Run

List tasks:

```bash
./02-run --list
```

Manual Pi task run:

```bash
./02-run pi smoke-dependent-setup-chain
```

Automatic task or suite run:

```bash
./02-run --auto smoke-dependent-setup-chain
./02-run --auto smoke
./02-run --auto pi smoke-dependent-setup-chain
```

`--verbose` is intended to stream more run detail. Current known issue: `--auto` output still needs operator UX cleanup so default mode shows brief milestones and verbose mode is proven with real public-command testing.

## Results

Dashboard:

```bash
./03-results
./03-results dash --suite smoke
```

Single run:

```bash
./03-results run <run-id>
```

Compare:

```bash
./03-results comp run:<run-id> suite:smoke
./03-results comp model:qwen3.6 model:qwen3.8 --suite smoke
```

Useful filters:

```bash
--suite smoke
--task smoke-dependent-setup-chain
--model qwen3.8
--harness pi
--result pass|fail|error
--notes text
--since -10m|10m|-2h|today|yesterday
--orchestra yes|no
--role builder
--filter model:qwen3.8,suite:smoke,result:pass
```

## Debug

Debug is separate from results and works on one run at a time:

```bash
./04-debug <run-id> orch
./04-debug <run-id> full
./04-debug <run-id> raw
```

Views:

- `orch` — parent/orchestrator session only.
- `full` — parent + children sessions in chronological order.
- `raw` — raw session/debug artifacts.

Debug output can contain prompts, tool output, model text, file paths, and other sensitive run data. Treat run artifacts as sensitive.

## Result ownership repair

New runs should be host-deleteable. If old result dirs are root-owned from earlier bugs, repair them with:

```bash
find results -mindepth 1 -maxdepth 1 -user root -exec chown -R "$(id -u):$(id -g)" {} +
```

## Current state

Core runtime regressions fixed:

- manual task runs sync container workspace back before grading
- harness startup failures are result errors and skip grading
- runtime config sync is outside public `results/`
- Orchestra catalog/runtime extension sync works with current Pi
- result trees are normalized to host ownership
- V2 scoring/reporting/task migration is mostly implemented

Known remaining issue:

- `02-run --auto` output/verbose behavior still needs real operator acceptance work.
