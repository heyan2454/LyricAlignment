# Run 布局偏差（P1-a）与净回归悖论归因（P1-e）

状态：**已文档化，不阻塞验收**。仅作数据解读修正，不重命名历史 run 目录。
涉及 run：

- `/home/hyan/Data/lyricalign/runs/unit_realign_formal_20260813`
- `/home/hyan/Data/lyricalign/runs/unit_realign_heldout_expansion_20260813`
- `/home/hyan/Data/lyricalign/runs/unit_realign_confirmation_no_gt_20260813`

## 1. P1-a：05 固定布局 vs 实际布局

05 计划「不可变产物布局」固定为：

`00_population/ 01_requests/ 02_forwards/ 03_unit_outcomes/ 04_no_gt_features/ 05_analysis/ 06_test_demo/ 07_runtime/`

三个 run 的实际布局（三 run 一致）：

`00_meta/ 01_detector_audit/ 02_behavior/ 05_analysis/ 06_evaluator_only/`

原因：这些 run 是从旧 `realign_gate` pipeline（`run_behavior_suite` + recovery_e5 proposal）直接产出的，
`02_behavior/` 保留了旧批次的目录骨架，未按 05 Batch 布局重命名。**映射如下**（供 report/文档对照）：

| 05 固定布局 | 实际目录 | 证据 |
| --- | --- | --- |
| `00_population/` | `01_detector_audit/CASE_POOL.jsonl`、`00_meta/`（formal 为空） | 候选 case pool / detector 审计 |
| `01_requests/` + `02_forwards/` | `02_behavior/`（REQUESTS.jsonl、SAMPLE_ACCOUNTING.json、CASES.jsonl、CANDIDATE_INDEX.jsonl、NO_GT_CHECK.jsonl、SKIPPED_CASES.jsonl、`forward/` 下 RUN_MANIFEST/FAILURES/evidence/items） | request 计划与 forward 证据均在此 |
| `03_unit_outcomes/` | `06_evaluator_only/`（UNIT_OUTCOMES.jsonl、EVALUATOR_ONLY_SUMMARY.json） | evaluator-only 口径 |
| `05_analysis/` | `05_analysis/` ✓ | FORMAL_AUDIT(_FINAL)/NO_GT_*/ROUND2_GATE_AUDIT/CLASSIFICATION_AGGREGATE 等 |
| `04_no_gt_features/`、`06_test_demo/`、`07_runtime/` | **缺失** | 本轮无 no-GT features 阶段，也无 test demo 阶段 |

验收影响：FINAL_REPORT 的拒绝路径（`03_unit_outcomes/STRATIFIED_POOL` 不存在）与布局偏差一致，非缺口；
仅当后续要按 05 命名读者时，应在下次 run 从新 pipeline（unit_realign builder + `p1-pool`）产出并沿用固定布局。

## 2. P1-e：improved/regressed 计数悖论与 R-B 退化归因

### 2.1 计数口径矛盾（三 run）

| run | rows | improved | regressed | mean_delta(ms) | onset MAE 旧→新 | hit_rate@500 旧→新 |
| --- | --- | --- | --- | --- | --- | --- |
| formal | 718 | 255 | 211 | **−1793.8** | 2534.7→812.5 | 0.3092→0.3538 (+4.46pp) |
| heldout | 5012 | 1817 | 2150 | **−677.9** | 1617.2→928.9 | 0.3966→0.3482 (**−4.85pp**) |
| confirmation | 1500 | 543 | 595 | **−1110.2** | 2019.4→871.0 | 0.4287→0.3913 (**−3.73pp**) |

解读：`improved/regressed` 是按 unit-row 的 delta 符号计数（任何非零位移都算），与 **MAE/hit_rate
（幅度与容差）不是同一度量**。heldout/confirmation 中 regressed 数量多于 improved 但 mean_delta 为负、
MAE 大幅下降，原因是**少量大位移的改进把 MAE 拉下来，但大量小位移回归把容差内 hit_rate 拉低**。
因此：

