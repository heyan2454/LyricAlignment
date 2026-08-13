# 2026-08-13 — Unit-level Realign / Sparse / Overnight Exploration

本 session 继承 `realign_gate_20260813_delivery` 的真实运行结果与随后 review，进一步把研究重点从 candidate/window 级迁移到 **unit-level realign behavior**。

本阶段的核心问题不是“某个 candidate 整体算不算 harm”，而是：

1. 一个本来错误的 unit 是否被 realign 修好；
2. 一个本来正确的 unit 是否被 realign 保持；
3. detector 判 REJECT/UNCERTAIN 但 GT 实际正确的 unit 是否特别脆弱；
4. 不同 request construction（unit-local、sparse、detector-direct、stable-anchor、left/right anchor、oracle-direct）各自在哪些 unit 上有效或有害；
5. realign 自身的 no-GT 行为能否形成可靠的 unit-level writeback gate；
6. 多个不同 request 是否对同一个 unit 收敛到一致时间，从而形成 consensus；
7. Test Demo 是否能在真实 production detector region 上复现这些行为，而不是继续用整首 pseudo-local request。

本轮允许 overnight 级别的较大规模自动探索，但仍禁止无意义笛卡尔积。总体策略是：

> **小规模 request-family screening → 淘汰明显无效路线 → 自适应扩展到约 200–300 个独立 GT regions → 对少数高价值 case 做扰动/consensus/fixed-point 深挖。**

同时冻结以下原则：

- 主评价单位是 **unit**；candidate/region 只作上下文与聚合。
- `<=1s` / `<=5s` 不再视为 repair success；主精度口径为 100/200/500ms 与 >1s。
- `n_big` 不再是候选 gate；现有 feature 必须按 unit-level 重新计算。
- `GT delta_error_ms` 永远只能作为 outcome，不能进入 no-GT gate feature。
- `97.5% any-reject whole-window unsafe` 不作为主要 KPI，也不作为整窗 realign trigger。
- Test Demo 必须使用真实 detector region + 真实 local/sparse realign。
- “样本不足”不能直接成为停止理由；必须先主动扩大 eligible population / 改 region 构造 / 使用 cache / 重新抽样，并输出 exhaustion audit 后才能宣告不可满足。

文件：

- `00_SESSION_DISCUSSION_RECORD.md`：从当前工作目录 review 到本轮 overnight 设计的完整讨论过程，用户意见和疑问忠实记录。
- `01_CURRENT_RESULTS_AND_REVIEW_CONCLUSIONS.md`：当前 delivery 中可保留结果、需要降级/重算结果、当前结论强度。
- `02_NEXT_ROUND_EXPERIMENT_DESIGN.md`：下一轮实验原因、目的、设计、预期结果及不同结果可支持的结论。
- `03_CODEX_HANDOFF.md`：要求 Codex 合并后先给出具体实现方案，再交给执行 agent/OpenCode。
- `05_GPT_REVIEW_IMPLEMENTATION_PLAN.md`：针对外部 GPT review 的文件级实施计划、P1 四象限补样、请求合同、评价和执行顺序。
- `07_OPENCODE_IMPLEMENTATION_REVIEW.md`：OpenCode review 的 5 项 P0/P1 整改清单（顶部含 fix status 验收表）。
- `08_OPENCODE_REVIEW_REBUTTAL.md`：对 review 的逐条抗辩核验；整改清单已完成标记。
- `09_OPENCODE_FIX_ACCEPTANCE.md`：P0/P1 修复验收 + 真实 run 补算结果（v2 pool/aggregate/audit）。

## 验收状态（2026-08-13）

- `07` review 的 5 项 P0/P1 全部修复，`tests/unit_realign tests/realign_gate` **149 passed**，
  `compileall` 与 `git diff --check` 通过。
- 修复后工具已对真实 run 补算：confirmation pool `CASE_POOL_V2.jsonl`（60 case，1,091 invalid
  baseline 排除）、两个旧 run 的 `CLASSIFICATION_AGGREGATE_V2.json`、formal 的
  `ROUND2_GATE_AUDIT_V2.json`（exploratory_only）。产物均在 `/home/hyan/Data/lyricalign/runs/`
  对应 run 目录下，原产物保留并备份，未静默覆盖。

## Backlog（MINOR，不阻塞）

