#!/usr/bin/env bash
# Run every diagnostic that can quickly change the current Qwen FA long-audio judgment.
# No training is performed. All stages are resumable at task-directory granularity.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-/home/hyan/Data/lyricalign/derived}"
OUT_ROOT="${OUT_ROOT:-$RUN_ROOT/20260725_qwen_fa_immediate_all}"
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
OUTLIER_AUDIT="${OUTLIER_AUDIT:-$PROJECT/results/comparisons/20260724_qwen_fa_long_b180_outlier_audit.json}"

R1_RUN="${R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
R2_RUN="${R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
R1_CHECKPOINT="${R1_CHECKPOINT:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"

SHIFT_SAMPLE_COUNT="${SHIFT_SAMPLE_COUNT:-3}"
SHIFT_OFFSETS="${SHIFT_OFFSETS:-0,60,120,180,220,232,236,240}"
CROP_WORST_COUNT="${CROP_WORST_COUNT:-3}"
CROP_WINDOWS="${CROP_WINDOWS:-90:120,110:150,120:140,140:151}"
REPEAT_GAPS="${REPEAT_GAPS:-0,0.5,1,2,4,8}"
SELECTION_SEED="${SELECTION_SEED:-20260725}"
MIR_MAX_ITEMS="${MIR_MAX_ITEMS:-0}"
LONG_MAX_ITEMS="${LONG_MAX_ITEMS:-0}"
RUN_CLIFF_TUNED="${RUN_CLIFF_TUNED:-1}"

mkdir -p "$OUT_ROOT"
log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$OUT_ROOT/pipeline.log"; }
fail() { log "ERROR: $*"; exit 1; }
require_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
require_dir() { [[ -d "$1" ]] || fail "missing directory: $1"; }
task_complete() {
  local dir="$1"
  [[ -f "$dir/identity.json" && -f "$dir/diagnostic_rows.jsonl" && -f "$dir/item_summary.jsonl" && -f "$dir/input_audit.jsonl" ]]
}

best_checkpoint() {
  local run="$1"
  "$PYTHON_BIN" - "$run" <<'PY'
import json,sys
from pathlib import Path
run=Path(sys.argv[1]); best=run/'best_checkpoint.json'
if best.is_file():
    data=json.loads(best.read_text(encoding='utf-8'))
    for key in ('checkpoint','checkpoint_path','best_checkpoint'):
        value=data.get(key)
        if value:
            print(value); raise SystemExit
checkpoints=sorted((run/'checkpoints').glob('step-*'))
if not checkpoints:
    raise SystemExit(f'no checkpoint under {run}')
print(checkpoints[-1])
PY
}

cd "$PROJECT"
for path in \
  scripts/evaluation/analyze_qwen_fa_time_coverage.py \
  scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py \
  scripts/evaluation/collect_qwen_fa_immediate_suite.py \
  scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py \
  scripts/evaluation/prepare_qwen_fa_immediate_all_selection.py \
  scripts/evaluation/collect_qwen_fa_240_cliff_probe.py \
  scripts/evaluation/summarize_qwen_fa_240_cliff_probe.py \
  scripts/evaluation/collect_qwen_fa_repeat_probe.py \
  scripts/evaluation/analyze_qwen_fa_error_blocks.py \
  scripts/evaluation/summarize_qwen_fa_immediate_all.py \
  scripts/training/run_qwen_fa_240_cliff_probe.sh \
  "$M4_LABELS" "$M4_CHARACTERS" \
  "$MIR_LABELS" "$MIR_CHARACTERS" \
  "$LONG_LABELS" "$LONG_CHARACTERS" "$LONG_MANIFEST" \
  "$OUTLIER_AUDIT"; do
  require_file "$path"
done
for path in "$M4_AUDIO_ROOT" "$MIR_AUDIO_ROOT" "$LONG_ROOT"; do require_dir "$path"; done

[[ -n "$R1_CHECKPOINT" ]] || R1_CHECKPOINT="$(best_checkpoint "$R1_RUN")"
[[ -n "$R2_CHECKPOINT" ]] || R2_CHECKPOINT="$(best_checkpoint "$R2_RUN")"
require_dir "$R1_CHECKPOINT"
require_dir "$R2_CHECKPOINT"

