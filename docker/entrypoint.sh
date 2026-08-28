#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  exec tail -f /dev/null
fi

exec python3 -m bench.runtime "$@"
