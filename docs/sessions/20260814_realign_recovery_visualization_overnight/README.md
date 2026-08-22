# 2026-08-14 Unit Realign Recovery + Visualization Overnight Session

本 session 是 `20260813_unit_level_realign_overnight` 的直接下一轮。它不覆盖上一轮证据，而是在已完成的 unit-level realign 结果上继续回答两个问题：

1. 困难区是否能通过多次 realign、细粒度拆分、改变 audio observation 或组合机制真正恢复；
2. 当前 full-slot baseline 与旧 pre-slot B4 的真实 Demo 行为是否有肉眼可见的系统级进步，以及当前 realign 各机制的行为差异。

## 阅读顺序

1. `00_SESSION_DISCUSSION_RECORD.md`：本次用户会话的完整记录与决策过程；
2. `01_CURRENT_EXPERIMENT_RESULTS_AND_CONCLUSIONS.md`：当前 evidence 的可信结论、negative results 与结论边界；
3. `02_NEXT_ROUND_EXPERIMENT_DESIGN.md`：下一轮主实验，含原因、目的、设计、预期结果和结论映射；
4. `03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md`：B4 vs Current 双路与 Current 四路消融的实现/验收要求；
5. `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md`：GPU 预算、GT firewall、cache、失败恢复和挂机自由探索合同；
6. `05_CODEX_HANDOFF.md`：要求 Codex 先生成实现方案，再交 OpenCode/agent 执行；
7. `06_PLANNED_RUNS.yaml`：建议 run/session 名称与阶段顺序，作为声明式工作清单，不代表代码已经实现。

## 2026-08-15 追加：窗口输入/装配层架构讨论

`00_SESSION_DISCUSSION_RECORD.md` 第 9 节（执行期记录）与第 10 节（架构讨论）记录了 strict/compress 实现前转入的架构讨论
（分窗只决定 core、上下文是装配可选项、装配与推进做成层式双向、避免上下文成为推进方式的
笛卡尔积等）。该节同时包含讨论前的代码落地状态（window_planning.py 改动与自检结果）与
待续事项；本 session 后续实现顺序以该节为准。

## 当前冻结原则

- `actual_writeback = 0`，所有 realign 仍为 shadow/evaluator-only；
- 不把 fixed-point、multi-view consensus 或 context displacement 当作 correctness 充分条件；
- 不做完整笛卡尔积，先机制筛选，再对显著方向扩量；
- no-GT 运行代码不得读取 GT；GT 只在事后 evaluator join；
- shared forward/cache 必须按完整 request identity 复用，presentation rerender 不能重复 Qwen forward；
- GPU target <=10h，hard cap <=12h；达到 cap 后继续 CPU 分析、hard-case mining 与自由探索，不得因某条路线 negative result 自动停止；
- Test Demo 尽量自动收集客观数据，同时保留原曲声音 + timeline 视频供人工复核。
