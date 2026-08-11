# 2026-08-12 Realign Recovery Research Session

本目录是下一轮 **Realign / Recovery 主线实验** 的新 session 文档目录。它独立于此前
`research_transition_recovery_detector_20260807`、`research_v7_align_behavior` 和
2026-08-10/11 real-GT/freeform 探索文档，不继续追加旧 session 编号。

## 本轮唯一主轴

在已经有成果的 **Raw detector** 基础上，研究：

1. 已经发生的严重对齐错误，在输入正确时是否本来就能被 realign 修复；
2. 没有 GT 时，系统如何为 realign 自动提供足够正确的音频范围和歌词范围；
3. realign 产生新结果后，Raw detector 是否能判断它真的变好、没变，还是变坏；
4. 通过安全写回，是否能把串行状态重新拉回正确轨道并阻断累计错误传播。

除 **realign** 与已冻结的 **Raw detector** 外，其他模型、align、window、silence、transition、
数据与 metric 行为继承既有 baseline，不重新展开消融。

## 阅读顺序

1. `00_SESSION_DISCUSSION_RECORD.md` — 本次会话完整讨论记录，尤其保留用户的意见、疑问和最终决定。
2. `01_CURRENT_RESULTS_AND_CONCLUSIONS.md` — 当前实验现象、可保留结论、不能继续引用的旧结论。
3. `02_FROZEN_BASELINE_AND_SCOPE.md` — 本轮冻结 baseline；什么能变、什么不能变。
4. `03_REALIGN_EXPERIMENT_PLAN.md` — 正式下一轮实验设计。
5. `04_EXECUTION_CONTRACT.md` — OpenCode/Agent 强制执行规则、缓存、恢复、GT 隔离、不中途停止。
6. `05_FREE_EXPLORATION_PROTOCOL.md` — 正式实验结束后的持续自由探索机制。
7. `06_DEFERRED_CORRECTION_ITEMS.md` — 已知但本轮允许延后修复的小问题。
8. `07_OPENCODE_IMPLEMENTATION_INDEX.md` — OpenCode 分批实现入口与运行根规则。
9. `08_PHASE0_BASELINE_GT_FIREWALL.md` — Phase 0 的 baseline mapping、real-GT 与 no-GT 防火墙。
10. `09_CORE_CONTRACTS_AND_RUNNER_WORKPACKAGES.md` — 数据契约、内容寻址 cache 与可恢复 runner。
11. `10_EXPERIMENT_EXECUTION_WORKPACKAGES.md` — E1--E10 的实际执行顺序和资源约束。
12. `11_VALIDATION_REPORTING_AND_HANDOFF.md` — 测试、review、报告与自由探索交接。

## 执行优先级

```text
P0 baseline mapping / real-GT / no-GT contract check
-> core contracts / runner CPU smoke
-> E1 exact-oracle repairability
-> E2 oracle range/text tolerance
-> E3 natural no-GT trajectories
-> E4 upstream single-point propagation
-> E5 no-GT audio/text proposal
-> E6 shared realign candidate bank
-> E7 detector judges realign quality
-> E8 writeback policy
-> E9 full serial closed loop
-> E10 selected fallback retry / recursive shrink
-> final report
-> if no user interruption: continuous free exploration loop
```

## 重要口径

- **Oracle 实验**：GT 可用于构造 oracle audio/text 输入和最后评分，但不能把字符 GT timestamp 直接交给 aligner。
- **No-GT 实验**：GT 只能在执行完成后评分；不得进入 detection、proposal、candidate ranking、retry、writeback、cursor 更新。
- **Raw 是主线**：Official 不再扩成全矩阵；若已有同-forward secondary view 可低成本保存，仅作参考。
- **不做笛卡尔积**：先用 oracle/小 pilot 筛掉无效维度，再扩大 candidate bank 和 closed-loop。
- **GPU 预算继承既有约束**：目标约 10 h、硬上限 12 h；挂机允许把预算用满。达到 GPU 上限后不得停止整个 session，应继续基于缓存做 CPU 分析和自由探索。
