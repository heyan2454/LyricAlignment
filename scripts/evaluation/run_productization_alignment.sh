#!/usr/bin/env bash
# Productization alignment entry: R2 + raw decoder (default) + short/medium window.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export PYTHONPATH=src

MODEL="${MODEL:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
REVISION="${REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R1="${R1:-/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r1_full_seed3407/checkpoints/step-000750}"
R2="${R2:-/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
DECODER_KIND="${DECODER_KIND:-raw}"
LANGUAGE="${LANGUAGE:-Chinese}"
CORE_SEC="${CORE_SEC:-30}"

LYRICS="${LYRICS:?}"; MIX="${MIX:?}"; VOCAL="${VOCAL:?}"; OUT="${OUT:?}"

python scripts/demo/align_qwen_fa_serial_demo.py \
  --lyrics "$LYRICS" --mix-audio "$MIX" --vocal-audio "$VOCAL" --out-root "$OUT" \
  --model "$MODEL" --revision "$REVISION" --r1-checkpoint "$R1" --r2-checkpoint "$R2" \
  --device cuda --language "$LANGUAGE" --decoder-kind "$DECODER_KIND" \
  --core-sec "$CORE_SEC" --left-context-sec 0 --right-context-sec 0 \
  --minimum-forward-characters 1 --startup-minimum-forward-characters 1 \
  --future-line-padding 0 --future-character-ratio 1.0 --max-candidate-expansions 0

GATE_ALIGNMENT="$OUT/alignments/r2/vocal/windowed/alignment.json"
if [[ -f "$GATE_ALIGNMENT" ]]; then
  python scripts/evaluation/check_alignment_quality_gate.py     --alignment "$GATE_ALIGNMENT"     --out "$OUT/quality_gate.json"     || echo "QUALITY_GATE_FAILED"
else
  echo "QUALITY_GATE_SKIPPED"
fi

echo "PRODUCTIZATION_ALIGNMENT_DONE"
