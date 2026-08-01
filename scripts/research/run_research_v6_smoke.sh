#!/usr/bin/env bash
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/research_v6_env.sh"; validate_research_v6_inputs
OUT_ROOT="${OUT_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/alignment_research_v6_smoke}"
cd "$REPO_ROOT"
exec "$PYTHON_BIN" scripts/research/run_research_v6_pipeline.py \
  --mode smoke --out-root "$OUT_ROOT" --python-bin "$PYTHON_BIN" \
  --demo-root "$DEMO_ROOT" --demo-prepared-suffixes "$DEMO_PREPARED_SUFFIXES" \
  --mir1k-subset-root "$MIR1K_SUBSET_ROOT" --m4-labels "$M4_LABELS" --m4-audio-root "$M4_AUDIO_ROOT" --m4-splits "$M4_SPLITS" \
  --m4-long-target-secs "$M4_LONG_TARGET_SECS" --model "$MODEL_SOURCE" --revision "$MODEL_REVISION" --r2-checkpoint "$R2_CHECKPOINT" --device "$DEVICE" \
  --pilot-items-per-dataset 1 "$@"
