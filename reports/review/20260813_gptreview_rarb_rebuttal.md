# 对 `202608131152_gptreview_rarb` 的核验与抗辩

对应外部评审原文：[20260813_gptreview_rarb.md](20260813_gptreview_rarb.md)。

## 结论

该评审准确识别了旧 P1 evidence 的几项根本性问题，尤其是 R-B 的 no-op、整窗 target
合同、whole-window `unsafe` 聚合，以及曾经错误地把 GT outcome 用作 writeback 依据。这些
问题均不能被辩护，旧的 `ACCEPT_WRITEBACK` 结论应保持废弃。

但评审把“旧 evidence 的缺陷”“当前 `realign_gate` 分支已修复的保护措施”与“正在建设的
unit-level 主线尚未完成的能力”混为一谈。它提出的 100-case P1 不是当前代码已声称完成却
失败的 formal result；而是下一轮的验收目标。当前 session 已经明确降级旧结论，并把研究
对象由整窗 candidate 移至 document-global unit / local region。因此，合理处置是保留评审
为设计约束，而非据其推断当前工作仍在主张旧结论。

本文件为截至 2026-08-13 工作树的只读核验，不代表已执行新的 GPU formal run。

## 逐项回应

| 评审主题 | 核验结果 | 抗辩或处置 |
| --- | --- | --- |
| P1 四象限严重失衡 | **接受。**旧整窗 formal 的有效 strata 以 S2/S3 为主，不能评价四象限 gate。 | 当前结论已明确该结果不能回答 reject-safe，也没有把它包装成 balanced formal。下一轮改以 contiguous detector interval / unit-region 抽样；S1--S4 各 25 是目标，不足时必须给 exhaustion audit。 |
| S1--S4 与灰区 | **已部分修复。**当前冻结语义为 correct/bad 与 ACCEPT/UNCERTAIN/REJECT 的 region 组合，`200--1000ms` 标为 `moderate/grey_gt`。 | 评审所说“不要静默丢弃”已被采纳。灰区不混入 high-confidence S1--S4，是为防止 correctness 口径被稀释，而非回避样本。 |
| R-B 为 null intervention | **接受，且已修复入口。**历史 R-B 23/23 无真实 bilateral anchors，不能视为 intervention。 | `case_selection` 已将缺 bilateral ACCEPT anchors 或等价 request 记为显式 skip/null；`test_case_selection` 覆盖该行为。R-B 不可构造时不应删除 R-U/R-A/R-S；这正是 unit-level plan 的 constructibility accounting。 |
| 所有 strategy 要记录实际干预 | **已部分实现，仍需 v2 统一 schema。**现有实现已检测 null request、记录 R-NULL，并防 whole-item pseudo-local request。 | 评审要求的 audio/text span、active/fixed units、identity digest、null reason 将由 `unit_realign` 的 `UnitRequest` / intervention check 汇总为同一 schema；旧 `realign_gate` 仅能作为历史 adapter，不能假装已具备完整 v2 合同。 |
| target scope 误用整窗 | **接受。**这是旧 Test Demo 与部分旧 evidence 的实际合同错误。 | 当前 `test_demo.to_behavior_suite_manifest` 已加入 local mapping 以及 whole-item pseudo-local fail-fast，测试覆盖该拒绝。仍需在新 package 中将 document-global ID、request-local index、active/fixed role 做成正式不可变契约，不能只靠报告层补救。 |
| missing harm 被 headline 漏掉 | **已修复旧分支的核心行级逻辑，聚合仍须升级。**`pair_gt` 已为 target 缺失产生 `new_missing`、`covered_to_missing` 和 catastrophic 标记。 | 评审指出的 `report.py` 对 finite `delta_error_ms` 的旧 headline 筛选仍说明历史汇总不可用；不能据此否定行级修复。unit-level v2 会把 paired、missing、extra、invalid 分开汇总，candidate 分类不再由单一 any-harm 代替。 |
| feature join 会丢 missing target | **部分接受。**当前 pairing 可通过显式 `target_cids` 保留 candidate missing 行，并已有 `test_target_missing_recorded_per_variant`。 | 真正可部署的 v2 gate 仍应以 `(song, region, canonical_unit[, request])` 为主键，而不是 new output key。该要求已写入 unit-level plan，完成前不得声称 missing-failure join 已被端到端证明。 |
| GT leakage 与 `ACCEPT_WRITEBACK` | **完全接受，当前已修正。** | `gate_features` 现在固定输出 `DIAGNOSTIC_ONLY_NO_WRITEBACK`；当前报告不会据 `delta_error_ms` 建议 writeback，测试也要求最终 conclusion 不含 `ACCEPT_WRITEBACK`。任何历史 artifact 中的该措辞只可作为 deprecated evidence 引用。 |
| AUROC 可能只是识别“有没有改变” | **接受。** | 当前结论已把 `n_big`、displacement 和 `abs_p_bad_delta` 降为 change-magnitude / instability diagnostic，明确不能证明 improve-vs-harm discrimination。新分析须分别报告 all、non-null、changed-only 与 harmful-vs-beneficial/mixed；当前没有相反的生产声明。 |
| S2 reject-safe、S3 recovery、S1/S4 对照 | **接受为尚未完成的正式实验，不接受“当前声称已证明”这一隐含前提。** | 当前 session 明确说 S2=21 仍不足、S1 对照不足、reject-safe 未获充分估计。新 sampler 会以 target region 而非“60s window 有 reject”构造 cohort，并设 per-song cap 与 non-overlap。 |
| Test Demo mock 与真实执行混淆 | **接受且已收紧命名。** | 当前文档只保留动态 discovery 和 real executor 可运行这一事实；mock 不能计入 formal behavior，未执行写 `not_executed`。whole-item pseudo-local Test Demo 已显式拒绝。真正多语言 local-region GPU stress 仍待执行。 |
| 100-case / P1-A、P1-B、resume | **接受为下一轮 protocol。** | 当前 overnight plan 采用 screen→expand、content-addressed request identity、completed/failed/null 分流与 `--resume`，并避免 decoder×threshold×window policy 笛卡尔积。评审的“四象限各 25”应成为 config-level acceptance target；若穷尽仍不足，报告 scarcity，而非静默降目标。 |
| unit / region 为主、window 为辅 | **已接受并已冻结。** | 当前主 session 的第一原则就是 unit-level；97.5% whole-window unsafe 被定性为聚合规则产物，不再作 detector KPI 或整窗 trigger。 |

