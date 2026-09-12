# 2026-09-12 会话交接页（第 1–33 轮，机器生成）

> 本页数字全部取自 `results/by_run/*/metrics.json`（canonical metric source），由 `scripts/evaluation/make_session_handoff.py` 生成；解读请看对应报告与`docs/status/20260912_session_findings_index.md`。
> 硬约束：realign 仍 shadow-only（`actual_writeback=0`）；未从 test/OOD 选 checkpoint；本会话零 GPU、未删除任何既有产物。

## 已确认（可据此行动）

| 主题 | canonical 来源 | headline（机器摘取） |
|---|---|---|
| GTSinger 人工真值上的逐单元效应与证据 | `results/by_run/20260912_gtsinger_gt_deep/metrics.json` | `config_matrix_is_degenerate`=True；`labelled_configs_per_item`=12.0；`distinct_prediction_vectors_per_item`=3.52；`mix_equals_vocal_audio_item_share`=1.0；`full_vs_windowed_start_identical_share`=1.0；`official_minus_raw_hit100_pp`=-1.66 |
| MIR-1K 自然收尾人工真值面板 | `results/by_run/20260912_mir1k_natural_panel/metrics.json` | `natural_mandarin_hit100_best`=0.9229；`upstream_base_hit100`=0.2265；`first_char_hit100_ref`=0.9412；`last_char_hit100_ref`=0.8235；`middle_char_hit100_ref`=0.911；`last_char_signed_end_ref`=0.1014 |
| 交付时间线结构合规 + 后处理净新增零长 | `results/by_run/20260912_structural_compliance/metrics.json` | `shipped_illegal_share`=0.1672；`post_repair_illegal_share`=0.0；`zero_units_raw`=1483；`zero_units_shipped`=2236；`created_by_postprocess_units`=1112；`healed_by_postprocess_units`=359 |
| raw 起止倒序取证（塌陷前兆 lift 与覆盖） | `results/by_run/20260912_raw_degeneracy/metrics.json` | `raw_negative_share`=0.0633；`chinese_negative_share`=0.011；`japanese_word_negative_share`=0.2263；`share_gt_1s`=0.7057；`cross_window_explained_share`=0.231 |
| 测量有效性：绝对精度是含退化单元的保守下界 | `results/by_run/20260912_measurement_validity/metrics.json` | `gtsinger_official_bound_pp`=3.31；`mir1k_overall_bound_pp`=3.21；`base_predictor_bound_pp`=5.38；`lora_predictors_bound_pp`=r0_raw_20260724:1.74, r1_full_20260724:0.41, r2_full_20260723:0.54, r2_ood_20260723:0.23, r2_seed_20260724:0.45；`clamp_present_in_gtsinger_official`=True；`real_song_extra_zeros_from_clamp`=1623 |
| 可解码上限（真值是否在 top-2 候选内） | `results/by_run/20260912_decodability_ceiling/metrics.json` | `long_note_end_outside_top2`=0.4；`all_units_end_outside_top2`=0.1573；`first_unit_end_outside_top2`=0.4403；`checkpoint_progression_long_note_unreachable`=r0:0.7083, r1:0.275, r2:0.2167；`auc_confidence_reachability_end`=all_units:0.792, long_note:0.6161, last_unit:0.9554, first_unit:0.7127, middle_units:0.7928, short_note:0.7929；`conclusion`=「on long notes 40% of GT end bins are not even in the top-2 candidates, so post-selection cannot reach them; training moved that from 70.8% to 21.7%」 |
| 多视图并集 oracle 与错误相关性 | `results/by_run/20260912_multi_view_ceiling/metrics.json` | `gtsinger_union_oracle_all`=0.9159；`gtsinger_selection_regret_pp_all`=2.4；`gtsinger_selection_regret_pp_long_note`=0.88；`gtsinger_no_view_correct_share_all`=0.0841；`gtsinger_error_correlation_all`=0.694；`mir1k_union_oracle_all`=0.9656 |
| 指标可分辨限（格点余量、带边稳定性） | `results/by_run/20260912_metric_stability/metrics.json` | `rule`=「differences in hit@tol smaller than max_spurious_gap_pp are not attributable」 |
| 长时序端到端候选（联合求解 vs 现装） | `results/by_run/20260912_longform_pipeline_candidate/metrics.json` | `consensus_gain_over_single_window_pp`=2.14；`consensus_solve_gain_over_single_window_pp`=1.61；`structure_cost_of_solve_pp`=0.53；`shipped_official_degenerate_share`=0.031；`shipped_official_hit100_delta_vs_raw`=-0.47 |
| 跨窗共识/选择（含选择器无效证据） | `results/by_run/20260912_cross_window_selection/metrics.json` | `single_window_penalty_pp`=2.14；`best_deployable_selector`=「D_max_support」；`best_deployable_gain_pp`=0.6；`oracle_headroom_pp`=3.33；`gap_closed_by_support_selector`=0.18；`entropy_selector_gain_pp`=0.09 |
| 多视图选择实验 + 因子内容审计 | `results/by_run/20260912_gtsinger_multiview/metrics.json` | `units`=2415；`nominal_views_per_unit`=12；`production_view_hit100`=0.8804；`consensus_delta_pp`=-0.75；`best_selector_delta_pp`=-0.67；`oracle_gap_pp`=2.97 |
| 真实歌多视图可比性与后处理归因 | `results/by_run/20260912_real_song_views/metrics.json` | `comparable_pair_units`=10909；`comparable_pair_share_gt100ms`=0.0008；`full_slot_index_mismatch_share`=0.2363；`views_recording_silence_flags`=b4_60s_windowed:25/25, current_silence_aware:0/33, full_slot:0/33；`zero_duration_worst_language_b4`=「Japanese」；`conclusion`=「B4 vs current_silence is not an identified contrast; no usable multi-view evidence exists on natural long songs」 |
| 联合约束求解 vs 顺序规则（结构会计） | `results/by_run/20260912_joint_cleanup/metrics.json` | `gtsinger_gain_over_shipped_pp`=2.02；`real_songs_degenerate_shipped`=0.1713；`real_songs_degenerate_joint`=0.0 |

