#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=inline_realign_env.sh
source "$SCRIPT_DIR/inline_realign_env.sh"
validate_inline_realign_inputs
OUT_ROOT="${OUT_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v3_20260728}"
CONFIG="${INLINE_REALIGN_CONFIG:-$REPO_ROOT/configs/experiments/inline_realign_multilingual_smoke_20260728.yaml}"
cd "$REPO_ROOT"
printf 'Output: %s\nMonitor in another terminal: %s scripts/demo/watch_inline_realign_status.py %q\n' "$OUT_ROOT" "$PYTHON_BIN" "$OUT_ROOT"
command=(
  "$PYTHON_BIN" scripts/demo/run_inline_realign_pipeline.py
  --mode smoke
  --config "$CONFIG"
  --out-root "$OUT_ROOT"
  --python-bin "$PYTHON_BIN"
  --mir1k-subset-root "$MIR1K_SUBSET_ROOT"
  --m4-labels "$M4_LABELS"
  --m4-audio-root "$M4_AUDIO_ROOT"
  --model "$MODEL_SOURCE"
  --revision "$MODEL_REVISION"
  --r2-checkpoint "$R2_CHECKPOINT"
  --device "$DEVICE"
  --demo-prepared-suffixes "$DEMO_PREPARED_SUFFIXES"
  --demo-recursive
  --require-demo
  --m4-long-target-secs "$M4_LONG_TARGET_SECS"
  --demo-publish-layout "$DEMO_PUBLISH_LAYOUT"
)
[[ -n "$DEMO_ROOT" ]] && command+=(--demo-root "$DEMO_ROOT")
[[ -n "$DEMO_PUBLISH_ROOT" ]] && command+=(--demo-publish-root "$DEMO_PUBLISH_ROOT")

exec "${command[@]}" "$@"
