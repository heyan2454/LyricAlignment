# OpenCode 实现方案：Detector Production Audit + Realign Gate

## 1. 已核实的基线与复用边界

- 冻结模型：`Qwen3-ForcedAligner-0.6B-hf`，revision `c07281df297b9905d24a508279258cccf987a064`，checkpoint `r2-step-000750`。
- 生产 baseline：60s core + 10/10s context，Raw decoder 为主。
- Raw detector：`standardized_logistic` / combo `R` / `light_merge`；`T_accept=0.16546343952822562`，`T_reject=0.16837782471409926`；artifact 为 `research_transition_recovery_detector_20260810_realgt_expansion_handoff/stage3b_cohort_ab_eval/FROZEN_OPERATING_POINTS.json`。
- 历史 detector 指标的权威字段是 `tri_unit_metrics.safe_accept_rate`、`tri_unit_metrics.protected_recall`、`interval_metrics.*`；实现不可自行改名或重定义。
- **历史比较 metric bridge（P1-3，实现前必须落地）**：`FROZEN_OPERATING_POINTS.json`（val frozen，n_val_units=761）是正式历史基线，直接读其 raw `tri_state_val`/`interval_val` 同名字段（raw `safe_accept_rate=0.8689`、`protected_recall=0.6552`）。retrospective-after-fix（safe accept≈0.8320 / protected recall≈0.9567）**只有文档 prose、无 exact artifact**，01_detector_audit 必须先尝试从 before/after source artifact 派生；若无法定位，必须标记 `not_reproduced_source_missing`，**禁止从 prose 填值**。retrospective 数字只能作为参考，与 audit 汇总并列时须标注口径差异（val frozen vs A cohort retrospective）。
- 真实 GT 唯一入口为 `src/lyricalign/research_transition_recovery_detector/real_gt.py::load_real_gt_with_audit`，来源为 `m4singer_overlay_slur_time_v1`。`LONG_TIMELINE_MANIFEST` 只能用于无 GT 的时间线/request 构造，不能作为 correctness GT。
- 旧 run `/home/hyan/Data/lyricalign/runs/realign_recovery_20260812_20260811T202813Z` 只读；其 E5/E7 产物可作为 schema 和 feature 实现参考，不能混入新运行的正式汇总。

## 2. 新增文件与复用 mapping

新增包 `src/lyricalign/realign_gate/`：

- `inventory.py`：枚举 real-GT source songs、可构造 60/10/10 window 的歌曲、现有 baseline/evidence/cache，及 Test Demo 音频+同名文本。
- `detector_audit.py`：复用 `candidate_scores.py`/`frozen_scorer.py` 的 Raw scorer 与 `detector_v2_intervals.py` 的 tri-state/light-merge；生成历史同口径 unit 与 window 汇总。
- `case_selection.py`：从 Raw baseline + real GT 形成 S1--S4 case 表；只在此模块读取 GT，输出的 request manifest 不得带 GT 字段。
- `behavior_metrics.py`：以 canonical unit id 配对 original/candidate，计算 displacement、locality、结构异常和 GT-only before/after 标签。
- `gate_features.py`：从候选 evidence 和 baseline detector 状态生成无 GT feature table；调用 `assert_no_label_leak`。
- `gate_analysis.py`：dev/holdout 分析、单变量扫阈值、2--3 条简单规则、counterexample 与 risk-coverage 汇总；不训练复杂模型。
- `test_demo.py`：动态发现 demo，复用 Demo parser/inference；以 Demo character index、Raw unsafe span 和 full-song rows 构造专用 narrow/anchor request，输出无 GT detector 与候选行为表。
- `report.py`：汇总各阶段、GPU 计数、失败、边界和结论强度。

新增 CLI `scripts/realign_gate/`：

- `00_inventory.py`
- `01_detector_production_audit.py`
- `02_realign_behavior_collect.py`
- `03_gate_feature_analysis.py`
- `04_test_demo_behavior.py`
- `05_report.py`
- `run_all.py`（仅编排，支持 `--stage`、`--smoke`、`--resume`）

复用但不修改核心语义的既有组件：

