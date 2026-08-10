# Second Supplement Report（二次补充）

second_supplement_completed: **True**

- GT 口径: **real_gt_pinyin_overlay**（二次补充的 binding/label 用真实 GT（pinyin overlay: derived/20260723_m4singer_overlay_slur_time_v1/prepare/m4singer_character_annotations.jsonl + 段偏移投影，见 src/lyricalign/research_transition_recovery_detector/real_gt.py）重建；旧 uniform GT 的 authoritative 549/804/2021 与 R=0.632 修正链作废。）

## Gates
- {"binding_mismatch_zero": true, "binding_consistent": true, "P_distinct_second_path": true, "interval_grey_separated": true, "sequence_fair_compared": true, "PR_heldout": true, "recovery_rebuilt": true}


## Binding（真实 GT）
- model_selection counts: {'safe': 3093, 'grey': 97, 'unsafe': 38, 'n_units': 3374}
- authoritative expected (real GT pinyin overlay): {'safe': 3093, 'grey': 97, 'unsafe': 38}，n_units=3374 → binding_consistent PASS（uniform GT 549/804/2021 已作废）

## Detector v4（真实 GT 对齐）
- 单信号 AUC: {"H": 0.8821, "R": 0.9762, "O": 0.7976, "RO": 0.7733, "V": 0.6599, "P": 0.83, "S": 0.8175}
- R+sel: 0.9606，selected=V
- R=0.976 反映真实 GT 下模型对齐质量（Safe 占比 91.7%）；旧 0.665→0.632 修正注释作废；V 无增益（delta_over_R=-0.0156）

## P（coherent second path）
- P 单信号 AUC: 0.83
- exact k-best DP 实现；修复后 evidence_P（recollect）：model_selection 34 ok + 2 no_monotone_path

## Interval v2
- real GT 下 n_safe=2890，unsafe=23，grey=109；R95 unsafe_reject=0.913；SA60+R95_joint feasible=False（91.3%<95%）；按 song intervalization

## Sequence（公平对比）
- MLP 0.9762 vs CNN1D 0.7745（共享 train-only scaler）→ MLP 与 R 等价，CNN1D 更低 → sequence negative

## PR（held-out）
- OOF pooled AUC 0.5103，LOSO macro 0.5497，correctness AUC 0.5103
- PR 与冻结 correctness 均 ~随机 → negative（决策时无法预测 episode risk）

## Recovery
- 36 retry windows: {"retry_not_improved": 30, "retry_worsened": 6}（30 not_improved / 6 worsened / 0 improved_block）
- 有 before 数据窗口 9/36（其余 serial 提交为空）
