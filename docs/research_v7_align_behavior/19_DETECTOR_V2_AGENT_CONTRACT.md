# Detector V2 Agent 执行合同

日期：2026-08-05  
优先级：高。完成 detector 下一阶段前必须遵守。

## 1. 首先阅读

1. `18_DETECTOR_V2_EXPERIMENT_PLAN.md`
2. `20_DETECTOR_V2_IMPLEMENTATION_BLUEPRINT.md`
3. `21_PREVIOUS_DETECTOR_RESULT_CORRECTIONS.md`
4. `22_DETECTOR_V2_EXPERIMENT_RESULT_REVIEW_20260806.md`
5. `17_IMPLEMENTATION_REVIEW_20260805.md`
6. `AGENTS.md`

旧 `13/14/15` 仅作历史依据；若与本合同冲突，以 `18/19/20/21/22` 为准。

## 2. 强制原则

- 产品主标签是正确文字的时间是否错位，不是 missing/replace/extra；
- 输入为一个或多个检测区间，输出必须是完整三态子区间 partition；
- raw-target 与 official-target 分开；
- H/R/O 及组合、跨视图必须复用同一 evidence；
- source-song split；
- 训练时无任何 GT/mutation 字段泄漏；
- test/demo 不选特征、模型、阈值；
- 单视图与多视图分开报告；
- 新 detector 不得导入旧 E1 detector/risk score；
- formal 目标 10h、硬上限 12h；
- 未完成覆盖矩阵不得宣布 detector 完成。

## 3. 明确禁止

- 禁止报告 `wrong_output_recall` 作为 detector 能力；
- 禁止用 slot coverage 作为检出率；
- 禁止用窗口尾部 1 ms 空白作为 missing detector；
- 禁止把无正例 family 的 recall 写成 1；
- 禁止按 attempt/window 随机拆 train/test；
- 禁止均匀合成字 GT 训练 100/250 ms detector；
- 禁止只做 tail-25%-replace；
- 禁止省略随机 1/2/4/8 stress；
- 禁止在 MIR replace/extra 数据补齐后不重跑跨域 detector；
- 禁止将 execution gate 命名为 scientific/formal approval；
- 禁止缺项填 0、success 或空字典；未知必须为 null+reason。

## 4. 必须先通过的 Gate

### G0 数据与标签

- 精确 GT source-song 数及 split；
- raw/official 标签一致性审计；
- repeated occurrence 目标可判定；
- synthetic-uniform GT 被排除出 detector train/test。

### G1 Hidden

- token/row/canonical 映射；
- layer/boundary 位置；
- hook 开关 logits 与 raw/official 数值等价；
- evidence shape/hash；
- 失败时 H 路线标 blocked，但 R/O 可继续，不能伪造零 hidden。

### G2 Request 与 cache

identity 必须包含 audio content/crop/transform、normalized units、slot mask/topology、view、window/lineage、model/checkpoint/processor、hidden schema、decoder、GT mapping version。不同项不得共享 cache 或 baseline。

### G3 Coverage

生成 `DETECTOR_V2_COVERAGE_MATRIX.json`，由 `scripts/research_v7/build_detector_v2_coverage_matrix.py --validate` 通过。所有 required 结果须有非零分母和对应 artifact 路径。

### G4 Pilot 预算

真实 pilot 预测 formal <=10h；硬停配置 <=12h。超时先按计划删除低优先级 cohort，不自行改成短片段全量。

## 5. 最低实现顺序

1. 契约/schema/metrics/coverage tests；
2. GT 与 split audit；
3. evidence schema v2 与 hidden audit；
4. 实际错位 manifests：crop/cursor/end-early/repeat/acoustic；
5. matched legal + multi-view manifests；
6. H/R/O feature extraction；
7. signal atlas；
8. Logistic/GBDT/hidden probe/一个序列模型 pilot；
9. val 冻结三态阈值与轻度区间合并；
10. M4 formal、family-LOO、M4→MIR、stress；
11. 真实 serial closed-loop；
12. compact evidence 与 draft report。

## 6. 交付物

至少存在：

- `PRECHECK_DETECTOR_V2.json`
- `SOURCE_SONG_SPLIT.json`
- `GT_LABEL_AUDIT.json`
- `HIDDEN_EXTRACTION_AUDIT.json`
- `REQUEST_IDENTITY_AUDIT.json`
- `ANOMALY_MANIFEST.jsonl`
- `MULTIVIEW_MANIFEST.jsonl`
- `SIGNAL_ATLAS.json` 与可读表
- `FEATURE_SCHEMA.json`
- `MODEL_SELECTION.json`
- `FROZEN_OPERATING_POINTS.json`
- `DETECTOR_V2_COVERAGE_MATRIX.json`
- `M4_SONG_HELDOUT.json`
- `FAMILY_LOO.json`
- `M4_TO_MIR_BY_FAMILY.json`
- `SERIAL_CLOSED_LOOP.json`
- `RUNTIME_BUDGET.json`
- `FAILURES.jsonl`
- `AUTO_FINDINGS_DRAFT.md`

机器报告必须包含真实 source-song、safe/unsafe/grey units、error intervals、各 family、各 domain 的分母。

## 7. 完成定义

只有以下全部满足才可写 `detector_v2_completed=true`：

- H/R/O 消融完整，或 H gate 明确失败且 R/O 完整；
- raw/official 两目标完整；
- M4 source-song heldout；
- product-like crop/cursor/end-early/repeat/acoustic；
- family-LOO；
- M4→MIR family 分项；
- replace 1/2/4/8 stress；
- interval@75/@100 与三态主指标；
- 单视图/多视图成本；
- serial closed-loop；
- coverage validator 通过。

运行无失败但缺上述任何一项，只能写 `partial_exploratory=true`。
