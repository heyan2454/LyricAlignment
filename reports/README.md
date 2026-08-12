# Reports

人类可读报告目录，保存阶段进展、审查、调研、审计与叙事材料。reports 应消费
`results/`，不要反向成为 canonical metric source；原始 run 事实位于
`/home/hyan/Data/lyricalign/runs/` 与外部数据盘。

## 当前子目录

```text
reports/progress/    阶段计划、实验报告、数据治理报告与错误分析。
reports/review/      合作者文档、代码、环境与依赖审查。
reports/research/    已实际阅读与核验后的文献调研、方法路线与研究设计。
reports/audits/      数据/结果审计与修复记录。
reports/research_v6/ research_v6 detector/repair 阶段结果报告。
reports/research_transition_recovery_detector_20260807/  transition-recovery 探索 session 报告与证据登记。
reports/assets/      模型/数据资产来源、路径、revision 与跨项目复用审计。
reports/smoke/       非指标推理 smoke 摘要。
reports/resume/      基于真实完成工作的简历表达。
```

## 当前主要内容

| 文件 | 作用 |
|---|---|
| `reports/progress/20260723_qwen_fa_lora_results.md` | qwen_fa LoRA 结果 |
| `reports/progress/20260724_qwen_fa_overnight_overall_summary.md` | 过夜全量 run 总览 |
| `reports/progress/project_plan_7_10_days.md` | 7–10 天项目计划 |
| `reports/audits/20260722_m4singer_audit_v1.md` | M4Singer 数据审计 |
| `reports/audits/20260724_qwen_fa_long_b180_outlier_audit.md` | long b180 outlier 审计 |
| `reports/research_v6/20260801_e9_lazy_compact_v8_formal.md` | E9 lazy-compact v8 formal 结果 |
| `reports/research_transition_recovery_detector_20260807/` | transition-recovery 探索 session 报告、negative results、transition map |
| `reports/review/` | 各阶段 archive/包/环境/依赖审查 |
| `reports/assets/` | 资产清单与 AST 数据集复用审计 |

## 数据边界

- 生成资产（`.pdf/.pptx/.docx`）不进 git（见 `.gitignore`）。
- 大型逐样本输出、模型响应、evidence pack 位于数据目录
  `/home/hyan/Data/lyricalign/runs/<run>/...`；reports 只登记路径与索引。
- md/json 源文件保留在 git。