- request/proposal：`realign_recovery.e5_proposals.build_proposals`；本轮仅启用 original、R-A narrow 与 R-B anchor；禁用 oracle/R-C 的正式 GPU 矩阵。
- GPU forward：`scripts/research_v7/run_behavior_suite.py --real --resume`。
- GT firewall：`realign_recovery.gt_firewall.validate_no_gt_request`。
- candidate detector evidence：`realign_recovery.candidate_scores.evidence_rows_from_request` 与 `build_frozen_scorer_from_artifacts`。
- cache：`realign_recovery.forward_cache.ContentAddressedCache`；沿用其 forward-affecting identity，不把 gate/GT 写入 key。Detector audit 先复用 identity 相同的 Raw baseline/evidence；未命中的可用歌曲按冻结 60/10/10 Raw 配置补跑 baseline forward，并单列 GPU 计数。
- old/candidate binding：以 `extract_e7_per_unit_gt.py` 的 canonical mapping 为基线，并在新 evaluator 中补齐缺失/重复计数。

## 3. 输出目录和阶段产物

新运行根：`/home/hyan/Data/lyricalign/runs/detector_production_realign_gate_20260812_<run-id>`。

```text
00_inventory/ DATA_INVENTORY.json  DETECTOR_BASELINE_IDENTITY.json  TEST_DEMO_INVENTORY.json
01_detector_audit/ RAW_UNIT_METRICS.json  RAW_WINDOW_METRICS.json  PER_SONG.csv  CASE_POOL.jsonl
02_behavior/ CASES.jsonl  REQUESTS.jsonl  proposals/  evidence/  CANDIDATE_INDEX.jsonl
03_gate/ GT_PAIR_METRICS.jsonl  NO_GT_FEATURES.jsonl  ANALYSIS.json  COUNTEREXAMPLES.jsonl
04_test_demo/ TEST_DEMO_DETECTOR_SUMMARY.json  TEST_DEMO_SUSPICIOUS_WINDOWS.jsonl  TEST_DEMO_REALIGN_BEHAVIOR.jsonl
05_report/ FINAL_REPORT.md  FINAL_SUMMARY.json
00_meta/ CONFIG.json  COMMANDS.md  GPU_BUDGET.json  failures.jsonl
```

所有阶段写自己的输入路径、artifact SHA、实际 song/case 列表和失败行；不为严格重放额外扩大工程复杂度。

## 4. Paired GT 与标签定义（实现前冻结）

配对键为 `(song_id, canonical_unit_id)`，比较范围是 case `target_unit_ids`；request context 中的 anchor 仅用于 locality 特征，不进入 target 误差主分母。正式主指标不允许因为文本跨度不一致而回退到时间 IoU：不能 canonical-bind 的 candidate row 记为 extra，对应 target 记为 missing；不得静默丢弃或混入 seconds delta。时间 IoU 若保留，只能作为独立 diagnostic，不能影响 coverage、label、seconds delta 或 gate 分析。

- 每个 target unit 分别保存 `old_start/end_error_ms`、`new_start/end_error_ms`，其中 unit error 是 `max(|Δstart|, |Δend|)`。
- `old_missing`、`new_missing`、`duplicate_prediction`、`extra_prediction` 必须显式计数。缺失不是 0 error：保留为 `null`，并在 paired coverage、missing transition、character coverage 中单报；seconds error 汇总只在双方均覆盖的 paired units 上计算，绝不把 coverage 增益混入 seconds delta。
- `delta_error_ms = new_error_ms - old_error_ms` 仅在双方覆盖时存在；输出 paired mean/median/sum、双方 coverage、以及 `old_missing -> new_covered` / `old_covered -> new_missing`。
- 标签：`improve` 为 paired error 下降至少 200ms 且不发生覆盖退化；`harm` 为上升至少 200ms 或 covered-to-missing；否则 `neutral`。`catastrophic_harm` 另标记任一 `<=100/200ms -> >500ms/>1s` 或 covered-to-missing。
- 同时报 100/200/500ms 边界 transition 与 >1/2/5/10s buckets。GT 标签只出现在 `GT_PAIR_METRICS.jsonl`，不得 join 回 `REQUESTS.jsonl` 或 `NO_GT_FEATURES.jsonl`。

## 5. 执行顺序

### 00_inventory

读取 real-GT annotation、accepted split、timeline manifest、旧 baseline/cache 与 `/home/hyan/Data/lyricalign/test`、`/home/hyan/LyricAlignment/夜苏打`。输出可用歌曲数、60/10/10 可构造窗口数、现有证据和动态发现的 demo；若少于 20 首 source song，记录原因后按实际规模继续。

