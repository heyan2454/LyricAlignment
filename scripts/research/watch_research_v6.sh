#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:?usage: $0 OUT_ROOT}"
while true; do clear; date; echo; [[ -f "$ROOT/live_status.json" ]] && cat "$ROOT/live_status.json" || echo "no live_status yet"; echo; [[ -f "$ROOT/run_status.jsonl" ]] && tail -20 "$ROOT/run_status.jsonl"; sleep 5; done
