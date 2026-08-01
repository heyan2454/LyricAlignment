# Alignment Research v6 正式实验报告

## 运行与数据完整性

- Manifest 条目：21562
- 实际选择：21562
- 完成：21562
- 失败：0
- Formal 数据政策：formal consumes every manifest item; no dataset item cap
- Case 执行政策：`{"case_level_subsampling": false, "cases_per_item": 0, "max_chunk_groups_per_item": 0, "max_realign_cases_per_item": 0, "zero_means_unlimited": true}`
- Case-level subsampling：否
- Inference cache：`{"forward_wall_sec": 27590.138293165714, "hits": 604951, "misses": 442226}`

## 参数冻结

- Freeze effectiveness：normal_pilot_freeze
- Freeze warnings：`[]`
- Detector：logistic
- Detector threshold：0.988617
- Recommended thresholds：`{"detector_model_threshold": 0.9886165490831127, "detector_risk_threshold": 1.0, "detector_safe_threshold": 0.853116256427052, "dynamic_safe_score": 0.6234416406517662, "repairable_score_threshold": 9.357622968839299e-14}`
- Decoder：weighted_isotonic
- Formal decoder execution：`{"formal_serial_commit_policy": "decoder applied per model window before ownership split and cursor update", "item_count": 21562, "model_backed_rerun_wall_sec": 1560.749475961551, "route_source_counts": {"B4_plan_decoder_fallback": 3, "model_backed_serial_rerun_under_frozen_baseline_plan": 21559}, "selected_decoder": "weighted_isotonic"}`

## E0 Decoder 汇总

| 方法 | all MAE | non-training MAE | coverage | raw harm | raw repair |
|---|---:|---:|---:|---:|---:|
| raw | 0.049348 | 0.046018 | 1.000000 | 0.000000 | 0.000000 |
| official | 0.047794 | 0.044966 | 1.000000 | 0.006570 | 0.037455 |
| joint_start_end | 0.048895 | 0.045592 | 1.000000 | 0.000649 | 0.024387 |
| topk_sequence | 0.047258 | 0.042127 | 1.000000 | 0.003348 | 0.108002 |
| weighted_isotonic | 0.046896 | 0.044071 | 1.000000 | 0.004461 | 0.104178 |

### raw：按 dataset/split

| dataset / split | items | MAE | coverage |
|---|---:|---:|---:|
| m4singer / test | 839 | 0.053119 | 1.000000 |
| m4singer / train | 17748 | 0.031339 | 1.000000 |
| m4singer / validation | 1711 | 0.028755 | 1.000000 |
| m4singer_synthetic_long / test | 54 | 0.404235 | 1.000000 |
| m4singer_synthetic_long / train | 1080 | 0.353621 | 1.000000 |
| m4singer_synthetic_long / validation | 78 | 0.102526 | 1.000000 |
| mir1k / development | 8 | 0.040099 | 1.000000 |
| mir1k / heldout | 4 | 0.031557 | 1.000000 |
| mir1k / quick_v2_extra | 4 | 0.032347 | 1.000000 |
| mir1k / spare | 1 | 0.033242 | 1.000000 |

### official：按 dataset/split

| dataset / split | items | MAE | coverage |
|---|---:|---:|---:|
| m4singer / test | 839 | 0.057565 | 1.000000 |
| m4singer / train | 17748 | 0.032703 | 1.000000 |
| m4singer / validation | 1711 | 0.029879 | 1.000000 |
| m4singer_synthetic_long / test | 54 | 0.264427 | 1.000000 |
| m4singer_synthetic_long / train | 1080 | 0.302859 | 1.000000 |
| m4singer_synthetic_long / validation | 78 | 0.090301 | 1.000000 |
| mir1k / development | 8 | 0.041215 | 1.000000 |
| mir1k / heldout | 4 | 0.031939 | 1.000000 |
| mir1k / quick_v2_extra | 4 | 0.032320 | 1.000000 |
| mir1k / spare | 1 | 0.033242 | 1.000000 |

### joint_start_end：按 dataset/split

| dataset / split | items | MAE | coverage |
|---|---:|---:|---:|
| m4singer / test | 839 | 0.053076 | 1.000000 |
| m4singer / train | 17748 | 0.031089 | 1.000000 |
| m4singer / validation | 1711 | 0.028569 | 1.000000 |
| m4singer_synthetic_long / test | 54 | 0.376423 | 1.000000 |
| m4singer_synthetic_long / train | 1080 | 0.349756 | 1.000000 |
| m4singer_synthetic_long / validation | 78 | 0.111514 | 1.000000 |
| mir1k / development | 8 | 0.040769 | 1.000000 |
| mir1k / heldout | 4 | 0.031520 | 1.000000 |
| mir1k / quick_v2_extra | 4 | 0.032372 | 1.000000 |
| mir1k / spare | 1 | 0.033806 | 1.000000 |

### topk_sequence：按 dataset/split

