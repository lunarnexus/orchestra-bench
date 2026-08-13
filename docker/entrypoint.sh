#!/usr/bin/env bash
# bench-entrypoint — container startup for orchestra-bench shared environment
# Usage: bench-entrypoint [reset|run <task-id>|eval <task-id>|init-runtime|sync-orchestra-config|shell]
set -euo pipefail

BENCH_TASKS="${BENCH_TASKS:-/bench/tasks}"
BENCH_RESULTS="${BENCH_RESULTS:-/bench/results}"
BENCH_ARTIFACTS="${BENCH_ARTIFACTS:-/bench/artifacts}"
BENCH_WORKSPACE="${BENCH_WORKSPACE:-/workspace}"
RUN_ID="${BENCH_RUN_ID:-$(date +%Y%m%dT%H%M%S)}"
BENCH_ORCHESTRA_CONFIG_SRC="${BENCH_ORCHESTRA_CONFIG_SRC:-/bench/orchestra-config}"
BENCH_LMSTUDIO_CONFIG_SRC="${BENCH_LMSTUDIO_CONFIG_SRC:-/bench/pi/lmstudio.json}"
PI_ORCHESTRA_RUNTIME_DIR="${PI_ORCHESTRA_RUNTIME_DIR:-/root/.pi/agent/orchestra}"
PI_LMSTUDIO_RUNTIME_FILE="${PI_LMSTUDIO_RUNTIME_FILE:-/root/.pi/agent/lmstudio.json}"
REQUIRED_ORCHESTRA_CONFIG_FILES="config.yaml prompts.yaml agent-catalog.yaml"

require_orchestra_config_source() {
  if [ ! -d "$BENCH_ORCHESTRA_CONFIG_SRC" ]; then
    echo "[bench] orchestra config source not found: $BENCH_ORCHESTRA_CONFIG_SRC" >&2
    return 1
  fi

  for config_file in $REQUIRED_ORCHESTRA_CONFIG_FILES; do
    if [ ! -f "$BENCH_ORCHESTRA_CONFIG_SRC/$config_file" ]; then
      echo "[bench] missing orchestra config file: $BENCH_ORCHESTRA_CONFIG_SRC/$config_file" >&2
      return 1
    fi
  done
}

require_lmstudio_config_source() {
  if [ ! -f "$BENCH_LMSTUDIO_CONFIG_SRC" ]; then
    echo "[bench] lmstudio config source not found: $BENCH_LMSTUDIO_CONFIG_SRC" >&2
    return 1
  fi
}

sync_orchestra_config() {
  require_orchestra_config_source
  rm -rf "$PI_ORCHESTRA_RUNTIME_DIR"
  mkdir -p "$PI_ORCHESTRA_RUNTIME_DIR"
  cp -a "$BENCH_ORCHESTRA_CONFIG_SRC"/. "$PI_ORCHESTRA_RUNTIME_DIR"/
}

sync_lmstudio_config() {
  require_lmstudio_config_source
  mkdir -p "$(dirname "$PI_LMSTUDIO_RUNTIME_FILE")"
  cp -f "$BENCH_LMSTUDIO_CONFIG_SRC" "$PI_LMSTUDIO_RUNTIME_FILE"
}

init_runtime() {
  sync_orchestra_config
  sync_lmstudio_config
  orchestra init pi --copy --force
  sync_orchestra_config
  sync_lmstudio_config
}

# Ensure dirs exist
mkdir -p "$BENCH_RESULTS" "$BENCH_ARTIFACTS"

cmd="${1:--}"

