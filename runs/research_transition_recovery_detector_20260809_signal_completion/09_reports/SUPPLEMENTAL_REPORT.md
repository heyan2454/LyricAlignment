# Supplemental Report（11 计划）

supplement_completed: **True**

## Transition（v3 权威口径）
- selection: product=T2_core_boundary_serial (250ms 0.401), mechanism=full_song
- T2−T1 paired CI: {"a": "T2_core_boundary_serial", "b": "T1_direct_serial", "win": 4, "tie": 2, "loss": 3, "mean": 0.0044, "median": 0.0, "ci95_low": -0.0015, "ci95_high": 0.0113} → T2 仅 nominal
- serial−full CI: {"a": "T2_core_boundary_serial", "b": "full_song", "win": 9, "tie": 0, "loss": 0, "mean": 0.0825, "median": 0.076, "ci95_low": 0.0529, "ci95_high": 0.1156} → serial 稳健
- raw vs official: 0.3481 vs 0.347 @250ms（≈相同 → 250ms 严格性）

## Detector（全信号消融）
- coverage: H/P/R/O/S 全 1.0（185 请求）
- best combo: R+sel；H 为负贡献（真实 negative）
- selected(V/P/S)=selected=V, R+V 0.6703508567667198 vs R 0.6646366339166124 (delta 0.0057)；sequence model: {"status": "executed", "families": ["R", "V"], "input_features": ["raw_start_entropy", "raw_end_entropy", "raw_start_margin", "raw_end_margin", "raw_start_top1_probability", "raw_end_top1_probability", "raw_start_interval_gap_sec", "raw_end_interval_gap_sec", "v_n_observations", "v_start_displacement_sec"], "mlp": {"auc": 0.6703508567667198, "auprc": 0.9070374541121993, "n": 2652, "auc_train": 0.7562834447341082}, "cnn1d": {"auc": 0.6218904332376531, "auprc": 0.8842522273521217, "n": 2652, "n_epochs": 40, "arch": "Conv1d(n_feat->16,k=3,pad=1)+ReLU+Conv1d(16->1,k=1); per-unit output", "input": "sequence features (10 dims) padded to 1041 per song", "n_songs_train": 26, "n_songs_eval": 9}, "comparison": {"cnn1d_gt_mlp": false}}

## PR
- audit: {"high": 171}（原 corpus 全 high）；mild 补集后 low 18/medium 63
- PR detector: pooled AUC 0.608、source-song macro 0.436（主要学到歌曲先验，per-episode 泛化弱）

## Recovery
- 36 retry decomposition: {"retry_worsened": 4, "retry_not_improved": 27, "retry_improved_detector_accept": 3, "retry_improved_detector_block": 2}
- 0 writeback 主因：retry 无改善（31/36）+ detector 拒绝全部改善（5/5）双瓶颈

## Gate
- {"transition_report_fixed": true, "paired_ci_nonempty": true, "raw_official_comparison": true, "interval_reproducible": true, "H_nonzero": true, "P_nonzero": true, "PR_executed": true, "retry_decomposition_complete": true, "signal_matrix_status": true}