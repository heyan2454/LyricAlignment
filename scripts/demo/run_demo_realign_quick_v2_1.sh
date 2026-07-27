#!/usr/bin/env bash
set -u -o pipefail

# Quick v2.1 reuses completed Quick v2 evidence/Q1/Q3 and reruns only Q2 with:
# - non-overlapping natural disagreement regions;
# - saved-stage recovery that includes blocking predecessors;
# - no GT anchor in automatic selection;
# - agreement required between two reasonable local input constructions.
# This is still quick scientific evaluation, not the later overnight smoke.
REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
SUBSET_ROOT="${SUBSET_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1}"
V2_SOURCE_ROOT="${V2_SOURCE_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/realign_quick_v2}"
OUT_ROOT="${OUT_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/realign_quick_v2_1}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
MODEL_SOURCE="${MODEL_SOURCE:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-}"
PYTHON_BIN="${PYTHON_BIN:-python}"
PHASES="${PHASES:-q2}"
ROLES="${ROLES:-development quick_v2_extra}"
AUDIO_VARIANTS="${AUDIO_VARIANTS:-demucs official_vocal}"
MAX_ARCHIVE_MIB="${MAX_ARCHIVE_MIB:-8}"
REUSE_Q3="${REUSE_Q3:-1}"

if [[ -z "$R2_CHECKPOINT" ]]; then
  echo "ERROR: set R2_CHECKPOINT to the external R2 checkpoint directory" >&2
  exit 2
fi
for required in projector.pt adapter/adapter_model.safetensors adapter/adapter_config.json; do
  if [[ ! -f "$R2_CHECKPOINT/$required" ]]; then
    echo "ERROR: incomplete R2 checkpoint; missing $R2_CHECKPOINT/$required" >&2
    exit 2
  fi
done

for required in evidence q1_anchor_scan; do
  if [[ ! -e "$V2_SOURCE_ROOT/$required" ]]; then
    echo "ERROR: Quick v2 source is missing $V2_SOURCE_ROOT/$required" >&2
    echo "Quick v2.1 is incremental and expects the completed Quick v2 output." >&2
    exit 2
  fi
done

resolve_model_source() {
  if [[ -n "$MODEL_SOURCE" && -f "$MODEL_SOURCE/model.safetensors" ]]; then
    printf '%s\n' "$MODEL_SOURCE"
    return 0
  fi
  local candidates=(
    "/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/$MODEL_REVISION"
    "/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/$MODEL_REVISION"
    "/root/.cache/huggingface/hub/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/$MODEL_REVISION"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate/model.safetensors" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  while IFS= read -r candidate; do
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(find -L \
    /root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache \
    /home/hyan/Data/lyricalign/models/hf_cache \
    /root/.cache/huggingface/hub \
    -path '*/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/*/model.safetensors' \
    -size +1000M -printf '%h\n' 2>/dev/null | sort -u)
  return 1
}

if ! MODEL_SOURCE="$(resolve_model_source)"; then
  echo "ERROR: could not find a complete local Qwen3 ForcedAligner snapshot." >&2
  echo "Set MODEL_SOURCE to the snapshot directory containing model.safetensors." >&2
  exit 2
fi
for required in model.safetensors config.json tokenizer_config.json; do
  if [[ ! -f "$MODEL_SOURCE/$required" ]]; then
    echo "ERROR: incomplete model snapshot; missing $MODEL_SOURCE/$required" >&2
    exit 2
  fi
done
if [[ ! -f "$MODEL_SOURCE/processor_config.json" && ! -f "$MODEL_SOURCE/preprocessor_config.json" ]]; then
  echo "ERROR: model snapshot has neither processor_config.json nor preprocessor_config.json" >&2
  exit 2
fi
model_bytes="$(stat -Lc '%s' "$MODEL_SOURCE/model.safetensors")"
if (( model_bytes < 1000000000 )); then
  echo "ERROR: model.safetensors is unexpectedly small: $model_bytes bytes" >&2
  exit 2
fi
export MODEL_SOURCE

mkdir -p "$OUT_ROOT/logs"
reuse_dir() {
  local relative="$1"
  if [[ -e "$OUT_ROOT/$relative" || -L "$OUT_ROOT/$relative" ]]; then
    return 0
  fi
  ln -s "$V2_SOURCE_ROOT/$relative" "$OUT_ROOT/$relative"
}
reuse_dir evidence
reuse_dir q1_anchor_scan
if [[ "$REUSE_Q3" == "1" && -e "$V2_SOURCE_ROOT/q3_injection_matrix" ]]; then
  reuse_dir q3_injection_matrix
fi
printf '%s\n' "$V2_SOURCE_ROOT" > "$OUT_ROOT/reused_quick_v2_root.txt"

cd "$REPO_ROOT"
read -r -a PHASE_ARGS <<< "$PHASES"
read -r -a ROLE_ARGS <<< "$ROLES"
read -r -a AUDIO_ARGS <<< "$AUDIO_VARIANTS"

COMMAND=(
  "$PYTHON_BIN" scripts/demo/run_demo_realign_quick.py
  --subset-root "$SUBSET_ROOT"
  --out-root "$OUT_ROOT"
  --phase "${PHASE_ARGS[@]}"
  --roles "${ROLE_ARGS[@]}"
  --model-kind lora
  --checkpoint "$R2_CHECKPOINT"
  --model "$MODEL_SOURCE"
  --revision "$MODEL_REVISION"
  --local-files-only
  --audio-variants "${AUDIO_ARGS[@]}"
  --core-sec 30
  --padding-sec 0.5
  --matched-context-units 2 4
  --selection-consensus-tolerance-sec 0.16
  --rollback-predecessor-units 4
  --max-target-units 8
  --disagreement-peak-threshold-sec 0.24
  --anchor-guard-units 1
  --max-anchor-search-units 16
  --max-anchor-span-units 16
  --max-anchor-span-sec 12
  --q3-song-count 6
  --q3-seams-per-song 2
)

printf '%q ' "${COMMAND[@]}" > "$OUT_ROOT/command.sh"
printf '\n' >> "$OUT_ROOT/command.sh"
printf '%s\n' "$MODEL_SOURCE" > "$OUT_ROOT/resolved_model_source.txt"
printf '%s\n' "$R2_CHECKPOINT" > "$OUT_ROOT/resolved_checkpoint.txt"

rm -f "$OUT_ROOT/return_code.txt" "$OUT_ROOT/collect_return_code.txt"
"${COMMAND[@]}" 2>&1 | tee -a "$OUT_ROOT/logs/quick_controller.log"
rc=${PIPESTATUS[0]}
printf '%s\n' "$rc" > "$OUT_ROOT/return_code.txt"

"$PYTHON_BIN" scripts/demo/collect_demo_realign_quick.py \
  --out-root "$OUT_ROOT" \
  --archive "$OUT_ROOT/realign_quick_v2_1_handoff_compact.tar.gz" \
  --compact \
  --max-archive-mib "$MAX_ARCHIVE_MIB" \
  2>&1 | tee -a "$OUT_ROOT/logs/collect.log"
collect_rc=${PIPESTATUS[0]}
printf '%s\n' "$collect_rc" > "$OUT_ROOT/collect_return_code.txt"
exit "$rc"