## 已否证 / 已降级（不要重复投入）

| 主题 | canonical 来源 | headline（机器摘取） |
|---|---|---|
| 事后声学阈值修末字/长音 | `results/by_run/20260912_tail_acoustics/metrics.json` | `model_end_mae_gtsinger_sec`=0.0389；`model_end_mae_mir1k_sec`=0.0358；`rms_anchor_max_coverage_gtsinger`=0.3008；`rms_anchor_coverage_on_last_char_mir1k`=1；`last_char_units_mir1k`=17；`frozen_theta_transfer_delta_pp`=-13.37 |
| 局部修补倒序（交换/顺延） | `results/by_run/20260912_inversion_policy/metrics.json` | `gtsinger_best_policy`=「P1_swap_endpoints」；`gtsinger_best_hit`=0.1053；`gtsinger_gain_vs_shipped_pp`=10.53；`m4_all_policies_hit_zero`=True；`illegal_share_P0`=0.1672；`illegal_share_swap`=0.1964 |
| 间隙触发器跨语料复现 | `results/by_run/20260912_trigger_replication/metrics.json` | `m4_gap_auc_truncated`=0.5059；`m4_gap_spearman`=-0.0602；`m4_gap_spread_ms`=97.0；`gtsinger_gap_spearman`=0.7774；`gtsinger_gap_spread_ms`=483.0；`m4_entropy_auc_end_error`=0.6619 |
| 历史批次对比的可归因性 | `results/by_run/20260912_evidence_identity_audit/metrics.json` | `b4_vs_current_verdict`=「duplicate_configuration」；`b4_vs_current_identical_output_share`=0.92；`b4_vs_current_same_plan_share`=1.0；`divergent_songs_explained_by_audio_change`=True |
| 间隙残余触发器跨语料复现（M4 失败） | `results/by_run/20260912_separation_leakage/metrics.json` | `product_input_is_demucs_separated`=True；`separator`=「demucs htdemucs_ft two_stems=vocals」；`separation_quality_gate_exists`=True；`separation_quality_all_passed`=True；`measurable_gap_share`=0.1991；`vocal_active_in_gap_share`=0.8431 |