- **GT 行被误丢弃（已修复 2026-08-13）**：`scripts/unit_realign/build_baseline_gt.py` 原来在
  detector shadow 区间退化（`start >= end`，如 `[19.28, 19.28]`）时 `continue` 跳过整行，导致
  GT 源（`BASELINE_UNITS.jsonl`，5027 个单元全部有效）中 81 个单元在 `BASELINE_GT.jsonl` 缺失，
  evaluate 时被误标 `extra_prediction`（74 个 context 单元）。已修复：GT 行总是输出，退化 detector
  行置 `detector_start/end_sec=None, max_boundary_error_ms=None`；重建 GT（5027 行）+ 重跑 evaluate
  后 `extra_prediction` 74→0，region outcome 零翻转（这些单元所在 region 原本就 harmful/catastrophic），
  R-S fixed-context 冻结结论不变（8090 context 行 0 移动）。备份：
  `BASELINE_GT.old_dropped_degenerate.jsonl` / `UNIT_OUTCOMES.old_gt_extra.jsonl` 等。
- **评估口径修正（已修 2026-08-13）：`degraded_finite` 只看 delta**。原 `classify_unit_outcome` 在
  `delta_max_boundary_error_ms >= material_ms` **或** `new_max_boundary_error_ms > catastrophic_ms`
  时判 degraded，后者不看 delta，导致 baseline 自身误差就 >1s 的 context 单元即使 candidate 无实质
  变化也被判 harmed。已改为纯 delta 驱动（`delta >= material_ms` 才 degraded）；绝对 catastrophic
  语义（target 的 `new_max > 1000ms` / `covered_to_missing`）由 `aggregate_region_outcome` 独立承担，
  不受影响。重跑 evaluate：43 个 region 翻转且全部正向（42 harmful→neutral、1 mixed→beneficial，
  零反向），`catastrophic_harmful` 152 不变，且 152 个 catastrophic 全部有 target driver 验证通过。
  备份：`REGION_OUTCOMES.old_delta_abs.jsonl` / `UNIT_OUTCOMES.old_delta_abs.jsonl` /
  `CANDIDATE_OUTCOMES.old_delta_abs.*`。新增测试
  `test_degraded_requires_material_delta_not_absolute_new_error`，`tests/unit_realign` 64 passed。

## 设计文档 P 项实验状态（2026-08-13 本轮完成）

主线 run：`/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify`（346 regions / 400 REQUESTS =
346 ready + 51 not_constructible + 3 null；evidence 692）。注：FINAL_REPORT 头部 not_constructible=39
与 REQUEST_STATUS=51 不一致，差异=region 去重口径（见 P13 复核段）。

- **P4 验收（PASS）**：`scripts/unit_realign/audit_p4_p11_stats.py` → `05_analysis/P4_ACCEPTANCE.json`。
  346≥200；family R-A=100/R-B=83/R-S=66/R-U=97（≥30）；stratum S1=94/S2=81/S3=80/S4=91（≥20）；
  13 歌每歌≥17；max 单歌 9.25%、top-3 27.5%（EXHAUSTION_AUDIT 48 采样、cap=4、complete）。
- **P5 审计**：`05_analysis/UNIT_GATE_FEATURES_AUDIT.md`。`unit_gate_features.py` 84 行、
  schema `unit_realign_no_gt_features_v1`、24 键 allowlist、实际 emit 12 键；未实现 ACCEPT/UNCERTAIN/REJECT
  transition、entropy/margin、temporal 细项；未接线根因=无 producer（screen 需 `--features` manifest、
  evidence 层缺 p_bad/state 字段）。接线方案见审计文档，MINOR 不阻塞。
- **P5 接线（已完成）**：`scripts/unit_realign/extract_unit_gate_features.py` →
  `05_analysis/UNIT_GATE_FEATURES.jsonl`（390/390 target units，纯 allowlist schema，`assert_no_gt_feature_row`
  强校验）+ `UNIT_GATE_FEATURE_REGION_LABELS.jsonl`（346 旁路标签，不混入 feature 行）。有效 feature：
  `mean_boundary_displacement_ms`（390，264 行 >0）、`duration_sec`（390）。detector 类键
  （p_bad/signed_detector_delta/state_*）**全 null——无 p_bad producer**（run 内无 detector_rows.jsonl），
  需 run_forward_real.py 落 p_bad 后重跑。接线说明见 `UNIT_GATE_FEATURES_WIREUP.md`。
- **P11 统计**：`05_analysis/P11_SONG_STATS.json`。9245 units：repair 81（0.88%）/ harm 137（1.48%）/
  unchanged 9027（97.64%）。bootstrap 1000×（seed=20260813, 13 歌）：repair 0.96% [0.17–2.98%]、
  harm 1.57% [0.75–2.93%]、unchanged 97.46% [94.38–99.0%]。LOO 无歌主导；最离群"我爱你中国"
  （自身 repair 42.4%），剔除后 -0.54pp。公平性：346 evaluated 全单一 model/checkpoint/decoder/mapping
  identity、evaluation_only=False。