log "prepare deterministic shared selection"
"$PYTHON_BIN" scripts/evaluation/prepare_qwen_fa_immediate_all_selection.py \
  --labels "$M4_LABELS" \
  --characters "$M4_CHARACTERS" \
  --audio-root "$M4_AUDIO_ROOT" \
  --outlier-audit "$OUTLIER_AUDIT" \
  --shift-count "$SHIFT_SAMPLE_COUNT" \
  --crop-worst-count "$CROP_WORST_COUNT" \
  --seed "$SELECTION_SEED" \
  --out "$OUT_ROOT/selection.json" \
  2>&1 | tee "$OUT_ROOT/selection.log"

mapfile -t SHIFT_ITEM_IDS < <("$PYTHON_BIN" - "$OUT_ROOT/selection.json" <<'PY'
import json,sys
from pathlib import Path
for row in json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['shift_items']:
    print(row['item_id'])
PY
)
mapfile -t CROP_ITEM_IDS < <("$PYTHON_BIN" - "$OUT_ROOT/selection.json" <<'PY'
import json,sys
from pathlib import Path
for row in json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['crop_items']:
    print(row['item_id'])
PY
)
A_ITEM_ID="$("$PYTHON_BIN" - "$OUT_ROOT/selection.json" <<'PY'
import json,sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['repeat_pair']['A']['item_id'])
PY
)"
B_ITEM_ID="$("$PYTHON_BIN" - "$OUT_ROOT/selection.json" <<'PY'
import json,sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['repeat_pair']['B']['item_id'])
PY
)"
DOMINANT_OUTLIER_ID="${CROP_ITEM_IDS[0]}"

log "timestamp coverage"
"$PYTHON_BIN" scripts/evaluation/analyze_qwen_fa_time_coverage.py \
  --dataset "m4_train::$M4_LABELS::train" \
  --dataset "m4_test::$M4_LABELS::test" \
  --dataset "mir1k_test::$MIR_LABELS::test" \
  --dataset "synthetic_b180::$LONG_LABELS::test" \
  --out "$OUT_ROOT/timestamp_coverage.json" \
  2>&1 | tee "$OUT_ROOT/timestamp_coverage.log"

run_core_suite() {
  local name="$1" kind="$2" checkpoint="${3:-}"
  local model_out="$OUT_ROOT/core/$name"
  local args=(
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --model-name "$name"
    --checkpoint-kind "$kind" --out-root "$model_out"
    --m4-labels "$M4_LABELS" --m4-characters "$M4_CHARACTERS" --m4-audio-root "$M4_AUDIO_ROOT"
    --mir-labels "$MIR_LABELS" --mir-characters "$MIR_CHARACTERS" --mir-audio-root "$MIR_AUDIO_ROOT"
    --long-labels "$LONG_LABELS" --long-characters "$LONG_CHARACTERS"
    --long-manifest "$LONG_MANIFEST" --long-audio-root "$LONG_ROOT"
    --outlier-item-id "$DOMINANT_OUTLIER_ID"
    --mir-max-items "$MIR_MAX_ITEMS" --long-max-items "$LONG_MAX_ITEMS"
    --skip-shift --skip-crop --device cuda --language Chinese --local-files-only
  )
  [[ -z "$checkpoint" ]] || args+=(--checkpoint "$checkpoint")
  log "core b180 + MIR-1K: $name"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" scripts/evaluation/collect_qwen_fa_immediate_suite.py "${args[@]}" \
    2>&1 | tee "$OUT_ROOT/core/${name}.log"
}

