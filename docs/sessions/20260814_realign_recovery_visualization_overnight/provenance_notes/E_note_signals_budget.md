# E note — 可导出信号(signals)核实 + GPU forward 预算

会话：20260814_realign_recovery_visualization_overnight
作用：为 `07_CODEX_IMPLEMENTATION_PLAN.md` 做前置核实，覆盖【事实8】与【事实10】。
核实人/时：本 Codex 前置核实子任务（STEP BUDGET=8）。所有结论均有源码/运行产物路径证据。

---

## 1. 总结论（快速答案）

- **事实8——信号可导出性**：raw/official 双 decoder 边界、per-step 后验 topk/top1、entropy、margin 都能从当前模型接口真实导出（由 `scripts/demo/align_qwen_fa_serial_demo.infer_slice` 在单次 forward 的 `output.logits` 上计算）；`hidden` 向量与 `full_posterior` npy 也可导出，但**只在显式设置 `research_evidence_config` 时**产出，当前 unit_realign formal/test_demo 生产路径**未接线**（默认不导出）。薄封装 `inference/qwen_forced_aligner.py` 只返回 `timestamps`，不暴露任何这些信号。
- **事实10——GPU 预算**：合同设 10h target / 12h hard cap（`04_EXECUTION_CONTRACT` §3）；forward 层已实测墙钟极低，forward_count 在 run 目录的 `RUN_MANIFEST.json.runtime_budget` 中登记。screening → expansion 两段式可轻松落在预算内，瓶颈不在 forward 墙钟，而在**模型加载、样例规模、缓存兜底**。

---

## 2. 事实8 分项：哪些信号实际可导出（逐项+证据路径）

### 2.1 当前 forward 返回什么（薄封装层）
- 文件：`src/lyricalign/inference/qwen_forced_aligner.py`
- `QwenForcedAligner.align_detailed` 返回 dict，只含：`timestamps`（`processor.decode_forced_alignment` 官方解码）、`audio_duration_sec`、`decoded_num_samples`、`timing{audio_decode/input_prepare/forward/alignment_decode/total}`。
- **不暴露**：raw/official 双 decoder 输出、per-step hidden、后验 logits、entropy、margin、置信度。它是 "metric-free thin adapter"（README.md 原文）。
- `align()` 只是 `.align_detailed(...)["timestamps"]` 兼容包装。

### 2.2 raw / official 双 decoder + per-step 后验 / entropy / margin 的真正产出位置
- 文件：`scripts/demo/align_qwen_fa_serial_demo.py`，函数 `infer_slice`（行 221–~486），单次 `model(**batch)` 后：
  - `positions = (input_ids == model.config.timestamp_token_id)` → 时间槽位（行 311）；
  - `slot_logits = output.logits[0, positions].float()`（行 312）；
  - **raw decoder** = `slot_logits.argmax(dim=-1)`（行 333）→ `raw_*_local/global_start/end`（行 413–416）；
  - **official decoder** = `processor.decode_forced_alignment(output.logits, ...)`（行 348–350）→ `official_fixed_*_local/global_*`（行 418–421）；
  - **per-step 后验**：`probabilities = softmax(slot_logits)`（行 334），`topk(probabilities, k=top_k)`（行 346）→ `raw_*_topk_classes/probabilities`、`raw_*_top1_probability`、`raw_*_top2_class`（行 430–437）；
  - **margin** = top1−top2（行 438–439）；**entropy** = −Σ p·log p（行 347, 440–441）。
- 结论：**raw/official、per-step posterior(topk/top1)、entropy、margin 均从当前接口真实计算并落进 rows**。raw 是"基于官方模型分类头 logits 的 argmax 解码"，official 是官方 timestamp 解码——二者是同一次 forward 的 logits 的两种解码视图，**不是两套独立 decoder head**（行 396 "elif decoder_kind=='official' or ... fixed=official_fixed"；行 398 raw→fixed=raw）。

