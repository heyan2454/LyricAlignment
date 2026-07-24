#!/usr/bin/env bash
# Immediate controlled diagnostic for the Qwen FA ~240 s collapse.
# No training. Raw runs a dense threshold sweep; R1/R2 run a smaller confirmation
# sweep plus the same equal-total A/B controls.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-/home/hyan/Data/lyricalign/derived}"
OUT_ROOT="${OUT_ROOT:-$RUN_ROOT/20260725_qwen_fa_240_cliff_probe}"
MODEL_ID="${MODEL_ID:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"

LABELS="${LABELS:-$DERIVED_ROOT/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl}"
CHARACTERS="${CHARACTERS:-$DERIVED_ROOT/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_character_annotations.jsonl}"
AUDIO_ROOT="${AUDIO_ROOT:-/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer}"

R1_RUN="${R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
R2_RUN="${R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
R1_CHECKPOINT="${R1_CHECKPOINT:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"

# Dense only for raw. Tuned models confirm key positions and equal-total controls.
RAW_OFFSETS="${RAW_OFFSETS:-0,120,180,220,228,232,234,236,238,240,242,245}"
TUNED_OFFSETS="${TUNED_OFFSETS:-0,120,180,232,236,240,242}"
LATE_START_SEC="${LATE_START_SEC:-240}"
MID_START_SEC="${MID_START_SEC:-180}"
RUN_TUNED="${RUN_TUNED:-1}"  # 0 = fastest raw-only first pass

A_ITEM_ID="${A_ITEM_ID:-}"
B_ITEM_ID="${B_ITEM_ID:-}"
SELECTION_SEED="${SELECTION_SEED:-20260725}"
MIN_DURATION="${MIN_DURATION:-5}"
MAX_DURATION="${MAX_DURATION:-15}"
MIN_CHARACTERS="${MIN_CHARACTERS:-15}"
MAX_CHARACTERS="${MAX_CHARACTERS:-40}"

mkdir -p "$OUT_ROOT"
log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$OUT_ROOT/pipeline.log"; }
fail() { log "ERROR: $*"; exit 1; }
require_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
require_dir() { [[ -d "$1" ]] || fail "missing directory: $1"; }

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
            print(value)
            raise SystemExit
checkpoints=sorted((run/'checkpoints').glob('step-*'))
if not checkpoints:
    raise SystemExit(f'no checkpoint under {run}')
print(checkpoints[-1])
PY
}

cd "$PROJECT"
for path in \
  "$PROJECT/scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py" \
  "$PROJECT/scripts/evaluation/collect_qwen_fa_240_cliff_probe.py" \
  "$PROJECT/scripts/evaluation/summarize_qwen_fa_240_cliff_probe.py" \
  "$LABELS" "$CHARACTERS"; do
  require_file "$path"
done
require_dir "$AUDIO_ROOT"

if [[ "$RUN_TUNED" == "1" ]]; then
  [[ -n "$R1_CHECKPOINT" ]] || R1_CHECKPOINT="$(best_checkpoint "$R1_RUN")"
  [[ -n "$R2_CHECKPOINT" ]] || R2_CHECKPOINT="$(best_checkpoint "$R2_RUN")"
  require_dir "$R1_CHECKPOINT"
  require_dir "$R2_CHECKPOINT"
fi

common_args=(
  --model "$MODEL_ID"
  --revision "$MODEL_REVISION"
  --labels "$LABELS"
  --characters "$CHARACTERS"
  --audio-root "$AUDIO_ROOT"
  --selection-seed "$SELECTION_SEED"
  --min-duration "$MIN_DURATION"
  --max-duration "$MAX_DURATION"
  --min-characters "$MIN_CHARACTERS"
  --max-characters "$MAX_CHARACTERS"
  --late-start-sec "$LATE_START_SEC"
  --mid-start-sec "$MID_START_SEC"
  --device cuda
  --language Chinese
  --local-files-only
)
[[ -z "$A_ITEM_ID" ]] || common_args+=(--a-item-id "$A_ITEM_ID")
[[ -z "$B_ITEM_ID" ]] || common_args+=(--b-item-id "$B_ITEM_ID")

run_probe() {
  local name="$1" kind="$2" offsets="$3" checkpoint="${4:-}"
  local args=(
    "${common_args[@]}"
    --model-name "$name"
    --checkpoint-kind "$kind"
    --shift-offsets "$offsets"
    --out-dir "$OUT_ROOT/$name"
  )
  [[ -z "$checkpoint" ]] || args+=(--checkpoint "$checkpoint")
  log "start $name: offsets=$offsets"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" "$PROJECT/scripts/evaluation/collect_qwen_fa_240_cliff_probe.py" "${args[@]}" \
    2>&1 | tee "$OUT_ROOT/${name}.log"
  log "complete $name"
}

# Raw first so an interrupted run still gives the fastest architecture-level answer.
run_probe raw raw "$RAW_OFFSETS"

if [[ "$RUN_TUNED" == "1" ]]; then
  run_probe r1 projector "$TUNED_OFFSETS" "$R1_CHECKPOINT"
  run_probe r2 lora "$TUNED_OFFSETS" "$R2_CHECKPOINT"
else
  log "RUN_TUNED=0: skip R1/R2 confirmation"
fi

"$PYTHON_BIN" "$PROJECT/scripts/evaluation/summarize_qwen_fa_240_cliff_probe.py" \
  --input-root "$OUT_ROOT" \
  --out "$OUT_ROOT/final_summary.json" \
  2>&1 | tee "$OUT_ROOT/summary.log"

touch "$OUT_ROOT/pipeline.complete"
log "complete: $OUT_ROOT/final_summary.json"
