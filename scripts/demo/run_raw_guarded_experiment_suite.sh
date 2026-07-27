#!/usr/bin/env bash
# E0-E5 raw/guarded experiment suite. Resumable and intentionally non-Cartesian.
set -Eeuo pipefail

PROJECT="${PROJECT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
MODEL_SOURCE="${MODEL_SOURCE:-/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
MIR1K_SUBSET_ROOT="${MIR1K_SUBSET_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/mir1k_subset_v1}"
OUT_ROOT="${OUT_ROOT:-/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/raw_guarded_experiment_suite_v1}"
ROLES="${ROLES:-development quick_v2_extra}"
RUN_MIR1K="${RUN_MIR1K:-1}"
RUN_LONG="${RUN_LONG:-auto}"

M4_MANIFEST="${M4_MANIFEST:-/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_manifest.jsonl}"
M4_CHARACTERS="${M4_CHARACTERS:-/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_character_annotations.jsonl}"
M4_AUDIO_ROOT="${M4_AUDIO_ROOT:-/home/hyan/Data/ast_data/m4singer/current}"
M4_LONG_SPLIT="${M4_LONG_SPLIT:-validation}"
M4_LONG_BUCKETS="${M4_LONG_BUCKETS:-60 120 240}"
M4_LONG_MAX_CANDIDATES="${M4_LONG_MAX_CANDIDATES:-8}"
DEMUCS_MODEL="${DEMUCS_MODEL:-htdemucs_ft}"

mkdir -p "$OUT_ROOT"
LOG="$OUT_ROOT/pipeline.log"
exec > >(tee -a "$LOG") 2>&1
cd "$PROJECT"

printf '{"time":"%s","stage":"suite","status":"running","out_root":"%s"}\n' "$(date -Iseconds)" "$OUT_ROOT"

if [[ "$RUN_MIR1K" == "1" ]]; then
  read -r -a ROLE_ARGS <<< "$ROLES"
  "$PYTHON_BIN" scripts/demo/run_demo_realign_quick.py \
    --subset-root "$MIR1K_SUBSET_ROOT" \
    --out-root "$OUT_ROOT/mir1k" \
    --phase evidence q2 q3 collect \
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
    --matched-context-units 2 \
    --max-target-units 8 \
    --q3-song-count "${Q3_SONG_COUNT:-6}" \
    --q3-seams-per-song "${Q3_SEAMS_PER_SONG:-2}" \
    "$@"

  "$PYTHON_BIN" scripts/demo/analyze_raw_detector_repair.py \
    --baseline-root "$OUT_ROOT/mir1k" \
    --q2-root "$OUT_ROOT/mir1k" \
    --output "$OUT_ROOT/mir1k/raw_detector_repair_metrics.json"

  "$PYTHON_BIN" scripts/demo/analyze_raw_guarded_experiments.py \
    --root "$OUT_ROOT/mir1k" \
    --out-dir "$OUT_ROOT/mir1k/analysis"
fi

assets_present=0
if [[ -f "$M4_MANIFEST" && -f "$M4_CHARACTERS" && -d "$M4_AUDIO_ROOT" ]]; then
  assets_present=1
fi
if [[ "$RUN_LONG" == "1" || ( "$RUN_LONG" == "auto" && "$assets_present" == "1" ) ]]; then
  read -r -a BUCKETS <<< "$M4_LONG_BUCKETS"
  for bucket in "${BUCKETS[@]}"; do
    derived="$OUT_ROOT/m4singer_long/bucket_${bucket}/derived"
    subset="$OUT_ROOT/m4singer_long/bucket_${bucket}/subset"
    result="$OUT_ROOT/m4singer_long/bucket_${bucket}/result"
    mkdir -p "$derived" "$subset" "$result"
    "$PYTHON_BIN" scripts/datasets/build_synthetic_long.py \
      --manifest "$M4_MANIFEST" \
      --annotations "$M4_CHARACTERS" \
      --audio-root "$M4_AUDIO_ROOT" \
      --out-dir "$derived" \
      --bucket-sec "$bucket" \
      --split "$M4_LONG_SPLIT" \
      --max-candidates "$M4_LONG_MAX_CANDIDATES"
    count="$($PYTHON_BIN - "$derived/run_summary.json" <<'PY'
import json,sys
print(int(json.load(open(sys.argv[1]))["synthetic_count"]))
PY
)"
    if [[ "$count" -eq 0 ]]; then
      printf '{"stage":"m4singer_long_%s","status":"data_limited","reason":"no qualifying sequence"}\n' "$bucket"
      continue
    fi
    "$PYTHON_BIN" scripts/demo/materialize_synthetic_long_demo_subset.py \
      --manifest "$derived/synthetic_manifest.jsonl" \
      --characters "$derived/synthetic_characters.jsonl" \
      --audio-root "$derived" \
      --out-dir "$subset" \
      --demucs-model "$DEMUCS_MODEL"
    "$PYTHON_BIN" scripts/demo/run_demo_realign_quick.py \
      --subset-root "$subset" \
      --out-root "$result" \
      --phase evidence q2 \
      --roles development \
      --model-kind lora \
      --checkpoint "$R2_CHECKPOINT" \
      --model "$MODEL_SOURCE" \
      --revision "$MODEL_REVISION" \
      --local-files-only \
      --device cuda \
      --decoder-kind raw \
      --audio-variants demucs \
      --demucs-model "$DEMUCS_MODEL" \
      --core-sec 30 \
      --q2-trial-profile exact_plus2 \
      --q2-require-context-agreement \
      --runtime-anchor-policy \
      --max-automatic-anchor-policies 0 \
      --matched-context-units 2 \
      --max-target-units 8
    "$PYTHON_BIN" scripts/demo/analyze_raw_guarded_long_propagation.py \
      --subset-root "$subset" \
      --result-root "$result" \
      --output "$OUT_ROOT/m4singer_long/bucket_${bucket}/e5_long_propagation.json"
  done
elif [[ "$RUN_LONG" == "1" ]]; then
  echo "M4Singer assets missing: $M4_MANIFEST $M4_CHARACTERS $M4_AUDIO_ROOT" >&2
  exit 2
else
  printf '{"stage":"m4singer_long","status":"skipped_data_unavailable"}\n'
fi

printf '{"time":"%s","stage":"suite","status":"complete","out_root":"%s"}\n' "$(date -Iseconds)" "$OUT_ROOT"
