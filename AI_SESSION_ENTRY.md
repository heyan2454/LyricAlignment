# AI Session Entry

## 2026-09-14 夜班追加（addendum，非 override）

一夜的验证轮：一条 GPU 主线（均匀重训 12000 步）+ 两条新臂（长流拼接、热启动 A/B 上采样）
+ 十余项零推理/低算力分析。全部细节见 `docs/status/20260914_night_report.md`（由脚本从
`results/by_run/**` 的 JSON 生成，缺数据显示「未跑」而不是沉默）。

后续轮次**不得重新假设**的八件事：

1. 「重训≈旧模型」是**错的**。早上那次结论来自被漏斗名额饿死的选点集合（只能评 step 1100–1450）。
   同协议全量复评：MAE 47.16 → 43.87 ms，逐字符配对 −4.21 ms（z=−4.97，n=9397）。
   但**周期终点曲线在第 4 个周期（step 8000）就饱和**（+0.93/+0.34/+0.19/−0.08/+0.03 pp），
   所以"再挂同样配置继续训"没有收益。见 `20260914_retrain_verdict.md`。
2. 长音符问题的**共同因子是字符时长**，不是流长、不是窗口边缘、不是分母口径：真歌批逐歌塌陷率与
   中位字符时长 **r=+0.815**；距窗口边界 0–0.5 s 处零长度 8.6% vs 10 s+ 处 10.9%（边缘假说**证伪**）；
   20 s/60 s 长流视图的退化只有 0.43/0.6 pp 且**漂移曲线是平的**。
3. 机制的**准确表述**（08:05 由置信度×时长交叉修正）：模型的**典型**预测并不收缩
   （每个「时长桶 × 熵四分位」格子里中位长度比都是 0.97–1.03）；收缩与偏早是**失败子集的条件性偏差**
   （≥2s 失败子集长度比 0.538、中点 −490 ms，而全体看起来正常）。
   同时真正稳定的信号是：**不确定性随时长急剧集中**——落在最低置信四分位的比例
   0–0.5s 14% → 0.5–1s 30% → 1–2s 67% → ≥2s 80%。
   教训：混池相关 r=+0.41 看着支持"回归到众数"，**分桶后全为 0**，那只是时长混杂 ⇒
   任何"模型偏向常见时长"的说法必须**在时长桶内**检验。
   对照臂 A（未改配比续训 600 步）在长字符结束点上**只有迹象**：均值 +9.55 ms，但**中位数与 2% 截尾
   均值均为 0.00**、McNemar 0/5（p=0.062，×4 校正后 0.250），四位置里挑最差来讲 ⇒ 未过任何校正，
   **不构成因果确证**。同一把尺子复查整条训练史（750→12000）：短字符结束点改善是**确证**
   （−2.86 ms，McNemar 39/17，p×4=0.018），**长字符结束点的改善是无证据**（−5.22 ms，p×4=0.862）
   ⇒ 不要再说"长音随训练改善"。读 B 时仍建议同时报 **B vs 起点** 与 **B vs A**（预防性，不依赖该迹象）。
   **强制流程**：任何按位置/子集分开报的配对效应，必须同时给①中位数+截尾均值②二项 McNemar
   ③对所考察位置数 ×K 校正；不同向只能写"迹象"（`scripts/evaluation/paired_robustness_check.py`）。
4. **不重训的四条路全部实测到边界**：同 logits 内重排（容差内质量中位 0.142、0/9 > 0.5）、
   约束解码（真歌上替代点证据更高仅 46%/51% ≈ 抛硬币 ⇒ 只修合法性）、
   跨窗共识（**更差** +18.7 ms，z=+9.9）、事后时长校准（无收益：2.60% → 2.63%）。
5. **DP 解码是今晚唯一到手的免费精度**：全量同一批 logits 下 0.9784 vs argmax 0.9743
   （配对 −2.24 ms，z=−5.27），可用率 1.0000；长流视图对三个存档各约 +0.95 pp。
   但**结构合法 ≠ 正确**：真歌重度塌陷区里 DP 会秒级重排，所以 **DP 必须与置信度门控同时上线**
   （否则零长度/重叠这两个唯一自动探针会全部变绿）。代码已备好且默认路径逐字节不变：
   `QwenForcedAligner(..., timestamp_decoder="dp")`。
