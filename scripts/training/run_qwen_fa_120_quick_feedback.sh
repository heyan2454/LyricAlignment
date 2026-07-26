#!/usr/bin/env bash
# Fast diagnostic-only feedback for the suspected 120s behavior.
# Per model: dense prefix-silence shift + fixed-position trailing-silence probe.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs}"
DERIVED_ROOT="${DERIVED_ROOT:-/home/hyan/Data/lyricalign/derived}"
OUT_ROOT="${OUT_ROOT:-$RUN_ROOT/20260725_qwen_fa_120_quick_feedback}"
MODEL_ID="${MODEL_ID:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
LABELS="${LABELS:-$DERIVED_ROOT/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl}"
CHARACTERS="${CHARACTERS:-$DERIVED_ROOT/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_character_annotations.jsonl}"
AUDIO_ROOT="${AUDIO_ROOT:-/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer}"
R1_RUN="${R1_RUN:-$RUN_ROOT/20260724_qwen_fa_r1_full_seed3407}"
R2_RUN="${R2_RUN:-$RUN_ROOT/20260723_qwen_fa_r2_full_seed3407}"
R1_CHECKPOINT="${R1_CHECKPOINT:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"
SAMPLE_COUNT="${SAMPLE_COUNT:-3}"
SHIFT_OFFSETS="${SHIFT_OFFSETS:-0,90,105,115,120,125,135,150}"
TARGET_DURATIONS="${TARGET_DURATIONS:-0,60,90,105,115,120,125,135,150,180}"
FORCE="${FORCE:-0}"
MODELS="${MODELS:-r0,r1,r2}" # comma-separated subset

mkdir -p "$OUT_ROOT"
LOG="$OUT_ROOT/pipeline.log"
log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
fail() { log "ERROR: $*"; exit 1; }
require_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
require_dir() { [[ -d "$1" ]] || fail "missing directory: $1"; }

best_checkpoint_strict() {
  "$PYTHON_BIN" - "$1" <<'PY'
import json,sys
from pathlib import Path
run=Path(sys.argv[1]); best=run/'best_checkpoint.json'
if not best.is_file():
    raise SystemExit(f'missing validation-selected best_checkpoint.json: {best}')
data=json.loads(best.read_text(encoding='utf-8'))
for key in ('checkpoint','checkpoint_path','best_checkpoint'):
    value=data.get(key)
    if value:
        path=Path(value)
        if not path.is_absolute(): path=(run/path).resolve()
        if not path.is_dir(): raise SystemExit(f'best checkpoint missing: {path}')
        print(path); raise SystemExit
raise SystemExit(f'no checkpoint path in {best}')
PY
}

run_model() {
  local name="$1" kind="$2" checkpoint="${3:-}"
  local args=(
    --model "$MODEL_ID" --revision "$MODEL_REVISION"
    --model-name "$name" --checkpoint-kind "$kind"
    --labels "$LABELS" --characters "$CHARACTERS" --audio-root "$AUDIO_ROOT"
    --out-root "$OUT_ROOT/$name" --split test --sample-count "$SAMPLE_COUNT"
    --shift-offsets "$SHIFT_OFFSETS" --target-durations "$TARGET_DURATIONS"
    --device cuda --language Chinese --local-files-only
  )
  [[ -z "$checkpoint" ]] || args+=(--checkpoint "$checkpoint")
  [[ "$FORCE" == "1" ]] && args+=(--force)
  log "quick 120s probes: $name"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" scripts/evaluation/collect_qwen_fa_120_quick_feedback.py "${args[@]}" \
    2>&1 | tee -a "$OUT_ROOT/${name}.log"
}

cd "$PROJECT"
for path in \
  scripts/evaluation/collect_qwen_fa_120_quick_feedback.py \
  scripts/evaluation/summarize_qwen_fa_120_quick_feedback.py \
  scripts/evaluation/analyze_qwen_fa_time_coverage.py \
  "$LABELS" "$CHARACTERS"; do require_file "$path"; done
require_dir "$AUDIO_ROOT"
[[ -x "$PYTHON_BIN" ]] || fail "python environment missing: $PYTHON_BIN"
model_selected() {
  local wanted=",${MODELS// /},"
  [[ "$wanted" == *",$1,"* ]]
}

IFS=',' read -r -a requested_models <<< "${MODELS// /}"
[[ ${#requested_models[@]} -gt 0 ]] || fail "MODELS is empty"
for requested_model in "${requested_models[@]}"; do
  case "$requested_model" in
    r0|r1|r2) ;;
    *) fail "invalid model in MODELS: $requested_model" ;;
  esac
done

if model_selected r1; then
  [[ -n "$R1_CHECKPOINT" ]] || R1_CHECKPOINT="$(best_checkpoint_strict "$R1_RUN")"
  require_dir "$R1_CHECKPOINT"
fi
if model_selected r2; then
  [[ -n "$R2_CHECKPOINT" ]] || R2_CHECKPOINT="$(best_checkpoint_strict "$R2_RUN")"
  require_dir "$R2_CHECKPOINT"
fi

log "static timestamp coverage"
"$PYTHON_BIN" scripts/evaluation/analyze_qwen_fa_time_coverage.py \
  --dataset "m4_train::$LABELS::train" \
  --dataset "m4_test::$LABELS::test" \
  --out "$OUT_ROOT/timestamp_coverage.json" \
  2>&1 | tee -a "$OUT_ROOT/timestamp_coverage.log"

# Explicitly serial to keep memory and model identity easy to audit.
model_selected r0 && run_model r0 raw
model_selected r1 && run_model r1 projector "$R1_CHECKPOINT"
model_selected r2 && run_model r2 lora "$R2_CHECKPOINT"

log "build compact readout"
"$PYTHON_BIN" scripts/evaluation/summarize_qwen_fa_120_quick_feedback.py \
  --input-root "$OUT_ROOT" \
  --out-json "$OUT_ROOT/final_summary.json" \
  --out-md "$OUT_ROOT/QUICK_READOUT.md" \
  2>&1 | tee -a "$OUT_ROOT/summary.log"

touch "$OUT_ROOT/pipeline.complete"
log "quick feedback complete: $OUT_ROOT/QUICK_READOUT.md"
