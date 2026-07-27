#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=inline_realign_env.sh
source "$SCRIPT_DIR/inline_realign_env.sh"
validate_inline_realign_inputs
OUT_ROOT="${OUT_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v2_20260728}"
cd "$REPO_ROOT"
command=(
  "$PYTHON_BIN" scripts/demo/run_inline_realign_pipeline.py
  --mode smoke
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
  --evidence-cap-mib "$EVIDENCE_CAP_MIB"
)
[[ -n "$DEMO_ROOT" ]] && command+=(--demo-root "$DEMO_ROOT")
exec "${command[@]}" "$@"
