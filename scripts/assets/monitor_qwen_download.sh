#!/usr/bin/env bash
# Restartable external-cache monitor. It never downloads a second model variant.
set -u

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
data_root=${LYRICALIGN_EXTERNAL_ROOT:-/home/hyan/Data/lyricalign}
cache_dir="$data_root/models/hf_cache"
manifest="$data_root/outputs/assets/qwen_forced_aligner_manifest.json"
log_dir="$data_root/logs"
log_file="$log_dir/qwen_download_monitor.log"

mkdir -p "$log_dir"
while [ ! -s "$manifest" ]; do
  printf '%s attempt=start\n' "$(date -Is)" >> "$log_file"
  if timeout 45m env HF_HUB_DISABLE_XET=1 python "$project_root/scripts/assets/download_qwen_model.py" \
    --cache-dir "$cache_dir" --manifest "$manifest" >> "$log_file" 2>&1; then
    printf '%s status=completed manifest=%s\n' "$(date -Is)" "$manifest" >> "$log_file"
    exit 0
  fi
  printf '%s attempt=failed retry_in_sec=300\n' "$(date -Is)" >> "$log_file"
  sleep 300
done
printf '%s status=already_completed manifest=%s\n' "$(date -Is)" "$manifest" >> "$log_file"
