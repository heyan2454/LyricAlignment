#!/usr/bin/env bash
set -u -o pipefail

REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
MODEL_SOURCE="${MODEL_SOURCE:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
M4_LABELS="${M4_LABELS:-/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl}"
M4_AUDIO_ROOT="${M4_AUDIO_ROOT:-/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer}"
MIR1K_SUBSET_ROOT="${MIR1K_SUBSET_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1}"
DEMO_ROOT="${DEMO_ROOT:-/home/hyan/Data/lyricalign/test}"
DEMO_PREPARED_SUFFIXES="${DEMO_PREPARED_SUFFIXES:-_qwen_fa,_qwen_fa_decoder_realign,_qwen_fa_raw_guarded}"
DEVICE="${DEVICE:-cuda}"
EVIDENCE_CAP_MIB="${EVIDENCE_CAP_MIB:-8}"
DEMO_PUBLISH_LAYOUT="${DEMO_PUBLISH_LAYOUT:-central}"
DEMO_PUBLISH_ROOT="${DEMO_PUBLISH_ROOT:-}"
M4_LONG_TARGET_SECS="${M4_LONG_TARGET_SECS:-60,120,180}"

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
    [[ -n "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done < <(find -L \
    /root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache \
    /home/hyan/Data/lyricalign/models/hf_cache \
    /root/.cache/huggingface/hub \
    -path '*/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/*/model.safetensors' \
    -size +1000M -printf '%h\n' 2>/dev/null | sort -u)
  return 1
}

validate_inline_realign_inputs() {
  local path
  for path in "$REPO_ROOT" "$R2_CHECKPOINT" "$M4_AUDIO_ROOT" "$MIR1K_SUBSET_ROOT"; do
    [[ -d "$path" ]] || { echo "ERROR: required directory missing: $path" >&2; return 2; }
  done
  [[ -x "$PYTHON_BIN" ]] || { echo "ERROR: Python missing or not executable: $PYTHON_BIN" >&2; return 2; }
  [[ -f "$M4_LABELS" ]] || { echo "ERROR: M4 labels missing: $M4_LABELS" >&2; return 2; }
  [[ -f "$MIR1K_SUBSET_ROOT/selection.jsonl" ]] || {
    echo "ERROR: MIR-1K selection missing: $MIR1K_SUBSET_ROOT/selection.jsonl" >&2; return 2;
  }
  for path in projector.pt adapter/adapter_model.safetensors adapter/adapter_config.json; do
    [[ -f "$R2_CHECKPOINT/$path" ]] || {
      echo "ERROR: incomplete R2 checkpoint; missing $R2_CHECKPOINT/$path" >&2; return 2;
    }
  done
  if ! MODEL_SOURCE="$(resolve_model_source)"; then
    echo "ERROR: complete local Qwen forced-aligner snapshot not found" >&2
    return 2
  fi
  for path in model.safetensors config.json tokenizer_config.json; do
    [[ -f "$MODEL_SOURCE/$path" ]] || {
      echo "ERROR: model snapshot missing $MODEL_SOURCE/$path" >&2; return 2;
    }
  done
  if [[ ! -f "$MODEL_SOURCE/processor_config.json" && ! -f "$MODEL_SOURCE/preprocessor_config.json" ]]; then
    echo "ERROR: snapshot has neither processor_config.json nor preprocessor_config.json" >&2
    return 2
  fi
  if [[ ! -d "$DEMO_ROOT" ]]; then
    echo "WARN: Demo root missing; Demo items will be skipped: $DEMO_ROOT" >&2
    DEMO_ROOT=""
  fi
  export REPO_ROOT PYTHON_BIN MODEL_REVISION MODEL_SOURCE R2_CHECKPOINT
  export M4_LABELS M4_AUDIO_ROOT MIR1K_SUBSET_ROOT DEMO_ROOT DEMO_PREPARED_SUFFIXES
  case "$DEMO_PUBLISH_LAYOUT" in
    central|adjacent|directory) ;;
    *) echo "ERROR: DEMO_PUBLISH_LAYOUT must be central, adjacent, or directory" >&2; return 2 ;;
  esac
  if [[ "$DEMO_PUBLISH_LAYOUT" == "directory" && -z "$DEMO_PUBLISH_ROOT" ]]; then
    echo "ERROR: DEMO_PUBLISH_ROOT is required when DEMO_PUBLISH_LAYOUT=directory" >&2
    return 2
  fi
  export DEVICE EVIDENCE_CAP_MIB DEMO_PUBLISH_LAYOUT DEMO_PUBLISH_ROOT M4_LONG_TARGET_SECS
}
