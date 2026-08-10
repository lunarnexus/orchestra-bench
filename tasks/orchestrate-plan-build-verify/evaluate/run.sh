#!/usr/bin/env bash
# Evaluate orchestrate-plan-build-verify — check plan quality and behavior.
set -euo pipefail

BENCH_TASK_ID="${BENCH_TASK_ID:-orchestrate-plan-build-verify}"
RUN_ID="${BENCH_RUN_ID:-unknown}"
BENCH_WORKSPACE="${BENCH_WORKSPACE:-/workspace}"

LATEST_DIR=$(ls -1d "$BENCH_WORKSPACE/"*-"$BENCH_TASK_ID" 2>/dev/null | sort | tail -1) || true
if [ -z "${LATEST_DIR:-}" ]; then
  echo "[eval] FAIL: no workdir found for task=$BENCH_TASK_ID in $BENCH_WORKSPACE"
  exit 1
fi

echo "[eval] checking workdir: $LATEST_DIR"

PLAN="$LATEST_DIR/plan.md"
STATS_PY="$LATEST_DIR/src/stats.py"

PASS=true
HAS_PLAN=false
HAS_GOAL=false
HAS_CHANGES=false
HAS_ACCEPTANCE=false
MENTIONS_TEST_CMD=false
HAS_MEAN=false
HAS_MEDIAN=false
PYTEST_PASS=false
BEHAVIOR_PASS=false
PASSED_COUNT=0
TOTAL_TESTS=0

# ── Plan checks ────────────────────────────────────────────────

if [ -f "$PLAN" ]; then
  HAS_PLAN=true
  CONTENT=$(cat "$PLAN")
  LOWER_CONTENT=$(echo "$CONTENT" | tr '[:upper:]' '[:lower:]')

  if echo "$LOWER_CONTENT" | grep -qiE '#.*goal'; then
    HAS_GOAL=true
  fi

  if echo "$LOWER_CONTENT" | grep -qiE '#.*change'; then
    FILE_REFS=$(echo "$CONTENT" \
      | grep -oE '([[:alnum:]_./-]+\.(py|sh|js|ts|jsonl?|yaml|yml|txt))' \
      | sort -u | wc -l) || true
    FILE_REFS=$((FILE_REFS + 0))
    if [ "$FILE_REFS" -ge 1 ]; then
      HAS_CHANGES=true
    fi
  fi

  if echo "$LOWER_CONTENT" | grep -qiE '#.*(accept|criteria)'; then
    CRIT_COUNT=$(echo "$CONTENT" \
      | grep -cE '^[[:space:]]*([-*]|[0-9]+[.)])' ) || true
    CRIT_COUNT=$((CRIT_COUNT + 0))
    if [ "$CRIT_COUNT" -ge 2 ]; then
      HAS_ACCEPTANCE=true
    fi
  fi

  if echo "$CONTENT" | grep -qE 'python3 -m pytest tests/test_stats\.py|tests/test_stats\.py|pytest'; then
    MENTIONS_TEST_CMD=true
  fi
fi

# ── Code checks ────────────────────────────────────────────────

if [ -f "$STATS_PY" ]; then
  grep -q 'def mean(' "$STATS_PY" && HAS_MEAN=true || true
  grep -q 'def median(' "$STATS_PY" && HAS_MEDIAN=true || true
fi

cd "$LATEST_DIR"

# ── Verification command from the task ─────────────────────────
PYTEST_OUTPUT=$(python3 -m pytest tests/test_stats.py -q 2>&1) || true
echo "$PYTEST_OUTPUT" | tail -20
if echo "$PYTEST_OUTPUT" | grep -Eq '^(\.+|[0-9]+ passed)'; then
  PYTEST_PASS=true
else
  if echo "$PYTEST_OUTPUT" | grep -q 'no tests ran'; then
    PYTEST_PASS=true
  fi
fi

# ── Direct behavior checks ─────────────────────────────────────
if STATS_DIR="$LATEST_DIR" python3 - <<'PY'
import os
import sys
from pathlib import Path

