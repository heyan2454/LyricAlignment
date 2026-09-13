#!/bin/bash
# A/B 判决一条命令：长流视图（主指标，两判据）+ 机制检查（若 dump 就绪）+ 重生成夜班报告。
# 用法：bash scripts/training/run_ab_verdict.sh            # 需要两臂都已完成
#      bash scripts/training/run_ab_verdict.sh --skip-view # 已有 ab_arms.json 时只重算判决
set -uo pipefail
cd /home/hyan/LyricAlignment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export HF_HUB_CACHE=/home/hyan/Data/lyricalign/models/hf_cache HF_HUB_OFFLINE=1 PYTHONPATH=src OMP_NUM_THREADS=4

D=/home/hyan/Data/lyricalign/runs
U=$D/20260913_qwen_fa_r2_from_official_seed20260724
A=$D/20260914_qwen_fa_r2_warmstart_control_seed20260724
B=$D/20260914_qwen_fa_r2_warmstart_oversample_seed20260724
OUT=results/by_run/20260914_long_context_view/ab_arms.json

latest_ckpt() { ls -d "$1"/checkpoints/step-* 2>/dev/null | sort | tail -1; }

SKIP_VIEW=0
[ "${1:-}" = "--skip-view" ] && SKIP_VIEW=1

for arm in "$A" "$B"; do
  if [ ! -s "$arm/metrics.jsonl" ]; then echo "缺少臂目录：$arm"; exit 1; fi
done
CK_A=$(latest_ckpt "$A"); CK_B=$(latest_ckpt "$B")
echo "A 存档 = $CK_A"
echo "B 存档 = $CK_B"
AVAIL=$(df --output=avail -BG /root/autodl-tmp | tail -1 | tr -dc '0-9')
echo "磁盘可用 ${AVAIL}G"

if ps -eo pid=,comm=,args= | awk '$2=="python" && /run_qwen_fa_lora/ {f=1} END{exit !f}'; then
  echo "检测到训练进程在跑：本脚本只做判决、不占卡 ⇒ 加 --skip-view 或等训练结束"; SKIP_VIEW=1
fi

if [ "$SKIP_VIEW" -eq 0 ] && [ "${AVAIL:-0}" -ge 15 ]; then
  # 起点（uniform-12000）与两臂放同一个文件、同一视图、同一协议
  python scripts/evaluation/eval_long_context_view.py --run-dir "$A" \
    --checkpoint "uniform-12000=$U/checkpoints/step-012000" \
    --checkpoint "warmstart-control=$CK_A" \
    --checkpoint "warmstart-oversample=$CK_B" \
    --batch-size 4 --out "$OUT" 2>&1 | tail -3
fi

DUR_ARGS=()
for arm in control treatment; do
  f=results/by_run/20260914_mech_$arm/duration_ratio.json
  [ -s "$f" ] && DUR_ARGS+=(--duration "warmstart-$arm=$f")
done

for DEC in fixed dp; do
  echo "=== 判决（判据 $DEC）==="
  python scripts/evaluation/warmstart_ab_verdict.py \
    --view results/by_run/20260914_long_context_view/baseline_aligned.summary.json \
    --view "$OUT" \
    ${DUR_ARGS[@]+"${DUR_ARGS[@]}"} \
    --decoder "$DEC" --control warmstart-control --treatment warmstart-oversample \
    --baseline old-r2-750 --reference uniform-12000 \
    --out "results/by_run/20260914_warmstart_ab_$DEC" 2>&1 | sed -n '/^| 比较/,/^$/p'
done

# 逐字符配对（B vs A），若两臂 dump 都已就绪
if [ -s results/by_run/20260914_mech_control/per_character.jsonl ] \
   && [ -s results/by_run/20260914_mech_treatment/per_character.jsonl ]; then
  python scripts/evaluation/paired_checkpoint_comparison.py \
    --old results/by_run/20260914_mech_control/per_character.jsonl \
    --new results/by_run/20260914_mech_treatment/per_character.jsonl \
    --out results/by_run/20260914_mech_ab_paired/metrics.json 2>&1 | tail -12
fi

python scripts/evaluation/make_night_report.py --repo . --out docs/status/20260914_night_report.md
echo "完成：判决在 results/by_run/20260914_warmstart_ab_{fixed,dp}/REPORT.md，总报告 docs/status/20260914_night_report.md"
