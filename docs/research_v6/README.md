# Alignment Research v6

阅读顺序：

1. `01_DECISIONS_ACCEPT_PENDING_REJECT.md`：全部想法及取舍；
2. `02_COMPLETE_EXPERIMENT_DESIGN.md`：E0–E9 完整设计；
3. `03_PIPELINE_ARCHITECTURE_AND_IMPLEMENTATION.md`：主流程抽象与实现对照；
4. `04_RUNBOOK.md`：smoke、全量、tmux、resume 和证据收集；
5. `05_IMPLEMENTATION_HANDOFF.md`：实现过程、依赖和限制；
6. `06_CORRECTNESS_FIXES_20260731.md`：formal-blocking 问题的代码、指标和验证修复；
7. `07_E8_E9_AND_BEST_EFFORT_FREEZE_FIXES_20260731.md`：二次 review 后的 E5/E8/E9、汇总、96-unit 与降级冻结修复。

主入口：

```bash
scripts/research/run_research_v6_smoke.sh
scripts/research/run_research_v6_formal.sh
scripts/research/start_research_v6_detached.sh formal --resume
```

## 2026-08-03 Transition to research v7

Research v6 formal E0–E9 has moved into conclusion repair and archival. The active next-stage documents are:

```text
../research_v7_align_behavior/README.md
../research_v7_align_behavior/00_EXECUTION_PLAN.md
../research_v7_align_behavior/01_USER_DECISIONS_AND_RATIONALE.md
```

The v7 direction does not continue tuning E3/E5/E6/E9. It first repairs E1/E5/E6 reporting and then studies production-like invalid-input alignment behaviour, strict serial short-text, sparse timestamp slots, posterior evidence and no-match cases.
