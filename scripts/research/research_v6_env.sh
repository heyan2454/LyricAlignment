#!/usr/bin/env bash
set -u -o pipefail
REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python}"
MODEL_REVISION="${MODEL_REVISION:-c07281df297b9905d24a508279258cccf987a064}"
MODEL_SOURCE="${MODEL_SOURCE:-}"
R2_CHECKPOINT="${R2_CHECKPOINT:-/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750}"
M4_LABELS="${M4_LABELS:-/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl}"
M4_AUDIO_ROOT="${M4_AUDIO_ROOT:-/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer}"
M4_SPLITS="${M4_SPLITS:-train,validation,test}"
MIR1K_SUBSET_ROOT="${MIR1K_SUBSET_ROOT:-/home/hyan/Data/lyricalign/demo_diagnostics/mir1k_subset_v1}"
DEMO_ROOT="${DEMO_ROOT:-/home/hyan/Data/lyricalign/test}"
DEMO_PREPARED_SUFFIXES="${DEMO_PREPARED_SUFFIXES:-_qwen_fa,_qwen_fa_decoder_realign,_qwen_fa_raw_guarded}"
DEVICE="${DEVICE:-cuda}"
M4_LONG_TARGET_SECS="${M4_LONG_TARGET_SECS:-60,120,180}"

resolve_model_source() {
  [[ -n "$MODEL_SOURCE" && -f "$MODEL_SOURCE/model.safetensors" ]] && { printf '%s\n' "$MODEL_SOURCE"; return; }
  local root candidate
  for root in /root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache /home/hyan/Data/lyricalign/models/hf_cache /root/.cache/huggingface/hub; do
    while IFS= read -r candidate; do [[ -n "$candidate" ]] && { printf '%s\n' "$candidate"; return; }; done < <(find -L "$root" -path '*/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/*/model.safetensors' -size +1000M -printf '%h\n' 2>/dev/null | sort -u)
  done
  return 1
}
validate_research_v6_inputs() {
  local p
  [[ -x "$PYTHON_BIN" ]] || { echo "ERROR Python: $PYTHON_BIN" >&2; return 2; }
  for p in "$REPO_ROOT" "$R2_CHECKPOINT" "$M4_AUDIO_ROOT" "$MIR1K_SUBSET_ROOT" "$DEMO_ROOT"; do [[ -d "$p" ]] || { echo "ERROR directory: $p" >&2; return 2; }; done
  [[ -f "$M4_LABELS" ]] || { echo "ERROR M4 labels: $M4_LABELS" >&2; return 2; }
  [[ -f "$MIR1K_SUBSET_ROOT/selection.jsonl" ]] || { echo "ERROR MIR selection.jsonl" >&2; return 2; }
  for p in projector.pt adapter/adapter_model.safetensors adapter/adapter_config.json; do [[ -f "$R2_CHECKPOINT/$p" ]] || { echo "ERROR checkpoint missing $p" >&2; return 2; }; done
  MODEL_SOURCE="$(resolve_model_source)" || { echo "ERROR complete Qwen snapshot not found" >&2; return 2; }
  for p in model.safetensors config.json tokenizer_config.json; do [[ -f "$MODEL_SOURCE/$p" ]] || { echo "ERROR model missing $p" >&2; return 2; }; done
  [[ -f "$MODEL_SOURCE/processor_config.json" || -f "$MODEL_SOURCE/preprocessor_config.json" ]] || {
    echo "ERROR model missing processor_config.json/preprocessor_config.json" >&2; return 2;
  }
  export REPO_ROOT PYTHON_BIN MODEL_REVISION MODEL_SOURCE R2_CHECKPOINT M4_LABELS M4_AUDIO_ROOT M4_SPLITS MIR1K_SUBSET_ROOT DEMO_ROOT DEMO_PREPARED_SUFFIXES DEVICE M4_LONG_TARGET_SECS
}
