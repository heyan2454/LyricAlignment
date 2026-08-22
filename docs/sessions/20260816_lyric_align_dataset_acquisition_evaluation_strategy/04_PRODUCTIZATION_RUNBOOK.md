# Evaluation V1 Productization Runbook

本 runbook 记录当前可复现的 CPU/GPU 验证命令。所有详细数据写到 `/home/hyan/Data/lyricalign/runs/`，不写系统盘。

## 0. 环境
```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
export PYTHONPATH=src
```

## 1. 生成 Evaluation V1 split draft
```bash
python scripts/evaluation/build_evaluation_v1_split_manifest.py \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft \
  --datasets-root /home/hyan/Data/datasets \
  --seed evaluation-v1-20260816
```

## 2. 过滤可运行 tier
```bash
python scripts/evaluation/filter_manifest.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_split_manifest.jsonl \
  --out /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_diagnostic_only.jsonl \
  --tiers diagnostic_visible
```

## 3. GTSinger diagnostic 全量运行
```bash
python scripts/evaluation/build_gtsinger_diagnostic_manifest.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_diagnostic_only.jsonl \
  --datasets-root /home/hyan/Data/datasets \
  --out /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/gtsinger_diagnostic_manifest.jsonl

python scripts/evaluation/run_gtsinger_diagnostic_batch.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/gtsinger_diagnostic_manifest.jsonl \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all \
  --model /root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064 \
  --revision c07281df297b9905d24a508279258cccf987a064 \
  --r1-checkpoint /home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r1_full_seed3407/checkpoints/step-000750 \
  --r2-checkpoint /home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
```

## 4. GTSinger 评测与汇总
```bash
python scripts/evaluation/evaluate_gtsinger_batch.py \
  --batch-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all \
  --gt-map /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all/gt_map.jsonl \
  --model r2 --audio vocal --mode windowed \
  --out /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all/eval_batch_r2.json

python scripts/evaluation/aggregate_gtsinger_batch_results.py \
  --r0 .../eval_batch_r0.json --r1 .../eval_batch_r1.json --r2 .../eval_batch_r2.json \
  --out .../aggregate_summary.json
```

## 5. PJS 日语 smoke
```bash
python scripts/evaluation/build_pjs_lyrics.py \
  --musicxml /home/hyan/Data/datasets/pjs/raw/extracted/PJS_corpus_ver1.1/pjs001/pjs001.musicxml \
  --out /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_pjs_smoke/lyrics.txt
# 然后用 align_qwen_fa_serial_demo.py --language Japanese 运行
```

## 6. Sealed 访问控制
```bash
# 默认拒绝 sealed
python scripts/evaluation/guarded_run.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_split_manifest.jsonl \
  -- echo should_not_run

# 仅 diagnostic 允许
python scripts/evaluation/guarded_run.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_diagnostic_only.jsonl \
  -- echo ok
```

## 7. 清理
每个 run 根目录都有 `cleanup_report.md`，可安全删除：
```bash
rm -rf /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_<batch>
```

## 8. Raw Decoder 验证
```bash
# GTSinger hard cases raw decoder
python scripts/evaluation/run_gtsinger_diagnostic_batch.py \
  --manifest /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/gtsinger_hard_manifest.jsonl \
  --out-root /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_ablation_rawdec_all \
  --model <MODEL> --revision <REV> \
  --r1-checkpoint <R1> --r2-checkpoint <R2> \
  --extra=--decoder-kind --extra=raw
```
然后使用 `evaluate_gtsinger_batch.py` 评测。

## 9. Sealed Milestone 显式开启
```bash
python scripts/evaluation/guarded_run.py \
  --manifest <full_manifest.jsonl> \
  --tiers diagnostic_visible,regression_selection,sealed_final \
  --allow-sealed -- <your_milestone_command>
```
只有显式传入 `--allow-sealed` 且 tiers 包含 sealed_final 才会放行。

## 10. MIR Vocal 分离 Smoke
```bash
# 使用 Spleeter 分离
MODEL_PATH=/root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter \
/root/autodl-tmp/AST_storage/conda/envs/spleeter/bin/spleeter separate \
  -p spleeter:2stems -o <out_dir> <input_wav>
# 然后用 vocal 作为 --vocal-audio 跑 align_qwen_fa_serial_demo.py
```
