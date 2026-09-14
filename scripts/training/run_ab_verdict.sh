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
    --out "results/by_run/20260914_warmstart_ab_$DEC" > "/tmp/verdict_$DEC.log" 2>&1
  status=$?
  if [ $status -ne 0 ]; then
    echo "!! 判决（$DEC）失败 exit=$status，末尾日志："; tail -5 "/tmp/verdict_$DEC.log"; continue
  fi
  sed -n '/^| 比较/,/^$/p' "results/by_run/20260914_warmstart_ab_$DEC/REPORT.md"
done

# 逐字符配对：§3g-4 规定必须同时看 B vs A（配比净效应）与 B vs 起点（是否真的修好），
# 且每个比较都要过稳健性检查（中位数/截尾均值 + 二项 McNemar + ×4 校正），三者不同向只能写"迹象"。
DUMP_A=results/by_run/20260914_mech_control/per_character.jsonl
DUMP_B=results/by_run/20260914_mech_treatment/per_character.jsonl
DUMP_START=results/by_run/20260914_mech_validation_uniform/per_character.jsonl
if [ -s "$DUMP_A" ] && [ -s "$DUMP_B" ]; then
  echo "=== 配对 B vs A（配比净效应）==="
  python scripts/evaluation/paired_checkpoint_comparison.py \
    --old "$DUMP_A" --new "$DUMP_B" --out results/by_run/20260914_mech_ab_paired/metrics.json 2>&1 | tail -6
  python scripts/evaluation/paired_robustness_check.py \
    --old "$DUMP_A" --new "$DUMP_B" \
    --out results/by_run/20260914_mech_ab_paired/robustness.json \
    --report docs/status/20260914_robustness_B_vs_A.md >/dev/null
fi
if [ -s "$DUMP_START" ] && [ -s "$DUMP_B" ]; then
  echo "=== 配对 B vs 起点（是否真的修好长音）==="
  python scripts/evaluation/paired_checkpoint_comparison.py \
    --old "$DUMP_START" --new "$DUMP_B" --out results/by_run/20260914_mech_B_vs_start/paired.json 2>&1 | tail -6
  python scripts/evaluation/paired_robustness_check.py \
    --old "$DUMP_START" --new "$DUMP_B" \
    --out results/by_run/20260914_mech_B_vs_start/robustness.json \
    --report docs/status/20260914_robustness_B_vs_start.md >/dev/null
fi
if [ -s "$DUMP_START" ] && [ -s "$DUMP_A" ]; then
  echo "=== 配对 A vs 起点（对照臂漂移，用于解释上面的差值）==="
  python scripts/evaluation/paired_robustness_check.py \
    --old "$DUMP_START" --new "$DUMP_A" \
    --out results/by_run/20260914_paired_A_vs_start/robustness.json \
    --report docs/status/20260914_robustness_A_vs_start.md >/dev/null
fi

# §3l 的 2×2 决策表：由代码给出所在格与预定下一步，避免明早临场判读
python scripts/evaluation/ab_decision_table.py \
  --long-paired results/by_run/20260914_mech_ab_paired/robustness.json \
  --long-vs-start results/by_run/20260914_mech_B_vs_start/robustness.json \
  --short results/by_run/20260914_matched_steps/B_vs_A.json \
  --out results/by_run/20260914_ab_decision/metrics.json > /tmp/decision_table.log 2>&1 \
  || { echo "!! 决策表生成失败"; tail -5 /tmp/decision_table.log; }
sed -n '/所在格/,$p' results/by_run/20260914_ab_decision/REPORT.md 2>/dev/null || true
python scripts/evaluation/make_night_report.py --repo . --out docs/status/20260914_night_report.md
python scripts/evaluation/make_plain_summary.py --repo . --out docs/status/20260914_plain_summary.md
echo "完成：判决在 results/by_run/20260914_warmstart_ab_{fixed,dp}/REPORT.md，总报告 docs/status/20260914_night_report.md"