run_extended_model() {
  local name="$1" kind="$2" checkpoint="${3:-}"
  local common=(
    --model "$MODEL_ID" --revision "$MODEL_REVISION" --model-name "$name"
    --checkpoint-kind "$kind" --device cuda --language Chinese --local-files-only
  )
  [[ -z "$checkpoint" ]] || common+=(--checkpoint "$checkpoint")

  local shift_out="$OUT_ROOT/extended/$name/multisample_shift"
  if ! task_complete "$shift_out"; then
    local shift_args=(
      "${common[@]}" --labels "$M4_LABELS" --characters "$M4_CHARACTERS"
      --audio-root "$M4_AUDIO_ROOT" --out-dir "$shift_out" --experiment shift
      --split test --shift-offsets "$SHIFT_OFFSETS"
    )
    for item_id in "${SHIFT_ITEM_IDS[@]}"; do shift_args+=(--item-id "$item_id"); done
    log "multi-sample shift: $name (${#SHIFT_ITEM_IDS[@]} samples)"
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
      "$PYTHON_BIN" scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py "${shift_args[@]}" \
      2>&1 | tee "$OUT_ROOT/extended/${name}_shift.log"
  else
    log "skip completed multi-sample shift: $name"
  fi

  local crop_out="$OUT_ROOT/extended/$name/expanded_crop"
  if ! task_complete "$crop_out"; then
    local crop_args=(
      "${common[@]}" --labels "$LONG_LABELS" --characters "$LONG_CHARACTERS"
      --manifest "$LONG_MANIFEST" --audio-root "$LONG_ROOT" --out-dir "$crop_out"
      --experiment crop --split test --crop-windows "$CROP_WINDOWS" --include-full
    )
    for item_id in "${CROP_ITEM_IDS[@]}"; do crop_args+=(--item-id "$item_id"); done
    log "expanded full/crop: $name (${#CROP_ITEM_IDS[@]} items)"
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
      "$PYTHON_BIN" scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py "${crop_args[@]}" \
      2>&1 | tee "$OUT_ROOT/extended/${name}_crop.log"
  else
    log "skip completed expanded crop: $name"
  fi

  local repeat_out="$OUT_ROOT/extended/$name/repeat"
  if ! task_complete "$repeat_out"; then
    local repeat_args=(
      "${common[@]}" --labels "$M4_LABELS" --characters "$M4_CHARACTERS"
      --audio-root "$M4_AUDIO_ROOT" --out-dir "$repeat_out"
      --a-item-id "$A_ITEM_ID" --b-item-id "$B_ITEM_ID"
      --selection-seed "$SELECTION_SEED" --gaps "$REPEAT_GAPS"
    )
    log "repeat A+A / control A+B: $name"
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
      "$PYTHON_BIN" scripts/evaluation/collect_qwen_fa_repeat_probe.py "${repeat_args[@]}" \
      2>&1 | tee "$OUT_ROOT/extended/${name}_repeat.log"
  else
    log "skip completed repeat probe: $name"
  fi
}

mkdir -p "$OUT_ROOT/core" "$OUT_ROOT/extended"
run_core_suite raw raw
run_core_suite r1 projector "$R1_CHECKPOINT"
run_core_suite r2 lora "$R2_CHECKPOINT"

run_extended_model raw raw
run_extended_model r1 projector "$R1_CHECKPOINT"
run_extended_model r2 lora "$R2_CHECKPOINT"

log "240-second cliff and equal-total A/B controls"
PROJECT="$PROJECT" PYTHON_BIN="$PYTHON_BIN" RUN_ROOT="$RUN_ROOT" DERIVED_ROOT="$DERIVED_ROOT" \
OUT_ROOT="$OUT_ROOT/cliff240" MODEL_ID="$MODEL_ID" MODEL_REVISION="$MODEL_REVISION" \
LABELS="$M4_LABELS" CHARACTERS="$M4_CHARACTERS" AUDIO_ROOT="$M4_AUDIO_ROOT" \
R1_RUN="$R1_RUN" R2_RUN="$R2_RUN" R1_CHECKPOINT="$R1_CHECKPOINT" R2_CHECKPOINT="$R2_CHECKPOINT" \
A_ITEM_ID="$A_ITEM_ID" B_ITEM_ID="$B_ITEM_ID" SELECTION_SEED="$SELECTION_SEED" \
RUN_TUNED="$RUN_CLIFF_TUNED" \
bash scripts/training/run_qwen_fa_240_cliff_probe.sh \
  2>&1 | tee "$OUT_ROOT/cliff240_launcher.log"

log "summaries"
"$PYTHON_BIN" scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py \
  --input-root "$OUT_ROOT/core" --out "$OUT_ROOT/core/final_summary.json" \
  2>&1 | tee "$OUT_ROOT/core/summary.log"
"$PYTHON_BIN" scripts/evaluation/summarize_qwen_fa_immediate_diagnostics.py \
  --input-root "$OUT_ROOT/extended" --out "$OUT_ROOT/extended/final_summary.json" \
  2>&1 | tee "$OUT_ROOT/extended/summary.log"
"$PYTHON_BIN" scripts/evaluation/analyze_qwen_fa_error_blocks.py \
  --input-root "$OUT_ROOT" --out "$OUT_ROOT/error_blocks.json" \
  2>&1 | tee "$OUT_ROOT/error_blocks.log"
"$PYTHON_BIN" scripts/evaluation/summarize_qwen_fa_immediate_all.py \
  --input-root "$OUT_ROOT" --out "$OUT_ROOT/final_summary.json" \
  2>&1 | tee "$OUT_ROOT/final_summary.log"

touch "$OUT_ROOT/pipeline.complete"
log "all immediate diagnostics complete: $OUT_ROOT/final_summary.json"
