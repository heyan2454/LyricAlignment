# 2026-08-12 Detector Production Audit & Realign Gate Session

本 session 是 `20260812_realign_recovery_research` 的后续研究入口。

本轮不重新展开模型、decoder、slot/serial、transition、silence planner 等旧大轴；沿用已经冻结的 production baseline。研究范围收缩为两条：

1. **Detector production audit**：核实当前 Raw detector 在接近生产的数据分布中是否仍保持较高 safe accept，而不是像上一轮 recovery cohort 中几乎全报；同时自动利用当前全部 Test Demo 做无 GT 产品行为检查。
2. **Realign behavior / gate**：以较小但比 5+5 更广的 song coverage，研究 realign 在正确、错误、detector false-positive 等不同起点上的行为，直接在机器上寻找可用于 no-GT writeback gate 的信号。

## 文件

- `00_SESSION_DISCUSSION_RECORD.md`：本次 review 后的完整讨论过程；用户意见与疑问按时间顺序忠实记录。
- `01_REVIEWED_RESULTS_AND_CORRECTIONS.md`：对上一轮 evidence 的审计结论、已纠正口径、当前可成立与不可成立的结论。
- `02_NEXT_ROUND_EXPERIMENT_PLAN.md`：下一轮实验原因、目的、设计、预期结果、可说明的结论、指标、规模与停止规则。
- `03_CODEX_HANDOFF.md`：给 Codex 合并与后续实现规划的边界、必须核实项和交付要求。

## 与上一 session 的关系

必须优先参考：

- `docs/sessions/20260812_realign_recovery_research/02_FROZEN_BASELINE_AND_SCOPE.md`
- `docs/sessions/20260812_realign_recovery_research/03_REALIGN_EXPERIMENT_PLAN.md`
- `docs/sessions/20260812_realign_recovery_research/04_EXECUTION_CONTRACT.md`

但上一轮 `FINAL_REPORT` 中与 E8/E9、repair threshold 有关的强结论，必须以本 session 的审计修正为准。