- **unit-row 符号计数不得作为策略优劣结论**；须按 04 Batch4 分类契约在 region-level
  （beneficial/harmful/catastrophic/mixed）判读。
- 三 run 的 `CLASSIFICATION_AGGREGATE.json`（region-level）是当前正确解读口径：
  - formal：beneficial 20 / neutral 7 / catastrophic_harmful 51（78 requests）
  - confirmation：beneficial 31 / neutral 109 / harmful 7 / catastrophic_harmful 76 / mixed 2（225 requests）
  - heldout：见其 `05_analysis/CLASSIFICATION_AGGREGATE.json`
  - 注：classification 的 catastrophic 需要 ≥200ms 实质效应或 covered-to-missing，与 unit-count
    improved/regressed 不是同一概念。

### 2.2 R-B 退化归因（核心数据问题）

**事实**：
- heldout R-B：135/135 requests `anchors=null`；R-B context mean_delta **+841.8ms**（退化）、hit_rate@500
  **−35.62pp**、@1000 **−36.92pp**。
- confirmation R-B：R-B context mean_delta **+209.4ms**、hit_rate@500 **−38.02pp**、@1000 −33.33pp。
- formal R-B：9/9 requests `anchors=null`；R-B **context** 退化（hit_rate@500 −30.56pp、@1000 −13.89pp），
  但 R-B **target** 改善（mean_delta −3790.9ms、hit_rate@500 +18.52pp、@1000 +16.67pp）。
- 三个 run 全部 requests 的 provenance 均为 `episode_family=realign_gate`、`realign_recovery_stage=realign_gate_p2`、
  `workflow_mode=recovery_e5_proposal`、`mutation_type=p2_dual_variant_proposal`。

**归因**：这批 REQUESTS 全部来自 **realign_gate 旧 adapter（recovery_e5 / p2 dual-variant proposal）的
preselected no-GT 数据**，不是 unit_realign 新 builder（`build_r_b` + ACCEPT anchor 候选）的产物。R-B 行
`anchors` 字段为空，意味着 bilateral anchor 未落库；其 context 构造退化为旧 pipeline 的 anchor-less
proposal，无法满足 05 冻结合同中「R-B 必须使用最近左右 ACCEPT anchor」的构造条件。因此：

- **R-B 的 context 级退化（heldout/confirmation/formar 的 context 角色）不能归因于 unit-level realign 策略本身**，
  而是 anchor 缺失导致 R-B 语义失效的构造缺陷。
- formal R-B target 改善与 heldout/confirmation R-B context 退化并存，进一步证明这批 R-B 数据跨 run 同源
  （均为旧 adapter 产物），不可作为新 builder R-B 策略的验收证据。
- 结论：**R-B 的 no-GT 结论一律不作数**；新一轮必须用 unit_realign builder 的 `build_r_b`
  （anchor provenance 校验 + 缺失时 `not_constructible/missing_*_anchor`）重新构造后再评价。

### 2.3 对验收的影响

- round-2 gate 为 `audit_round2_gates.py` **自定 exploratory 阈值**（eligible>=500、selected>=300，
  **非本 session 冻结门槛**，见 `08_OPENCODE_REVIEW_REBUTTAL.md` P1-5）：formal eligible 40/500、
  selected 25/300 均未达成（`05_analysis/ROUND2_GATE_AUDIT.json`：eligible gap 460、selected gap 275）。
  该阈值不得被 formal pass/fail 或 writeback 讨论消费；**本轮 P1 acceptance 仍按 05 契约
  （S1–S4 各 25 valid case）判定，未达成**。heldout/confirmation 无 SAMPLE_ACCOUNTING 的 S1–S4 统计，
  非正式四象限 run。
- 新 run 需按 05 布局 + `p1-pool`/`p1-refill` 自然 population 采样，排除旧 adapter 数据混入，
  并在 `FINAL_REPORT.md` 中禁止引用 `deprecated_historical/` 旧 evidence。
