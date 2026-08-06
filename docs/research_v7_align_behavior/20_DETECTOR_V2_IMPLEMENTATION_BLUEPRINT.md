# Detector V2 实现蓝图

## 1. 新旧边界

继续复用 research_v7 的 request/evidence/canonical mapping 基础，但不得直接复用旧 `LogisticAssessor` 的模型、阈值或旧 E1 risk。建议新增 v2 文件，旧实现保留为历史对照。

建议运行根：

```text
runs/research_v7_detector_v2/<run_id>/
  preflight/
  manifests/
  evidence/
  features/
  signal_atlas/
  models/
  evaluations/
  reports/
  failures.jsonl
```

## 2. 建议模块

| 文件 | 职责 |
|---|---|
| `detector_v2_contract.py` | 三态枚举、half-open 区间、输出 partition 校验 |
| `detector_v2_metrics.py` | false-accept、reject/protected recall、safe 代价、interval@75/@100 |
| `detector_v2_coverage.py` | 必做覆盖矩阵、禁用指标名、完成 gate |
| `detector_v2_labels.py` | raw/official correctness、grey、repeat occurrence 标签 |
| `detector_v2_evidence.py` | H/R/O/V evidence schema 与防泄漏 |
| `detector_v2_features.py` | 单 unit、邻域、跨视图、区间序列特征 |
| `detector_v2_models.py` | logistic、GBDT、hidden probe、一个序列模型 |
| `detector_v2_intervals.py` | 两阈值三态与轻度合并 |
| `detector_v2_serial.py` | accept/reject/uncertain 到 commit/provisional/unresolved |

本 patch 先提供 contract、metrics、coverage 基础；agent 继续实现其余模块。

## 3. Evidence schema

每个 row 至少包含：

```json
{
  "request_identity": "sha256:...",
  "view_id": "full|sparse|overlap|review",
  "canonical_unit_id": 123,
  "raw": {
    "start_sec": 12.3,
    "end_sec": 12.6,
    "start_entropy": 0.4,
    "end_entropy": 0.5,
    "start_margin": 0.2,
    "end_margin": 0.3,
    "topk": []
  },
  "official": {
    "start_sec": 12.35,
    "end_sec": 12.62,
    "repair_start_shift_sec": 0.05,
    "repair_end_shift_sec": 0.02
  },
  "hidden": {
    "available": true,
    "schema": "boundary_last4_v1",
    "start": {},
    "end": {}
  }
}
```

GT、mutation mask、family 和 error magnitude 只能出现在 label/stratification 文件，feature extractor 启动时必须 assert 禁止字段未进入 features。

## 4. Label schema

raw 与 official 分别输出：

```json
{
  "canonical_unit_id": 123,
  "raw_label": "safe|unsafe|grey|ambiguous",
  "official_label": "safe|unsafe|grey|ambiguous",
  "raw_onset_error_ms": 40,
  "raw_offset_error_ms": 70,
  "official_onset_error_ms": 35,
  "official_offset_error_ms": 60,
  "occurrence_correct": true
}
```

训练只使用 safe/unsafe；grey/ambiguous 只进入测试分层与 uncertain 行为分析。

## 5. 异常 manifest

每条异常必须有 matched legal baseline identity 与唯一主要因素：

```json
{
  "cohort": "crop_shift",
  "family": "start_late",
  "severity": {"seconds": 2.0},
  "source_song_id": "...",
  "split": "test",
  "baseline_request_identity": "sha256:...",
  "request_identity": "sha256:..."
}
```

不得用大量相关 attempts 代替 source-song 数。random replace 的 indices 与 seed 必须显式保存。

## 6. Hidden audit

hook 开/关对同一 deterministic input 比较：

- logits/top-k；
- raw time；
- official time；
- output row 数与 canonical mapping；
- 最大绝对差与容忍度；
- hidden token/layer/boundary shape。

失败时不能把全零 hidden 当作 H 特征。coverage matrix 中 `hidden.status=blocked`，并记录原因。

## 7. Feature 与模型

先生成统一 feature table，再离线做所有消融。每列带 group：H/R/O/V/context。训练器通过列组选择，不重复 forward。

区间序列模型的输入必须保留 canonical 顺序与 mask。不得把同一歌曲不同窗口随机打散后用于 train/test。

## 8. 三态与区间

使用 half-open canonical 区间 `[start,end)`。输出必须精确覆盖输入 queried intervals。当前 patch 的 `validate_detector_output()` 是硬 gate。

由 `p_bad` 冻结双阈值，生成 unit state 后合并相邻同态。只允许：

- 填补长度 1 的小孔；
- reject 两侧最多 1 unit 降为 uncertain。

所有后处理规则在 validation 冻结并写 hash。

## 9. 指标

主函数输入 unit state、safe/unsafe/grey GT 与真实错误区间，输出：

- unsafe false-accept；
- reject/protected recall；
- safe accept/reject/uncertain；
- interval reject/protected @75/@100；
- 长错误区完全接受率；
- 最长连续 unsafe 被 accept 长度。

报告必须同时给 micro 与 source-song macro，并明确空分母为 `null`，不得自动变 1。

## 10. 覆盖矩阵

`DETECTOR_V2_COVERAGE_MATRIX.json` 中每个 required cell 至少含：

```json
{"status":"complete","artifact":"...","n_source_songs":6,"n_unsafe_units":123}
```

`status=complete` 但分母为 0 或 artifact 不存在，validator 必须失败。旧禁用指标名出现也必须失败。

## 11. 推荐命令

```bash
PYTHONPATH=src python scripts/research_v7/build_detector_v2_coverage_matrix.py \
  --init configs/research_v7/detector_v2_required_coverage.json \
  --out runs/.../DETECTOR_V2_COVERAGE_MATRIX.json

PYTHONPATH=src python scripts/research_v7/build_detector_v2_coverage_matrix.py \
  --validate runs/.../DETECTOR_V2_COVERAGE_MATRIX.json \
  --repo-root .

pytest -q tests/research_v7/test_detector_v2_contract.py \
          tests/research_v7/test_detector_v2_metrics.py \
          tests/research_v7/test_detector_v2_coverage.py
```
