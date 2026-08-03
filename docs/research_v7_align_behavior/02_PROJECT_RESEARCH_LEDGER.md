# 项目研究总账（压缩版）

本文汇总项目主要实验、猜想、目的、结果、结论和当前去留。详细实现仍以 research_v6 和各 session 文档为准。

| 方向 | 目的 | 主要结果 | 当前结论/去留 |
|---|---|---|---|
| M4Singer 清洗 | 建立字符级歌唱 GT | 形成 manifest、规则分层；大量复杂连音需谨慎 | 保留，严格区分 validated/candidate |
| MIR-1K OOD | 测试非 M4Singer 泛化 | R2 可用但样本有限 | 保留 OOD |
| R0/R1/R2/R3 LoRA | 找歌唱域适配位置 | R2 audio tower 上半层 + projector 最好；R3 无增益 | R2 为当前模型基线 |
| Vocal separation | 降低伴奏干扰 | Demucs vocal 通常优于 mix；伴唱残差仍有问题 | 保留，加入 robustness 变量 |
| Raw decoder | 看原始模型证据 | 逆序、零时长、挤压 | 研究证据，不作输出 |
| Official decoder | 稳定单调输出 | 明显优于 raw，但规则简单，会吸附/插值 | 当前展示基线，继续改进 |
| Top-K / weighted | 利用更多候选 | 不同数据和长短序列最优不同 | 不存在统一最优，保留候选 |
| 绝对位置/240s | 测长音频位置稳定性 | 特定位置出现波动/坍塌，不是单调随长度下降 | 保留为长程现象，待 correspondence 分解 |
| 30/60s 窗口 | 平衡局部能力和串行成本 | 用户 Demo 观察 60s 较稳；30s 窗多传播风险 | fixed 60s 当前 baseline |
| Stable anchor | 找安全提交/重跑边界 | 内部稳定不等于绝对正确，覆盖有限 | 只作证据，不直接控制 planner |
| Future text/dosage | 测多给文本影响 | 曾出现长尾扰动，提示冗余文本危险 | 升级为百分比行为曲线 |
| E0 | 正式 decoder 对比 | all/nontraining/M4/synthetic-long 最优不同 | 场景依赖，避免 pilot 过拟合 |
| E1 | detector | unit F1 极低；event 聚合有 bug | 旧 detector 停止，event 重算 |
| E2 | 扰动 + detector | clean 误触发与整体平移漏检并存 | detector 结论退役，mutation 保留 |
| E3 | 局部 decoder repair | 没有 paired baseline，且问题不匹配 | 停止 |
| E4-old | 1×96 vs 3×32 | 局部音频+短文本明显更好 | 只作 oracle/localized 上限 |
| E5 | 动态安全边界 | 秒级恶化，seam 远近都差 | 同子集重算后负结果归档 |
| E6 | 静音压缩/边界 | cursor 和静音前后显著恶化 | 同子集重算后负结果归档 |
| E7 | 串行状态注入 | core boundary 影响大；reset 不完整 | 排除单一 cursor 简化，待事务状态重做 |
| E8 | rerun realign | harm > improve，clean harm 高；continuation 框架可用 | 保留 rerun，废弃当前选择器 |
| E9 | request/beam | 候选和评分弱，结果不可靠 | 不能否定有界 pool，暂停 |
| DS D1–D8 | 探索 align/detect 解耦 | 明确 request、evidence、controller、score 维度 | 组合为最小 contract-first 架构 |
| 结构探针 | 找 detector 盲区 | 局部结构检测不到整体自洽错误 | correspondence 必须引入外部/多视图证据 |
| Qwen 技术报告 | 理解模型边界 | slot-filling、因果 LLM、dynamic slots、无 no-match 公开机制 | sparse slots、posterior、repair trace 成为重点 |
| 无 GT Demo | 真实完整歌曲评价 | 更接近产品，但反复查看会变 dev | 建 EvidencePack、人工 span 和 heldout |

## 当前最高价值积累

1. 模型在严格 correspondence 下基础能力较强；
2. 输入范围与文本匹配性可能比 decoder 更关键；
3. 错误输入也会被迫得到时间，可能内部自洽；
4. 旧 detector 的局部几何不足以判断 correctness；
5. 少量多次只有在严格生产 workflow 中才有意义；
6. posterior、repair trace、request sensitivity 和辅助 correspondence 是下一代质量证据；
7. realign 必须 acceptance-gated、可回滚并允许 unresolved。

## 当前停止投入

- E3；
- 旧 logistic detector 阈值调优；
- E5 参数继续扫描；
- E6 cap 继续扫描；
- 在旧 score 上扩大 E9；
- 以 train-heavy 总体 MAE 选择路线；
- 过早建设复杂状态机；
- 大量人工规则 detector。
