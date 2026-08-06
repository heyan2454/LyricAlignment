# Full-slot 串行 Detector 与恢复研究

本目录是一个**独立于 `research_v7_align_behavior` 编号链**的新阶段。它不继续扩展 v7 文档编号，以免旧证据审计、Detector V2 修复与新串行系统实验混在同一长链中。

## 研究入口

1. `01_EXPERIMENT_PLAN.md`：下一阶段冻结实验计划，包含问题、目的、设计、指标、预期结果及结论边界；
2. `02_B4_60_SILENCE_OFFICIAL_SHADOW_V1.md`：历史 B4 对照的冻结定义与 shadow-only 约束；
3. `03_AGENT_IMPLEMENTATION_PLAN.md`：面向实现 agent 的模块、状态机、阶段、测试与预算方案；
4. `../../configs/research_fullslot_serial_detector/b4_60_silence_official_shadow_v1.yaml`：声明式 profile；实现 agent 接线前不得声称它已经可直接执行；
5. `../sessions/20260806_fullslot_serial_detector_discussion_record.md`：本轮完整讨论、用户反馈、修正过程与最终决定。

## 与 v7 的关系

v7 仍是上游证据和问题来源，尤其包括：

- Detector V2 的标签、raw/official 信号、M4 heldout、M4→MIR、stress 与 serial 证据；
- 标签覆盖差异、Family-LOO 报告串列、stress evaluator 模型不一致、serial 部分提交传播漏记、跨 request light merge、伪 extra request 等待修复项；
- hidden 提取被 fail-closed block 的历史原因。

本阶段不重跑旧 detector，也不继续把旧 detector 纳入比较。引用 v7 时应优先使用当前 authoritative JSON/evidence；若工作目录中缺少 v7 的 18–22 号文档，应先从对应 evidence pack 恢复，不得凭旧 README 中的摘要代替原始结果。

## 当前冻结方向

```text
冻结 Qwen forced aligner
+ full slot
+ 左 10s / core 60s / 右 10s
+ 静音吸附、跳过纯静音窗、短尾窗重分配
+ raw/official decoder 先保留，decoder 消融独立运行
+ stable-window serial
+ 整窗否决回退 W / 子区间局部重对齐 L 两种一致 route
+ raw、hidden 及各自 sequence-derived 特征
+ SA60、R95 必做；联合不可行时分别完成
+ M4 / MIR / 构造数据 / 全量 test demo 分开汇报
```

## 不在本阶段主线中的内容

- 旧 detector 新实验；
- sparse/overlap slot 的全量矩阵；
- 歌词与歌曲不正确对应的重复鲁棒性主实验；
- official 作为 detector 独立特征家族；
- 全序列高成本 Top-K DP；
- decoder、route、阈值、错误 family 的笛卡尔积。