### 01_detector_production_audit

对 inventory 内实际可用的歌曲，先复用 forward identity 相同的 Raw baseline/evidence；没有可复用 evidence 时，按冻结 60/10/10 Raw 配置补跑 baseline forward，再做 scorer/reaggregation。补跑的 baseline forward 与 realign candidate forward 分开记入 `GPU_BUDGET.json`。tri-state 先按冻结阈值计算，再用 `light_merge`；历史比较直接引用 `safe_accept_rate`、`protected_recall` 和 interval metrics 的同名字段。报告 unit 与 window 两层、per-song 与 pooled；window trigger 规则须从历史实现 adapter 原样复用并写入 identity 文件。主线不调 threshold；仅可另存 exploratory 阈值表，不能覆盖主汇总。

### 02_realign_behavior_collect

由 audit 的 case pool 构造 S1 正确+ACCEPT、S2 正确+UNCERTAIN/REJECT、S3 bad+UNCERTAIN/REJECT、S4 bad+ACCEPT。sampling 以 `<=200ms` / `>1s` 作主标签，同时保留全部连续 GT error；目标 60--100 case，S2 占 25--35%。每首歌每个 stratum 至多一个 case、每首歌总数最多 3 个；优先扩大歌曲覆盖后再使用同歌的第二/第三个 case。S4 稀少时不强补。

每 case 只跑两种 no-GT request：R-A narrow/local 与 R-B anchor/context。先用 `--smoke --limit 2` 验证，再真跑 `--resume`。生成请求后对每行运行 GT firewall 和 text identity 校验；预算超 6h 时先缩 case 数，保留 detector audit 与 S2。仅在 top counterexample/ambiguous case 追加最多一次稳定性 probe。

### 03_gate_feature_analysis

从 original/R-A/R-B 的 evidence 生成：`n_big`、changed ratio、sum/max timestamp displacement、unsafe-inside/safe-outside displacement、safe-context changed count、request 外改动、p_bad before/after/delta、entropy/margin delta、pile-up、inversion、compression、text identity、R-A/R-B candidate agreement。特征表先递归运行 no-label-leak 检查，再与 GT-only 标签表在分析进程中临时 join。

按 source song 切 dev/quick-holdout（约 2/3 : 1/3）；优先报 Spearman、AUROC/AUPRC、分布、阈值 sweep、`n_big` 与 locality 的少量组合，以及 harmful-risk 对 coverage/capture 曲线。输出 `ACCEPT_WRITEBACK`、`UNCERTAIN_KEEP_OR_RETRY`、`REJECT_KEEP_ORIGINAL` 三态建议，均为离线建议，不写回任何 timeline/state。

### 04_test_demo_behavior

复用 `scripts/research_transition_recovery_detector/run_demo_analysis.py`（注意：该脚本不在 `scripts/demo/` 下）的动态发现与 parser，但 detector adapter 切到本轮冻结 Raw/light_merge identity。全量 Demo 先做 detector summary；从排序前 10--20 个且跨语言/异常类型的 windows 跑两种专用 no-GT request：以 detector unsafe span 为中心的 narrow request，以及由相邻 ACCEPT character anchor 限定的 context request。Demo adapter 只使用 parser character index、audio/text、Raw rows 和 detector states；不得调用依赖 M4 timeline/episode/canonical-GT schema 的 `e5_proposals.build_proposals`。只报 displacement、candidate agreement、detector delta 和结构异常，不生成 accuracy/harm GT 标签。

### 05_report

明确分开：production detector audit、GT realign behavior、no-GT gate 信号、Test Demo stress。不能把 `E8.net_improved` 写成 seconds，不能把 shadow `actual_writeback=0` 写成 stateful recovery。若 holdout 弱或 harmful risk 不能接受，结论应为不冻结 writeback gate。

## 6. 测试与成本

新增 `tests/realign_gate/` 覆盖：GT firewall；canonical paired binding（含 cid 无交集、时间重叠但错文本不得配对的回归场景）；缺失/重复/extra 的 coverage 与 transition；100/200/500ms corruption；历史 detector metric adapter（含 `not_reproduced_source_missing` 分支）；dynamic demo discovery；text identity；feature 表无 GT；song split；两 variants/case 上限；resume。

