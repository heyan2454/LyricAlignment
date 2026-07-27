#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
MODEL_SOURCE="${MODEL_SOURCE:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
MIR1K_SUBSET_ROOT="${MIR1K_SUBSET_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/mir1k_subset_v1}"
RAW_PRF_OUT_ROOT="${RAW_PRF_OUT_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/raw_guarded_prf_v1}"
ROLES="${ROLES:-development quick_v2_extra}"

read -r -a ROLE_ARGS <<< "$ROLES"
mkdir -p "$RAW_PRF_OUT_ROOT"
LOG="$RAW_PRF_OUT_ROOT/pipeline.log"

PYTHONUNBUFFERED=1 "$PYTHON_BIN" scripts/demo/run_demo_realign_quick.py \
  --subset-root "$MIR1K_SUBSET_ROOT" \
  --out-root "$RAW_PRF_OUT_ROOT" \
  --phase evidence q2 collect \
  --roles "${ROLE_ARGS[@]}" \
  --model-kind lora \
  --checkpoint "$R2_CHECKPOINT" \
  --model "$MODEL_SOURCE" \
  --revision "$MODEL_REVISION" \
  --local-files-only \
  --device cuda \
  --decoder-kind raw \
  --audio-variants demucs \
  --core-sec 30 \
  --q2-trial-profile exact_plus2 \
  --q2-require-context-agreement \
  --runtime-anchor-policy \
  --max-automatic-anchor-policies 0 \
  --max-target-units 8 \
  "$@" 2>&1 | tee -a "$LOG"

PYTHONUNBUFFERED=1 "$PYTHON_BIN" scripts/demo/analyze_raw_detector_repair.py \
  --baseline-root "$RAW_PRF_OUT_ROOT" \
  --q2-root "$RAW_PRF_OUT_ROOT" \
  --output "$RAW_PRF_OUT_ROOT/raw_detector_repair_metrics.json" \
  --markdown-output "$RAW_PRF_OUT_ROOT/raw_detector_repair_metrics.md" \
  2>&1 | tee -a "$LOG"

echo "complete: $RAW_PRF_OUT_ROOT/raw_detector_repair_metrics.json"
