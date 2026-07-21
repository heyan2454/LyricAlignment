
# Current Work Review: Dataset-Cleaning Transition

**Date:** 2026-07-22

## 结论

研究进度已从“smoke 基础设施待执行”进入“数据处理与清洗自动化”。Qwen schema-v2 smoke、M4Singer 元数据准备和 MIR-1K OOD 资产均已有执行证据。当前主要风险不再是模型能否调用，而是字符映射可靠性、数据来源一致性、长音频口径、自动评测和归档完整性。

## 高优先级问题

1. 源归档漏收 `src/lyricalign/datasets/` 与 `scripts/datasets/`，导致本地 pytest collection 报错；服务器有实现，应修复打包规则而不是重写/删除服务器代码。
2. M4Singer 14,845/20,896 items 为 group-count mismatch，尚未形成可解释 taxonomy。
3. 当前没有 accepted 高置信训练子集，不能进入 LoRA。
4. vocal-only 来源合同尚未冻结；原生人声、官方声道和模型分离人声需明确区分。
5. song-level split、synthetic-long、自动 metric 和 raw baseline 尚未闭环。
6. smoke 输出存在零时长字符，但诊断未触发 warning。

## 决策

- 下一步由 Codex 完成所有可自动化的数据处理阶段，每阶段设硬 gate；
- 主评测音频使用分离/独立人声；
- 同音伪歌词推迟为鲁棒性和低标准标注副实验；
- OpenCpop 外部授权阻塞不应成为停止 M4Singer/MIR-1K 主线的理由；
- 自动化闭环完成前不启动 LoRA。
