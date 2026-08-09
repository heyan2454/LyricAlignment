# Final Session Report v2（10_FOLLOWUP 权威口径）

- label schema: `safe100_grey100_250_unsafe250_structural_v1`
- primary: `250ms correct coverage over ALL target units`
- scope: `development_selection (model_selection)`

## Transition（Task A reaggregate）
- **T1_direct_serial**: correct_coverage_250ms=0.396 (n=3374/3374) Safe=549 Grey=788 Unsafe=2037 legacy_320ms=0.491
- **T2_core_boundary_serial**: correct_coverage_250ms=0.401 (n=3374/3374) Safe=549 Grey=804 Unsafe=2021 legacy_320ms=0.496
- **T3_stable_boundary_serial**: correct_coverage_250ms=0.111 (n=998/3374) Safe=143 Grey=231 Unsafe=624 legacy_320ms=0.479
- **full_song**: correct_coverage_250ms=0.315 (n=3374/3374) Safe=414 Grey=648 Unsafe=2312 legacy_320ms=0.388

- **Selection v2（数据导出）**: product=`None`, mechanism=`None`, primary=250ms correct coverage over ALL target units

## Detector（Task C，partial evidence）
- H: blocked_api（hidden 未接入 real inference）
- PR: not_executed（需 Gate P corpus）
- combo AUC（heldout, 100/250 标签, Grey 排除）: R=0.6378250792299324; O=0.46111867934345585; R+O=0.6333456317108936; legacy8=0.5993880282677136; extended=0.6276902528610023
- working points（threshold_validation）: [{"point": "SA60", "threshold": 0.7822, "safe_accuracy": 0.5992, "unsafe_reject_rate": 0.6018269747447609}, {"point": "SA80", "threshold": 0.8324, "safe_accuracy": 0.7996, "unsafe_reject_rate": 0.4416980118216013}, {"point": "R95", "threshold": 0.6505, "safe_accuracy": 0.07976653696498054, "unsafe_reject_rate": 0.95}]

## Closed loop v3（Task B，retry-driven writeback）
- gate_c: {"passed": false, "n_songs": 9, "n_songs_passed": 0, "n_songs_failed": 9}
- conclusion: retry 无改善（v2 detector 保守）→ 无 retry-derived 写回 → Gate C 诚实失败，不虚报 recovery

## Superseded
- runs/research_transition_recovery_detector_20260808_corrected/09_reports/FINAL_SESSION_REPORT.json → superseded_for_formal_interpretation by FINAL_SESSION_REPORT_v2.json
- 原因: 旧报告以 320ms/0.32s 为 primary、无 Safe/Grey/Unsafe 标签、closed loop 无 retry writeback 语义