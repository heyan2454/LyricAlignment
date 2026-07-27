#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
MODEL_SOURCE="${MODEL_SOURCE:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
RAW_GUARDED_OUT_ROOT="${RAW_GUARDED_OUT_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/raw_guarded_demo_v1}"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 LYRICS.txt VOCAL.wav [extra align_qwen_fa_raw_guarded_demo.py args...]" >&2
  exit 2
fi
LYRICS="$1"
AUDIO="$2"
shift 2

exec "$PYTHON_BIN" scripts/demo/align_qwen_fa_raw_guarded_demo.py \
  --lyrics "$LYRICS" \
  --audio "$AUDIO" \
  --out-root "$RAW_GUARDED_OUT_ROOT" \
  --model "$MODEL_SOURCE" \
  --revision "$MODEL_REVISION" \
  --r2-checkpoint "$R2_CHECKPOINT" \
  --local-files-only \
  "$@"