## 预算与决策

| 主题 | canonical 来源 | headline（机器摘取） |
|---|---|---|
| 重解码预算的可达上界 | `results/by_run/20260912_redecode_budget/metrics.json` | `fixable_share`=0.9153；`end_reachable_share`=0.9396；`start_reachable_share`=0.9552；`production_view`=5pct:{'trigger_reachable_pp': 1.02, 'trigger_optimistic_pp': 3.18, 'random_reachable_pp': 0.24, 'oracle_recoverable_pp': 5.02}, 10pct:{'trigger_reachable_pp': 1.88, 'trigger_optimistic_pp': 4.63, 'random_reachable_pp': 0.75, 'oracle_recoverable_pp': 7.02}, 20pct:{'trigger_reachable_pp': 2.67, 'trigger_optimistic_pp': 6.2, 'random_reachable_pp': 1.33, 'oracle_recoverable_pp': 7.02}；`long_note_unrecoverable_share`=0.6129；`long_note_trigger_matches_random`=True |
| 免费触发器的召回/精度 | `results/by_run/20260912_trigger_fusion/metrics.json` | `gtsinger_end_error_auc`=inversion:0.5035, low_conf_end:0.8054, high_entropy_end:0.8449, gap_residual:0.8838, fused_mean_rank:0.8501, any_flag_boolean:0.805；`gtsinger_end_error_recall_at_20pct`=inversion:0.1927, low_conf_end:0.5978, high_entropy_end:0.6402, gap_residual:0.2397, fused_mean_rank:0.6707, any_flag_boolean:0.6177；`production_view_auc`=inversion:0.5024, low_conf_end:0.8387, high_entropy_end:0.8716, gap_residual:0.6519, fused_mean_rank:0.8461, any_flag_boolean:0.7563；`long_note_auc`=inversion:0.5023, low_conf_end:0.6372, high_entropy_end:0.6946, gap_residual:0.9407, fused_mean_rank:0.6778, any_flag_boolean:0.6313；`real_song_flag_shares`=inversion:0.0633, gap_residual:0.1099, high_entropy_end:0.2001；`real_song_any_flag_share`=0.2904 |
| 字间隙触发器（GTSinger 口径） | `results/by_run/20260912_gap_shape/metrics.json` | `gap_over_core_pooled_auc`=0.925；`gap_over_core_within_item_median`=1.0；`gap_over_core_within_model_median`=0.8726；`rise_ratio_pooled_auc`=0.5799；`shape_hypothesis_supported`=False |

## 立即可用的三件产物

- `scripts/evaluation/audit_batch.py`：一条命令做可归因性 / 结构合法 / 阶段归因 / 钉锚点 / 起止顺序 / 修复可行性六项检查（gate 阈值集中在 `GATES`）；
- `docs/status/20260912_predelivery_checklist.md`：交付前检查清单（含本会话新增的口径规则）；
- `docs/status/20260912_session_findings_index.md`：按轮次的结论索引（✅/❌/♻️/⛔ 标注）。

## 仍待办（含需要资源的两项）

- **训练侧**（唯一被证明能抬高上限的方向：长音端点不可达率 70.8%→21.7%，r1→r2 已递减）：需 GPU；
- **能产生新候选的重解码实验**（更长右上下文 / 换窗口；须按域分别验证，因为长音端点偏置方向在清唱与伴奏间相反）：需 GPU；
- **产品语义决定**：raw 起止倒序目前是「静默钳成零长」，可选 (a) 重排 (b) 标 needs_redecode (c) 仅计入 summary（观测已实现）；
- **真实长片段自然收尾的人工真值**：GTSinger 全曲连续片段方案已评估可行（第 9 轮），需少量 GPU；
- 三项 HEAD 自带失败测试（`test_archive_builder`、`test_inline_realign_v4_full_mechanism`、`unit_realign/test_request_families`）本会话刻意未动，属主线待处理。