### 2.3 hidden / full_posterior 的可导出性
- 同一 `infer_slice` 支持：`evidence_cfg = args.research_evidence_config`（行 304）非 None 时 `model(**batch, output_hidden_states=True)`（行 307）。
  - `hidden_evidence`：取 `layers[-4,-1]` 的 hidden states，按 slot 位置裁剪存为 float16 npy（行 313–328, 497–505）；
  - `full_posterior`：`save_full_posterior=True` 时把整块 slot softmax (n_slots × n_classes) 存 float16 npy（行 335–344, 506–511）。
- 唯一实际设置者：`scripts/research_transition_recovery_detector/collect_evidence_v3.py`
  - `EVIDENCE_CONFIG = {"hidden_layers": [-4, -1], "save_full_posterior": True}`（行 28）。
- **当前 unit_realign formal / test_demo 生产路径未接线**：`scripts/research_v7/run_behavior_suite.py`（真实执行批）不设置 `research_evidence_config`，故其 forward 只跑 `model(**batch)`，`hidden_evidence=None`、`full_posterior=None`——行 492 跳过写入。也就是说 hidden/全后验在正式 run 里**默认不导出**，只在 `collect_evidence_v3.py` 这类专门收集路径导出。

### 2.4 下游消费这些信号的已实现代码
- `research_v7/real_executor.py`：把 rows 拆成 `decoder_outputs["raw"/"official"/"top_k"/"_posterior"/"weighted_isotonic"]`；其中 raw 标注为 `"derived_from_official_decoder_raw_geometry"`（行 344），`_posterior` 消费 `raw_*_topk/entropy/margin`（行 308–316）。weighted_isotonic 后处理见 `research_v6/decoders.py`。
- 特征/评分链：`research_v7/detector_v2_features.py`（raw_start_entropy/margin）、`research_transition_recovery_detector/detector_features.py`、`realign_recovery/candidate_scores.py`（把 flat `raw_*` 映射为 v2 EvidenceRow `raw{start_sec,end_sec,start/end_entropy,start/end_margin,topk}`）。
- 结论：**posterior/entropy/margin 不仅能导出，且下游特征链已实现并消费**；hidden 只在小规模收集路径导出。

---

## 3. 事实10 分项：detector tri-state / 连续 score

### 3.1 产出形式：accept / uncertain / reject 三态 + 连续 p_bad
- 文件：`src/lyricalign/research_v7/detector_v2_intervals.py`
  - 连续分 = `p_bad`（per-unit unsafe 概率）。
  - `tristate_from_p_bad(probabilities, accept_threshold, reject_threshold, ...)`（行 73）：`output_from_probabilities` 按冻结双阈值切三态 → `light_merge`（行 40：填充单一 ACCEPT 岛、REJECT 段两端各扩 1 为 UNCERTAIN）。
  - 冻结阈值：`freeze_thresholds(...)`（protected_recall 0.95/0.99，行 113–243）。
- tri-state 枚举定义在 `research_v7/detector_v2_contract.py`（`TriState`、`output_from_probabilities`、`validate_detector_output`）。
- **评分函数**：`realign_recovery/candidate_scores.py` `score_units(scorer, evidence_rows)`（行 335–386）→ 返回 `{"units":[{canonical_unit_id,start_sec,end_sec,p_bad,state}], "n_units", "decision"}`，state ∈ accept|uncertain|reject。连续 score = `p_bad`，来源 `FrozenScorer`（standardized logistic，`realign_recovery/frozen_scorer.py`）。
- 结论：detector 同时产出连续 score(p_bad) 与三态(ACCEPT/REJECT/UNCERTAIN)，函数入口见上。

---

## 4. 事实10 分项 / 第3问：unit-realign / realign_recovery 已收集的 no-GT 候选信号字段

### 4.1 `extract_unit_gate_features.py`（脚本入口）
- 文件：`scripts/unit_realign/extract_unit_gate_features.py`
- 输出 schema `unit_realign_no_gt_features_v1`，allowed 键（行 115–123）：
  `mean_boundary_displacement_ms`, `signed_start_displacement_ms`, `signed_end_displacement_ms`,
  `detector_p_bad_before`, `detector_p_bad_after`, `signed_detector_delta`, `context_protected`,
  `duration_sec`, `decoder_confidence`, `state_before`, `state_after`, `monotonicity_violation`,
  `inversion_count`, `overlap_sec`, `compression_ratio`, `slot_violation`,
  `safe_context_changed_count`, `raw_official_disagreement_ms`, `local_consistency`.