- **P12 转换表**：`scripts/unit_realign/report_unit_transition_tables.py` →
  `05_analysis/UNIT_TRANSITION_TABLES.json` + `reports/UNIT_TRANSITION_TABLES.md`（n_regions=346、
  key=(region_id, family)、12.3 各 family 求和=346）。S1 remain≤200 86.2%/→>500 2.1%/→>1s 2.1%/
  collateral 2.7%；S2 70.6%/7.1%/2.4%/6.9%。12.3 R-A 68/44%、R-B 53/41%、R-S 48/48%、R-U 67/43%
  （active/catastrophic）。12.4 R-S context 位移恒 0（8090 行 delta 全 0、preservation 100%）vs
  R-U 99–1718ms（preservation 19–53%）。stratum 语义：S1=safe+ACCEPT/S2=safe+REJECT/S3=bad+REJECT/
  S4=bad+ACCEPT。
- **P6 Oracle Basin**：`scripts/unit_realign/build_r_o_requests.py` + `analyze_oracle_basin.py` →
  `/home/hyan/Data/lyricalign/runs/unit_realign_r_o_oracle_20260813/05_analysis/ORACLE_BASIN.json` +
  `ORACLE_BASIN_REPORT.md`。40 regions（五桶 recovery7/mixed3/harm10/safe5/catastrophic15；
  S1:11 S2:11 S3:11 S4:7）。修复 R-O full-window bug（原 76 行 text vs 2s audio 退化；改走 R-U
  窄窗口，request_families.py L136）。结果（48 target units）：recovery_within_100ms 39.6%、
  regions_recovered 45%；bucket 恢复率 recovery 85.7% > safe 100% > harm 60% > mixed 33% >
  catastrophic 0%（mean err 644ms）。**catastrophic 全 0 恢复 → 根因不在时间提示缺失，而在内容/声学层面**
  （no-GT 策略应对 catastrophic 保守保留/标记不可修复）。
- **P7 Fixed-point**：`scripts/unit_realign/build_fixedpoint_requests.py` + `analyze_fixedpoint.py` →
  `/home/hyan/Data/lyricalign/runs/unit_realign_fixedpoint_20260813/05_analysis/FIXED_POINT.json` +
  `FIXED_POINT_REPORT.md`。24 regions（R-A6/R-U6/R-S4/R-B8，R-S 回退 catastrophic_harmful）真实
  forward 两轮：A→B displacement mean 16.7ms / median 10 / max 60 / p90 60，24/24 stable（A≈B<200ms）、
  0 drifted、consensus 24/24。**candidate 普遍落入稳定 fixed point**；R-S 区标 stable 仅指不动点，
  不代表安全（round1 为 catastrophic_harmful）。
- **P9 Test Demo 验收**：`unit_realign_test_demo_formal_20260813/04_test_demo/`（TEST_DEMO_* 7 文件）。
  33 items（3 failed）、60 windows、120 requests→118 real forward（R-U 59 + R-S 59）+ 61 R-NULL、
  real executor、no_gt=True、result_status=ok。
- **P6 Extended Perturbation（已完成）**：`scripts/unit_realign/build_perturbation_requests.py` +
  `analyze_perturbation.py` → `/home/hyan/Data/lyricalign/runs/unit_realign_perturbation_20260813/`
  （9 case × 扰动，43 requests 真实 forward 全成功，identity none=0）。结论 **B**：oracle 0 点在
  GT±100ms 仅 50% recovered（harm 3/3 全过、recovery 1/3、catastrophic 1/4）；audioL-2s 使 2 target
  漂移 -1.9s/-1.7s，audioR/text 轴零响应；无 discrete jump；basin 普遍宽（median 2s、≥1s 占 90%）。
  产物：`05_analysis/PERTURBATION_BASIN.json` + `_REPORT.md`。
- **P6 textL-2u 轴（2026-08-13 补齐）**：harm schedule 补 `textL-2u`（text 轴 L 侧对称），
  3 个 harm case 真实 forward（--resume 只跑新增 3 请求），textL n 3→6。
  **textL-1u/-2u/textR+2u 全部 0.0ms 响应（text 轴完全稳定），frac_gt_recovered 仍 1.0、mean err 46ms**——
  结论 B 不变，对称性闭合。
- **P12.5 Consensus（已完成）**：`scripts/unit_realign/analyze_multi_request_consensus.py` →
  `05_analysis/MULTI_REQUEST_CONSENSUS.json` + `_REPORT.md`。target units=390，span median 20ms/p90 80ms、
  consistent(≥3/4 view <100ms)=84.6%。**结论：不支持 P13-E**——consensus strong 组 GT 命中 39.7%
  < weak 组 43.6%，median span 20ms 但 strong 组 err ~500ms：多 view 共识反映稳定 re-interpretation
 而非向 GT 收敛。