## 需要保留的历史边界

以下 artifact 只能作为历史/diagnostic，不得驱动当前 writeback 或作为新策略的胜负证据：

- 旧 R-A vs R-B 对比：R-B 为 null control，非公平策略比较；
- 以整窗 `target_unit_ids` 评价局部 request 的 covered-to-missing 汇总；
- 含 `ACCEPT_WRITEBACK` 或以 `delta_error_ms` 参与 gate recommendation 的旧报告；
- mock Test Demo 的 behavior 质量结论；
- 基于粗 candidate `any-harm` label 的高 AUROC / candidate harm rate。

这不是删除原始 evidence，而是保留其 provenance 并在新报告中标注 `deprecated_historical`。

## 当前尚不能抗辩的缺口

以下没有足够现有 evidence，不能以“已有计划”替代实现或实验结果：

1. S1/S2/S3/S4 各 25 个**有效、非 null、真实 forward** case；
2. R-U/R-A/R-B/R-S 的公平 paired comparison，含 R-B constructibility 分母；
3. active target、fixed context、outside unit 的 end-to-end evaluator 合同；
4. missing/extra/invalid 与 finite pair 并列的正式 unit、region、candidate 指标；
5. changed-only 的 no-GT harmful-vs-beneficial gate 泛化；
6. 真实 local-region、多语言 Test Demo GPU behavior；
7. 完整 resume / atomic write / retry 的 formal-run 验证。

这些缺口应被记录为 `not_yet_executed`，而非 `failed` 或 `fixed`。

## 对下一轮实施顺序的约束

1. 先完成 schema/contract 与 CPU tests：local/global mapping、fixed context、missing preservation、null detection、R-B non-blocking、GT firewall、resume dedupe。
2. 运行小型 real smoke，验证每个 request family 的输入 identity、active/fixed invariant 和 artifacts；失败只隔离对应 request/family。
3. 从全量 eligible region 建立可审计 pool；用 song cap、region non-overlap、replenishment 和 exhaustion audit 尝试补齐四象限。
4. 冻结少数 family 和 resolved config 后运行 P1-A；每 strategy 单独报告 selected/constructible/executed/null/failed/valid。
5. 仅在真实 intervention 子集上做 unit、region、candidate outcome 与 no-GT gate 分析；writeback 保持 `NOT_FROZEN`。
6. 最后运行 Test Demo local-region stress，并把 request plan 与 real behavior 分开输出。

## 最终立场

外部评审对旧实验结论的否定是正当的；对当前工作的正确表述应是：**旧结论已被降级，若干防呆与 GT-firewall 修复已经存在，unit-level formal rerun 尚未完成。** 因此本轮不应恢复 `ACCEPT_WRITEBACK`，也不应把实现计划写成已经取得的实验结果。
