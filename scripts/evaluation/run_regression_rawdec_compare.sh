#!/usr/bin/env bash
# Reproduce GTSinger regression_selection official vs raw decoder comparison.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export PYTHONPATH=src

MODEL=/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064
REV=c07281df297b9905d24a508279258cccf987a064
R1=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r1_full_seed3407/checkpoints/step-000750
R2=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
MANIFEST=/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/gtsinger_regression_manifest.jsonl
OUT=/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_regression_rawdec_all

# Raw decoder full regression
python scripts/evaluation/run_gtsinger_diagnostic_batch.py \
  --manifest "$MANIFEST" --out-root "$OUT" \
  --model "$MODEL" --revision "$REV" --r1-checkpoint "$R1" --r2-checkpoint "$R2" \
  --extra=--decoder-kind --extra=raw

# Evaluate
python scripts/evaluation/evaluate_gtsinger_batch.py \
  --batch-root "$OUT" --gt-map "$OUT/gt_map.jsonl" \
  --model r2 --audio vocal --mode windowed \
  --out "$OUT/eval_batch_r2_rawdec.json"

echo "DONE_RAWDEC"
