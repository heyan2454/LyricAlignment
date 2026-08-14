# WP7 — E5 no-GT selector/safety（V）

- 阶段：G6 (P5) E5 no-GT selector/safety
- 日期/运行：2026-08-14
- 实现：
  - `src/lyricalign/unit_realign/no_gt_selector.py`
  - `scripts/unit_realign/run_no_gt_selector.py`
- 修订：`src/lyricalign/unit_realign/unit_gate_features.py`（`ALLOWED_FEATURE_KEYS` 增补 no-GT selector 信号：`margin/entropy/detector_state/detector_p_bad/context_displacement_ms/fixed_point_spread_ms/min_margin/num_margins_above/split`；schema 仍 `unit_realign_no_gt_features_v1`，向后兼容追加）
- smoke 产物：`/home/hyan/Data/lyricalign/runs/wp7_no_gt_selector_smoke_20260814/`
  - `01_signals/SIGNAL_AUDIT.json`
  - `02_selector/FROZEN_SELECTOR.json`
  - `03_heldout/HELDOUT_EVAL.json`
  - `06_runtime/RUN_STATE.json`
  - `FINAL_SELECTOR.json`
- 纯 CPU：读缓存 candidate/evidence，`forward=0`、无 GPU。

---

## 1. 只接实际可得信号

按 07 §WP7 / E_note §2，仅接受能从「已有缓存 candidate/evidence + 可选 FrozenScorer feature matrix」真正导出的 no-GT 信号。信号白名单 `SIGNAL_NAMES`（13 项）全部来自 `unit_gate_features.ALLOWED_FEATURE_KEYS` 与 `audio_views`
的 `_SELECTABLE_NUMERIC_KEYS`，方向语义：
- **lower_is_safer**：`detector_p_bad`、`detector_p_bad_after`、`entropy`、`raw_official_disagreement_ms`、`mean_boundary_displacement_ms`、`context_displacement_ms`、`fixed_point_spread_ms`
- **higher_is_safer**：`margin`

**NO_GT_PROXY = `detector_p_bad`**：no-GT 主代理，来自 FrozenScorer 特征矩阵（`--features`），**非 GT 误差**（不读 `gt_eval`/`verdict`/GT delta）。

### smoke 实测信号可用性（`SIGNAL_AUDIT.json`）

证据源：`unit_realign_confirmation_no_gt_20260813/02_behavior/forward/evidence`（content-addressed `.json`，40 条 payload，sample），`n_unit_rows=305`。

| 信号 | usable? | 状态 |
|---|---|---|
| `entropy` | ✅ 可用 | 来自 posterior/raw `start/end_entropy` |
| `margin` | ✅ 可用 | 来自 posterior/raw `start/end_margin` |
| `raw_official_disagreement_ms` | ✅ 可用 | raw vs official decoder 边界差 |
| `detector_p_bad`（proxy） | ❌ 缺失 | 本 evidence 无；需 FrozenScorer feature matrix（`--features`） |
| `detector_state` | ❌ 缺失 | 本 evidence 未携带三态；来自 detector 归并 |
| `context_displacement_ms` / `mean_boundary_displacement_ms` | ⚠️ smoke 缺 | confirmation evidence 中 raw/official 用 `global_character_index`、baseline 用 `canonical_unit_id`，跨命名空间未 merge（真实校准应预对齐） |
| structural / `fixed_point_spread_ms` | ❌ 缺失 | 视 multi-iteration/multi-view 产物是否携带 |

→ `audit_available_signals(payloads, feat_rows)` 逐信号输出 `{signal: n_available, n_missing}`；`--features` 给入特征矩阵后 `detector_p_bad` 亦转可用（见下）。

### 带 FrozenScorer 矩阵的代理路径（合成 smoke）

`unit_realign_no_gt_selector_feat_smoke_20260814`：60 行 `unit_realign_no_gt_features_v1`（带 `detector_p_bad/margin/entropy/raw_official_disagreement/context_displacement`）。`detector_p_bad` 进入 usable，`p_bad_threshold` 在 freeze split 按 85 百分位校准为 0.79。证明「proxy 来自特征矩阵、非 GT 误差」路径可跑。

---

## 2. Frozen selector（`FROZEN_SELECTOR.json`）

规则冻结于 discovery/validation split，**不调参对 heldout**。默认规则：

