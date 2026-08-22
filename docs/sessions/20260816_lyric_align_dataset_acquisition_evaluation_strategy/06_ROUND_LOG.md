# Round Log — 2026-08-16 产品化验证

> 记录每轮主要动作与产物。详细技术报告见 `03_PRODUCTIZATION_EVALUATION_V1_NEXT_STEPS.md`、`04_PRODUCTIZATION_RUNBOOK.md`、`05_NEXT_ACTIONS.md` 和 `reports/`。

| Round | 主要进展 |
|---|---|
| 1 | 阅读 session/Codex 指导；设计 Evaluation V1 split 方案 |
| 2 | 实现 split manifest builder；生成 draft split、cleanup report |
| 3 | 完成 GTSinger 全量 diagnostic 75 段 R0/R1/R2；生成 aggregate |
| 4 | MIR raw mixture 30s smoke；GTSinger hard-case 子清单；PJS manifest |
| 5 | PJS 日语 smoke；MIR raw smoke 记录；runbook 雏形 |
| 6 | Sealed runner `guarded_run.py`；PJS 5 段 batch |
| 7 | 产品化 Runbook 完善；quality check 脚本 |
| 8 | 首个 hard-case 消融：compress/strict/skip 无变化 |
| 9 | quality check 自动化；cleanup audit |
| 10 | 第三个消融 skip-silent；三消融汇总 |
| 11 | canonical ablation summary |
| 12 | guarded_run CLI 自动化测试 |
| 13 | Milestone 清单；quality check ALL_OK |
| 14 | Behavior registry 更新 |
| 15 | raw decoder 3 hard cases 出现正向信号 |
| 16 | raw decoder 全量 diagnostic 验证（90.05%->91.84%） |
| 17 | raw decoder 回退段分析 |
| 18 | PJS raw decoder 5 段对比 |
| 19 | Behavior registry 增加 decoder.raw_vs_official |
| 20 | 产品化建议文档 |
| 21 | PJS rawdecoder canonical summary |
| 22 | Runbook 增加 raw decoder 命令 |
| 23 | 新增 compare 脚本 |
| 24 | 产品化状态总览 JSON |
| 25 | 综合审查 review8 |
| 26 | GTSinger regression rawdec smoke 5 段 |
| 27 | GTSinger regression rawdec 全量 84 段（89.49%） |
| 28 | GTSinger regression official 全量 84 段；对比 rawdec 更优 |
| 29 | 产品化建议更新；milestone 更新 |
| 30 | Sealed milestone 显式开启验证 |
| 31 | Sealed milestone 自动化测试 |
| 32 | 产品化最终摘要 |
| 33 | 新增 regression rawdec 复现脚本 |
| 34 | Regression quality warning 对比 |
| 35 | 最终摘要补充 warning 观察 |
| 36 | 外部产物索引 |
| 37 | 数据登记更新 |
| 38 | Next Actions 清单 |
| 39 | MIR vocal 分离 smoke 成功 |
| 40 | MIR vocal separation canonical 结果 |
| 41 | Runbook 增加 MIR 分离命令；MIR rawdec vocal smoke 完成 |
| 42 | 2026-08-21 核查：window 三消融样本均为 7–9s 单窗口短片段，机制未被激活 → 报告/建议文档补 inconclusive 口径（非"机制无效"） |
| 43 | 2026-08-21 漂移修复（最小版）：`AI_SESSION_ENTRY.md` 顶部补 2026-08-16 指路 entry；`AGENTS.md` 指针注明"以 entry 最新段为准、与 0814 关系不作裁定" |
| 44 | 2026-08-21 数据核查：GTSinger 中文原库仅 10 首（2 歌手×5 技巧），所选 5 首=技巧各一；诊断组 75 段=《倒带》单曲，需显式单歌边界；MIR-MLPop 音频 20/30（缺 10：403/geo/视频失效）、yue 3/5 |
| 45 | 2026-08-21 GTSinger 全曲拼接可行性研究：25 段=全曲连续切分（歌词逐句连续、wav 时长==TextGrid xmax、段内 `<AP>` 呼吸经 RMS 证实保留、25 段合计 200.4s≈全曲、无伴奏清唱）→ 可按段序 concat 还原全曲，接缝审计与 GT 重建待 pilot |

## 说明
- 每轮都有最终回复摘要；关键产物均有 `cleanup_report.md` 或报告文件。
- 不是每一轮都单独建立 markdown，但关键信息已沉淀到 session/reports/results 中。
