# Phase 4.3/4.4 结论（oracle recovery + closed-loop 探索）

## Phase 4.3：Oracle Recovery（B 5 首，已跑通 3-mode）

CLI：`run_oracle_recovery.py --session-root <B> --role model_selection
--timeline-manifest manifest_cohort_b/LONG_TIMELINE_MANIFEST.jsonl --mode O0/O1/O2`
（需 `HF_HUB_OFFLINE=1`；现场 load R2 checkpoint step-000750 full-song infer，不复用 evidence_v2）

结果（52 段 / 1141 rows）：

| mode | 语义 | recovery_rate | fixed_rows |
|---|---|---|---|
| O0 | legacy GT-range rerun | 0.1394 | 159 |
| O1 | GT 只设正确 head（query 起点=GT 首行） | 0.1586 | 181 |
| O2 | GT exact-pair query | 0.1586 | 181 |

- **oracle recovery 上界 ≈15.9%**（O1=O2），O0=13.9%。与旧 run 20260808_corrected 的
  18.6~19.5% 同量级（差异来自歌集不同）。confirm：aligner 对同段重跑产生系统性偏移，
  GT head/exact-pair 信息只能修复 ~16% 的 rows。
- 输出：`04_oracle_recovery/ORACLE_{mode}{suffix}.json` + `ORACLE_SUMMARY.json`（聚合）。

## Phase 4.4：detector-triggered recovery（closed-loop，评估为 backlog）

### 契约（run_closed_loop.py）
- 必填 `--session-root` + `--timeline-manifest` + `--detector-pkl` + `--working-point`
  （--route-mode L/W/shadow；--transition T2_CORE）。
- 依赖：`00_meta/DATASET_SPLIT.json`（已建）、`00_meta/VALIDITY_GATES.json`（gate_d_detector=pass
  才运行）、`06_detector/FROZEN_WORKING_POINTS.json`（v1，工作点须 feasible 且含 t_accept/t_reject）。
- detector pkl 契约：pickle.load → `{"model","scaler","feature_names"}`，
  `predict_p_bad(artifact, [extract_unit_features(r) for r in rows], feature_names)`。
  特征为 v1 8 维（raw_start_entropy/raw_end_entropy/raw_start_margin/raw_end_margin/
  raw_start_top1_probability/raw_end_top1_probability/official_start_sec/repair_shift...）。

### 缺口清单（research_v7 产物 → closed-loop 的最小接线）
1. **FROZEN_OPERATING_POINTS.json 不能直接当 FROZEN_WORKING_POINTS**：v2 冻结值嵌套在
   `operating_points` 下、无 feasible/约束语义。需映射为 v1 结构（可用 frozen T_accept/T_reject
   填 t_accept/t_reject，feasible=true）——阈值部分可转。
2. **detector pkl 必须重训**：MODEL_SELECTION 无模型参数。v1 特征与 detector_v2 R combo 特征
   不同源，须用 `extract_unit_features` 体系在 evidence rows（含 raw_start_entropy 等全部 v1 字段）
   上重训。evidence 的 `attempt.decoder_outputs.raw.rows` 已验证含全部所需字段（可行）。
3. **transition 记录缺失**：closed-loop 的 detector_predict 在真实 forward 中逐请求调用，
   需要 research_transition 的 T2 轨迹体系（02_transition records）或独立重跑路径；当前
   research_v7 evidence 是另一套格式，无 02_transition 记录。
4. `VALIDITY_GATES.json` 需构造（gate_d_detector=pass）。

### 结论
- closed-loop 完整跑通需要跨 research_transition/research_v7 两套特征-记录体系装配，
  属架构性开发。当前 mainline 为"实现前阶段、overlay 未接线"（AGENTS.md），本阶段不强行实现。
- 记录为 backlog；可行路径：① 用 evidence rows + extract_unit_features 重训 v1 pkl →
  ② 构造 FROZEN_WORKING_POINTS v1 + VALIDITY_GATES → ③ 在 B 上跑 closed_loop。
- 关键可行性已验证：evidence rows 含全部 v1 特征字段，pkl 重训无数据缺口。
