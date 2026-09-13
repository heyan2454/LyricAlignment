#!/bin/bash
# 长上下文臂启动脚本：日志与哨兵放在 run 目录之外（trainer 把非空 run 目录视为"已存在"）。
set -uo pipefail
cd /home/hyan/LyricAlignment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export HF_HUB_CACHE=/home/hyan/Data/lyricalign/models/hf_cache HF_HUB_OFFLINE=1 PYTHONPATH=src OMP_NUM_THREADS=6
LOG=/home/hyan/Data/lyricalign/runs/_launch_logs/20260914_qwen_fa_r2_concat20.log
DONE=/home/hyan/Data/lyricalign/runs/_launch_logs/20260914_qwen_fa_r2_concat20.done
R=/home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_concat20c_seed20260724
echo "=== start $(date -Iseconds) ===" >> "$LOG"
if [ -e "$DONE" ]; then echo "已有完成哨兵，跳过" >> "$LOG"; exit 0; fi
if ps -eo pid=,comm=,args= | awk '$2=="python" && /run_qwen_fa_lora/ {found=1} END{exit !found}'; then
  echo "已有训练进程在跑，拒绝并发" >> "$LOG"; exit 1
fi
AVAIL=$(df --output=avail -BG /root/autodl-tmp | tail -1 | tr -dc '0-9')
if [ "${AVAIL:-0}" -lt 24 ]; then echo "磁盘 ${AVAIL}G < 24G，拒绝启动" >> "$LOG"; exit 1; fi
python scripts/training/run_qwen_fa_lora.py \
  --config configs/training/qwen_fa_lora_concat20_20260914.yaml \
  --run-dir "$R" --stage r2 --device cuda --local-files-only >> "$LOG" 2>&1
STATUS=$?
echo "EXIT=$STATUS $(date -Iseconds)" >> "$LOG"
# 只有成功退出才立哨兵；失败时保留现场，由巡检决定下一步（不自动重试第三次）
if [ "$STATUS" -eq 0 ]; then echo "DONE $(date -Iseconds)" > "$DONE"; else echo "FAILED $STATUS $(date -Iseconds)" > "$DONE.failed"; fi
