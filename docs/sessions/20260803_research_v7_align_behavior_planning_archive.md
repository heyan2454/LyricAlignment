# 2026-08-03 Research v7 Alignment Behaviour 规划与讨论归档

## 0. 文档角色

本文记录从 research v6 formal 结果审查、E0–E9 结论修正、DS 架构探索、Qwen 技术报告查阅，到 research v7 行为研究计划形成的全过程。重点保留用户质疑、评论、取舍和最终决定，而不是只列最终方案。

## 1. 起点：formal 结果审查

审查确认 21,562 个 item 的 E0–E9 已完成，但运行完整性不代表方向成立：

- E1 detector 极弱；
- E5 动态边界、E6 静音处理和 E8 自动 realign 表现差；
- E4 3×32 是最明确正结果，但同时使用了局部短音频；
- E1 event 聚合存在跨 item bug；
- E5/E6 主表子集不公平；
- 条件指标分母不透明。

## 2. 用户对旧实验的处理意见

用户要求：

- E1 event 修；
- E5/E6 简单 paired 重算；
- 条件分母补齐；
- E3 若只换 decoder 不重推理则放弃；
- 不要为了旧计划完整而修没有研究价值的实验；
- decoder 要结合 test demo，并警惕 pilot/GT 过拟合；
- detector 先研究异常性质和可学习信号；
- realign 可能必要，但当前设计不安全。

最终决定是“修可信度，不救旧方向”。

## 3. E4 的关键纠正

用户明确指出，想要的不是 GT/localized 3×32，而是：

```text
同一个 production 长音频
一次给全部正确文本
vs
严格按生产 cursor/commit 少量多次给短文本
```

必须观察前一次是否吞字、重复和污染后续。非串行短文本只作诊断。

Qwen 报告进一步引出 sparse slots：保留歌词前缀，只对当前 chunk 插 timestamp slots。该路线加入新 E4。

## 4. 对 GT 和无 GT 的判断

用户认为当前分析过多依赖 GT MAE，容易过拟合。无 GT 完整歌曲更接近真实生产，应形成结构化数据，而不是只看视频。

因此建立 demo_dev/validation/heldout/challenge、Request lineage、EvidencePack、多路线一致性、辅助音频信号和人工 span 评论。

## 5. 对 detector 的新理解

用户提出 detector 与 realign 可以是两个循环模块，detector 主要评价质量和 safe/danger 区间，realign 后再判断是否接受。无需提前证明候选最优。

最终结构支持 safe/danger/unknown 和 acceptance；repairability predictor 降为可选效率模块。

## 6. DS 架构意见

用户逐项评价：

- D1 未来可作基线；
- D2 Request 可重放有价值但要简单；
- D3 EvidencePack 适合作为 cache/分析；
- D4 暂不做复杂状态机；
- D5 不作长期主架构；
- D6 思想保留，旧 E9 无可靠结论；
- D7 避免复杂人工规则，重视学习与 OOD；
- D8 是总结性 contract-first 原则。

## 7. Qwen 报告带来的变化

- ForcedAligner 是 Qwen3 Transformer 上的 timestamp slot filling；
- 每个 slot 被迫选择时间，公开设计没有 no-match；
- causal attention 使尾部文字对前部 raw 影响有限，但 official 修复和 serial cursor 可传播；
- dynamic slots 支持 sparse-slot 实验；
- 官方 300 秒实验是完整 correspondence，不回答 production mismatch；
- official decoder 简单，posterior-aware decoder 有空间；
- ASR 与 aligner 是独立发布模型，近期不假设只加小 head。

## 8. 文本严重度修正

用户指出 `+2/+5/+16` 对 60 秒窗口太保守，要求至少采用百分比。最终冻结建议：

- extra +10/+25/+50/+100/+200%；
- missing 10/25/50/75/90%；
- replacement/no-match 10/25/50/75/100%。

## 9. 完全不对应文本实现

用户要求明确 no-match 如何构造。最终主实现：同语言、同 unit mode、同长度、跨歌曲连续真实歌词，并用 LCS、连续匹配、n-gram 和可用 phonetic similarity 过滤偶然对应，pilot 后冻结 donor manifest。

同歌错段、重复副歌、纯器乐区、行序错和随机文本分别处理。

## 10. 新主线

1. 历史结论修复；
2. strict serial / sparse-slot 新 E4；
3. production-like extra/missing/replacement/no-match behaviour atlas；
4. posterior、official repair trace、request sensitivity；
5. 无 GT 结构化数据；
6. 再决定 QualityAssessor、decoder、coarse localization 和 transactional realign。

## 11. 当前主要 negative results

- 旧 detector 不能自动控制；
- E3 停止；
- E5/E6 不继续扫参；
- 旧 E7 reset 不完整；
- 旧 E9 不能证明 request pool 无效；
- GT-localized 3×32 不能证明 production 少量多次。

## 12. 后续交付

本 session 形成 `docs/research_v7_align_behavior` 文档组和 agent 执行计划。当前 patch 仅整理文档与配置规范，不修改实验代码；后续 agent 应在原包上按 overlay 方式实现。
