#!/usr/bin/env bash
# Evaluate research-api-integration — verify structured findings and the integration metadata choice.
set -euo pipefail

BENCH_TASK_ID="${BENCH_TASK_ID:-research-api-integration}"
RUN_ID="${BENCH_RUN_ID:-unknown}"
BENCH_WORKSPACE="${BENCH_WORKSPACE:-/workspace}"

LATEST_DIR=$(ls -1d "$BENCH_WORKSPACE/"*-"$BENCH_TASK_ID" 2>/dev/null | sort | tail -1) || true
if [ -z "${LATEST_DIR:-}" ]; then
  echo "[eval] FAIL: no workdir found for task=$BENCH_TASK_ID in $BENCH_WORKSPACE"
  exit 1
fi

echo "[eval] checking workdir: $LATEST_DIR"
OUTPUT="$LATEST_DIR/research_output.json"
SERVICE="$LATEST_DIR/src/inventory_service.py"

write_result() {
  local score="$1"
  local file_exists="$2"
  local valid_json="$3"
  local nova_mode_push="$4"
  local syncpulse_mode_polling="$5"
  local nova_auth_bearer_token="$6"
  local syncpulse_auth_api_key="$7"
  local correct_webhook_endpoint="$8"
  local recommends_nova_notify="$9"
  local reason_mentions_push_vs_polling="${10}"
  local current_service_auth_bearer_token="${11}"
  local implementation_artifact="${12}"

  local result_root="${BENCH_RESULTS_DIR:-/bench/results}"
  RESULT_DIR="$result_root/$RUN_ID-$BENCH_TASK_ID"
  if ! mkdir -p "$RESULT_DIR" 2>/dev/null; then
    RESULT_DIR="$LATEST_DIR/.bench-results/$RUN_ID-$BENCH_TASK_ID"
    mkdir -p "$RESULT_DIR"
  fi
  cat > "$RESULT_DIR/result.json" <<EOF2
{
  "task": "$BENCH_TASK_ID",
  "run_id": "$RUN_ID",
  "score": "$score",
  "workdir": "$LATEST_DIR",
  "checks": {
    "file_exists": $file_exists,
    "valid_json": $valid_json,
    "nova_mode_push": $nova_mode_push,
    "syncpulse_mode_polling": $syncpulse_mode_polling,
    "nova_auth_bearer_token": $nova_auth_bearer_token,
    "syncpulse_auth_api_key": $syncpulse_auth_api_key,
    "correct_webhook_endpoint": $correct_webhook_endpoint,
    "recommends_nova_notify": $recommends_nova_notify,
    "reason_mentions_push_vs_polling": $reason_mentions_push_vs_polling,
    "current_service_auth_bearer_token": $current_service_auth_bearer_token,
    "implementation_artifact": $implementation_artifact
  }
}
EOF2
}

if [ ! -f "$OUTPUT" ]; then
  echo "[eval] FAIL: research_output.json not found in $LATEST_DIR"
  write_result fail false false false false false false false false false false false
  exit 1
fi

if [ ! -f "$SERVICE" ]; then
  echo "[eval] FAIL: inventory_service.py not found in $LATEST_DIR/src"
  write_result fail true false false false false false false false false false false
  exit 1
fi

