
# Project Current

**Snapshot date:** 2026-07-22  
**Stage:** dataset processing and cleaning automation

## 当前定位

```text
known Mandarin lyrics + vocal-only singing audio
-> character-level timestamp dataset
-> automatic raw Qwen baseline
-> staged domain adaptation
-> frozen in-domain and OOD evaluation
```

## 已完成基础

### Qwen Forced Aligner

- model ID：`Qwen/Qwen3-ForcedAligner-0.6B-hf`
- resolved revision：`c07281df297b9905d24a508279258cccf987a064`
- Transformers source commit：`7ea2320c76117e6742364808a666ef6f2fb40a67`
- schema-v2 M4Singer smoke：5/5 success；
- 模型、配置、输入 hash、外部输出 hash、分阶段 runtime 均已记录；
- smoke 预览可见若干零时长字符，说明结构诊断仍需增加 near-zero/zero-duration 统计；
- raw smoke 无 GT，不构成准确率结论。

### M4Singer

- 外部只读资产已可访问；
- preparation 结果：20,896 items、193,666 character records；
- 6,051 条为 `review_required_auto_phoneme_grouping`；
- 14,845 条为 `review_required_group_count_mismatch`；
- 当前没有 accepted 训练子集；
- 下一步必须将 mismatch 拆成可解释 taxonomy，并实现 phoneme -> syllable -> character 映射和质量分层。

### MIR-1K

- 原始归档 MD5 与发布值一致；
- 110 首整曲和 1,000 条短片段均可读；
- 17 首人工字符级对齐整曲、2,035 字符已准备；
- 固定为 vocal-only OOD test-only；不用于训练、validation、规则选择或 checkpoint 选择。

### OpenCpop

- 尚未获取；
- 受官方授权/获取流程阻塞；
- 该外部阻塞不应阻止完成 M4Singer + MIR-1K 的所有自动化基础设施。

## 当前输入合同方向

正式主输入统一为 vocal-only：

```text
vocal_source_type = native_vocal | official_vocal_channel | model_separated_vocal
```

模型分离人声必须记录 separator 名称、版本/权重 hash、配置、输入输出 hash。原生人声与模型分离人声分别统计。

## 当前归档缺口

本轮源 ZIP 漏收：

```text
src/lyricalign/datasets/
scripts/datasets/
```

服务器上已有这些实现。当前包只能合并，不能覆盖服务器工作树。归档本地验证为 compile 通过、pytest 因上述模块缺失在 collection 阶段报 2 个错误；这不是服务器执行结论。

## 当前目标

本阶段必须形成：

1. 可解释的 M4Singer mismatch taxonomy；
2. `text_normalization_v1`；
3. `character_mapping_v1` 与高置信训练子集；
4. vocal audio contract 和可恢复规范化管线；
5. song-level split 与跨数据集泄漏审计；
6. synthetic-long 20/30/60/120 秒数据；
7. MIR-1K vocal-only OOD frozen manifest；
8. 自动 metric fixture、评测执行和 raw baseline；
9. 测试、运行证据、状态文档、Git commit/push 闭环。

## 推迟事项

- 同音同调随机字副实验：用于鲁棒性和低标准标注可接受性，不作为当前主清洗输入；
- projector/score 全量训练、audio tower LoRA、language model LoRA；
- 英文 word-level；
- OpenCpop 依赖的正式 in-domain test。
