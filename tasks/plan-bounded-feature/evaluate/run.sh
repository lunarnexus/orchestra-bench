#!/usr/bin/env bash
# Evaluate plan-bounded-feature — verify plan artifact plus bounded CLI filtering behavior.
set -euo pipefail

BENCH_TASK_ID="${BENCH_TASK_ID:-plan-bounded-feature}"
RUN_ID="${BENCH_RUN_ID:-unknown}"
BENCH_WORKSPACE="${BENCH_WORKSPACE:-/workspace}"

LATEST_DIR=$(ls -1d "$BENCH_WORKSPACE/"*"-$BENCH_TASK_ID" 2>/dev/null | sort | tail -1) || true
if [ -z "${LATEST_DIR:-}" ]; then
  echo "[eval] FAIL: no workdir found for task=$BENCH_TASK_ID in $BENCH_WORKSPACE"
  exit 1
fi

cd "$LATEST_DIR"

echo "[eval] checking workdir: $LATEST_DIR"
PLAN="$LATEST_DIR/plan.md"

PLAN_EXISTS=false
[ -f "$PLAN" ] && PLAN_EXISTS=true

CONTENT=$(cat "$PLAN" 2>/dev/null || true)
LOWER_CONTENT=$(echo "$CONTENT" | tr '[:upper:]' '[:lower:]')

HAS_GOAL=false
if echo "$LOWER_CONTENT" | grep -qiE '#.*goal'; then HAS_GOAL=true; fi

HAS_SCOPE=false
if echo "$LOWER_CONTENT" | grep -qiE '#.*scope'; then HAS_SCOPE=true; fi

HAS_CHANGES=false
FILE_COUNT=0
if echo "$LOWER_CONTENT" | grep -qiE '#.*change'; then
  FILE_COUNT=$(echo "$CONTENT" | grep -oE '\w+\.(py|sh|js|ts|jsonl?|yaml|yml|txt)' | sort -u | wc -l) || true
  FILE_COUNT=$((FILE_COUNT + 0))
  if [ "$FILE_COUNT" -ge 2 ]; then HAS_CHANGES=true; fi
fi

HAS_ACCEPTANCE=false
CRIT_COUNT=0
if echo "$LOWER_CONTENT" | grep -qiE '#.*(accept|criteria)'; then
  CRIT_COUNT=$(echo "$CONTENT" | grep -cE '(^|[[:space:]])[[:space:]]*([-*]|[0-9]+[.)])') || true
  CRIT_COUNT=$((CRIT_COUNT + 0))
  if [ "$CRIT_COUNT" -ge 3 ]; then HAS_ACCEPTANCE=true; fi
fi

HAS_RISKS=false
if echo "$LOWER_CONTENT" | grep -qiE '#.*(risk|edge.?case)'; then HAS_RISKS=true; fi

HAS_SRC_REF=false
if echo "$CONTENT" | grep -qE 'log_viewer\.py'; then HAS_SRC_REF=true; fi

HAS_SAMPLE_REF=false
if echo "$CONTENT" | grep -qE 'sample\.log\.jsonl'; then HAS_SAMPLE_REF=true; fi

HAS_VERIFICATION_CMD=false
if echo "$CONTENT" | grep -qE 'python3\s+src/log_viewer\.py\s+sample\.log\.jsonl'; then HAS_VERIFICATION_CMD=true; fi

PLAN_PASS=true
[ "$PLAN_EXISTS" = true ] || PLAN_PASS=false
[ "$HAS_GOAL" = true ] || PLAN_PASS=false
[ "$HAS_SCOPE" = true ] || PLAN_PASS=false
[ "$HAS_CHANGES" = true ] || PLAN_PASS=false
[ "$HAS_ACCEPTANCE" = true ] || PLAN_PASS=false
[ "$HAS_RISKS" = true ] || PLAN_PASS=false
[ "$HAS_SRC_REF" = true ] || PLAN_PASS=false
[ "$HAS_SAMPLE_REF" = true ] || PLAN_PASS=false
[ "$HAS_VERIFICATION_CMD" = true ] || PLAN_PASS=false

DEFAULT_OUT=$(mktemp)
DEFAULT_ERR=$(mktemp)
INFO_OUT=$(mktemp)
INFO_ERR=$(mktemp)
AND_OUT=$(mktemp)
AND_ERR=$(mktemp)
WARN_OUT=$(mktemp)
WARN_ERR=$(mktemp)

