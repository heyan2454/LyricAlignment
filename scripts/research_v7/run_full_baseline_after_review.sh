#!/usr/bin/env bash
# Start the all-segment baseline only after every blinded review video exists.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 REVIEW_ROOT REVIEW_PID BASELINE_ROOT" >&2
  exit 2
fi
review_root=$1
review_pid=$2
baseline_root=$3
expected=140
status_path="$baseline_root/queue_status.json"
mkdir -p "$baseline_root"

while true; do
  completed=$(find "$review_root/videos" -maxdepth 1 -type f -name '*.mp4' 2>/dev/null | wc -l)
  printf '{"stage":"waiting_for_review_videos","rendered":%s,"expected":%s}\n' "$completed" "$expected" > "$status_path"
  if [[ "$completed" -eq "$expected" ]]; then
    break
  fi
  if ! kill -0 "$review_pid" 2>/dev/null; then
    printf '{"stage":"blocked","reason":"review renderer stopped before all videos completed","rendered":%s,"expected":%s}\n' "$completed" "$expected" > "$status_path"
    exit 1
  fi
  sleep 30
done

printf '{"stage":"running_baseline","rendered":%s,"expected":%s}\n' "$completed" "$expected" > "$status_path"
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
PYTHONPATH=src:. python scripts/research_v7/run_behavior_suite.py \
  --manifest "$baseline_root/manifest.jsonl" --out-root "$baseline_root" --real --resume \
  --model-dir /root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064 \
  --checkpoint-path /home/hyan/LyricAlignment/models/qwen_fa_r2_step000750/adapter
printf '{"stage":"baseline_inference_complete"}\n' > "$status_path"
