# Alignment Research v7：输入合法性与行为图谱

本目录记录从 research v6 正式 E0–E9 之后形成的新研究阶段。当前主线是修复旧结论、研究生产型合法/不合法输入、建立可重放 evidence，并进一步研究 60 秒窗口上的 slot/串行混合与子区间判别器。

## 当前阅读顺序

1. `13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md`：**当前冻结的下一阶段实验计划**；
2. `14_AGENT_EXECUTION_CONTRACT_12H.md`：当前 agent 执行合同；
3. `15_LONG_SLOT_REGION_ASSESSOR_IMPLEMENTATION_BLUEPRINT.md`：交给实现 agent 的文件级实现蓝图、JSON 契约、测试与 gate；
4. `../sessions/20260804_align_behavior_slot_region_assessor_archive.md`：用户评论、结果解释与设计演化；
5. `11_STAGE_B_FORMAL_REPORT.md`：当前 Stage B 自动实验结果真值；
6. `12_COMPLETION_AUDIT.md`：当前完成状态、不可验证项与人工结果导入缺口；
7. `01_USER_DECISIONS_AND_RATIONALE.md`：此前用户意见与取舍；
8. `02_PROJECT_RESEARCH_LEDGER.md`：项目主要实验、猜想、结果和去留；
9. `03_QWEN_TECHNICAL_REPORT_IMPLICATIONS.md`、`04_ARCHITECTURE_OPTIONS_AND_CURRENT_DIRECTION.md`：技术背景与架构路线；
10. `05_MUTATION_AND_NO_MATCH_SPEC.md`、`06_HISTORICAL_REPAIR_SCOPE.md`、`07_DEMO_AND_COLLABORATOR_SHARE_PREPARATION.md`：专题规范；
11. `08_AGENT_HANDOFF.md`：上一阶段 handoff，仅供历史实现对照。

## 文档状态

| 文件 | 当前状态 |
|---|---|
| `00_EXECUTION_PLAN.md` | 历史原始计划；不再作为当前 agent 入口 |
| `08_AGENT_HANDOFF.md` | 上一阶段执行合同；已被 `14` 取代 |
| `09_STAGE_A_REPAIR_REPORT.md` | 历史阶段报告；E5 已更正为“现有 artifact 不可验证” |
| `10_STAGE_B_PROGRESS.md` | 历史进度报告；P1 和人工标签状态已更正 |
| `11_STAGE_B_FORMAL_REPORT.md` | 当前 Stage B 自动结果口径 |
| `12_COMPLETION_AUDIT.md` | 当前完成状态与可声明边界 |
| `13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md` | 当前冻结实验计划 |
| `14_AGENT_EXECUTION_CONTRACT_12H.md` | 当前 agent 执行入口 |
| `15_LONG_SLOT_REGION_ASSESSOR_IMPLEMENTATION_BLUEPRINT.md` | 当前实现 agent 的工程交接入口；不包含 formal 结论 |

## 当前冻结判断

- E1 event-level 已按 item 修复；
- E5 当前 artifact 缺真正 fixed baseline，不可验证，不写成已证明负结果；
- E6 时间压缩负结果保留；
- E3 decoder-only local repair 停止；
- 旧 detector 暂不自动写回；
- raw、official、hidden 分开诊断，本阶段不急于冻结最终生产 commit；
- 人工 review 结果与标签已经存在，但当前 archive 尚未正确导入和审计；
- M4 native-short、M4 synthetic-long、MIR natural-song 和 demo 分开汇报。

## 2026-08-04 补充冻结计划

- ≥90 秒、以 ≥180 秒为主体的是**数据时间线**，主 acoustic request 仍为 fixed 60s；
- 禁止强塞静音凑长数据；仅做少量 0.5 秒 seam-silence 对照；
- slot 与串行不是互斥路线，机制消融与系统配置比较分开；
- slot density 主比较固定 common units，并轮换 stride phase；
- extra/missing/replace 同时保留 1/2/4/8 units 与百分比曲线；
- missing 使用 virtual gap 评价，replace 同时评价 wrong-output 与 omitted-original；
- 判别器报告 unit recall、interval recall@75%、interval recall@100% 和 correct-unit FPR；
- hidden extraction 先冻结 token/row/layer 映射和数值等价契约；
- 增加 M4→MIR、leave-one-family-out 等跨域评价；
- 弱人声校准作为第一批并行工作尽早交付；
- formal 目标 10 小时，硬上限 12 小时；使用严格 matched baseline 和内容寻址缓存；禁止全笛卡尔积。