- detector 键（`detector_p_bad_before/after`、`signed_detector_delta`、`state_before/after`）在无 `detector_rows.jsonl`（`emit_detector_rows.py` 产出）时保持 None（行 58–66, 132–133）。
- `.get(detector_before/after)` 只从 detector row 取 `p_bad_before/after`（行 84–87）。
- 构建函数：`lyricalign/unit_realign/unit_gate_features.build_unit_features`；每行经 `assert_no_gt_feature_row`（GT 防火墙）。

### 4.2 `candidate_scores.py`（realign_recovery）
- 文件：`src/lyricalign/realign_recovery/candidate_scores.py`
  - `evidence_rows_from_request(request_row, evidence_payload)`（行 213）：从 `attempt.decoder_outputs.raw.rows` 提取，映射 v2 `EvidenceRow`，raw 字段 = start_sec/end_sec/start/end_entropy/start/end_margin/topk（行 251–259）；official 字段 = official_fixed_global_* + repair shift；`hidden={"available":False,...}`、`cross_view={}`（行 274–277）。
  - GT 契约：no-GT，`assert_no_label_leak` 每行递归校验（行 279）。
  - no-GT 代理量 = `p_bad`（no-GT），来自 FrozenScorer 特征矩阵（entropy/margin/topk 等），非 GT 误差。

### 4.3 `audit_evaluator_only.py`
- 文件：`scripts/unit_realign/audit_evaluator_only.py`
- 不是信号特征层，而是 **GT 防火墙 fail-closed 审计**：校验 `mode=="post_hoc_evaluator_only"`、`runtime_gt_access is False`、`actual_writeback==0`、`NO_GT_CHECK` 全 validated、request 数与 REQUESTS 对齐、outcome 全 canonical 且无 missing/extra/duplicate。
- 不采集 p_bad/disagreement 字段本身（这些字段来自 4.1/4.2）。

---

## 5. 事实10 / 第4-5问：GPU 预算 + 实测 forward 数与墙钟

### 5.1 预算合同（本 session）
- `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md` §3：target GPU ≤10h、hard cap ≤12h；预算优先级 = 机制 screening > 对有效机制扩量 > 重复无效 family；到 cap 后停止新增 GPU formal forward，转 CPU evaluator/统计/report/hard-case mining/已有 cache 的 candidate selector/可视化 rerender/free-exploration。
- `06_PLANNED_RUNS.yaml`：`gpu_budget.target_hours: 10`, `hard_cap_hours: 12`, `actual_writeback: 0`；phases P0–PF（freeze_preflight → visualization_smoke → screening → split screening → context → coarse2fine → no_gt_selection → adaptive_expansion(只扩 top1/2) → atlas_mining → stress → multilingual_viz → free_exploration）。
- 扩展策略（合同 §4）：40–60 独立 hard regions screening → 每问题只比较 3–5 branch → 淘汰 no-op → 只把 1–2 有效方向扩到 ≥200 regions。

### 5.2 forward 数 / 墙钟实测（运行产物）
- 账本载体：**每 run 的 `RUN_MANIFEST.json` → `runtime_budget`（`elapsed_sec`/`forward_count`/`cache_hit`/`cache_miss`）+ `item_count.forward`**。产出自 `scripts/research_v7/run_behavior_suite.py:369`。它记录的是 **forward 批次墙钟（不含模型加载）**。
- 实测（`/home/hyan/Data/lyricalign/runs/`）：
  - `unit_realign_formal_20260813`：78 forward, elapsed 26.422s（≈0.34s/forward，warm GPU 小窗）。
  - `unit_realign_test_demo_formal_20260813/04_test_demo`：118 forward（R-U 59 + R-S 59），elapsed 88.796s（≈0.75s/forward）。会话 01 §11 确认：33 items 成功、3 failed、60 windows、118 real forward。
  - `unit_realign_gpu_smoke{,_2}`：4 forward, ~9s each。
