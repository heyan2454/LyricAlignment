# AI Session Entry

## 2026-08-06 Full-slot Serial Detector Independent Stage Override

The active next-phase planning entry is independent from the research-v7 numbering chain:

```text
docs/research_fullslot_serial_detector/README.md
docs/research_fullslot_serial_detector/01_EXPERIMENT_PLAN.md
docs/research_fullslot_serial_detector/02_B4_60_SILENCE_OFFICIAL_SHADOW_V1.md
docs/research_fullslot_serial_detector/03_AGENT_IMPLEMENTATION_PLAN.md
docs/sessions/20260806_fullslot_serial_detector_discussion_record.md
```

Upstream Detector V2 evidence and corrections remain under `docs/research_v7_align_behavior/` and the
2026-08-06 Detector V2 evidence pack. They are referenced, not extended with more v7 document numbers.

Current stage:

```text
close v7 reporting/evaluator/serial audit defects
-> freeze full-slot 10s-left + 60s-core + 10s-right silence-snap Base
-> run hard serial and stable-window clean baselines
-> create sufficient carried-prefix / provisional / repeated-occurrence cumulative errors
-> compare consistent whole-window rollback W and local-gap realign L
-> run mandatory SA60-primary and R95-primary; add joint point only when feasible
-> evaluate raw/hidden unit and sequence-derived evidence
-> run M4 formal, fixed M4->MIR transfer and all-discovered Test Demo objective regression
-> keep B4-60-silence-official-shadow-v1 as zero-writeback historical control
```

Hard requirements:

- old detector experiments do not continue;
- audio and lyrics remain correctly corresponding in the primary repeated-section experiments;
- a mutation attempt is not enough: pre-registered effective cumulative-error quotas must be met or bounded-budget insufficiency must be reported with the full attempt denominator;
- `window_decision`, route planning and simulation must have one consistent execution semantics;
- Test Demo statistics feed automated regression gates and case mining, not merely later manual viewing;
- decoder ablations remain separate from route/threshold/family matrices;
- SA60 and R95 experiments both run even if one joint double-threshold operating point does not exist.

## 2026-08-05 Detector V2 Current Stage Override

The active planning entry is now:

```text
docs/research_v7_align_behavior/README.md
docs/research_v7_align_behavior/18_DETECTOR_V2_EXPERIMENT_PLAN.md
docs/research_v7_align_behavior/19_DETECTOR_V2_AGENT_CONTRACT.md
docs/research_v7_align_behavior/20_DETECTOR_V2_IMPLEMENTATION_BLUEPRINT.md
docs/research_v7_align_behavior/21_PREVIOUS_DETECTOR_RESULT_CORRECTIONS.md
```

Current stage:

```text
Detector V2 contract / metrics / coverage gate merged
→ audit GT, source-song split, hidden extraction and request identity
→ build product-like crop/cursor/end-early/repeat/acoustic and matched multi-view evidence
→ freeze H/R/O/V features, models, tri-state thresholds and interval post-processing on validation
→ run M4 heldout, family-LOO, M4→MIR, stress and real serial closed-loop evaluation
```

Completion is governed by the coverage matrix. Missing a required non-zero-denominator artifact means
`partial_exploratory=true`, not detector completion. The older entries below are preserved for history;
where they conflict with documents 18–21, documents 18–21 take precedence.

## Previous 2026-08-03 Stage Override (preserved)

The active planning entry is now:

```text
docs/research_v7_align_behavior/README.md
docs/research_v7_align_behavior/00_EXECUTION_PLAN.md
docs/research_v7_align_behavior/01_USER_DECISIONS_AND_RATIONALE.md
docs/research_v7_align_behavior/08_AGENT_HANDOFF.md
```

Current stage:

```text
research v6 formal E0–E9 completed
→ repair E1 event aggregation, E5/E6 paired subsets and conditional denominators
→ freeze old negative results rather than tuning them further
→ research production-like invalid-input alignment behaviour
→ prioritize strict-serial same-audio short-text, sparse slots, percentage text mismatch, posterior and official repair trace
→ only after evidence collection decide QualityAssessor, posterior decoder, coarse localization and transactional realign
```

Important user decisions:

- E3 decoder-only local repair is stopped;
- extra/missing text severity must be percentage-based, not only +2/+5 units;
- strict serial workflow is the primary new E4 route;
- no-match uses frozen same-language, same-length cross-song real lyrics;
- no-GT full-song Demo must become structured evidence and heldout data;
- detector may improve later, but it cannot currently write back;
- serial alignment is a candidate architecture, not the project definition.

---

## Previous Entry (preserved)

## Read in this order

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/sessions/20260728_multilingual_inline_realign_completion_archive.md`
5. `docs/sessions/20260728_inline_realign_followup_experiments.md`
6. `docs/manual/inline_realign_smoke_formal.md`
7. `docs/sessions/20260727_inline_realign_smoke_formal_archive.md`
8. `docs/sessions/20260727_inline_realign_discussion_and_experiment_plan.md`
9. `docs/archive/20260727_inline_realign_archive_validation.md`
10. `docs/sessions/20260727_realign_demo_silence_aware_window_archive.md`
11. `docs/sessions/20260727_mir1k_demo_diagnostic_experiment.md`
12. `docs/principles.md`

## Current stage

```text
first Qwen FA LoRA cycle archived
-> shared-raw four-way Demo exposed official/raw, anchor and tail problems
-> GT-oracle showed local realign can repair some errors; direct stable-cursor replacement was negative
-> multilingual all-discovered Test Demo and the complete shadow suite are implemented
-> current focus: server smoke/formal for detector P/R, clean harm, exact/+2/+4, expansion guard, pending and rollback
-> all alignments finish before batch rendering and optional link-only publishing
-> do not enable automatic writeback before GT-backed follow-up evidence
```

## Current executable entry

```bash
bash scripts/demo/run_inline_realign_smoke.sh
bash scripts/demo/run_inline_realign_formal.sh
```

The pipeline runs:

```text
manifest/input audit
→ B0-B3 or B2-only alignment according to bounded variant_set
→ localized precommit detector + GT-oracle local-realign capability test
→ stable segments actively propose/re-run next-window transcript starts
→ forced +25%/+50% future-text expansion
→ all Demo align first, then one-directory official rendering
→ compact result summary and evidence capped at 8 MiB
```

## Canonical facts

- official timestamps are structurally better than raw in the current six-Demo evidence;
- current O0 is not equivalent to the old R2 vocal-window path because shared raw planning controls lyric ownership and cursor;
- current post-hoc realign wrote almost nothing, mainly due to anchor filtering and late insertion;
- fixed 16-character, fixed 12-second, fixed line-count and hard two-window-observation anchor rules are rejected;
- stable references are contiguous segments searched within one or two adjacent windows;
- future-lookahead text is not treated as a true repeated acoustic observation;
- strong silence no longer bypasses confidence/context checks;
- current inline realign is shadow-only and cannot change serial ownership/cursor;
- MIR-1K held-out is excluded unless explicitly requested after rules are frozen;
- M4Singer defaults to validation; synthetic-long and natural full-song results remain separate;
- formal uses every discovered+prepared Test Demo by default; current song counts are input metadata, never hard-coded limits; smoke samples one item per discovered language;
- MIR-1K development/spare and M4Singer remain bounded development datasets; M4 synthetic-long is stratified at 60/120/180 seconds and synthetic seams are reported separately;
- evidence excludes audio/video/weights/full logs and automatically shrinks full→anomaly→severe; partial item failure still proceeds to bounded collection when the experiment summary exists;
- Demo is required by the wrappers; rendering starts only after every item finishes alignment and uses only `items/<id>/render/official.mp4`.
- follow-up summaries keep automatic candidates, GT oracle, stable-window assistance, expansion, planner divergence and constructed incomplete results separate.

## Current unknowns

- whether 30 seconds itself is weaker than 60 seconds;
- whether silence-aware boundary movement is beneficial;
- how much shared raw planning causes official degradation;
- whether selected→final compression is the dominant secondary collapse;
- stable-segment GT precision and clean harm;
- whether stable-prefix failure predicts propagation early enough;
- whether exact/+2/+4 consensus improves the accepted repair set without clean harm;
- automatic detector case/unit precision and recall;
- whether stable-prefix failure rejects dangerous future-text expansion early enough;
- whether cross-window pending confirmation and severe-tail two-window rollback improve GT;
- whether current B1/B2 differences remain after excluding text-expansion failures;
- whether multilingual Test Demo exposes language-specific unit/tokenizer failures.

## Constraints

- no automatic local writeback before shadow evidence;
- no threshold selection from Demo listening or structural metrics alone;
- no MIR-1K held-out tuning;
- no mixing M4 synthetic seams with natural MIR-1K conclusions;
- no unconditional tail commit as a future repair strategy;
- checkpoints, audio, video and large runtime outputs stay external.

## 2026-08-04 长时间线 Slot/串行混合与子区间判别器（review 后修订）

当前冻结入口：

1. `docs/research_v7_align_behavior/13_LONG_SLOT_REGION_ASSESSOR_EXPERIMENT_PLAN.md`
2. `docs/research_v7_align_behavior/14_AGENT_EXECUTION_CONTRACT_12H.md`
3. `docs/sessions/20260804_align_behavior_slot_region_assessor_archive.md`

当前方向：

```text
≥90 秒、以 ≥180 秒为主体的数据时间线
+ fixed 60s acoustic requests
→ 连续/非连续 sparse slots 与真实串行组合
→ absolute-unit + percentage 文本错误
→ missing gap / replace 双向评价
→ raw / official / hidden 逐 unit/gap evidence
→ 95/99 operating points：unit、75% interval、100% interval
→ 跨域 region assessor、有限复查、unresolved 和后续重新入轨
```

硬约束：formal 目标 10 小时、硬上限 12 小时；禁止人工静音凑长数据；baseline 必须按完整 request identity 配对；机制消融与系统配置分开；density 使用 common units 和 phase 轮换；英文不得切断单词，日文不得切断 processor 最小对齐 unit；人工 review 结果与标签已经存在，须先定位审计，不得继续写“未填写”。

## 2026-08-05 Detector V2 执行快照（压缩上下文前的续接点）

阶段进度（最新优先）：
- **Phase3-1 完成**：M4 song-heldout + family-LOO 真实结果已落盘 run1/
  （M4_SONG_HELDOUT.json：raw reject_recall=0.909/protected_recall=0.999/interval@75=0.948；
  official reject_recall=0.883/protected=1.000/interval@75=0.990；family-LOO 全 family protected≈1.0，
  crop_early 最弱 0.641）。真实结果证明 detector 有效（protected≈1.0、long interval 零全接受）。
- **Phase2 完成**：signal atlas（单信号弱判别 AUC 0.46-0.53，需组合）+ train/freeze 真实跑通
  （raw/official 最优组合 O，H 五组合 blocked，T_accept≈0.835/0.845、T_reject≈0.865/0.870）。
- **Phase1 完成**：run1 真实 forward 740 请求（51 边界失败已修）+ converter（137k rows）+ labeling
  （unsafe_rate 91.4% 合成轴口径，gt_unavailable ~60%）。
- **Phase0 完成**：labels/evidence/identity/gt_split + 402→410 测试。

**下一步（未完成）**：
- Phase3-2 serial closed-loop（detector_v2_serial.py 已侦察未实现：/tmp/opencode/wt_a 分支 detv2_serial）
- Phase3-3a M4→MIR 跨域（MIR anomaly manifest 已建 974 行在 /tmp/opencode/wt_c/out；真实 forward 未跑）
- Phase3-3b coverage matrix 全绿 + 18 交付物核对 + completed/partial_exploratory 判定

关键产物：/home/hyan/Data/lyricalign/runs/research_v7_detector_v2/run1/（FROZEN_OPERATING_POINTS/
MODEL_SELECTION/M4_SONG_HELDOUT/FAMILY_LOO/LABEL_SUMMARY/RUN_NOTES）+ manifests/（ANOMALY 740 行）。
代码：main 分支（408+ 测试）；opencode.json 已配 steps=8；运行约定见 AGENTS.md。

## 2026-08-06 Detector V2 完成快照（detector_v2_completed=true）

**Detector V2 主线全部完成**：Phase0-Phase3-3b 全部收尾，11 项完成定义全过（19 §7），
DETECTOR_V2_CONCLUSION.json 判定 detector_v2_completed=true、partial_exploratory=false。

### 真实结果（全部落盘 runs/research_v7_detector_v2/）
- M4 song-heldout：official reject_recall 0.883、protected_recall 1.000、interval@75 0.990、
  long 区间零全接受；raw reject 0.909/protected 0.999
- family-LOO：end_early 0.957 最强、crop_early 0.641 最弱（n_test=64）
- M4→MIR 跨域（weak_labeled_qwen_fa，21 §1 不混合）：official reject 0.894/protected 1.000/0 误拒
- serial closed-loop：all_commit 错误提交 0.75 vs detector 0.000（零错误正式提交；
  run1 标签口径 unsafe 91.4% → detector 极端保守，提交率低）
- stress（replace/missing 1/2/4/8 + repeated + acoustic）：accept_rate=0.000（零误提交）；
  acoustic 文本未变 → 有真实 GT（reject 0.959/protected 1.000）
- coverage matrix：final + validator ok（0 errors）；RUNTIME_BUDGET 10h 预算内

### 关键代码（main 分支，427 测试）
- detector_v2_serial.py：4 路线串行闭环（review 后：variant mtype 修复、传播仅 committed 窗、
  series_premise 声明窗无共享 units）
- evaluate_m4_to_mir.py：跨域打分 + scoring_subset 声明
- evaluate_stress_detector_v2.py：动态 gt_kind（acoustic 有 GT → labels）
- build_detector_v2_anomaly_manifest.py：--replace-counts/--missing-counts（集合过滤裁剪）
- train_detector_v2.py build_matrix keep_labels 参数
- label_detector_v2_run.py --gt-valid-statuses（MIR ground_truth_character）

### 收尾提交
- ba01da2（stress）+ f42d64f（review fixes）+ 之前 76ad422/dfb77dd

### backlog（非阻塞）
extra stress 未跑（矩阵 partial）；crop_early LOO n_test=64；标签为 rule-based weak
supervision 非人工 GT；detector 保守性成本/收益未权衡；H gate 明确失败（hidden 不可提取）。

## 2026-08-06 Detector V2 返工完成快照（partial_exploratory=true）

**22 文档 Phase A-D 返工全部执行完毕**，判定 DETECTOR_V2_CONCLUSION.json：
detector_v2_completed=false, partial_exploratory=true（22 §11 清单 12/13，serial
propagation=0 未满足）。

### 关键成果（全部落盘 runs/research_v7_detector_v2/）
- Phase A 坐标修复：M4 unsafe 91.4%→7.2%（全局 GT + sparse 分母）；signal atlas
  AUC 0.462→0.954（因果证据）
- Phase B：20/5/5 song-grouped + 4 模型阶梯 + 双约束冻结（constraint_violated 如实）；
  official small_mlp prot 0.999/safe 0.047（val）；trade-off 表公开（GBDT 0.901/0.857）
- Phase C：M4 heldout prot 0.998/safe 0.081；M4→MIR prot 0.996/safe 0.135；
  STRESS（含 extra 1/2/4/8）GT prot 0.93-1.0、replace/missing/extra accept 0.87-0.93
  （弱检测负结果）；matched views agree 0.92-0.99
- Phase D：serial unit 级闭环（3 歌×5 重叠窗）：detector 86/1774 正确提交、
  multi-view 30 真实额外请求 → 9 增量提交；propagation=0（提交集小，验收 10 未满足）
- F1 校准：isotonic ECE 0.26→0.013、Brier 0.12→0.048（PBAD_CALIBRATION.json）
- F3 cross-view：数据缺失（posterior 未采集）→ 负结果记 backlog

### 代码状态
main 分支 442 测试全绿；提交链 42522c3→0b3576a（含 review 修复 0ceb1fc、
extra 修复 945f883）。关键脚本：train_detector_v2（model_kinds/min_safe_accept_rate/
labels-path）、evaluate_detector_v2（frozen model_kind 回填）、detector_v2_serial
（unit 级/serial-mode/train-root）、build_detector_v2_serial_manifest、
evaluate_stress_detector_v2、analyze_pbad_calibration、cleanup_run_cache。

### 存储
40G 预算内（当前 ~17G 含新增）；清理脚本 dry-run 可回收 14.5G
（cleanup_run_cache.py --apply）；STORAGE_CLEANUP.md 已写。

### 下一步（backlog）
1. serial 传播观测：降低保护点（GBDT 端点）或增大提交预算重跑
2. safe_accept 提升：isotonic 校准后重冻结阈值（F1 已验证校准有效）
3. stress 弱检测：窗口级文本扰动的特征工程（repeat 已稍强）
4. F3 需 multiview posterior 数据采集（forward 保存）
5. explore 方向报告 → docs/23_FUTURE_DIRECTIONS.md（repair 闭环 > 校准 > CNN1D）

## 证据包（2026-08-06 打包完成）
- 未压缩 3.4MB：`/home/hyan/Data/lyricalign/runs/research_v7_detector_v2/EVIDENCE_PACK_20260806.tar`
- 压缩 345KB：`/tmp/opencode/detector_v2_evidence_pack_20260806.tar.gz`
- 包结构：00_MASTER_CONCLUSION（最终结论，主线+自由探索）/ 01_mainline（核心产物+展开表）/
  02_exploration（F1 校准+F3 负结果+方向摘要）/ 03_reproduction（复现+环境+代码清单）/
  04_docs（22/23 文档+session entry）/ 05_samples（LABELS 260/组抽样、evidence 行、GT+timeline 抽样）

## 2026-08-06 探索批次（23 方向 2/3/4，子 agent 并行 + 2×review）
- 方向 2 SGCV 校准+成本模型（analyze_pbad_calibration_sgcv.py）：20 歌 5 折 CV raw ECE
  0.257±0.012 → isotonic 0.0197±0.0040（official 0.0205±0.0043）；temperature 差；
  单次 5 歌 val 有轻度乐观偏置（0.013）；cost model：C3<<C1 时 uncertain 带无价值，
  最优审查阈值 = T_reject。产物 exploration/sgcv_calibration.json。
- 方向 3 CNN1D 公平比较（evaluate_sequence_cnn1d.py）：T=4465 序列数据集 + 三方对比；
  CNN1D 收敛但窗口级广播评价 degenerate（protocol=0，small_mlp 0.798 领先）→ 探索性
  负结论（序列级 any-unsafe 监督广播无区分度，需序列级评价或逐窗口监督）。
- 方向 4 cross-view 审计（audit_cross_view_signal.py）：**结构性缺失**（134538 行 0 行
  posterior；request 单 view；离线不可重算）→ F3 None 根因确认，复活需请求管线落盘。
- review 结果：2×并行（代码/契约 + 数据/接线）→ P0 无；P1-1 行序错位（CNN1D 窗口
  指标口径）已修（window_indices/y_window 对齐 + 2 个回归测试）；P1-1 label 口径
  （audit 全为 official target）已修（label_target 声明 + 优先 official）；P2 修复：
  max-songs 空集、T_accept 缺失防御、song_id 缺省禁止降级、ECE bin0 边界、死代码、
  degenerate 标注、created_at。23 文档已回填结论。L2 463 passed。

## 2026-08-06 总体 review（2×并行，对照 18/19/20/21/22/23）
- P0：无。主线路唯一硬性未达标 = serial propagation=0（22 item 10，已登记
  detector_v2_completed=false / partial_exploratory=true，coverage 如实 partial）。
- 已处理：① CONCLUSION key_results.family_loo 数字 0.832/0.485 与产物不符
  （FAMILY_LOO.json 真实值 crop_late 1.0/safe 0.0817、end_late 1.0/safe 0.0952）
  → 已修正 CONCLUSION（旧数字仅存于旧 run1/mir_run manifest，21 纠偏已弃用）；
  ② exploration 三产物未入证据包 → 已生成 EVIDENCE_PACK_20260806_EXPLORATION.tar
  （6.3MB：3 JSON + 3 脚本 + 修正后 CONCLUSION）；③ audit 补 created_at。
- 确认无 P1：旧路径残留仅 build_detector_v2_anomaly_manifest.py docstring 引用
  formal_manifest_v3（该目录保留中，引用合法）。
- 待办 backlog：重冻结阈值（isotonic 后，safe_accept 优化）、序列模型三选一决策
  （detector_v2_models.py:423 未实现，需实现或显式降级）、F3 posterior 管线采集、
  stress 特征工程、19 §6 三交付物缺失登记（PRECHECK_DETECTOR_V2/HIDDEN_
  EXTRACTION_AUDIT/REQUEST_IDENTITY_AUDIT，22 复审以等价证据通过未登记）、
  serial 传播可观测 → 移交 research_fullslot_serial_detector 新阶段。
