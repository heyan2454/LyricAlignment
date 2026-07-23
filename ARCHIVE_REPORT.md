# Archive Report: Qwen FA LoRA Full R2

**Archive date:** 2026-07-23  
**Stable extracted root:** `LyricAlignment/`  
**Output archive:** `LyricAlignment_20260723_qwen_fa_lora_full_r2_archive.zip`  
**Source archive:** `LyricAlignment_202607231143_tryloraovernight(1).zip`

## Purpose

将 Qwen Forced Aligner LoRA 首轮实验的已知状态、轻量指标和后续手动入口归档。此次归档不运行 GPU 训练或评测，不复制 checkpoint、音频、predictions 或外部 manifest。

## Added or updated

- 更新 `README.md`、`AI_SESSION_ENTRY.md`、`docs/status/project_current.md`；
- 将下一步收敛为 final full-R2 MIR-1K OOD；
- 新增 `docs/sessions/20260723_qwen_fa_lora_full_r2_archive.md`；
- 新增 `reports/progress/20260723_qwen_fa_lora_results.md`；
- 新增结构化比较 `results/comparisons/20260723_qwen_fa_lora_summary.json`；
- 保存用户提供的三份原始 `metrics.json`；
- 新增安全入口 `scripts/training/finalize_qwen_fa_r2_manual.sh`；
- 新增入口安全性测试；
- 保存原始 Codex LoRA 执行计划与轻量 external-run summary。

## Current result

- R2 pilot：55.247 ms validation song-macro boundary MAE；
- R2 full final validation：46.634 ms；
- 程序 validation-best：step 1000，46.734 ms；
- full R2 M4Singer sealed test：79.590 ms；
- final full-R2 MIR-1K OOD：尚未执行；已有 OOD 为 pilot 结果。

## Evidence boundary

- pilot/full validation 数值来自用户贴出的服务器控制台；结构化 summary 明确记录该 provenance；
- sealed test 与 pilot OOD 使用用户提供的原始 metrics 文件；
- sealed-test metrics 未记录 checkpoint 身份，因此归档不补造该事实；
- watcher 曾创建 full sealed-test 目录并产生指标，但自动串联未完成 final full-R2 OOD；
- 本地只验证项目文件、脚本语法和不依赖外部资产的测试。

## Manual continuation

```bash
conda activate lyricalign-qwen
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```

## Local validation

- `bash -n scripts/training/finalize_qwen_fa_r2_manual.sh`：通过；
- `python -m compileall -q src scripts tests`：通过；
- LoRA finalizer/training/model/label/metric 相关 targeted tests：12 passed；
- 全量 pytest 在本地归档容器 collection 阶段因缺少可安装的 `pypinyin` 依赖而未完成；这不是服务器 Conda 环境的实验结果，也未被写成全套测试通过。