6. 置信度门控可用且**跨歌泛化**：真歌批按歌留一，复核 10% 消除 55% 塌陷（剩余 5.43% vs 原 10.80%）。
   **注意口径**：`export_review_gating.py` 的实测数字与「按歌留一交叉验证」是**同一次计算的两种呈现**，
   不是两条独立证据；真正独立的印证只有 2026-09-12 在 GTSinger 上测到的熵 AUC 0.913
   （不同语料、不同会话；今晚真歌 AUC 0.9227）。工具：`scripts/evaluation/export_review_gating.py`。
7. **数据路径无法补长音暴露**：GTSinger 全库仅 300 个 ≥1s / 70 个 ≥2s；MIR-1K 这份发行
   没有字符级时间边界（要用就得伪标签，已被禁止）。条目级上采样又**自我稀释**
   （含长字符的条目占 38.8% 字符 ⇒ 份额增益饱和于 ×2.58）。若字符级 loss 加权（C 臂，
   代码与预注册已备好）也无效，剩下的只有**结构改动**（时间戳头改为起始+时长参数化）。
8. 口径纪律（今晚我自己栽过的坑）：机制类绝对数字必须确认 **split 过滤**（早先 dump 混入 1042 条
   训练条目，已加 `--splits` 默认 validation + `--allow-test` 防火墙）；≥2s 在验证集只有 137 个字符，
   **不可单独作决定性数字**（配对 SE 13.8 ms，见预注册 §3i）；报告数字必须由脚本从 JSON 生成，
   我手抄一次表格就把 −0.46 pp 写成了 −1.38 pp。

## 2026-09-12 GTSinger Ground-Truth Deep Analysis — Addendum (not an override)

A CPU-only round re-read the already-produced `evaluation_v1` GTSinger runs at unit level
(no new GPU forward, no new training, ~8 MB added to the data dir):

```text
docs/sessions/20260912_gtsinger_gt_deep_analysis/README.md
reports/progress/20260912_gtsinger_gt_deep_analysis.md
results/by_run/20260912_gtsinger_gt_deep/metrics.json
```

Thirteen things later rounds must not re-assume:

1. The 3x2x2 evaluation matrix is degenerate — `mix`/`vocal` were fed the same wav and
   `full`/`windowed` coincide on short clips, so those runs contain no audio-input or planning-mode
   evidence at all (redundancy factor 3.4x).
2. In the *demo* official pipeline, post-processing is net negative against real ground truth at
   100 ms (overlap resolution pins a start to the previous end in 98% of moved cases). Replaying
   rule variants on the same panel shows the fixable headroom is +2.4 pp and a plain
   "trim the earlier tail + 0.05 s minimum duration" rule captures 88% of it. This does **not**
   transfer to the research_v7 official stage, which touches 1.2% of units and is neutral there.
3. Decoder entropy plus cross-configuration disagreement are real-GT-validated no-GT error signals
   (grouped-CV AUC 0.913 on GTSinger), but entropy detects *gross* errors: AUC 0.78 at 100 ms versus
   0.93 at 250 ms on the long-form panel. Use it as a re-align trigger, not as a refinement judge.
4. On **natural Mandarin with human per-character GT** (MIR-1K partial-align, 2,035 chars / 17 real
   accompanied songs, six retained predictors) the aligner reaches hit@100 91.8-92.3% and the r0->r1->r2
   ladder reproduces (+16.4pp / +0.4pp), but the failing position is the **last character of an item**
   (82.3% vs 91.1% middle, with the sign of the offset flipping per checkpoint), accuracy is unrelated to
   item *duration* (r=0.003) while it rises with lyric *density* (r=+0.31), and error clustering is much
   weaker than in studio clips (42% of bad units in runs >=2 vs 67.6% on GTSinger) — region-level
   realign gains must therefore be calibrated per domain. See
   `reports/progress/20260912_mir1k_natural_panel.md`.
5. **Multi-view consensus over existing inference configurations is not worth GPU.** On the natural
   Mandarin panel, the best deployable selection (median / agreement-cluster over 5 configurations) gains
   +0.34 pp hit@100 while a per-unit oracle pick over the same members would gain +4.57 pp — consensus
   closes only 7.4% of that gap, gated variants give +0.10 pp for 8% re-compute budget, and
   leave-one-out median fallbacks are *negative*. Averaging also *damages* the last character of an item
   (82.4% -> 76.5%). See `reports/progress/20260912_mir1k_natural_panel.md` section 5b and
   `src/lyricalign/analysis/multiview_consensus.py`.