- **P8 + P13 书面（已完成）**：`05_analysis/P8_ATTEMPT_WRITEBACK_GATES.md`（Attempt=stable anchor/
   短 region 优先、severity 弱；Writeback=fixed-point<60ms + context protected 必要条件，consensus 仅辅助）
   + `05_analysis/P13_CONCLUSION_MATRIX.md`（A 支持 / B 部分支持 / C 支持 / D 不支持 / E 不支持 /
   F 部分支持待 P5）。**FINAL_REPORT 39 vs 51 根因已复核**：39=region 去重口径、51=raw 行
   （12 行同 region 双 family 重复，nc 分布 R-S 34/R-B 17），见 P13 文档末尾复核段。
- **P5 Detector 接线 + P13-F 定案（2026-08-13 补齐）**：`scripts/unit_realign/emit_detector_rows.py`
   产出 evidence-only p_bad 代理（`02_forwards/detector_rows.jsonl`，390 行、schema
   `unit_realign_detector_row_v1`、identity 显式标注 proxy；before=baseline 结构风险、after=结构+
   跨视图不一致+缺失惩罚）。`extract_unit_gate_features.py` 加 `--detector-rows` 接线 →
   `detector_p_bad_before/after`、`signed_detector_delta` **390/390 非 null**。判别力评估（P13-F
   定案为**不支持，strong negative**）：delta AUC=0.411、p_bad_after AUC=0.512、span AUC=0.462、
   n_views AUC=0.434——全随机附近，纯时间行 evidence 无法复现训练检测器（需 raw/official/entropy/
   margin）。唯一具判别力的 no-GT 信号是 context 结构位移（见下）。
- **P8 Structural Sanity 专项（2026-08-13 补齐）**：`scripts/unit_realign/analyze_structure_sanity.py`
   → `05_analysis/STRUCTURE_SANITY.json|md`（346 请求 / 8855 context unit）。**context 位移是唯一
   强判别 no-GT 信号**：harmful 组 mean 252ms / 仅 41%≤60ms / 12%≤10ms；neutral 组 mean 3ms /
   99%≤60ms / 96%≤10ms；mixed mean 6008ms 最坏。无单调性破坏（0/346）；169 对相邻 candidate 重叠
   （轻微）。beneficial 组 context 位移也偏大（mean 1010ms）——context 位移小是**必要条件**而非
   修复性信号。P8 Writeback 构成已更新：signed p_bad 不启用、structural sanity（candidate 上下文
   位移 ≤60ms）升为必要条件。
- **FINAL_REPORT 口径标注（2026-08-13 补齐）**：`reports/FINAL_REPORT.md` 头部已加双口径注释
   （raw=51 / region-dedup=39），正文 family×stratum 表按 raw 行合计的差异明确为口径而非数据丢失。

## Backlog（MINOR，不阻塞，2026-08-13 追加）

- **FINAL_REPORT 头 39 vs 51 已复核并标注（2026-08-13 完成）**：39=region 去重口径、51=raw 行
  （12 行同 region 双 family 重复）。FINAL_REPORT 头部已加双口径注释。
- **detector p_bad producer（2026-08-13 完成，负面结论）**：evidence-only 代理已实现并接线
  （emit_detector_rows.py + extract --detector-rows，390/390 非 null），但判别力 AUC 0.41–0.51
  无区分 good/harm 能力。真实 detector_v5 RNN_TV 需 raw/official/entropy/margin 特征，纯时间行
  evidence 无法复现——维持 shadow-only，能力下沉模型/接口层。
- **P8 structural sanity（2026-08-13 完成）**：context 位移是唯一强判别 no-GT 信号
  （harmful 41%≤60ms vs neutral 99%≤60ms），已升为 Writeback 必要条件。
- P6 extended 未做 anchor 一档（40 region 全无 anchor，标 not_applicable）；textL-2u 轴未构造。
- **consensus.py 接线（2026-08-13 完成）**：`aggregate_consensus` 现在有真实 producer 链
  （`extract_unit_gate_features.py` → `UNIT_GATE_FEATURES.jsonl` → 新
  `scripts/unit_realign/run_unit_consensus.py` → `05_analysis/UNIT_CONSENSUS.jsonl`）。
  smoke_v2_verify 验证：118 组 consensus、113 组跨 family（95.8%）、median displacement 100% 填充。
  注：`context_protection_ratio` 恒 None——extract 只保留 `role=target` 行，target 的
  `context_protected` 按设计置 None（见 build_unit_features `cid in targets`）。该 median/MAD 视图与
  P12.5 的 span/consistent_34 视图互补，均只消费 no-GT 数据。
- configs/experiments/unit_realign_*.json（6 个）与 results/by_run 新产物未提交 git。