| dataset / split | items | MAE | coverage |
|---|---:|---:|---:|
| m4singer / test | 839 | 0.049614 | 1.000000 |
| m4singer / train | 17748 | 0.030656 | 1.000000 |
| m4singer / validation | 1711 | 0.028395 | 1.000000 |
| m4singer_synthetic_long / test | 54 | 0.295837 | 1.000000 |
| m4singer_synthetic_long / train | 1080 | 0.332908 | 1.000000 |
| m4singer_synthetic_long / validation | 78 | 0.088448 | 1.000000 |
| mir1k / development | 8 | 0.041203 | 1.000000 |
| mir1k / heldout | 4 | 0.031690 | 1.000000 |
| mir1k / quick_v2_extra | 4 | 0.032245 | 1.000000 |
| mir1k / spare | 1 | 0.032867 | 1.000000 |

### weighted_isotonic：按 dataset/split

| dataset / split | items | MAE | coverage |
|---|---:|---:|---:|
| m4singer / test | 839 | 0.053768 | 1.000000 |
| m4singer / train | 17748 | 0.031425 | 1.000000 |
| m4singer / validation | 1711 | 0.028714 | 1.000000 |
| m4singer_synthetic_long / test | 54 | 0.319549 | 1.000000 |
| m4singer_synthetic_long / train | 1080 | 0.308183 | 1.000000 |
| m4singer_synthetic_long / validation | 78 | 0.087733 | 1.000000 |
| mir1k / development | 8 | 0.039816 | 1.000000 |
| mir1k / heldout | 4 | 0.031510 | 1.000000 |
| mir1k / quick_v2_extra | 4 | 0.032159 | 1.000000 |
| mir1k / spare | 1 | 0.033242 | 1.000000 |

## Detector 汇总

- 有 GT 的单位数：440646
- 冻结 Detector：`logistic`；score=`learned_risk_score`；threshold=0.988617

| 口径 | Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|
| unit error | 0.086277 | 0.052334 | 0.065150 | 0.050537 |
| event error | 0.062500 | 1.000000 | 0.117647 | — |
| repairable unit | 0.044194 | 1.000000 | 0.084647 | 1.000000 |
| safe boundary | 0.985418 | 0.347343 | 0.513638 | 0.064178 |
- source-song cluster bootstrap：clusters=436，F1 95% CI=[0.05925278272858728, 0.07135717552984228]。

## E2 人工腐化

- records：839308
- Detector unit F1=0.108026，event F1=0.197267，clean risk spans/case=0.901208。

### 按腐化类别

| category | items | MAE | coverage |
|---|---:|---:|---:|
| audio_end | 135468 | 0.109656 | 0.999808 |
| audio_start | 135468 | 0.214415 | 0.999808 |
| output_shift | 67734 | 0.952033 | 0.999808 |
| repeated_committed_text | 67734 | 0.057578 | 0.999825 |
| text_amount | 90312 | 0.221875 | 0.819763 |
| text_end | 135468 | 0.266160 | 0.776799 |
| text_start | 135468 | 0.457583 | 0.776912 |
| wrong_text | 67734 | 0.301930 | 0.999808 |

## E3 Decoder 困难区修复

- candidates：28618

### 按 span 来源与方法

| span_source / method | items | MAE | coverage |
|---|---:|---:|---:|
| detector / local_topk_sequence | 8826 | 0.235352 | 1.000000 |
| detector / local_weighted_isotonic | 8826 | 0.235465 | 1.000000 |
| oracle / local_topk_sequence | 5453 | 0.421786 | 1.000000 |
| oracle / local_weighted_isotonic | 5453 | 0.438156 | 1.000000 |

## E4 歌词输入与少量多次

| selector | items | MAE | coverage |
|---|---:|---:|---:|
| detector_selected | 22578 | 0.052993 | 0.999808 |
| fixed_longest | 22578 | 0.053596 | 0.999808 |
| fixed_shortest | 22578 | 0.541785 | 0.476162 |
| oracle_best | 22578 | 0.039108 | 0.996632 |
| sequential_expansion | 22578 | 0.053356 | 0.999808 |

### 96 vs 3×32

| method | items | MAE | coverage |
|---|---:|---:|---:|
| 1x96 | 2070 | 0.113433 | 1.000000 |
| 3x32_overlap_0 | 2070 | 0.071598 | 1.000000 |
| 3x32_overlap_4 | 2070 | 0.072376 | 1.000000 |
| 3x32_overlap_8 | 2070 | 0.074494 | 1.000000 |
- 调用与 RTF：`{"1x96": {"mean_calls": 1.0, "mean_rtf": 0.0020299358137628397}, "3x32_overlap_0": {"mean_calls": 3.0, "mean_rtf": 0.00391381203607029}, "3x32_overlap_4": {"mean_calls": 3.0, "mean_rtf": 0.003704433428690253}, "3x32_overlap_8": {"mean_calls": 3.0, "mean_rtf": 0.003560243382966419}}`

## E5 动态安全边界分窗


### 主指标