6. The last-character deficit is a *long-note tail* problem, not truncation: last characters average
   1.43 s of ground-truth duration (middle: 0.43 s), start sides are fine (94.1%), ends are not
   (88.2%), and only 11.8% of last-char failures are shared by every predictor.
7. The retained 2026-08-14/15 real-song "B4 vs Current" pair is **not an identified contrast**: their
   window plans are field-for-field identical and 99.92% of the 10,909 units agree within 100 ms, while the
   only genuinely different view (`full_slot`) drifts on 23.6% of its indices and records no audio hash or
   schema version. Cross-view work on natural long songs therefore has **no usable evidence base** yet, and a
   comparability gate (same text per index + same audio sha + different plan) is now implemented in
   `src/lyricalign/analysis/real_song_views.py`.
8. The long-form panel is **per attempt, not per unit**: a row is one (request_identity, view_id,
   canonical_unit_id) and the 134,538 rows cover only 14,441 lyric units (fan-out 9.3x, up to 24 windows
   per unit), so row-level statistics are attempt-weighted; the correct unit key needs `song`
   (`view_id, song, canonical_unit_id`). Unit-level medians are better than attempt-level (87.33% vs
   84.97% raw hit@100) while worst-attempt is 73.65% — long-form risk is per-unit variance, not the mean.
9. A single **joint constrained solve** (min 50 ms, max 3 s, monotone starts, no overlap, weighted-L1 to
   clipped raw, weights from recorded boundary entropy ranks) is the first cleanup change that validates
   positively on human GT: GTSinger hit@100 83.59% vs 81.57% shipped (+2.02pp), degenerate 4.61%->0%,
   MAE 101.2ms; accuracy-neutral on natural long-form (86.57% vs 86.54% raw) and the only rule reaching
   0% degenerate/overlap/regression on 25 real accompanied songs. See
   `src/lyricalign/analysis/joint_cleanup.py` and `reports/progress/20260912_joint_cleanup.md`.
10. The long-form panel's `label_*_err_sec` are **unsigned**, so `raw − err` cannot recover the
    reference (± ambiguity, previously misread as "24% of units disagree across attempts"). The verified
    reconstruction is `segment timestamp_class_ids × 0.08 s + segment_offsets.global_start_sec`
    (`src/lyricalign/analysis/longform_signed_gt.py`): it reproduces the frozen errors with **max deviation
    0.0 s** on both stages, and shows the panel's own `gt_*` axis agrees with raw only 15.9% of the time vs
    89.1% for the rebuilt reference.
11. **Long-form risk is window choice, not decoder quality**: an arbitrary single covering window scores
    84.81% hit@100 vs 86.95% for the cross-window median attempt (worst attempt 64.85%, MAE 1.85 s). A
    label-free support selector (most peers within 50 ms) reaches 87.55% (+0.60 pp, 18% of the 3.33 pp oracle
    gap) while entropy/margin add only +0.09/+0.16 pp, and *placing the unit centrally in its window is
    1.15 pp worse* — which undercuts "re-crop to centre the hard unit" realign designs. See
    `reports/progress/20260912_cross_window_selection.md`.
12. For long-form, the deployable output should be the **cross-window consensus** (median boundary over
    the windows covering a unit): +2.14 pp hit@100 over an arbitrary single window (86.60% vs 84.46%) and
    MAE 271->117 ms, free of cost. Adding the round-7 joint solve on top yields zero degenerate/overlap/
    regression units and the best deployable MAE (102.4 ms) for −0.53 pp. **Only 40% of units have ≥2
    attempts**, so consensus needs deliberate multi-view generation to cover everything.
13. Cross-window *disagreement* is a poor realign trigger (AUC 0.584 for >100 ms, 0.705 for ≥250 ms; its
    error-capture curve is near random: 20% budget catches 26.9% of errors) — **boundary entropy remains the
    best trigger** (0.779 / 0.881), reproducing rounds 1/3/5. Also corrected this round: the −0.5 pp cost of
    the joint solve is *not* the 3 s duration cap (3/6/12 s give 86.07/86.08/86.08%) but the non-overlap and
    monotone constraints themselves.
14. `LONG_TIMELINE_MANIFEST.canonical_units[*].start_sec` is a **fabricated uniform axis**, not
   ground truth: joining predictions to it yields hit@100 = 5.3% where the frozen real-GT labels give
   87.9%. Any reuse of `research_v7_detector_v2` evidence must reconcile recomputed errors against
   that run's frozen `LABELS.jsonl` before believing a number (see `uniform_axis_trap`), and run1's
   reference timeline is already gone from disk (evidence is therefore un-reusable).