base = Path(os.environ["STATS_DIR"]) / "src"
sys.path.insert(0, str(base))
from stats import count, total, mean, median  # noqa: E402


def assert_equal(actual, expected, label):
    if actual != expected:
        raise SystemExit(f"{label}: expected {expected!r}, got {actual!r}")


def assert_raises(fn, label):
    try:
        fn([])
    except ValueError:
        return
    raise SystemExit(f"{label}: expected ValueError")

assert_equal(count([1.0, 2.0, 3.0]), 3, "count")
assert_equal(total([1.0, 2.0, 3.0]), 6.0, "total")
assert_equal(mean([2.0, 4.0, 6.0]), 4.0, "mean basic")
assert_equal(mean([1.0, 2.0, 2.0]), 1.67, "mean rounding")
assert_equal(median([3.0, 1.0, 2.0]), 2.0, "median odd")
assert_equal(median([1.0, 2.0, 3.0, 4.0]), 2.5, "median even")
assert_raises(mean, "mean empty")
assert_raises(median, "median empty")
PY
then
  BEHAVIOR_PASS=true
else
  BEHAVIOR_PASS=false
fi

# Extract the pytest summary if available
PASSED_COUNT=$(echo "$PYTEST_OUTPUT" | grep -oP '\d+(?= passed)' | tail -1) || true
PASSED_COUNT=${PASSED_COUNT:-0}
TOTAL_TESTS=${PASSED_COUNT}

echo "[eval] plan=$HAS_PLAN goal=$HAS_GOAL changes=$HAS_CHANGES acceptance=$HAS_ACCEPTANCE test_cmd=$MENTIONS_TEST_CMD mean=$HAS_MEAN median=$HAS_MEDIAN pytest=$PYTEST_PASS behavior=$BEHAVIOR_PASS"

[ "$HAS_PLAN" = true ] || PASS=false
[ "$HAS_GOAL" = true ] || PASS=false
[ "$HAS_CHANGES" = true ] || PASS=false
[ "$HAS_ACCEPTANCE" = true ] || PASS=false
[ "$MENTIONS_TEST_CMD" = true ] || PASS=false
[ "$HAS_MEAN" = true ] || PASS=false
[ "$HAS_MEDIAN" = true ] || PASS=false
[ "$PYTEST_PASS" = true ] || PASS=false
[ "$BEHAVIOR_PASS" = true ] || PASS=false

SCORE="$([ "$PASS" = true ] && echo "pass" || echo "fail")"
echo "[eval] result: $SCORE (run=$RUN_ID task=$BENCH_TASK_ID)"

RESULT_ROOT="${BENCH_RESULTS_DIR:-/bench/results}"
if ! mkdir -p "$RESULT_ROOT" 2>/dev/null; then
  RESULT_ROOT="$LATEST_DIR/.bench-results"
  mkdir -p "$RESULT_ROOT"
fi
RESULT_DIR="$RESULT_ROOT/$RUN_ID-$BENCH_TASK_ID"
mkdir -p "$RESULT_DIR"
cat > "$RESULT_DIR/result.json" <<EOF2
{
  "task": "$BENCH_TASK_ID",
  "run_id": "$RUN_ID",
  "score": "$SCORE",
  "workdir": "$LATEST_DIR",
  "checks": {
    "plan_exists": $HAS_PLAN,
    "has_goal_section": $HAS_GOAL,
    "has_changes_1plus_file": $HAS_CHANGES,
    "has_acceptance_2plus_items": $HAS_ACCEPTANCE,
    "mentions_test_command": $MENTIONS_TEST_CMD,
    "has_mean_function": $HAS_MEAN,
    "has_median_function": $HAS_MEDIAN,
    "pytest_command_passed": $PYTEST_PASS,
    "behavior_checks_passed": $BEHAVIOR_PASS,
    "tests_passed": ${PASSED_COUNT:-0},
    "tests_total": ${TOTAL_TESTS:-0}
  }
}
EOF2

[ "$PASS" = true ] || exit 1