| variant | items | MAE | coverage |
|---|---:|---:|---:|
| dynamic_safe_minus0 | 807 | 1.464202 | 1.000000 |
| dynamic_safe_minus2 | 807 | 1.471570 | 1.000000 |
| dynamic_safe_minus4 | 807 | 1.454823 | 1.000000 |

| variant | cursor MAE(units) | missing | extra | recovery(units) | persistent failure |
|---|---:|---:|---:|---:|---:|
| dynamic_safe_minus0 | 0.836741 | 0.000000 | 0.000000 | 2.363065 | 0.013631 |
| dynamic_safe_minus2 | 0.728934 | 0.000000 | 0.000000 | 2.546366 | 0.011152 |
| dynamic_safe_minus4 | 0.613073 | 0.000000 | 0.000000 | 2.546366 | 0.011152 |

## E6 静音机制


### 主指标

| variant | items | MAE | coverage |
|---|---:|---:|---:|
| S0_baseline | 21527 | 0.126290 | 1.000000 |
| S1_hard_core_full_context | 2997 | 1.612631 | 1.000000 |
| S_cap_1p5s | 2997 | 1.799537 | 1.000000 |
| S_cap_4p0s | 2997 | 1.622748 | 1.000000 |
| S_history_cap_0p4s | 2997 | 2.026740 | 1.000000 |

| variant | cursor MAE(units) | missing | extra | recovery(units) | persistent failure |
|---|---:|---:|---:|---:|---:|
| S0_baseline | 0.014997 | 0.000000 | 0.000000 | 0.321190 | 0.108654 |
| S1_hard_core_full_context | 2.544909 | 0.000000 | 0.000000 | 2.008224 | 0.107441 |
| S_cap_1p5s | 2.723553 | 0.000000 | 0.000000 | 2.132309 | 0.109776 |
| S_cap_4p0s | 2.552877 | 0.000000 | 0.000000 | 2.054145 | 0.106440 |
| S_history_cap_0p4s | 3.074592 | 0.000000 | 0.000000 | 2.368219 | 0.132799 |
- 有静音、可评价的 item：3032；按静音长度分组数：20。

## E7 串行累计因果

- records：12736；满足“持续恶化且 reset 恢复”比例：0.136873

| injection | post MAE Δ | coverage Δ | degradation rate |
|---|---:|---:|---:|
| core_boundary_sec | 0.885882 | 0.000000 | 0.517735 |
| cursor_units | 0.094056 | 0.000000 | 0.272277 |
| previous_end_sec | 0.001485 | 0.000000 | 0.328104 |
- Reset 恢复：`{"full_reset": {"complete_count": 10358, "mean_coverage_change_vs_injected": 0.0, "mean_mae_change_vs_injected_sec": 1.4685546317074902, "recovery_rate": 0.356342923344275}, "text_reset": {"complete_count": 10358, "mean_coverage_change_vs_injected": 0.0, "mean_mae_change_vs_injected_sec": 1.471013858000997, "recovery_rate": 0.3562463796099633}, "time_reset": {"complete_count": 10360, "mean_coverage_change_vs_injected": 0.0, "mean_mae_change_vs_injected_sec": 1.51036879833498, "recovery_rate": 0.35164092664092667}}`

## E8 简化 Realign

- cases=18893；clean cases=16775；alternate-input candidates=37786。
- selected improvement=0.248371；harm=0.346514；clean harm=0.351021；oracle match=0.563503。
- 后续区域 MAE Δ=-0.002833，coverage Δ=0.000000；complete=111012，failed=2346，continuation failure=0.020695。
- 下游效应统计条件：`propagation_status == complete`；失败候选只保留 static diagnostic，不进入传播效应均值。

### Local candidate

| candidate | items | MAE | coverage |
|---|---:|---:|---:|
| alternate_official | 18571 | 0.217224 | 1.000000 |
| alternate_topk_sequence | 18571 | 0.211954 | 1.000000 |
| joint_start_end | 18571 | 0.188170 | 1.000000 |
| official | 18571 | 0.188586 | 1.000000 |
| raw | 18571 | 0.188512 | 1.000000 |
| topk_sequence | 18571 | 0.189582 | 1.000000 |

## E9 系统级 Pilot

- items=21562；beam width=0.110750；平均多 hypothesis 窗数=0.034552；平均 fallback 窗数=0.054077。
- selected complete rate=1.000000；selected/final-beam oracle match=0.529412；selected MAE Δ=0.000570；line boundary MAE=0.428036。

## 失败与 negative results

- Formal 未记录 item failure。

## 结论使用限制

- 无 GT test demo 只能用于结构、稳定性、跨输入一致性和人工视听，不用于声称 accuracy 提升。
- M4Singer train/validation/test 与 MIR-1K selection role 独立汇报；主泛化口径排除 training_exposure。
- Synthetic-long 按 source_song_id 聚类，seam-near 与 seam-far 分开解释。
- 参数仅由 pilot train/calibration 冻结；formal/held-out 不用于回调阈值。best-effort/default freeze 会降低结论效力，但不阻断 formal。
- 本报告只汇总实际存在的结果字段，不补写未运行或失败实验。
