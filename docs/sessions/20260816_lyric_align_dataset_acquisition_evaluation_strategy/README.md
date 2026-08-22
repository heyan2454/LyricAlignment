# 2026-08-16 Lyric Align 数据获取与无训练评测策略 Session

本 session 记录用户从“当前 Lyric Align 模式/行为很多，但缺少好坏依据”的困惑出发，转向数据资产补充、实际获取，以及暂不训练新模型时的评测与机制研究策略。

本轮跨 2026-08-15 至 2026-08-16（UTC）。大型数据仍位于外部数据盘；仓库只保存轻量会话、登记和资产摘要。

## 阅读顺序

1. `00_SESSION_DISCUSSION_RECORD.md`：按时间顺序记录用户问题、决定、实际执行和讨论结论；
2. `01_DATA_ACQUISITION_RESULT.md`：本轮已取得、部分取得和受限数据的冻结快照；
3. `02_EVALUATION_V1_NO_TRAINING_PLAN.md`：2:5:3 暴露策略、分数据集建议和旧模型研究路线；
4. `03_PRODUCTIZATION_EVALUATION_V1_NEXT_STEPS.md`：产品化研究入口、draft split 结果与下一步 gate。
5. `04_PRODUCTIZATION_RUNBOOK.md`：可复现命令与产物清理说明。
6. `05_NEXT_ACTIONS.md`：下一步优先行动清单。
7. `06_ROUND_LOG.md`：逐轮进展记录。

长期资产状态以以下稳定文档为准：

- `data/datasets_registry.md`
- `reports/assets/asset_inventory.md`
- `/home/hyan/Data/datasets/<dataset_id>/{README.md,SOURCE.md,TERMS.md,acquisition.json,checksums.sha256}`

## 本轮用户已经明确的方向

- 讨论对象是 Lyric Align，而不是一般模型行为；
- 当前数据对复杂机制组合的证据支撑不足；
- 先补充并妥善保存数据，包含少量英语、日语和粤语；
- 暂时不训练新模型，优先在旧模型/现有推理链路上继续研究；
- 希望保留一部分真正封存的数据，提出 2:5:3 的训练/测试/封存想法。

## Assistant 给出的当前建议

- 在不训练的阶段，把 2:5:3 改称 `diagnostic_visible : regression_selection : sealed_final`；
- 只要根据某一集合挑过模式或参数，它就是 development/selection，不是真正 test；只有 sealed 是最终无偏测试；
- 不跨数据集随机混切，必须按歌曲/歌手/配对样本分组，并保留官方 split；
- 不把不同语言和标注粒度压成一个总分；
- 先冻结旧模型 baseline，再做单因素消融，只有胜出机制进入少量两两交互，不遍历所有开关笛卡尔积。

## 尚未执行或冻结的事项

- 已生成 `evaluation_v1` **draft** split manifest（见 `03_...NEXT_STEPS.md`），但尚未 review/冻结；
- 尚未决定各数据集的具体歌曲 ID 分配；
- JamendoLyrics 和 MIR-MLPop 的 raw mixture 尚未生成满足项目 provenance 规则的 vocal-only 派生资产；
- sealed runner 的访问控制、运行频率和报告可见范围尚未实现；
- 本 session 的分配数字是下一步设计建议，不代表已经运行评测或查看 sealed 结果。

## 2026-08-21 复核补充（未整理版）

- 三个 window 机制消融（compress/strict/skip）结论修正为 **inconclusive（短片段上未激活）**，
  详见 `reports/progress/20260816_productization_validation_report.md` 与 `..._recommendations.md` 的 ⚠️ 口径行。
- 主线指路已最小化更新：`AI_SESSION_ENTRY.md` 顶部新增 2026-08-16 entry（只指路，不作裁定）。
- GTSinger 拼接全曲可行性已验证（25 段连续切分、wav==标签、`<AP>` 呼吸保留、段序 concat 即可）；
  接缝审计与全曲资产尚未执行（待 pilot）。