成本目标：inventory/feature/report 主要 CPU；detector audit 的缓存命中为 CPU，未命中的冻结 Raw baseline forward 单独计数。original 优先复用该 baseline evidence；若 identity 不同而必须重跑，也作为 original forward 单独计数。GT realign candidate 最多 100 x 2（R-A/R-B）；Demo candidate 最多 20 x 2；stability probe 最多 10。smoke 先 2 GT case + 1 Demo。GPU 达 6h 时停止新增 case，8h 硬停，不进入 stateful closed loop。

## 7. OpenCode 实现复查后的阻塞修正清单（必须先修）

2026-08-12 对当前 `src/lyricalign/realign_gate/` 实现与实际 run
`/home/hyan/Data/lyricalign/runs/detector_production_realign_gate_20260812_20260812T195343Z`
复查：`PYTHONPATH=src pytest -q tests/realign_gate` 为 49 passed，但 fixture tests 未覆盖真实旧 run identity 与阶段间 evidence schema。以下问题修复并以真实小 smoke 验证前，不得继续正式 GPU realign。

### B1 — Detector audit 旧 evidence identity 不兼容，0 命中必须 fail/blocked

现状：当前 run 的 `RAW_UNIT_METRICS.json` 是 `n_requests=988`、`n_hits=0`、`n_missing=988`，但 stage 写成 `result_status=ok`。`detector_audit.locate_old_evidence()` 用 `realign_recovery.forward_cache.build_forward_key/forward_digest` 寻找并校验 research-v7 evidence 的 `content_identity`；两者 identity schema 不同。旧 E5 request 还缺少 `audio_sha256`、`processor_id`、`request_mode`、`code_version` 等 forward-cache 所需字段。

修复：不得用 forward-cache digest 猜测 research-v7 content identity。实现 research-v7 evidence adapter：从 `attempt.request.request_id` 建 request-id 索引，再校验 evidence 内 request 与 REQUESTS 行的 forward-affecting 字段（audio path/range、text units、model/checkpoint/input variant）一致后复用。若不存在 identity 一致 evidence，按冻结 60/10/10 Raw baseline 配置补跑 baseline forward，并在 `GPU_BUDGET.json` 单列。`n_hits==0`、无 windows、或仅缺失数据时必须输出 `blocked`/`incomplete`，不得报告 production metric 为 `ok`。

### B2 — Unit tri-state tally 键错配

现状：`_unit_tally()` 初始化 `n_accept/n_uncertain/n_reject`，却检查 `state in tally`；state 值实际是 `accept/uncertain/reject`，故三项永远为零。

修复：显式映射 `accept -> n_accept`、`uncertain -> n_uncertain`、`reject -> n_reject`，并加一个非空 unit-state fixture 与真实 smoke assertion，验证 count 总和等于 `n_units`。

### B3 — S1--S4 不能以 detector 自己替代 real-GT correctness

现状：`build_case_pool()` 固定 `old_error_ms=None`；`case_selection._classify()` 随即用 ACCEPT 推断 correct、非 ACCEPT 推断 bad。这样 S2/S3/S4 实际由 detector 输出定义，不能评估 required 的 `correct + detector UNCERTAIN/REJECT` hard negative 或 `bad + ACCEPT` false negative。

修复：在 audit/case-pool 的**离线 GT 分支**通过 `load_real_gt_with_audit` 和 canonical unit binding 计算 baseline `old_error_ms`，并据此形成 S1--S4。GT 字段可留在 `CASE_POOL_GT.jsonl`/`CASES.jsonl` 供抽样和最终评分，但严禁复制进 `REQUESTS.jsonl`、proposal plan、candidate evidence 或任何 no-GT feature 字段。若 canonical baseline binding 不完整，记录/排除该 case，不能回退到 detector 伪标签。

### B4 — 03 阶段必须解析真实 evidence，并显式提供 original 配对

现状：03 将整个 research-v7 evidence JSON 当作 prediction row，真实 raw rows 位于 `attempt.decoder_outputs.raw.rows`，所以 `_new_pred()` 得不到时间，`new_rows` 为空。02 的 CASES 也未写 `old_units`，但 03 仅从该字段取得 original，导致 paired GT metrics 和 feature analysis 都为空。

