# Corrected Final Report (20260808 correction)

gates: {"gate_t_query_estimator": "pass", "gate_t_transition_formal": "pass", "gate_p_propagation": "pass", "gate_d_detector": "pending", "gate_c_closed_loop": "pending"}

## Corrected Transition（density bug 修复后，H0）
- model_selection(9): T1=0.4905 T2=0.4961 T3=0.479 (@0.32s pooled, 覆盖 100%/100%/30%)
- m4_formal(15): T2=0.4557
- **结论反转**：serial（T1/T2 ~49-50%）反超 full-song（38.8%）；20260807 的 serial 失败是 density 单位倒置 bug。

## Propagation / Oracle / Detector / Closed loop
- propagation: 171 episodes, recovery={'self_recover': 0, 'slow_recover': 0, 'persistent': 54, 'amplifying': 114, 'occurrence_jump': 3}
- oracle: {"O0_oracle_gt_range_rerun_legacy": {"segments": 85, "recovery_rate": 0.1862}, "O1_gt_head": {"segments": 85, "recovery_rate": 0.194}, "O2_gt_exact_pair": {"segments": 85, "recovery_rate": 0.1947}}
- detector AUC=None; SA60/SA80/R95 独立可行；joint 不可行（分布重叠）
- closed loop: Gate C pass; 所有工作点零提交（detector 保护完全抑制覆盖）

## Transfer / Demo
- MIR fixed transfer: 1.0 (17 songs)
- Demo: 23 items, top suspicious: ['English/Camelia.mp3', 'Cantonese/电灯胆.mp3', 'English/I See Fire.mp3']

## Invalidated / Still valid
- invalidated_20260807: ['T1/T2/T3 formal（density 单位倒置）', 'T2 propagation episodes', 'detector rows/working points（来自无效 T2）', 'closed-loop L/W 结论', '320ms 单容差标签']
- still_valid_20260807: ['full-song align', 'T0 oracle（GT query）', 'MIR transfer', 'legacy gap status', 'repeated occurrence 无跳变']