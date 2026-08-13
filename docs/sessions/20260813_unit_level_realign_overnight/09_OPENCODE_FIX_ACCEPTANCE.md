# OpenCode P0/P1 fix acceptance — code + experiment recompute (2026-08-13)

本文件记录 `07_OPENCODE_IMPLEMENTATION_REVIEW.md` 中 5 项 P0/P1 修复的最终验收状态：代码修复、
单元/回归测试、以及用修复后工具对真实 run 的**补算结果**。所有补算产物写入 run 数据目录
（`/home/hyan/Data/lyricalign/runs/`），原始产物均保留并备份，未静默覆盖。

## 0. 总验收

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
PYTHONPATH=src python -m pytest -q tests/unit_realign tests/realign_gate   # 149 passed
python -m compileall -q src scripts
git diff --check
```

- `tests/unit_realign`：43 passed（含 P0-1 v2 controller end-to-end、P0-2 overlap/invalid-interval、
  P0-3 context/extra 分类、P1-4 empty/all-null/one-valid report 回归）
- `tests/realign_gate`：106 passed
- 均秒级完成，无 GPU 依赖。

## 1. P0-1 — v2 controller 与 execute/evaluate/report 接线

- 状态：已修复。
- `scripts/unit_realign/run_unit_realign.py` 提供 `execute/evaluate/report` 子命令，消费 v2 布局
  （`00_population/01_requests/02_forwards/03_unit_outcomes/05_analysis/07_runtime`）；
  GPU forward 经 research_v7 real-executor adapter 接线（`execute` 校验 + identity-keyed
  `RUN_STATE.json`；`evaluate` 调 `pair_unit_outcomes()` + `unit_outcome` 聚合；
  `report` 只读 v2 artifacts 出 `FINAL_REPORT.md`）。
- 回归：synthetic CPU integration test（one ready / one R-NULL / one failed request）。

## 2. P0-2 — confirmation pool 补算（真实 frozen shadow）

- 修复点：`materialize_no_gt_confirmation_pool.py` 不再只做 per-song cap，改用
  `balanced_replenishment()` 同级排除：`(song_id, canonical_unit_id)` 同 target 去重、同 song
  strict-time-overlap 排除、`baseline_available=false` 排除（标 `ineligible_invalid_baseline_interval`）；
  case 显式写 `active_target_unit_ids/fixed_context_unit_ids/outside_unit_ids` 与
  `baseline_audio_range_sec`，不再整窗 `old_units`。
- 真实 shadow：`detector_production_realign_gate_20260812_20260812T195343Z/00_inventory/BASELINE_DETECTOR_SHADOW.jsonl`（40 windows）
- population：`build_region_population` → 8,694 rows（UNSAFE 4,849 / ACCEPT 3,845）
- 补算命令：
  ```bash
  PYTHONPATH=src python scripts/unit_realign/materialize_no_gt_confirmation_pool.py \
    --regions <pop_8694> --shadow <SHADOW> --out <run>/01_detector_audit/CASE_POOL_V2.jsonl \
    --unsafe-count 45 --accept-count 15 --per-song-cap 5 --seed 20260813
  ```
- 产物（`unit_realign_confirmation_no_gt_20260813/01_detector_audit/`）：
  - `CASE_POOL_V2.jsonl`：60 行（unsafe 45 / accept 15），per-song ≤5，status=complete
  - `CONFIRMATION_POOL_AUDIT_V2.json`：`eligible_total=7603`、`excluded_total=8634`、
    `excluded_by_reason.ineligible_invalid_baseline_interval=1091`、`duplicate_target_unit=5`、
    `time_overlap=2`、`per_song_cap=5`；available unsafe 4,849 / accept 3,845
  - 原始 `CASE_POOL.jsonl`/audit 保留，旧 audit 备份 `CONFIRMATION_POOL_AUDIT_v1_backup.json`
- 校验：selected 60 行无 (song, canonical_unit_id) 重复、无 `baseline_available=false`，字段齐全。
- 结论：修复后抽样与 review/06 read-only audit 数据完全吻合（8,694 / 1,091），1,091 个 invalid
  baseline 不再进入 primary cohort。

## 3. P0-3 — 旧 run v2 aggregate 补算

- 修复点：`aggregate_classification.py` 删除脚本内独立 classification policy，group rows 后
  delegate 到 `unit_outcome.aggregate_region_outcome()`（target + fixed-context + extra 均影响
  harm）与 `aggregate_candidate_outcome()`（per request）。
- 补算（`--unit-outcomes <旧 run>/06_evaluator_only/UNIT_OUTCOMES.jsonl` → 新文件
  `CLASSIFICATION_AGGREGATE_V2.json`，原 v1 备份 `CLASSIFICATION_AGGREGATE.v1.bak.json`）：
  - formal：`unit_realign_formal_20260813/05_analysis/CLASSIFICATION_AGGREGATE_V2.json`（n_rows=718）
  - confirmation_no_gt：`unit_realign_confirmation_no_gt_20260813/05_analysis/CLASSIFICATION_AGGREGATE_V2.json`（n_rows=1500）
- 校验：`schema=unit_realign_classification_aggregate_v2`，note 注明 delegated to `unit_outcome`；
  `region_level` 含 `target_rows/fixed_context_rows` 双分母，`candidate_level/extra_and_unpairable`
  保留 `n_extra/n_invalid_unpairable`；beneficial/harmful/mixed/catastrophic_harmful 四标签齐全。
- v2 vs v1 结论差异（v2 收紧，因 context/extra 计入 harm）：
  - formal：beneficial 20→4、harmful 0→2、mixed 0→16；catastrophic_harmful 51→51（不变）
  - confirmation_no_gt：beneficial 31→10、harmful 7→55、mixed 2→29；catastrophic_harmful 76→76（不变）
- 结论：catastrophic_harmful 两 run 均不变，说明最严重档结论在 v1/v2 口径下一致；beneficial 减少
  主要来自 fixed-context/extra 计入 harm 导致的 mixed/harmful 迁移。

## 4. P1-4 — report_final v2 + null-safe

- 状态：已修复。`report_final.py` 只读 v2 布局（不再读 `02_behavior/06_evaluator_only`）；
  nullable metric 用 null-safe formatter，empty/all-null/exhausted 输出 `NOT_EVALUATED/EXHAUSTED`
  报告且不抛异常。回归覆盖 empty、all-null、one-valid-case。
- 旧 run 为旧布局（`02_behavior/06_evaluator_only`），未对其重跑 FINAL_REPORT（属 v2 布局才适用）；
  真实 v2 run 的端到端报告产出由 P1-4 回归 + P0-1 integration 覆盖。

## 5. P1-5 — round-2 gate 降级为 exploratory audit

- 修复点：`audit_round2_gates.py` 输出顶层 `"exploratory_only": true`；500/300 明示为 audit 自定
  exploratory 阈值，非本 session 冻结 P1 门槛（S1–S4 各 25 valid）。`report_final.py` 不再消费
  `ROUND2_GATE_AUDIT.json`（grep 确认无引用）。
- formal run 重跑：`unit_realign_formal_20260813/05_analysis/ROUND2_GATE_AUDIT_V2.json`，
  `exploratory_only=true`、eligible 40/500、selected 25/300、`round2_gate_pass=false`；
  原文件备份 `ROUND2_GATE_AUDIT.v1.bak.json`。
- 文档修正：`07_RUN_ARTIFACT_LAYOUT_DEVIATION.md:83` 已把 "round-2 gate 门槛（06 契约）" 误引修正为
  "audit 脚本自定 exploratory 阈值，非冻结门槛"。

## 6. 遗留（MINOR，不阻塞）

- `aggregate_classification.py` region 级 `target_rows/fixed_context_rows` 为计数（int）而非 list；
  行级分母逐条确认未完成。已在 V2 输出的 `region_level` 保留 `target_rows/fixed_context_rows`
  两个计数路径，语义由 `unit_outcome.aggregate_region_outcome` 保证，后续如需展示行级明细可扩展。
- 真实 v2 布局 run 的 GPU 端到端（`00_population/.../07_runtime` 完整跑通并出 FINAL_REPORT）尚未在
  GPU 上执行；CPU integration 已覆盖逻辑路径。