| 规则 | 默认 | 说明 |
|---|---|---|
| `p_bad_threshold` | 0.5（freeze 后可校准到 p85） | proxy>thr => suspect |
| `raw_official_tight_ms` / `loose_ms` | 30 / 80 | raw/official 一致窗口；>loose 判 disagreement |
| `context_disp_tight_ms` / `loose_ms` | 5 / 20 | 仅上下文 displacement 安全窗口 |
| `max_overlap_sec` | 0.020 | 单元重叠/inversion 结构嫌疑 |
| `max_spread_ms` | 50 | fixed-point spread>50ms 判不稳定（仅 stability） |
| `margin_min` | 0.2 | margin<0.2 低置信 |

`freeze_simple_selector(features, split)` 输出冻结规则 + `calibration_stats`（freeze split 上各信号 p50/p90）。

---

## 3. Heldout 一次评价（`HELDOUT_EVAL.json`）

`evaluate_heldout_once(selector, heldout_features)` 只对 heldout 求值**一次**，同一读上分开恢复优先 / 安全优先两个 operating point。分档：`safe/suspect/reject/unsupported`。

### 缓存 evidence smoke（无 proxy）

| operating point | n_selected | safe_cov | reject | unsupported | 解读 |
|---|---|---|---|---|---|
| **recovery-first** | 208 | 0.682 | 0.102 | 0 | 用 margin/entropy/raw-official 选中较安全候选 |
| **safety-first** | 0 | 0.0 | 0.059 | **208** | 要求 p_bad proxy；缺失 → 全部 fail-closed `unsupported` |

→ 正确体现「proxy 缺席时 safety-first 拒批」的 fail-closed 语义。

### FrozenScorer 特征矩阵 smoke（proxy 可用）

`p_bad_threshold=0.79`（freeze p85）。recovery-first reject=0.667 / safety-first reject=0.350、safe_cov 0 vs 0.167 —— 两口径因 disagreement/context 门限不同而分开报告。

---

## 4. GT firewall（全绿）

- 每条 feature/selector row 过 `unit_gate_features.assert_no_gt_feature_row`（严格 allowlist，仅 `ALLOWED_FEATURE_KEYS`，递归）。
- 每条 row 过本模块 `assert_no_label_leak`（词级拦截 evaluator 结局命名空间：`gt_eval/verdict/evaluator/oracle_/rescue/outcome/harm`）。
- 经豁免修正：①`repeat_gt_starts`（请求构造参数，非 evaluator 结局）不再误触发；②`attempt.gt_eval`（evaluator-only 结局）正确拦截，故防火墙施加于**发射出的 no-GT row**（而非含 evaluator 列的多消费者证据 envelope）。
- 编排层仍在 `evaluate_*` join GT，runner/ranker 不接 GT 路径、不读 `attempt.gt_eval/verdict`/GT delta。

负测试样例（全部拦截）：
```
{'verdict':'bad'}       -> no-GT leak at .verdict
{'oracle_disp':1.0}     -> no-GT leak at .oracle_disp
{'gt_eval':None}        -> no-GT leak at .gt_eval
{'evaluator_row':{}}    -> no-GT leak at .evaluator_row
```

---

## 5. 遗留（MINOR → backlog，不阻塞）

1. **confirmation evidence 单元命名空间未对齐**：raw/official 以 `global_character_index`、baseline 以 `canonical_unit_id` 标识，`mean/context_displacement_ms` 在 smoke 上为 None。真实 WP8 接线应对齐 canonical 归并（建议复用 `unit_gate_features.build_unit_features`，其已按 `canonical_unit_id` 合并）。
2. `detector_p_bad`/tri-state 需 FrozenScorer 特征矩阵（`--features`）或 WP8 接线后透传；本 evidence 无。
3. `evaluate_heldout_once` smoke 在相同缓存集上运行并打印 `_smoke_split_warning`；正式脚本须按 region identity 先切 discovery/heldout 再送评价。
4. `disjoint_check` 目前作为独立 helper 保留未接线；正式 split 管理落地后可删或接。

---
## 复现

```bash
conda activate lyricalign-qwen; cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/unit_realign/run_no_gt_selector.py \
  --evidence-dir /home/hyan/Data/lyricalign/runs/unit_realign_confirmation_no_gt_20260813/02_behavior/forward/evidence \
  --out-root /home/hyan/Data/lyricalign/runs/wp7_no_gt_selector_smoke_20260814 \
  --split heldout --smoke --max-payloads 40
```