修复：复用/抽取 `realign_recovery.candidate_scores.evidence_rows_from_request` 与 E7 的 canonical mapping，把 candidate evidence 解析为 canonical per-unit rows；并从同一 identity 的 Raw baseline evidence 显式导出 `original` per-unit rows。对每 case/variant 产出 canonical paired rows、old/new coverage、duplicate 和 extra 计数；若 candidate/original 任一缺失，阶段应为 incomplete，不得产生可接受 gate 的结论。

### B5 — 正式 paired GT 禁止 time-IoU fallback

现状：`pair_gt()` 在 canonical id 缺失时按 time-IoU 绑定 GT。歌词错段或 semantic drift 正可能有时间重叠，这会把错误文本挽救为有效单位，污染 improve/harm。

修复：正式主指标仅接受 `(song_id, canonical_unit_id)` 配对。不能 canonical-bind 的 candidate row 记为 `extra_prediction`，对应 target 缺失记为 `new_missing`；绝不使用 time-IoU fallback。IoU 若保留，只能作为单独 diagnostic 字段，且不得参与 label、coverage、seconds delta 或 gate 分析。新增错文本但时间重叠的回归测试。

### B6 — Gate 分析 join key 必须包含 variant

现状：`gate_features.analyze()` 用 `(case_id, canonical_unit_id)` 索引/连接 GT 与 no-GT 表，未包含 `variant`。同一 case 的 R-A/R-B 会互相覆盖，最终保留项取决于文件顺序，AUROC、threshold sweep 和 gate 结论均不可信。

修复：GT metrics、no-GT features、analysis merged rows 的唯一键统一为 `(case_id, variant, canonical_unit_id)`；在 join 前断言同键唯一，若重复必须显式记录 duplicate 而非静默覆盖。新增同一 case 同 cid 的 R-A/R-B fixture，验证两个 variant 都参与分析且相互不覆盖。

### B7 — `n_big` 必须是 before/after p_bad 的 candidate 级聚合变化计数

现状：`extract_no_gt_features()` 把每 unit 的 `n_big` 写为 `p_bad_after > T_reject` 的 0/1。这不是设计中的 `count(|p_bad_after - p_bad_before| > 0.05)`，把“candidate 当前风险高”误当作“candidate 相对 original 改动大”。

修复：先以 `(song_id, case_id, canonical_unit_id)` 正确绑定 original/candidate `p_bad`，计算每 unit `abs_p_bad_delta`；再以 `(case_id, variant)` 聚合 `n_big=count(abs_p_bad_delta > 0.05)`。每个 candidate 的所有 feature rows 均写入相同的 candidate-level `n_big`，但保留 per-unit delta 供诊断。threshold/gate 分析只能使用该定义；新增“高 p_bad 但 delta=0”与“低 p_bad 但 delta 大”的回归测试。

### B8 — Baseline shadow 与 unsafe intervals 必须按 song/case 隔离

现状：03 将所有 case 的 `old_units` 合并进 `shadow_units[canonical_unit_id]`；不同歌曲 canonical id 可重复，后写歌曲会覆盖前一首。随后 feature extraction 仅按 cid 查 baseline，unsafe interval 也被跨 case 合并，因此会把其他歌曲/窗口的 before state 关联到当前 candidate。

修复：baseline/shadow 的键至少为 `(song_id, case_id, canonical_unit_id)`，unsafe intervals 也必须按 `(song_id, case_id)` 保存和查询。`extract_no_gt_features` 的输入/输出需要显式携带 song 与 case；不得接受仅 cid 的全局 fallback。新增两个不同 song、相同 cid、不同 baseline p_bad/timestamp 的 fixture，验证 feature 互不污染。

### B9 — 当前 20/20 audit 是 smoke，不是 production 结论

现状：修正后 audit 成功复用 20/20 evidence，证明 B1 adapter 可工作；该运行由 `--limit 20` 产生，不能代表 988 request 的完整 production-style population。

修复：在 `RAW_UNIT_METRICS.json`、`RAW_WINDOW_METRICS.json`、`05_report` 中持久化 `requested_limit`、`full_population_size`、`evaluated_count` 与 `is_smoke`。只有 `limit=0` 且所有 inventory-eligible windows 均成功或明确记录缺失原因时，才允许 `production_audit_complete=true`。任何 limited run 的报告标题和结论必须标为 smoke/partial，不得用于解释历史 safe-accept 与 recovery subset 的差异。

### B10 — `01` 审计的是 E5 多变体 proposal bank，不是 production baseline population（阻断）

