#!/usr/bin/env bash
# Evaluate the smoke task — verify output is correct and workdir is clean.
set -euo pipefail

BENCH_TASK_ID="${BENCH_TASK_ID:-smoke}"
RUN_ID="${BENCH_RUN_ID:-unknown}"
BENCH_WORKSPACE="${BENCH_WORKSPACE:-/workspace}"

# Find the most recent workdir for this task id in this run
LATEST_DIR=$(ls -1d "$BENCH_WORKSPACE/"*-"$BENCH_TASK_ID" 2>/dev/null | sort | tail -1)
if [ -z "$LATEST_DIR" ]; then
  echo "[eval] FAIL: no workdir found for task=$BENCH_TASK_ID in $BENCH_WORKSPACE"
  exit 1
fi

echo "[eval] checking workdir: $LATEST_DIR"
OUTPUT="$LATEST_DIR/output.txt"

PASS=true

# Check output file exists
if [ ! -f "$OUTPUT" ]; then
  echo "[eval] FAIL: output.txt not found in $LATEST_DIR"
  PASS=false
fi

# Check exact content (trim trailing newline for comparison)
CONTENT=$(cat "$OUTPUT" 2>/dev/null | tr -d '\n' || echo "")
EXPECTED="BENCH_OK"
if [ "$CONTENT" != "$EXPECTED" ]; then
  echo "[eval] FAIL: expected '$EXPECTED', got '$(printf '%q' "$CONTENT")'"
  PASS=false
fi

# Check no extra files (only output.txt should exist)
FILE_COUNT=$(find "$LATEST_DIR" -maxdepth 1 -type f | wc -l)
if [ "$FILE_COUNT" -ne 1 ]; then
  echo "[eval] WARN: $FILE_COUNT files in workdir, expected 1"
fi

# Write result to mounted results volume
RESULT_DIR="/bench/results/$RUN_ID-$BENCH_TASK_ID"
mkdir -p "$RESULT_DIR"
SCORE="$([ "$PASS" = true ] && echo "pass" || echo "fail")"
cat > "$RESULT_DIR/result.json" <<EOF2
{
  "task": "$BENCH_TASK_ID",
  "run_id": "$RUN_ID",
  "score": "$SCORE",
  "workdir": "$LATEST_DIR",
  "checks": {
    "output_exists": $([ -f "$OUTPUT" ] && echo true || echo false),
    "content_correct": $([ "$CONTENT" = "$EXPECTED" ] && echo true || echo false)
  }
}
EOF2

echo "[eval] result: $SCORE (run=$RUN_ID task=$BENCH_TASK_ID)"
[ "$PASS" = true ] || exit 1