Forward determinism was verified positively: the same request identity reproduced a bit-identical
raw stage across two independent forwards (0/28,980 units differing), so content-addressed evidence
reuse is sound *when the reference artifacts are retained*.

## 2026-08-16 Lyric Align Dataset Acquisition & No-Training Evaluation — Newer Session

A newer 2026-08-16 session exists and is the current focus:

```text
docs/sessions/20260816_lyric_align_dataset_acquisition_evaluation_strategy/README.md
docs/sessions/20260816_lyric_align_dataset_acquisition_evaluation_strategy/00..06_*.md
```

Direction (as stated in that session's own README): dataset acquisition plus a
no-training evaluation-v1 / productization research line. This entry only points
the way; it does not rule on how this session relates to the 2026-08-14 session
or to the current mainline — verify and judge for yourself before relying on either.

## 2026-08-14 Unit Realign Recovery + Visualization — Active Override

The active planning entry is now:

```text
docs/sessions/20260814_realign_recovery_visualization_overnight/README.md
docs/sessions/20260814_realign_recovery_visualization_overnight/00_SESSION_DISCUSSION_RECORD.md
docs/sessions/20260814_realign_recovery_visualization_overnight/01_CURRENT_EXPERIMENT_RESULTS_AND_CONCLUSIONS.md
docs/sessions/20260814_realign_recovery_visualization_overnight/02_NEXT_ROUND_EXPERIMENT_DESIGN.md
docs/sessions/20260814_realign_recovery_visualization_overnight/03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md
docs/sessions/20260814_realign_recovery_visualization_overnight/04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md
docs/sessions/20260814_realign_recovery_visualization_overnight/05_CODEX_HANDOFF.md
docs/sessions/20260814_realign_recovery_visualization_overnight/06_PLANNED_RUNS.yaml
```

Read 00--06 in order. Codex first verifies current code/provenance and writes `07_CODEX_IMPLEMENTATION_PLAN.md`; only then hand the implementation work packages to OpenCode/agent.

Current stage:

```text
freeze exact Current/B4 baselines and scientific identities
-> build a thin visualization adapter and Side by Side smoke
-> study multi-realign dynamics, fine-grained splitting and audio recrop/multi-view
-> pilot R-U coarse proposal -> bounded sparse/fixed refinement
-> expand only mechanisms with evidence of strict recovery and acceptable context safety
-> evaluate real no-GT candidate/safety signals without GT leakage
-> grow recovery-basin atlas and real serial accumulated-error stress tests
-> render B4-vs-Current and Current four-way diagnostic videos
-> continue free exploration after the main plan or GPU cap unless the user interrupts
```

Hard requirements:

- `actual_writeback=0`;
- no-GT control/ranking code cannot read GT; GT is evaluator-only;
- do not treat fixed-point, multi-view consensus or context displacement as correctness sufficient conditions;
- do not treat legacy/compat R-B data as genuine bilateral-anchor evidence unless provenance checks pass;
- avoid Cartesian products; screen mechanism-level variants first and expand only 1--2 useful routes;
- collection must complete before visualization; presentation rerender cannot repeat Qwen forwards;
- target GPU <=10h, hard cap <=12h; after cap continue CPU analysis, hard-case mining, cached exploration and the recursive free-exploration todo loop.

The previous 2026-08-12 and 2026-08-13 sessions remain authoritative historical evidence, but this 2026-08-14 session wins for next execution when conflicts exist.

---

## 2026-08-12 Realign Recovery — Active Implementation Override

The active planning and implementation handoff is now:

```text
docs/sessions/20260812_realign_recovery_research/README.md
docs/sessions/20260812_realign_recovery_research/00_SESSION_DISCUSSION_RECORD.md
docs/sessions/20260812_realign_recovery_research/01_CURRENT_RESULTS_AND_CONCLUSIONS.md
docs/sessions/20260812_realign_recovery_research/02_FROZEN_BASELINE_AND_SCOPE.md
docs/sessions/20260812_realign_recovery_research/03_REALIGN_EXPERIMENT_PLAN.md
docs/sessions/20260812_realign_recovery_research/04_EXECUTION_CONTRACT.md
docs/sessions/20260812_realign_recovery_research/05_FREE_EXPLORATION_PROTOCOL.md
docs/sessions/20260812_realign_recovery_research/06_DEFERRED_CORRECTION_ITEMS.md
docs/sessions/20260812_realign_recovery_research/07_OPENCODE_IMPLEMENTATION_INDEX.md
docs/sessions/20260812_realign_recovery_research/08_PHASE0_BASELINE_GT_FIREWALL.md
docs/sessions/20260812_realign_recovery_research/09_CORE_CONTRACTS_AND_RUNNER_WORKPACKAGES.md
docs/sessions/20260812_realign_recovery_research/10_EXPERIMENT_EXECUTION_WORKPACKAGES.md
docs/sessions/20260812_realign_recovery_research/11_VALIDATION_REPORTING_AND_HANDOFF.md
```

Read 00--06 in order, then use 07 as the OpenCode entrypoint and consume 08--11 one work package at a time.  The only active research axis is Raw-triggered Realign/Recovery: oracle repairability, no-GT request proposal, repair-quality judgement, safe writeback, and serial closed-loop recovery.  All other baseline choices remain frozen.

Hard requirements:

- old synthetic-uniform timing results, including the historical 14--16% recovery values, are diagnostic only and cannot be cited as real-GT/no-GT capability;
- no-GT control code must neither receive nor read GT; join GT only in a post-run evaluator;
- create a fresh, resumable OUT_ROOT and freeze implementation/config/provenance before GPU work;
- run Phase 0 and its tests before any new model forward; do not restart old transition, decoder, planner, or detector feature-selection matrices;
- use a shared content-addressed candidate cache; analyses of thresholds, ranking and writeback must not repeat forwards;
- target GPU use is 10 h and hard cap is 12 h; after the cap, continue CPU analysis and the documented free-exploration loop unless the user interrupts.

The 2026-08-10 correction and earlier transition documents below are retained as historical evidence and implementation references.  When they conflict with the active 2026-08-12 session, the active session wins.

---


## 2026-08-07 Transition–Recovery–Detector Reviewed Stage Override

The active planning entry is now the reviewed Transition–Recovery–Detector stage:

```text
docs/research_transition_recovery_detector_20260807/README.md
docs/research_transition_recovery_detector_20260807/00_FACTOR_MODEL_AND_FREEZE.md
docs/research_transition_recovery_detector_20260807/01_MASTER_EXPERIMENT_PLAN.md
docs/research_transition_recovery_detector_20260807/02_TRANSITION_RECOVERY_MAINLINE.md
docs/research_transition_recovery_detector_20260807/03_LEGACY_GAP_COMPLETION.md
docs/research_transition_recovery_detector_20260807/04_DETECTOR_RESEARCH_PLAN.md
docs/research_transition_recovery_detector_20260807/05_DATA_METRICS_BUDGET.md
docs/research_transition_recovery_detector_20260807/06_AGENT_EXECUTION_CONTRACT.md
docs/research_transition_recovery_detector_20260807/07_REVIEWED_IMPLEMENTATION_PLAN.md
docs/sessions/20260807_transition_recovery_detector_discussion_record.md
```

`07_REVIEWED_IMPLEMENTATION_PLAN.md` is the implementation handoff and errata layer.  Where it
conflicts with the imported 00–06 planning documents or declarative YAML, 07 takes precedence.
The imported overlay and its SHA-256 manifest remain unchanged for provenance.

Current stage:

```text
inventory and freeze exact T0/T1/T2/T3 behavior
-> implement shared request/state/trajectory contracts and state-aware cache identities
-> qualify 3–5 s retained-silence preprocessing and original-clock mapping
-> run paired Transition pilot/formal and select product/mechanism candidates
-> collect natural/model-native/controlled propagation episodes
-> establish oracle L/W recovery bounds
-> freeze SA60/SA80/R95 detector points and selected new signals
-> execute real (not evidence-only simulated) L/W closed loop
-> run M4 formal, fixed M4-to-MIR transfer, and all-discovered no-GT Demo analysis
```

Hard corrections from review:

- exact per-window query text cannot be held equal after Transition states diverge; freeze the query-construction algorithm and share a model forward only while the full request identity is equal;
- the existing silence compressor retains only edge padding and does not implement the planned 3–5 second retained-silence rule;
- the existing strict serial demo maps most closely to T2 core-boundary serial; T1 and T3 still need explicit, tested state machines;
- the existing Detector V2 serial script is an offline evidence simulation, not a real retry/writeback closed loop;
- feature/model selection, threshold selection, and M4 formal must use four source-song-disjoint roles;
- the formal GPU target is 10 hours with a separate 12-hour hard ceiling and explicit reserve.

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
