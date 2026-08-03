# Alignment Research v7：输入合法性与行为图谱

本目录记录从 research v6 正式 E0–E9 之后形成的新研究阶段。当前主线不再是继续调旧 detector、dynamic boundary 或 silence cap，而是：

1. 修复并冻结旧实验结论；
2. 系统研究 Aligner 在生产型合法、部分合法、不合法和多解输入下的行为；
3. 建立可重放的 Request / Attempt / Evidence 数据；
4. 从 posterior、official repair trace、多 request 稳定性和辅助音频信号中寻找危险区证据；
5. 再决定是否训练 QualityAssessor、开发 posterior-aware decoder 或引入 coarse localization；
6. 最终将 realign 改造成可接受、可回滚、允许 unresolved 的有界流程。

## 阅读顺序

1. `00_EXECUTION_PLAN.md`：可直接交给 agent 的完整执行计划；
2. `01_USER_DECISIONS_AND_RATIONALE.md`：用户意见、质疑、取舍和最终决定；
3. `02_PROJECT_RESEARCH_LEDGER.md`：整个项目的主要实验、猜想、结果和去留；
4. `03_QWEN_TECHNICAL_REPORT_IMPLICATIONS.md`：Qwen 技术报告对本项目的具体影响；
5. `04_ARCHITECTURE_OPTIONS_AND_CURRENT_DIRECTION.md`：D1–D8 架构评价与最小新架构；
6. `05_MUTATION_AND_NO_MATCH_SPEC.md`：百分比文本扰动、完全不对应文本和 donor 规则；
7. `06_HISTORICAL_REPAIR_SCOPE.md`：E1/E5/E6/条件分母的历史修复边界；
8. `07_DEMO_AND_COLLABORATOR_SHARE_PREPARATION.md`：阶段性 Demo 与环境包准备；
9. `08_AGENT_HANDOFF.md`：执行顺序、完成门槛和禁止事项。

## 当前冻结判断

- E1 event-level 必须按 item 重算；
- E5、E6 只做同子集 paired 重算和负结果归档，不继续扫参数；
- E3 decoder-only local repair 停止；
- E2 旧 detector 评价退役，扰动基础设施转为 alignment behaviour 研究；
- 旧 E4 只保留为 oracle/localized upper bound；
- 新 E4 必须包含同一长音频下的严格串行短文本和 sparse-slot 路线；
- 旧 detector 暂不自动写回；
- 无 GT Demo 要成为结构化真实行为数据，而不只是视频；
- GT MAE 仍保留，但不再单独决定研究路线。