RESULT=$(python3 - "$OUTPUT" "$SERVICE" <<'PY'
import ast
import json
import pathlib
import sys

output = pathlib.Path(sys.argv[1])
service = pathlib.Path(sys.argv[2])
checks = {
    "file_exists": True,
    "valid_json": False,
    "nova_mode_push": False,
    "syncpulse_mode_polling": False,
    "nova_auth_bearer_token": False,
    "syncpulse_auth_api_key": False,
    "correct_webhook_endpoint": False,
    "recommends_nova_notify": False,
    "reason_mentions_push_vs_polling": False,
    "current_service_auth_bearer_token": False,
    "implementation_artifact": False,
}

try:
    data = json.loads(output.read_text())
    checks["valid_json"] = True
except Exception:
    print(json.dumps(checks))
    sys.exit(0)

candidate_apis = data.get("candidate_apis", [])
checks["candidate_api_count"] = len(candidate_apis) == 2
lookup = {api.get("name"): api for api in candidate_apis if isinstance(api, dict)}

nova = lookup.get("Nova Notify")
syncpulse = lookup.get("SyncPulse")

checks["nova_mode_push"] = bool(nova and nova.get("mode") == "push")
checks["syncpulse_mode_polling"] = bool(syncpulse and syncpulse.get("mode") == "polling")
checks["nova_auth_bearer_token"] = bool(nova and nova.get("auth_method") == "bearer_token")
checks["syncpulse_auth_api_key"] = bool(syncpulse and syncpulse.get("auth_method") == "api_key")
checks["correct_webhook_endpoint"] = bool(
    nova and nova.get("webhook_registration_endpoint") == "https://api.novanotify.io/v1/webhooks/register"
)

rec = data.get("recommendation", {})
checks["recommends_nova_notify"] = rec.get("chosen_api") == "Nova Notify"
reason = str(rec.get("reason", "")).lower()
checks["reason_mentions_push_vs_polling"] = (
    "nova" in reason and "syncpulse" in reason and "push" in reason and "polling" in reason
)
checks["current_service_auth_bearer_token"] = data.get("current_service_auth") == "bearer_token"

try:
    module = ast.parse(service.read_text())
    integration = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "WEBHOOK_INTEGRATION":
                    integration = ast.literal_eval(node.value)
                    break
            if integration is not None:
                break
    checks["implementation_artifact"] = integration == {
        "provider": "Nova Notify",
        "mode": "push",
        "auth_method": "bearer_token",
        "webhook_registration_endpoint": "https://api.novanotify.io/v1/webhooks/register",
    }
except Exception:
    checks["implementation_artifact"] = False

print(json.dumps(checks))
PY
) || { RESULT="{}"; }

check_valid_json=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('valid_json',False); print(json.dumps(v).lower())")
check_nova_mode=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('nova_mode_push',False); print(json.dumps(v).lower())")
check_syncpulse_mode=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('syncpulse_mode_polling',False); print(json.dumps(v).lower())")
check_nova_auth=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('nova_auth_bearer_token',False); print(json.dumps(v).lower())")
check_syncpulse_auth=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('syncpulse_auth_api_key',False); print(json.dumps(v).lower())")
check_webhook_ep=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('correct_webhook_endpoint',False); print(json.dumps(v).lower())")
check_recommends_nova=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('recommends_nova_notify',False); print(json.dumps(v).lower())")
check_reason=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('reason_mentions_push_vs_polling',False); print(json.dumps(v).lower())")
check_current_auth=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('current_service_auth_bearer_token',False); print(json.dumps(v).lower())")
check_impl=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('implementation_artifact',False); print(json.dumps(v).lower())")
check_count=$(echo "$RESULT" | python3 -c "import json,sys; v=json.load(sys.stdin).get('candidate_api_count',False); print(json.dumps(v).lower())")

PASS=true
for val in "$check_valid_json" "$check_count" "$check_nova_mode" "$check_syncpulse_mode" "$check_nova_auth" "$check_syncpulse_auth" "$check_webhook_ep" "$check_recommends_nova" "$check_reason" "$check_current_auth" "$check_impl"; do
  [ "$val" = "true" ] || PASS=false
done

echo "[eval] checks: count=$check_count nova_push=$check_nova_mode syncpolling=$check_syncpulse_mode nova_auth=$check_nova_auth sync_auth=$check_syncpulse_auth webhook_ep=$check_webhook_ep recommends_nova=$check_recommends_nova reason_ok=$check_reason current_auth=$check_current_auth impl=$check_impl"

SCORE="$([ "$PASS" = true ] && echo "pass" || echo "fail")"
echo "[eval] result: $SCORE (run=$RUN_ID task=$BENCH_TASK_ID)"
write_result "$SCORE" true "$check_valid_json" "$check_nova_mode" "$check_syncpulse_mode" "$check_nova_auth" "$check_syncpulse_auth" "$check_webhook_ep" "$check_recommends_nova" "$check_reason" "$check_current_auth" "$check_impl"

[ "$PASS" = true ] || exit 1
