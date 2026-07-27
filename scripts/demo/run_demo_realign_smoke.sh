#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=demo_realign_overnight_env.sh
source "$SCRIPT_DIR/demo_realign_overnight_env.sh"
validate_overnight_inputs
OUT_ROOT="${OUT_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/realign_gpu_decoder_smoke_v2}"
cd "$REPO_ROOT"
exec "$PYTHON_BIN" scripts/demo/run_demo_realign_overnight.py \
  --mode smoke \
  --repo-root "$REPO_ROOT" \
  --out-root "$OUT_ROOT" \
  --subset-root "$MIR1K_SUBSET_ROOT" \
  --m4-labels "$M4_LABELS" \
  --m4-audio-root "$M4_AUDIO_ROOT" \
  --model "$MODEL_SOURCE" \
  --revision "$MODEL_REVISION" \
  --r2-checkpoint "$R2_CHECKPOINT" \
  --device "$DEVICE" \
  "$@"
