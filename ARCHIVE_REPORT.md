
# Archive Report: Dataset Cleaning Execution Handoff

**Archive date:** 2026-07-22  
**Output archive:** `LyricAlignment_20260722_dataset_cleaning_execution_archive.zip`  
**Stable extracted root:** `LyricAlignment/`  
**Source:** `LyricAlignment_202607211613_datasetok.zip`

## Purpose

将已完成的 schema-v2 smoke、M4Singer preparation、MIR-1K OOD 准备和当前 review，归档为下一阶段可直接交给 Codex 的数据清洗自动化执行包。当前包冻结逐阶段硬 gate、vocal-only 输入原则、长音频口径、自动 metric/raw baseline 和 Git/证据闭环要求。

## Key updates

- 状态从“server smoke pending”更新为“dataset cleaning automation”；
- 记录 5/5 M4Singer schema-v2 smoke、Transformers commit 和零时长诊断缺口；
- 记录 M4Singer 20,896 items、6,051 自动候选与 14,845 mismatch；
- 记录 MIR-1K 17 首/2,035 字符 vocal-only OOD test-only；
- 主输入冻结为原生/官方/模型分离 vocal-only，并要求 separator identity；
- 建立 Stage 0–11 自动化执行合同和 Gate S0–S11；
- 同音伪歌词推迟为鲁棒性/低标准标注副实验；
- 增加直接可交给 Codex 的完整执行 prompt；
- 更新 AI 协作、negative results、依赖与 session 温度。

## Important merge constraint

源 ZIP 漏收服务器已有的：

```text
src/lyricalign/datasets/
scripts/datasets/
```

本归档不得覆盖式替换服务器仓库。Codex 必须保留服务器实现、合并文档、先完成 Stage S0，然后在下一次完整归档中纳入这些文件。

## Local validation

- `python -m compileall -q src scripts tests`: passed
- `python -m pytest -q`: collection failed with two missing `lyricalign.datasets` module errors caused by the source ZIP omission

没有伪造 `10 passed` 或服务器测试事实。完整测试结果留给服务器 Stage S0。

## Scope intentionally not executed during archive

- 未修改或伪造服务器数据集实现；
- 未运行 M4Singer 全量清洗；
- 未生成 synthetic-long；
- 未执行 metric/raw baseline；
- 未启动 LoRA/training；
- 未绕过 OpenCpop 授权。

## Next entry

`docs/sessions/20260722_codex_dataset_cleaning_prompt.md`
