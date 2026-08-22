# Review 6 — 产品化验证 Round 3 代码/数据审查

审查范围：
- `scripts/evaluation/run_gtsinger_diagnostic_batch.py`
- `scripts/evaluation/evaluate_gtsinger_alignment.py`
- `scripts/evaluation/evaluate_gtsinger_batch.py`
- `scripts/evaluation/aggregate_gtsinger_batch_results.py`
- `scripts/evaluation/build_operational_input_manifest.py`
- `results/comparisons/20260816_gtsinger_diagnostic_summary.json`
- `reports/progress/20260816_productization_validation_report.md`

方法：静态读码 + 实际运行 + 与外部 JSON 交叉核对。

## 结论
无 P0/P1。GTSinger 75 段全量结果来自实际 alignment JSON + GT JSON 重算，不是手抄。

## 已验证
- 75/75 段完成 R0/R1/R2，1226 单元全部 count match。
- R2 aggregate：both_100ms=0.9005, both_200ms=0.9551, both_500ms=0.9812，与 `aggregate_summary.json` 一致。
- `build_operational_input_manifest.py` 生成 30 条 raw-mixture 输入，路径均存在。
- 所有外部批次都有 `cleanup_report.md` 或可清理说明。

## MINOR
1. `run_gtsinger_diagnostic_batch.py` 没有 per-item 失败隔离；单条失败会中断整个 batch。当前 75/75 成功，后续可加 `--resume-failed` 或 per-item try/except。
2. `evaluate_gtsinger_batch.py` 的 aggregate 使用 round 后累加，可能产生 ±1 计数误差；当前与真实值误差可忽略。
3. `build_operational_input_manifest.py` 未把 annotation 的 aligned lyrics 内容抽成纯文本；后续 vocal 派生后需要再生成 lyrics txt。

## 建议
- 下一步在 MIR/Jamendo vocal 派生后，用 `operational_input_manifest.jsonl` 驱动正式评测。
- GTSinger speech-like 低分段应单独维护一个 hard-case 子清单。
