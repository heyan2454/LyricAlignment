# Next Execution Plan: Finalize Full R2

**Date:** 2026-07-23  
**Goal:** close the first Qwen FA LoRA experiment without rerunning sealed test or using test/OOD for model selection.

## Stage F0：只读检查

```bash
cd /home/hyan/LyricAlignment
conda activate lyricalign-qwen
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
```

检查：

- full run、`best_checkpoint.json` 和 step 1000 checkpoint 完整；
- adapter/projector SHA-256 可读；
- sealed-test metrics 已存在；
- sealed-test checkpoint identity 是否有独立记录；
- final full-R2 OOD 目录是否不存在；
- pilot OOD 被明确识别为历史比较，不当作 final。

若 final OOD 路径已经存在但不完整，不得直接覆盖；先重命名为带 `failed_<timestamp>` 后再运行。

## Stage F1：运行缺失的 full R2 MIR-1K OOD

```bash
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
```

固定条件：

- checkpoint 来自 full run 的 `best_checkpoint.json`；
- 当前预期为 step 1000；
- split=`test`，usage=`ood_test_only`；
- MIR-1K labels/characters hash 必须匹配冻结身份；
- 输出先写临时目录，成功后原子改名；
- 输出目录：`20260723_qwen_fa_r2_full_mir1k_ood`；
- 不调用 M4Singer sealed test。

成功产物：

```text
metrics.json
predictions.jsonl
command.sh
stdout.log
stderr.log
return_code.txt
evaluation_identity.json
```

`evaluation_identity.json` 必须记录：

- model/revision；
- checkpoint path/step；
- adapter/projector/checkpoint identity SHA-256；
- best checkpoint JSON SHA-256；
- labels/characters SHA-256；
- split/use。

## Stage F2：汇总

```bash
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```

输出：

```text
/home/hyan/Data/lyricalign/runs/20260723_qwen_fa_r2_final_summary.json
```

检查 sealed test 与 final OOD 均存在，并确认 OOD identity 使用 step 1000。

## Stage F3：报告与 Git

- 将 final OOD 的轻量 `metrics.json`、`evaluation_identity.json` 和 final summary 加入项目归档；
- 不加入 predictions、checkpoint、音频或大日志；
- 更新 `reports/progress/20260723_qwen_fa_lora_results.md`；
- 更新当前 session record；
- 运行工程测试；
- 检查 Git branch/dirty/ahead 状态并 push。

## 不做

- 不重复 M4Singer sealed test；
- 不根据 sealed test 或 MIR-1K 在 step 1000/1110 间反选；
- 不继续追加 epoch；
- 不重调 R3；
- 不立即增加第二 seed；
- 不把 pilot OOD 改名为 final OOD。
