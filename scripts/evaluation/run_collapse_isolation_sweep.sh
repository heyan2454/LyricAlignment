#!/usr/bin/env bash
# 塌陷块 → 单独切片重标 的逐块诊断扫描（四个模型点，取**全部**塌陷块）。
#
# 只做一件事：把窗内"连续 ≥5 字共用同一结束点"的块全部挑出来，单独切给同一个 checkpoint 重标，
# 逐块看误差与候选质量是否反转。**不含任何生产路线判断**（那属于另一件事）。
#
#   bash scripts/evaluation/run_collapse_isolation_sweep.sh
#   MODELS="old750" bash scripts/evaluation/run_collapse_isolation_sweep.sh    # 只跑一个点
#
# 产物：$EVAL_ROOT/units_window_<model>.jsonl.gz（窗内逐单元）与 $EVAL_ROOT/isolation_<model>/（切片+重标）
# 已存在的产物自动跳过，可安全续跑；单卡串行。
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/hyan/LyricAlignment}"
DERIVED="${DERIVED:-/home/hyan/Data/lyricalign/derived/20260924_opencpop_eval}"
EVAL_ROOT="${EVAL_ROOT:-/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval}"
MODELS="${MODELS:-baseweight old750 uniform12000 pick4850}"

source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export HF_HUB_CACHE="${HF_HUB_CACHE:-/home/hyan/Data/lyricalign/models/hf_cache}"
export HF_HUB_OFFLINE=1
export PYTHONPATH="$REPO_ROOT/src"
cd "$REPO_ROOT"

FROM_OFFICIAL=configs/training/qwen_fa_lora_from_official_20260913.yaml
OLD_R2=configs/training/qwen_fa_lora_full_r2_seed2_v1.yaml
R13=/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/checkpoints
R07=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints

spec_for() {  # 标签 -> "config|checkpoint|stage|mode"
  case "$1" in
    baseweight)    echo "$FROM_OFFICIAL|none|r0|base" ;;
    old750)        echo "$OLD_R2|$R07/step-000750|r2|lora" ;;
    uniform12000)  echo "$FROM_OFFICIAL|$R13/step-012000|r2|lora" ;;
    pick4850)      echo "$FROM_OFFICIAL|$R13/step-004850|r2|lora" ;;
    *) echo "" >&2; return 1 ;;
  esac
}

replay() {  # $1=evidence $2=out $3=dump $4=config $5=checkpoint $6=stage $7=mode $8=label
  local extra=()
  [[ "$7" == "base" ]] && extra=(--base-model-only)
  python scripts/evaluation/ood_dp_replay.py --evidence "$1" --config "$4" --stage "$6" \
    --checkpoint "${5/none//nonexistent}" --dataset-label "$8" --out "$2" --dump-units "$3" "${extra[@]}" \
    > "${2%.json}.log" 2>&1
}

for model in $MODELS; do
  IFS='|' read -r cfg ckpt stage mode <<< "$(spec_for "$model")"
  window_dump="$EVAL_ROOT/units_window_$model.jsonl.gz"
  iso_dir="$EVAL_ROOT/isolation_$model"
  echo "=== $model ==="

  if [[ ! -s "$window_dump" ]]; then
    echo "[1/3] 窗视图逐单元 dump"
    replay "$DERIVED/evidence_window.jsonl.gz" "$EVAL_ROOT/probe_window_$model.json" \
           "$window_dump" "$cfg" "$ckpt" "$stage" "$mode" "OpenCPOP/window/$model"
  else
    echo "[1/3] 窗 dump 已存在，跳过"
  fi

  echo "[2/3] 挑全部塌陷块并切片"
  python scripts/evaluation/prepare_collapse_isolation.py --dump "$window_dump" --out-dir "$iso_dir" \
    > "$iso_dir.prepare.log" 2>&1 || { cat "$iso_dir.prepare.log"; continue; }
  head -1 "$iso_dir.prepare.log"

  if [[ -s "$iso_dir/evidence_isolation.jsonl.gz" ]]; then
    echo "[3/3] 切片重标"
    replay "$iso_dir/evidence_isolation.jsonl.gz" "$iso_dir/eval_isolation_$model.json" \
           "$iso_dir/units_isolation_$model.jsonl.gz" "$cfg" "$ckpt" "$stage" "$mode" \
           "OpenCPOP/isolation/$model"
  else
    echo "      该模型点没有塌陷块，跳过重标"
  fi
done
touch "$EVAL_ROOT/_isolation_sweep.done"
echo "[sweep done] $(date -u +%H:%M:%S)"