python3 src/log_viewer.py sample.log.jsonl >"$DEFAULT_OUT" 2>"$DEFAULT_ERR"
python3 src/log_viewer.py --filter user.name:Alice sample.log.jsonl >"$INFO_OUT" 2>"$INFO_ERR"
python3 src/log_viewer.py --filter level:info --filter user.role:viewer sample.log.jsonl >"$AND_OUT" 2>"$AND_ERR"
python3 src/log_viewer.py --filter user.team:platform sample.log.jsonl >"$WARN_OUT" 2>"$WARN_ERR"

EXPECTED_DEFAULT='[1] 2025-01-15T10:00:01Z  INFO   Server started on port 8080
[2] 2025-01-15T10:00:02Z  DEBUG  Loading config from /etc/app/config.yml
[3] 2025-01-15T10:01:15Z  INFO   Request received GET /api/users
[4] 2025-01-15T10:01:16Z  DEBUG  Querying users table, limit=50
[5] 2025-01-15T10:02:30Z  WARN   Slow query detected: 340ms
[6] 2025-01-15T10:03:00Z  ERROR  Connection timeout to redis://cache:6379'
EXPECTED_USER='[1] 2025-01-15T10:00:01Z  INFO   Server started on port 8080
[3] 2025-01-15T10:01:15Z  INFO   Request received GET /api/users
[4] 2025-01-15T10:01:16Z  DEBUG  Querying users table, limit=50'
EXPECTED_AND='[3] 2025-01-15T10:01:15Z  INFO   Request received GET /api/users'

DEFAULT_PASS=false
INFO_PASS=false
AND_PASS=false
WARN_PASS=false

if [ "$(cat "$DEFAULT_OUT")" = "$EXPECTED_DEFAULT" ] && [ ! -s "$DEFAULT_ERR" ]; then DEFAULT_PASS=true; fi
if [ "$(cat "$INFO_OUT")" = "$EXPECTED_USER" ] && [ ! -s "$INFO_ERR" ]; then INFO_PASS=true; fi
if [ "$(cat "$AND_OUT")" = "$EXPECTED_AND" ] && [ ! -s "$AND_ERR" ]; then AND_PASS=true; fi
if [ ! -s "$WARN_OUT" ] && [ -s "$WARN_ERR" ] && grep -qi 'warning' "$WARN_ERR"; then WARN_PASS=true; fi

RESULT_DIR="/bench/results/$RUN_ID-$BENCH_TASK_ID"
mkdir -p "$RESULT_DIR"
cat > "$RESULT_DIR/result.json" <<EOF2
{
  "task": "$BENCH_TASK_ID",
  "run_id": "$RUN_ID",
  "score": "$([ "$PLAN_PASS" = true ] && [ "$DEFAULT_PASS" = true ] && [ "$INFO_PASS" = true ] && [ "$AND_PASS" = true ] && [ "$WARN_PASS" = true ] && echo pass || echo fail)",
  "workdir": "$LATEST_DIR",
  "checks": {
    "plan_exists": $PLAN_EXISTS,
    "has_goal_section": $HAS_GOAL,
    "has_scope_section": $HAS_SCOPE,
    "has_changes_2plus_files": $HAS_CHANGES,
    "files_referenced_count": $FILE_COUNT,
    "has_acceptance_3plus_items": $HAS_ACCEPTANCE,
    "criteria_count": $CRIT_COUNT,
    "has_risks_section": $HAS_RISKS,
    "references_src_log_viewer": $HAS_SRC_REF,
    "references_sample_log": $HAS_SAMPLE_REF,
    "mentions_verification_command": $HAS_VERIFICATION_CMD,
    "default_output_matches": $DEFAULT_PASS,
    "nested_filter_matches": $INFO_PASS,
    "and_filter_matches": $AND_PASS,
    "invalid_path_warns": $WARN_PASS
  }
}
EOF2

rm -f "$DEFAULT_OUT" "$DEFAULT_ERR" "$INFO_OUT" "$INFO_ERR" "$AND_OUT" "$AND_ERR" "$WARN_OUT" "$WARN_ERR"

[ "$PLAN_PASS" = true ] || exit 1
[ "$DEFAULT_PASS" = true ] || exit 1
[ "$INFO_PASS" = true ] || exit 1
[ "$AND_PASS" = true ] || exit 1
[ "$WARN_PASS" = true ] || exit 1
