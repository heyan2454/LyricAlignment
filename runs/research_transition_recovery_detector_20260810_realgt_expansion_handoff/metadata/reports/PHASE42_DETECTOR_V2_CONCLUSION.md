# Phase 4.2 Detector V2 结论（Raw-only detector：fit B → lock → eval A）

## 结果摘要

| 评估 | raw R combo | official R combo |
|---|---|---|
| M4 song-heldout (A=test) | n_test=4150 | n_test=4149 |
| protected_recall | **0.904** | **0.914** |
| reject_recall | 0.895 | 0.903 |
| safe_accept_rate | **0.900** | 0.839 |
| safe_reject_rate | 0.061 | 0.110 |
| safe_uncertain_rate | 0.039 | 0.051 |
| unsafe_accept (漏放) | 31/323 | 30/349 |
| unsafe_reject (命中) | 289 | 315 |
| interval reject_recall@75/@100 | 0.697 / 0.688 | 0.729 / 0.720 |
| n_unsafe_intervals | 109 | 107 |

Family-LOO（mutation family=baseline/missing，排除一 family 重训再打分）：
- raw: baseline-excluded pr=0.909/sa=0.906；missing-excluded pr=0.891/sa=0.903
- official: baseline-excluded pr=0.922/sa=0.857；missing-excluded pr=0.910/sa=0.835
- 排除任一 family 性能几乎不变 → 无 family 过拟合。

## 关键事实
- B (dev) 5 首歌拆 4 train (8500 units) + 1 validation (真实, 1908 units, 仅 29 unsafe)。
- train_detector_v2 在 raw 与 official 均自动选 **R (Raw-only)** combo 为最优
  （inner-split pr95=0.957/sa=0.816；O 仅 sa=0.005，R+O sa=0.392）→ Raw-only 成立。
- 冻结阈值 T_accept=0.1655, T_reject=0.1684 (raw)；0.1519/0.1522 (official)。
- 外部 validation 仅 1 首 29 unsafe → FROZEN 报 protected_recall=0.655、constraint_violated=true，
  但 A 上实际 pr=0.904 → **validation 样本过小是悲观低估，非过拟合或阈值错置**。

## 执行链
1. B: manifests/{ANOMALY=90×REQUESTS, MULTIVIEW=15×comparison_group} → build_detector_v2_evidence (90/90→5204 rows)
2. B: label_detector_v2_run（preflight/SOURCE_SONG_SPLIT: 4 train + 1 validation）
3. B: train_detector_v2（--min-safe-accept-rate 0.7）→ detector_v2/MODEL_SELECTION + FROZEN_OPERATING_POINTS
4. A: manifests（同构 90/15）→ build_detector_v2_evidence (90/90→4511 rows) → label (5×test)
5. 合并 stage3b_cohort_ab_eval/: evidence_v2(180) + LABELS(19430; train 8500/val 1908/test 9022)
   + FROZEN_OPERATING_POINTS.json
6. evaluate_detector_v2 → detector_eval/M4_SONG_HELDOUT.json + FAMILY_LOO.json

## 备注 / 修正记录
- family-LOO 初跑崩（NaN）：LABELS family=None → _family_map 全 'unknown' → loo 后 train 空。
  补丁：由 evidence 内 attempt.request.request_id + ANOMALY_MANIFEST.mutation_type 回填
  family ∈ {baseline, missing}，全 19430 行无缺失。
- LABELS 里 request_identity 是 evidence 文件名 sha256；真实 request_id 需从 evidence 内容取。
- 合并 run-root 仅为评估使用；train/val/test 均未跨界（train/val 只来自 B，test 只来自 A）。