现状：`detector_audit.run_stage()` 默认输入仍是 `realign_recovery/.../e5_proposals/raw/REQUESTS.jsonl`（`detector_audit.py:488-489`）。本次实际 run 的该文件有 988 条，包含 `original_full`、4 个 oracle、R-A、R-B、2 个 R-C 变体；`RAW_UNIT_METRICS.json` 也记录 `n_requests=988`。它不是“生产 Raw baseline 的 eligible 60s/10s 窗口”总体，故 `safe_accept_rate=0.1550`、unsafe window rate 都不能解释为 production detector audit。

修复：`01` 的人口必须改为冻结的 production serial baseline（每个可构造窗口仅一条 Raw baseline），或由 inventory 显式构造并落盘该 baseline requests/evidence；不得把 oracle 和 realign proposal 混入分母。输出 `population_kind=production_raw_baseline`、去重 window key 与排除原因。

验收：输入只包含 baseline/original Raw；同一 `(song_id, window_id)` 仅一次。没有可复用 evidence 时应按冻结配置补跑该 population，而不是仅以状态终止；production rate 只在该 population 完成后产生。

### B11 — `02` 未生成 R-A，且把整首歌 unit 列表当成窗口文本（阻断）

现状：本次 `02_behavior/REQUESTS.jsonl` 和 `CANDIDATE_INDEX.jsonl` 都是 60 条、全部 `R-B_safe_anchor_bounded`，R-A 为零。`case_selection.run_stage()` 又把 E5 `old_run_requests` 直接作为 `baseline_rows` 传给 `build_proposals`（`case_selection.py:452-459`），该输入不是带 detector shadow 的 production baseline，R-A 无法由 unsafe span 构造。另 `_window_text_unit_ids()` 返回 `timeline[song_id]["units"]` 的所有 unit（`case_selection.py:189-194`），未按 `window_index` 截取 source window。

修复：由 `01` 输出的 per-case baseline detector intervals/units 构造 R-A；每 case 按实际 60s window 的 text ids 构造 source window，不能使用整首歌。R-A/R-B request 与 candidate 必须可追溯至同一 case/window。

验收：每个可构造 case 同时有一条 R-A 和一条 R-B；缺一种时逐 case 写入 `SKIPPED_CASES`，并以该 case 的 baseline interval、window text 与可用 anchors 重新构造，而不是让单变体样本进入 gate 学习。

### B12 — no-GT feature 聚合跨 case/variant 污染，displacement 只写第一行（阻断）

现状：`extract_no_gt_features()` 对整批 evidence 共用 `changed_flags`/`disp_values`（`gate_features.py:319-320,384,412`），再把全局 changed ratio 写入 records（433-438）；写 displacement 的循环在首个有效 record 后 `break`（439-451）。`_pile_up(evidence_rows)`、`_ra_rb_agreement(evidence_rows)` 也以整批 rows 计算（452-453）。本次 `03` 对 60 个候选产生 5,648 行 feature/GT pair，当前 holdout AUROC 和 `ACCEPT_WRITEBACK` 因此不可采信。

修复：先按完整 candidate identity（至少 `(song_id, case_id, variant)`，必要时 request id）分组；changed ratio、displacement、unsafe/safe locality、pile-up 均在组内计算并写给该组每行，R-A/R-B agreement 只在同 case 两组之间算。删除首行赋值的 `break`。

验收：两 case、两 variant fixture 证明任一组特征不会随另一组 rows 改变；每个有效组均有自身 displacement/locality；分析前对 feature identity 做唯一性和完整性检查。

### B13 — paired-GT 标签与 catastrophic 定义未按既定口径实现（阻断）

现状：本文档第 4 节规定 improve/harm 至少 200ms，但实现 `NEUTRAL_EPS_MS=10.0` 并以 ±10ms 贴标签（`gate_features.py:31,71-78`）。`catastrophic_harm` 只判断 paired `delta_error_ms > 200`（180-181），未实现 `<=100/200ms -> >500ms/>1s` 和 covered-to-missing。

修复：改善/伤害阈值改为 200ms；coverage transition 正确参与标签；按计划的绝对阈值 transition 与 covered-to-missing 实现 catastrophic，并在 metrics/report 单报原因。

验收：覆盖 10ms 抖动、±200ms 边界、correct-to->500ms/1s、covered-to-missing 的测试；label/catastrophic reason 与第 4 节一致。

