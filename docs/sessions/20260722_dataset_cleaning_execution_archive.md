
# 数据清洗自动化执行归档

**Date:** 2026-07-22  
**Status:** archived execution handoff  
**Scope:** 当前工作 review、数据清洗路线冻结、Codex 分阶段执行合同

## 本轮确认

1. 服务器工作树中已有 M4Singer/MIR-1K 数据集模块与准备脚本；当前 ZIP 缺失是归档收集问题，不是实现不存在。
2. 下一阶段进入数据集处理和清理，不立刻训练。
3. 主输入统一使用分离/独立人声音频：原生人声、官方 vocal channel 或固定模型分离 stem。
4. 同音随机字保持读音的方案有研究价值，但推迟为后续鲁棒性/低标准标注副实验，不进入当前主清洗流程。
5. metric fixture、评测和 raw baseline 应自动化，不依赖每次人工执行。
6. Codex 应完成所有不依赖外部授权的自动内容；每阶段必须有明确标准，不得因局部困难中断整个任务。

## 当前证据

- Qwen schema-v2 M4Singer smoke：5/5 success；
- Transformers commit：`7ea2320c76117e6742364808a666ef6f2fb40a67`；
- M4Singer：20,896 items、193,666 character records；
- M4Singer mapping：6,051 自动候选、14,845 group-count mismatch；
- MIR-1K：原始集校验完成，17 首/2,035 字符人工对齐 OOD test-only。

## Negative results / 未解决问题

- 当前归档本地 pytest 在 collection 阶段报 2 个 `lyricalign.datasets` 缺失错误；原因是 ZIP 漏收服务器代码。
- M4Singer 当前 accepted=0，不能描述为可训练字符数据集已完成。
- 短 smoke 预览存在零时长字符；现有诊断未标记。
- OpenCpop 尚未获取，in-domain official test 仍缺失。
- 尚无 song split、synthetic-long、自动 metric 或 raw baseline。

## AI 协作与依赖状态

- GPT：负责 review、执行合同、状态/manual/session 和归档一致性；
- Codex：在服务器实际实现、测试、运行、修复、提交与推送；
- 用户：仅需处理外部授权、无法自动获取的数据资产和必要的少量人工抽检；
- 不应把大量人工标注设为当前前置条件；自动规则先形成高置信子集与分层抽检包。

## 下一入口

`docs/sessions/20260722_codex_dataset_cleaning_prompt.md`
