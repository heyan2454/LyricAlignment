#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:?usage: $0 EXPERIMENT_ROOT [refresh_seconds]}"
REFRESH="${2:-3}"
exec python scripts/demo/watch_inline_realign_status.py "$ROOT" --refresh-seconds "$REFRESH"