- 注意：`elapsed_sec` 不含模型加载/processor 初始化，且是 warm 后批处理；单 forward 绝对值随窗长/文本长浮动（0.2–1s 量级，本数据为小窗）。

### 5.3 推理：screening + expansion 如何在预算内
- 若按 "per-forward ≈0.5s（warm, ~固定60s window）" 估算：40–60 screening regions × 每 region 3–5 branch ≈ 120–300 forward；扩 1–2 机制 ×（≥200 regions −已筛出）+确认 population ≈ 数百 forward。合计 ~500–1000 forward ≈ **5–10 分钟 warm GPU**，远低于 10h target。
- 真实墙钟大头=模型加载 + 每 forward 的预取/解码 + 大规模样例的 cache 冷 start + 磁盘 evidence 写读，而非前向本身。这与合同 §3"GPU 预算是机制、缓存 / cache identity 复用决定实际耗时"一致。
- 落地点：screening 阶段 freeze 所有机制超参；expansion 只扩 top1/2；`content_addressed_cache`（`infer_slice` 的 `research_infer_cache_root`，行 241–284）在已有 cache 时跳过 forward。**需在 07 计划里给出 `BUDGET_PROJECTION.json`（含 per-forward 假设 + 每 phase forward 数 + 冷/热 cache 墙钟）**。

---

## 6. 未知 / 需核实项

- 【未知】`elapsed_sec` 口径是"仅 executor 内 forward 墙钟"，当前实测不含模型加载；单次含加载的真实端到端 per-run 墙钟未在本会话记录中直接给出（可查 `00_meta` / shell 日志补证）。
- 【未知】`unit_realign_formal_20260813` 的 78 forward 不含 evidence hidden/full_posterior（未配 `research_evidence_config`），因此**无该正式 run 的 hidden 耗时记录**；欲为 visualization 采 hidden 需走 `collect_evidence_v3.py`，其单 run 墙钟未实测。
- 【未知】上下文粒度（k1 vs k3）、audio recrop 是否改变窗长从而显著影响单 forward 时长——当前无对照时序证据。
- 【需核实/下一轮】`research_v7/real_executor.py` 中 raw 标注 `"derived_from_official_decoder_raw_geometry"`（非真正独立 decoder head）——若 07 计划假设 raw/official 是"两个独立 decoder 输出"，需在计划中明确为"同一 logits 的两种解码"，避免口径错误。

---

## 7. 关键证据路径索引

- `src/lyricalign/inference/qwen_forced_aligner.py`（薄封装，只回 timestamps）
- `scripts/demo/align_qwen_fa_serial_demo.py` `infer_slice`(行 221–486)（raw/official/entropy/margin/topk/hidden/full_posterior 唯一产出点）
- `scripts/research_transition_recovery_detector/collect_evidence_v3.py`（hidden/full_posterior 唯一接线方）
- `scripts/research_v7/run_behavior_suite.py`（生产 forward + `runtime_budget` 账本）
- `src/lyricalign/research_v7/detector_v2_intervals.py` `tristate_from_p_bad` / `freeze_thresholds`（三态+连续 p_bad）
- `src/lyricalign/research_v7/detector_v2_contract.py`（TriState 定义）
- `src/lyricalign/realign_recovery/candidate_scores.py` `score_units`（p_bad/state 评分入口）
- `scripts/unit_realign/extract_unit_gate_features.py` + `src/lyricalign/unit_realign/unit_gate_features.py`（no-GT 特征 schema）
- `scripts/unit_realign/audit_evaluator_only.py`（GT 防火墙审计）
- `/home/hyan/Data/lyricalign/runs/unit_realign_{formal,test_demo_formal,gpu_smoke*}_20260813/*/RUN_MANIFEST.json`（forward_count/elapsed 实测）
- `docs/sessions/20260814_realign_recovery_visualization_overnight/{04_EXECUTION_CONTRACT §3, 06_PLANNED_RUNS.yaml, 01 §11}`（预算合同 + test_demo 计数）