case "$cmd" in
  reset)
    # Clear the workspace entirely so no state leaks between runs
    rm -rf "${BENCH_WORKSPACE:?}/"* /tmp/bench-*
    echo "[bench] workspace reset (run_id=$RUN_ID)"
    exit 0
    ;;

  run)
    task_id="${2:-}"
    [ -z "$task_id" ] && { echo "usage: bench-entrypoint run <task-id>"; exit 1; }

    sync_orchestra_config
    sync_lmstudio_config

    # Per-run workdir — isolated, disposable
    WORKDIR="$BENCH_WORKSPACE/$RUN_ID-$task_id"
    rm -rf "$WORKDIR"
    mkdir -p "$WORKDIR"
    export BENCH_CURRENT_TASK="$task_id"
    export BENCH_RUN_ID="$RUN_ID"
    export BENCH_WORKDIR="$WORKDIR"

    # Copy task files into the workdir (fixture is read-only on host, we copy)
    TASK_SRC="$BENCH_TASKS/$task_id"
    if [ -d "$TASK_SRC/fixture" ]; then
      cp -a "$TASK_SRC/fixture/"* "$WORKDIR"/ 2>/dev/null || true
    fi

    # Copy PRD.md (authoritative product spec) into workdir
    if [ -f "$TASK_SRC/PRD.md" ]; then
      cp -f "$TASK_SRC/PRD.md" "$WORKDIR/"
    fi

    # Copy kb/ markdown knowledge base into workdir if it exists
    if [ -d "$TASK_SRC/kb" ]; then
      cp -a "$TASK_SRC/kb/"* "$WORKDIR/" 2>/dev/null || true
    fi
    if [ -f "$TASK_SRC/kb.md" ]; then
      cp -f "$TASK_SRC/kb.md" "$WORKDIR/"
    fi

    echo "[bench] run=$RUN_ID task=$task_id workdir=$WORKDIR"
    cd "$WORKDIR"

    # If a command is given after the task id, exec it in the workdir
    shift 2
    if [ $# -gt 0 ]; then
      exec "$@"
    fi
    echo "[bench] workdir prepared"
    exit 0
    ;;

  eval)    # Enter existing workdir without recreating (for grading)
    task_id="${2:-}"
    [ -z "$task_id" ] && { echo "usage: bench-entrypoint eval <task-id> [<cmd>]"; exit 1; }
    sync_orchestra_config
    WORKDIR="$BENCH_WORKSPACE/$RUN_ID-$task_id"
    if [ ! -d "$WORKDIR" ]; then
      echo "[bench] workdir not found: $WORKDIR (run_id=$RUN_ID task=$task_id)" >&2
      exit 1
    fi
    export BENCH_CURRENT_TASK="$task_id"
    export BENCH_WORKDIR="$WORKDIR"
    cd "$WORKDIR"
    shift 2
    if [ $# -gt 0 ]; then
      exec "$@"
    fi
    ;;

  shell)
    rm -rf "${BENCH_WORKSPACE:?}"/* /tmp/bench-*
    cd "$BENCH_WORKSPACE"
    exec "${SHELL:-/bin/bash}"
    ;;

  init-runtime)
    init_runtime
    echo "[bench] orchestra runtime initialized"
    exit 0
    ;;

  sync-orchestra-config)
    sync_orchestra_config
    sync_lmstudio_config
    echo "[bench] benchmark runtime configs synced"
    exit 0
    ;;

  -help|help|--help|-h)
    cat <<'EOF'
orchestra-bench shared environment

Commands:
  run <task-id> [<cmd>]   Set up workdir for task and optionally exec a command
  eval <task-id> [<cmd>]  Enter existing workdir without recreating (for grading)
  init-runtime            Copy benchmark config into Pi and run orchestra init
  sync-orchestra-config   Copy benchmark-local runtime config into Pi runtime
  reset                   Clear workspace so next run is clean
  shell                   Drop into an interactive shell (after reset)
  (no args)               Reset workspace then stay alive for docker exec/attach

Environment:
  BENCH_TASKS          /bench/tasks       — mounted task definitions (read-only)
  BENCH_RESULTS        /bench/results     — grading output directory
  BENCH_ARTIFACTS      /bench/artifacts   — logs, traces, snapshots
  BENCH_WORKSPACE      /workspace         — disposable in-container work area
  BENCH_RUN_ID         timestamp override for run id

EOF
    ;;

  *)
    # Default: reset workspace, then stay alive for exec or attach
    rm -rf "${BENCH_WORKSPACE:?}"/* /tmp/bench-* >/dev/null 2>&1 || true
    sync_orchestra_config
    sync_lmstudio_config
    cd "$BENCH_WORKSPACE"
    echo "[bench] ready (run_id=${RUN_ID})" >&2
    tail -f /dev/null
    ;;
esac
