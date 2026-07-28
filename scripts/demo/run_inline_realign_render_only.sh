#!/usr/bin/env bash
set -euo pipefail
MODE="${1:?usage: $0 smoke|formal OUT_ROOT [extra pipeline args...]}"
OUT_ROOT_ARG="${2:?usage: $0 smoke|formal OUT_ROOT [extra pipeline args...]}"
shift 2
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$MODE" in
  smoke) ENTRY="$SCRIPT_DIR/run_inline_realign_smoke.sh" ;;
  formal) ENTRY="$SCRIPT_DIR/run_inline_realign_formal.sh" ;;
  *) echo "MODE must be smoke or formal" >&2; exit 2 ;;
esac
OUT_ROOT="$OUT_ROOT_ARG" RESUME=1 RENDER_MODE=after FROM_STAGE=render exec "$ENTRY" "$@"
