#!/usr/bin/env bash
# Immediate, decision-relevant Qwen FA diagnostics. No training is performed.
# One model load is reused across b180, shift, crop and MIR-1K collection.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-/home/hyan/Data/lyricalign/derived}"
OUT_ROOT="${OUT_ROOT:-$RUN_ROOT/20260725_qwen_fa_immediate_diagnostics}"
MODEL_ID="${MODEL_ID:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"

M4_LABELS="${M4_LABELS:-$DERIVED_ROOT/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl}"
M4_CHARACTERS="${M4_CHARACTERS:-$DERIVED_ROOT/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_character_annotations.jsonl}"
M4_AUDIO_ROOT="${M4_AUDIO_ROOT:-/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer}"

MIR_LABELS="${MIR_LABELS:-$DERIVED_ROOT/20260724_mir1k_qwen_fa_labels_v1/mir1k_qwen_fa_labels.jsonl}"
MIR_CHARACTERS="${MIR_CHARACTERS:-$DERIVED_ROOT/20260722_mir1k_vocal_channel1_ood/mir1k_vocal_ood_characters.jsonl}"
MIR_AUDIO_ROOT="${MIR_AUDIO_ROOT:-$DERIVED_ROOT/20260722_mir1k_vocal_channel1_ood}"

LONG_ROOT="${LONG_ROOT:-$DERIVED_ROOT/20260724_m4singer_test_synthetic_long_v1/bucket_180}"
LONG_LABELS="${LONG_LABELS:-$LONG_ROOT/labels/qwen_fa_labels.jsonl}"
LONG_CHARACTERS="${LONG_CHARACTERS:-$LONG_ROOT/synthetic_characters.jsonl}"
LONG_MANIFEST="${LONG_MANIFEST:-$LONG_ROOT/synthetic_manifest.jsonl}"

R1_RUN="${R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
R2_RUN="${R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
R1_CHECKPOINT="${R1_CHECKPOINT:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"

SHIFT_OFFSETS="${SHIFT_OFFSETS:-0,30,60,120,180,240}"
CROP_WINDOWS="${CROP_WINDOWS:-90:120,110:150,120:140,140:151}"
MIR_MAX_ITEMS="${MIR_MAX_ITEMS:-0}"   # 0 = all available MIR-1K items
LONG_MAX_ITEMS="${LONG_MAX_ITEMS:-0}" # 0 = all b180 items

mkdir -p "$OUT_ROOT"
log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$OUT_ROOT/pipeline.log"; }
fail() { log "ERROR: $*"; exit 1; }
require_file() { [ -f "$1" ] || fail "missing file: $1"; }
require_dir() { [ -d "$1" ] || fail "missing directory: $1"; }

best_checkpoint() {
  local run="$1"
  "$PYTHON_BIN" - "$run" <<'PY'
import json,sys
from pathlib import Path
run=Path(sys.argv[1]); best=run/'best_checkpoint.json'
if best.is_file():
    data=json.loads(best.read_text(encoding='utf-8'))
    for key in ('checkpoint','checkpoint_path','best_checkpoint'):
        if data.get(key): print(data[key]); raise SystemExit
checkpoints=sorted((run/'checkpoints').glob('step-*'))
if not checkpoints: raise SystemExit(f'no checkpoint under {run}')
print(checkpoints[-1])
PY
}

cd "$PROJECT"
for path in \
  "$PROJECT/scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py" \
  "$PROJECT/scripts/evaluation/collect_qwen_fa_immediate_suite.py" \
  "$PROJECT/scripts/evaluation/analyze_qwen_fa_time_coverage.py" \
  "$PROJECT/scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py" \
  "$M4_LABELS" "$M4_CHARACTERS" "$MIR_LABELS" "$MIR_CHARACTERS" \
  "$LONG_LABELS" "$LONG_CHARACTERS" "$LONG_MANIFEST"; do require_file "$path"; done
for path in "$M4_AUDIO_ROOT" "$MIR_AUDIO_ROOT" "$LONG_ROOT"; do require_dir "$path"; done

[ -n "$R1_CHECKPOINT" ] || R1_CHECKPOINT="$(best_checkpoint "$R1_RUN")"
[ -n "$R2_CHECKPOINT" ] || R2_CHECKPOINT="$(best_checkpoint "$R2_RUN")"
require_dir "$R1_CHECKPOINT"; require_dir "$R2_CHECKPOINT"

log "CPU timestamp coverage"
"$PYTHON_BIN" "$PROJECT/scripts/evaluation/analyze_qwen_fa_time_coverage.py" \
  --dataset "m4_train::$M4_LABELS::train" \
  --dataset "m4_test::$M4_LABELS::test" \
  --dataset "mir1k_test::$MIR_LABELS::test" \
  --dataset "synthetic_b180::$LONG_LABELS::test" \
  --out "$OUT_ROOT/timestamp_coverage.json" | tee "$OUT_ROOT/timestamp_coverage.log"

OUTLIER_ID="$($PYTHON_BIN - "$PROJECT/results/comparisons/20260724_qwen_fa_long_b180_outlier_audit.json" <<'PY'
import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(data['paired_items'][0]['item_id'])
PY
)"
log "dominant outlier selected from archived audit"

run_model_suite() {
  local name="$1" kind="$2" checkpoint="${3:-}"
  local args=(
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --model-name "$name"
    --checkpoint-kind "$kind" --out-root "$OUT_ROOT/$name"
    --m4-labels "$M4_LABELS" --m4-characters "$M4_CHARACTERS" --m4-audio-root "$M4_AUDIO_ROOT"
    --mir-labels "$MIR_LABELS" --mir-characters "$MIR_CHARACTERS" --mir-audio-root "$MIR_AUDIO_ROOT"
    --long-labels "$LONG_LABELS" --long-characters "$LONG_CHARACTERS"
    --long-manifest "$LONG_MANIFEST" --long-audio-root "$LONG_ROOT"
    --outlier-item-id "$OUTLIER_ID" --shift-offsets "$SHIFT_OFFSETS" --crop-windows "$CROP_WINDOWS"
    --mir-max-items "$MIR_MAX_ITEMS" --long-max-items "$LONG_MAX_ITEMS"
    --device cuda --language Chinese --local-files-only
  )
  [ -z "$checkpoint" ] || args+=(--checkpoint "$checkpoint")
  log "start model suite: $name (single model load)"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" "$PROJECT/scripts/evaluation/collect_qwen_fa_immediate_suite.py" "${args[@]}" \
    2>&1 | tee "$OUT_ROOT/${name}.log"
  log "complete model suite: $name"
}

run_model_suite raw raw
run_model_suite r1 projector "$R1_CHECKPOINT"
run_model_suite r2 lora "$R2_CHECKPOINT"

"$PYTHON_BIN" "$PROJECT/scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py" \
  --input-root "$OUT_ROOT" --out "$OUT_ROOT/final_summary.json" | tee "$OUT_ROOT/summary.log"

touch "$OUT_ROOT/pipeline.complete"
log "complete: $OUT_ROOT/final_summary.json"
