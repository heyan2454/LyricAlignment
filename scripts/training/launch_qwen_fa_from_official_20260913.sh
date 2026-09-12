#!/usr/bin/env bash
# Detached launch of the from-official re-finetune with funnelled validation.
# Survives terminal disconnect (setsid + nohup); writes a completion sentinel when the python exits.
set -uo pipefail
cd /home/hyan/LyricAlignment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export HF_HUB_CACHE=/home/hyan/Data/lyricalign/models/hf_cache
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH=src
RUN=/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724
# the log must live OUTSIDE the run dir: the trainer treats a non-empty run dir as an existing run
LOGDIR=/home/hyan/Data/lyricalign/runs/_launch_logs
mkdir -p "$LOGDIR"
LOG="$LOGDIR/20260913_qwen_fa_r2_from_official.log"
rm -f "$LOGDIR/20260913_qwen_fa_r2_from_official.done"
{
  echo "=== start $(date -Is) pid=$$ ==="
  python scripts/training/run_qwen_fa_lora.py \
      --config configs/training/qwen_fa_lora_from_official_20260913.yaml \
      --run-dir "$RUN" --stage r2 --device cuda --local-files-only
  echo "EXIT=$?"
  echo "=== end $(date -Is) ==="
} >> "$LOG" 2>&1
echo "$(date -Is)" > "$LOGDIR/20260913_qwen_fa_r2_from_official.done"
