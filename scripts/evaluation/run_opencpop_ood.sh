#!/usr/bin/env bash
# OpenCPOP 域外字符级复评（2026-09-24）。
#
# 复用既有 runner（scripts/evaluation/ood_dp_replay.py），不新建 runner：official 与整句 DP 走
# **同一次前向**，只比结束点误差；GT 只来自 OpenCPOP 人工汉字轨，**只作报告，不参与任何选点**
# （所有 checkpoint 的训练时间都早于该数据到手时间 2026-09-22）。
#
# 模型点用 `:` 分隔的 spec 描述：  标签:config:checkpoint:stage:mode
#   mode=base  ⇒ 跳过权重加载，测**未微调的官方底座**（checkpoint 字段写 none）
#   mode=lora  ⇒ 正常加载 checkpoint（trainer_state.pt 的 trainable_state）
#
#   bash scripts/evaluation/run_opencpop_ood.sh                                  # 句级，默认四点
#   VIEWS="window" bash scripts/evaluation/run_opencpop_ood.sh                   # 60s 长窗口视图
#   VIEWS="sentence window" LIMIT_ITEMS=8 bash scripts/evaluation/run_opencpop_ood.sh   # smoke
#   SPECS="base:cfg:none:r0:base" bash scripts/evaluation/run_opencpop_ood.sh    # 只跑一个点
#
# 已存在的 eval_*.json 会被跳过（可安全续跑），产物与日志各模型独立文件，禁止两个 controller 并发。
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
DERIVED="${DERIVED:-/home/hyan/Data/lyricalign/derived/20260924_opencpop_eval}"
RUN_ROOT="${RUN_ROOT:-/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval}"
VIEWS="${VIEWS:-sentence}"
LIMIT_ITEMS="${LIMIT_ITEMS:-0}"

source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export HF_HUB_CACHE="${HF_HUB_CACHE:-/home/hyan/Data/lyricalign/models/hf_cache}"
export HF_HUB_OFFLINE=1
export PYTHONPATH="$REPO_ROOT/src"
cd "$REPO_ROOT"
mkdir -p "$RUN_ROOT"

FROM_OFFICIAL_CONFIG=configs/training/qwen_fa_lora_from_official_20260913.yaml
OLD_R2_CONFIG=configs/training/qwen_fa_lora_full_r2_seed2_v1.yaml
RUN_20260913=/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/checkpoints
RUN_20260724=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints

# 默认四点：先未微调底座（baseline），再线上 750，再终局与选点。
DEFAULT_SPECS=(
  "baseweight:$FROM_OFFICIAL_CONFIG:none:r0:base"
  "old750:$OLD_R2_CONFIG:$RUN_20260724/step-000750:r2:lora"
  "uniform12000:$FROM_OFFICIAL_CONFIG:$RUN_20260913/step-012000:r2:lora"
  "pick4850:$FROM_OFFICIAL_CONFIG:$RUN_20260913/step-004850:r2:lora"
)
if [[ -n "${SPECS:-}" ]]; then
  read -r -a SPECS_ARR <<< "$SPECS"
else
  SPECS_ARR=("${DEFAULT_SPECS[@]}")
fi

run_one() {  # $1=view 的 evidence 路径 $2=view 标签 $3=spec
  local evidence=$1 view=$2 spec=$3
  local IFS=:
  read -r name cfg ckpt stage mode <<< "$spec"
  unset IFS
  local out="$RUN_ROOT/eval_${view}_${name}.json" log="$RUN_ROOT/log_${view}_${name}.txt"
  if [[ -s "$out" ]]; then
    echo "[skip ] ${view}/${name}: 已有产物 $out"
    return 0
  fi
  if [[ "$mode" == "lora" && ! -d "$ckpt" ]]; then
    echo "MISSING checkpoint for ${view}/${name}: $ckpt" >&2
    return 1
  fi
  echo "[start] ${view}/${name} mode=$mode stage=$stage $(date -u +%H:%M:%S)"
  local extra=()
  [[ "$LIMIT_ITEMS" != "0" ]] && extra=(--limit-items "$LIMIT_ITEMS")
  [[ "$mode" == "base" ]] && extra+=(--base-model-only)
  python scripts/evaluation/ood_dp_replay.py \
    --evidence "$evidence" --config "$cfg" --stage "$stage" --checkpoint "${ckpt/#none//nonexistent}" \
    --dataset-label "OpenCPOP/$view" "${extra[@]}" --out "$out" > "$log" 2>&1
  echo "[done ] ${view}/${name} -> $out"
}

for view in $VIEWS; do
  evidence="$DERIVED/evidence_${view}.jsonl.gz"
  [[ -s "$evidence" ]] || { echo "MISSING evidence: $evidence" >&2; exit 1; }
  for spec in "${SPECS_ARR[@]}"; do
    run_one "$evidence" "$view" "$spec"
  done
  touch "$RUN_ROOT/_${view}_all.done"
done
echo "[all done] $(date -u +%H:%M:%S)"