### B14 — 报告必须执行实验分阶段准入，而非将缺口简单标为状态（阻断）

现状：当前 `05_report/FINAL_SUMMARY.json` 对仅 R-B 的结果仍给出 `suggestion=ACCEPT_WRITEBACK`、`writeback_gate=eligible_for_review`，绕过了完整 production population、R-A/R-B 双变体和 feature 完整性。

修复：`05` 增加必要条件：`01.population_kind` 合格、`02` 每 case required variants 完整、`03` 无 feature/GT completeness 或 duplicate failure、paired 定义版本匹配。条件未满足时，报告必须给出对应的下一轮重建输入、样本数和执行命令/产物路径；只允许形成该阶段的诊断结论，不得把不完整样本的模型分数升级为 writeback 建议。

验收：用本次仅 R-B 的 run 回归，报告列出“重建 baseline shadow → 补齐 R-A → 重跑 paired/gate”的行动清单与预计样本规模；B10--B13 均满足后才可计算正式 recommendation。

### B15 — 以实验设计重建本轮，而非用状态掩盖缺口（执行方案）

目标不是直接得到一个全局 writeback 分类器，而是回答两个可证伪的问题：

1. 冻结 detector 在**生产式 baseline 窗口**上能否把真实坏窗口集中到可恢复子集，同时保留足够的正确窗口；
2. 在 detector 已指向的窗口内，R-A 与 R-B 哪一种干预能在 real-GT 上稳定改善、且 no-GT 信号能否区分“可接受改善”与“有害改动”。

因此按下面的四个实验单元执行，前一单元的产物是后一单元的输入，而不是把 E5 proposal bank 直接串成一个总体：

1. **P0：生产 baseline population。** inventory 按 cohort manifest 的 60s stride/10s overlap 构造唯一 `(song_id, window_id)` 表；对每行生成 `original_raw_baseline` request，并复用或补跑其 Raw evidence。输出 `BASELINE_WINDOW_INDEX.jsonl`、`BASELINE_UNITS.jsonl`、`BASELINE_DETECTOR_SHADOW.jsonl`。这里仅评估 detector，不生成 proposal。
2. **P1：GT 分层 case sampling。** 将 P0 baseline 以 canonical GT 分成 S1--S4；主试验抽 60--100 case，优先 song coverage，S2 25--35%，S4 自然稀少则如实保留。每个 case 保存固定的 `window_start/end`、target ids、unsafe intervals 和相邻 safe anchors。先做 2 case smoke，确认双变体均可构造后再跑正式矩阵。
3. **P2：配对的 R-A/R-B intervention。** 对同一 P1 case 必跑 R-A（以 P0 unsafe interval 为中心的窄局部文本/音频范围）和 R-B（由同一 window 内相邻 ACCEPT anchors 限定的上下文范围）。两者共享 baseline、model、window 和 target ids，只改变 intervention；以 `(song, case, variant, cid)` 记录 request、evidence、original/candidate pair。不可构造 R-A 的 case 不替换成只有 R-B，而是回到 P1 补抽可构造 case。
4. **P3：按 candidate 聚合的评估与 gate。** 先在每个 candidate 内计算 no-GT features，再将 GT pair labels 留在独立表中。以 source-song 划分 dev/holdout，比较：(a) original→R-A，(b) original→R-B，(c) R-A 与 R-B 的同-case difference；首要指标为 harmful/catastrophic rate、coverage transition 与 paired error delta，AUROC/AUPRC 仅是 gate 可行性证据，不是 writeback 决策本身。

正式 recommendation 应是分层策略而非单个分数：若某 detector state × intervention 组合在 holdout 上具有足够的 paired 改善、零/预设上限内 catastrophic harm、且 coverage 不退化，则列为“候选重试策略”；否则保留 original。随后只在候选策略覆盖的 top counterexample/ambiguous windows 做最多一次 stability probe。Test Demo 始终是独立压力测试，不参与阈值学习或总体 rate。

每次报告应展示 P0→P3 的 cohort flow（eligible → baseline evidence → GT strata → 双变体 pairs → valid paired units），以及每一步的自然流失原因。这让实验能定位是 detector、proposal 构造、模型行为，还是 gate 特征失效，而不是用 `blocked/incomplete` 代替设计上的修复。
