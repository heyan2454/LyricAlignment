# B Note — Current baseline 与 B4 pre-slot 核实

> 生成时间：Codex 前置核实，为 `07_CODEX_IMPLEMENTATION_PLAN.md` 提供证据。
> 用途：回答 4 个核实问题（Current exact resolved / hash 序列化机制 / B4 pre-slot 可复现性 / commit-provisional 编码位置）。
> 说明：以下搜索范围主要有 `src/lyricalign/demo/`、`src/lyricalign/realign_recovery/`、`src/lyricalign/unit_realign/`、`scripts/demo/`。未逐一读全每一行，凡未确认项标记"未知/需核实"。

---

## 问题 1 — 当前 Current baseline 的 exact resolved values

### 定位（代码默认字面量，非文档猜测）

**核心 identity 来源**：`src/lyricalign/realign_recovery/frozen_baseline.py` 的 `FROZEN_BASELINE_IDENTITY`（第 24-39 行），这是 Current full-slot baseline 的权威冻结字面量：

```python
{
  "model_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
  "model_revision": "c07281df297b9905d24a508279258cccf987a064",
  "checkpoint_path": "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750",
  "processor_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
  "request_mode": "full_slot",              # ← Current 是 full-slot
  "core_sec": 60,
  "left_context_sec": 10,
  "right_context_sec": 10,
  "silence_aware_window_plan": True,
  "decoder_view": "raw",                     # ← 对应 B4 的 decoder_kind=official? 需核实映射
  "detector_artifact_sha256": <运行时计算，文件缺失为 "MISSING">,
  "detector_accept_threshold": 0.16546343952822562,
  "detector_reject_threshold": 0.16837782471409926,
  "real_gt_source": "m4singer_overlay_slur_time_v1",
  "schema_version": "realign_recovery_baseline_identity_v1",
}
```

- detector artifact 路径：`/home/hyan/Data/lyricalign/runs/research_transition_recovery_detector_20260810_realgt_expansion_handoff/stage3b_cohort_ab_eval/FROZEN_OPERATING_POINTS.json`（第 11-15 行）。若文件不存在，sha256 为字面量 `"MISSING"`。

### Window / silence resolved values（代码默认参数字面量）

`src/lyricalign/demo/window_planning.py` → `build_silence_aware_window_plan`（第 129-142 行）默认参数：
- `min_silence_sec = 0.8`（对应 B4 `silence_boundary_min_sec=0.8`）
- `strong_silence_sec = 1.5`（对应 `strong_silence_anchor_sec=1.5`）
- `boundary_search_sec = 6.0`（对应 `silence_boundary_search_sec=6.0`）
- `leading_silence_min_sec = 2.0`（对应 `leading_silence_min_sec=2.0`）
- `tail_min_core_sec = 18.0`（对应 `tail_min_core_sec=18.0`）
- `minimum_core_sec = 12.0`（对应 `minimum_core_sec=12.0`）

该函数另导出 `parameters` 内联 dict 记录 `left_context_sec/right_context_sec`，schema_version=`silence_aware_window_plan_v1`，policy=`target_core_with_silence_snap_and_tail_redistribution`。

> 注：`window_planning.py` 还包含 `build_strict_silence_boundary_window_plan`（strict_silence_v1），但 B4/Current 均 `strict_silence_boundary_plan=false`，故 Current 使用 **silence_aware 全局版**，与 B4 冻结一致。

### Current baseline 的 decoder / transition state machine / full-slot semantics

- **decoder**：`decoder_view == "raw"`（frozen_baseline.py 第 34 行）。GPU decoder 位于 `demo/gpu_boundary_decoder.py`（raw infer_slice → timestamp slots，含 TCN/Transformer、`build_slot_features`、非降序投影）。B4 冻结项为 `decoder_kind=official`；当前字段是 `decoder_view=raw`。两者是否等价（official ≤> raw）是**需核实**项。
- **serial/full-slot**：frozen_baseline.py 明确 `request_mode = "full_slot"`。串行窗口构造在 `demo/karaoke.py`（`build_serial_windows`、`inference_source: "strict_serial_core"`）。切片/所有权/commit 逻辑在 `demo/alignment_artifacts.py`（`stage_rows`，注释 "serial ownership/commit decisions"，4 阶段 raw/processor_decoded/selected/final）与 `demo/karaoke.py`。
- **transition/state machine**：`demo/realign_diagnostics.py`（`stage_transition_provenance`）有 stage 快照与 transition 记录，但未证明这是唯一"exact transition/state machine"。**需核实**完整状态机入口（建议查 `demo/inline_realign.py` 与 serial runner 主循环）。

### CURRENT_BASELINE_RESOLVED.json 建议字段

应输出（与 frozen_baseline 字段对齐 + 展开的窗口参数 + decoder/serial）：
- identity 字段全集（model/checkpoint/revision/core/left/right/silence_aware/decoder_view/阈值/gt_source/schema_version/request_mode）
- cascade: silence_aware_window_plan=True, strict_silence_boundary_plan=False, compress_silence_audio=False, skip_silent_windows=True（skip_silent 未在 frozen_baseline 显式见，**需核实**其默认/接线位置）
- 窗口参数：min_silence_sec/strong_silence_sec/boundary_search_sec/leading_silence_min_sec/tail_min_core_sec/minimum_core_sec(left/right)
- decoder_kind/decoder_view 映射；serial semantics（request_mode=full_slot）
- actual_writeback=0（shadow-only）

---

## 问题 2 — resolved config 序列化为 hash 的机制

已确认存在可复用机制：
- `src/lyricalign/realign_recovery/baseline_identity.py`：`canonical_identity_json`（sort_keys/compact/ensure_ascii）→ `identity_digest` = sha256(dict)。`validate_identity` 校验字段。**可直接复用**。
- `src/lyricalign/realign_recovery/frozen_baseline.py`：`FROZEN_BASELINE_IDENTITY` dict + detector 文件 sha256。可作为 resolved 输出的源。
- `src/lyricalign/demo/run_state.py`：`canonical_hash(payload)` / `file_identity` / stage/item begin/finish 带 `request_hash` 缓存管理（`begin_stage`/`stage_is_complete`/`invalidate_stage`）。可复用为内容寻址 stage 缓存。
- `src/lyricalign/research_v7/canonical_mapping.py`：未在本轮直接读取，存在性已在 AGENTS 架构中确认。**需核实**其 canonical hash 契约能否直接复用。

> 结论：序列化机制已存在（baseline_identity + run_state），CURRENT_BASELINE_RESOLVED.json 可基于 `FROZEN_BASELINE_IDENTITY` + 窗口参数 dict 做 canonical sha256，建议复用 `baseline_identity.identity_digest`。

---

## 问题 3 — B4 pre-slot / non-slot serial 语义是否仍可真实复现

### 关键结论：Current 与 B4 语义在 request 层级不同

`FROZEN_BASELINE_IDENTITY.request_mode == "full_slot"` 是 Current；B4 冻结文档（`02_B4_60_...md`）描述的是 **pre-slot / non-slot / serial** 行为，且 03 文档明确警告："不能仅把当前 full-slot runner 配成同样 60/10/10 参数后冒充 B4"。

### B4 参数 → 代码配置项映射

| B4 冻结项 | 代码对应 | 状态 |
|---|---|---|
| core_sec=60 | frozen_baseline `core_sec`；window_planning target_core_sec | ✅ 确认 |
| left/right_context_sec=10 | frozen_baseline；window_planning | ✅ 确认 |
| decoder_kind=official | frozen_baseline `decoder_view=raw`（映射**需核实**） | ⚠️ 需核实 |
| silence_aware_window_plan=true | `build_silence_aware_window_plan` | ✅ 确认 |
| strict_silence_boundary_plan=false | 使用 silence_aware 版 | ✅ 确认 |
| compress_silence_audio=false | **需核实**（未在该窗口规划模块见） | ⚠️ 需核实 |
| skip_silent_windows=true | **需核实**（serial runner 层） | ⚠️ 需核实 |
| silence_boundary_min_sec=0.8 | `min_silence_sec=0.8` | ✅ 确认 |
| strong_silence_anchor_sec=1.5 | `strong_silence_sec=1.5` | ✅ 确认 |
| silence_boundary_search_sec=6.0 | `boundary_search_sec=6.0` | ✅ 确认 |
| leading_silence_min_sec=2.0 | `leading_silence_min_sec=2.0` | ✅ 确认 |
| tail_min_core_sec=18.0 | `tail_min_core_sec=18.0` | ✅ 确认 |
| minimum_core_sec=12.0 | `minimum_core_sec=12.0` | ✅ 确认 |
| actual_writeback=0 | shadow-only（run_state/realign 默认） | ✅ 语义确认 |

### 是否存在可运行的 pre-slot/non-slot runner

候选 runner 盘点（均存在文件，是否可直接跑 B4 **需核实**）：
- `scripts/demo/align_qwen_fa_serial_demo.py` — 串行 demo runner，最接近 B4 serial/non-slot 语义。
- **追加核实（主 agent 2026-08-14）**：该 serial demo 通过 `--decoder` 参数支持 `decoder_kind ∈ {official, raw, gpu_tcn, gpu_transformer, *RESEARCH_TIMESTAMP_DECODERS}`，默认 `decoder_kind="official"`（第 257/354/376 行校验 official/raw；第 417 行 official 分支走 slot 非空，raw 分支 `timestamp_slot_indices=None` 仅第 488 行）。它是 **serial/non-slot 语义** runner（`build_serial_windows` + committed cursor），不是 Current 的 `request_mode=full_slot`。因此 **B4 可用该 serial runner + `decoder_kind=official` + B4 窗口参数 复现**，无需 full-slot runner 冒充。但"exact B4 是否要求特定 serial control / cursor 版本"仍需跑一个 B4 对照 run 与历史 B4 artifact 对账。
- `scripts/demo/run_inline_realign_pipeline.py` / `scripts/demo/run_inline_realign_experiment.py` / `run_inline_realign_*` batch（AGENTS 中 listed）— inline realign v4 现行版。
- `scripts/demo/align_qwen_fa_raw_guarded_demo.py` — raw-guarded ("strict_serial_core") 版。
- `scripts/realign_recovery/`（B4 shadow oracle/e5/e7/e8/closed_loop 系列，为非修复 shadow 实验）。
- `scripts/unit_realign/run_unit_realign.py`、`run_forward_real.py`、`run_unit_consensus.py` — unit-level，带 `active_slot_indices/fixed_slot_rows/slot_constraint_schema`（见 `unit_realign/request_families.py`）。

**结论**：B4 的 60/10/10 + silence-aware 参数基本都能通过代码默认参数字面量复现，但 B4 的 **request_mode 是否也为 full_slot 还是真 non-slot/pre-slot** 无法仅凭已读代码断定为"与 Current 相同"。判断为：
- 参数层（60/10/10/window/silence）可复用同一 window_planning 函数复现。
- **semantics 层差异存在**（Current 明确 full_slot）；复现 B4 exact 行为需要独立 serial/non-slot runner（如 `align_qwen_fa_serial_demo.py` 或真实历史 run 的固化 resolved profile），避免用 full-slot runner 冒充。

> 状态：**参数可映射，但 B4 真 non-slot exact semantics 是否仍能原样复现 "未知/需核实"** — 需读 serial runner 主循环与其 request_mode 来源。

---

## 问题 4 — commit / provisional semantics 编码位置

多头分布：
- **`src/lyricalign/demo/karaoke.py`**：`committed_character_start` 硬 commit 语义（早期核已冻结、永不重提交）；`_finalize_core` 式 committed/uncommitted/lookahead 划分；hard-commit 序列空隙检查（"hard-commit sequence gap: expected character..."）。是 committed-prefix 的核心。
- **`src/lyricalign/demo/inline_realign.py`**：precommit trial（`trial_committed_character_count`）、committed prefix、`next_input_boundary_sec` cursor 推进。
- **`src/lyricalign/demo/alignment_artifacts.py`**：4-stage 产物（raw/processor_decoded/selected/final），注释 "serial ownership/commit decisions"（第 91 行）。
- **`src/lyricalign/demo/run_state.py`**：**不是** commit/provisional 的主体；它是 run/stage/item 状态机 + canonical_hash + 内容寻址缓存（begin/finish item，request_hash），用于控制流与可续跑。

> 结论：commit/provisional 真编码在 `karaoke.py`（核心 hard-commit + committed prefix）与 `inline_realign.py`（precommit trial / cursor）。`run_state.py` 是 orchestration/缓存状态机，不承载 provisional row 语义。unit_realign 侧在 `request_families.py` 显式带 `timestamp_slot_indices/active_slot_indices/fixed_slot_rows/slot_constraint_schema`。

---

## 汇总

| 核实项 | 状态 | 关键证据 |
|---|---|---|
| Current exact resolved | ✅ | `realign_recovery/frozen_baseline.py` `FROZEN_BASELINE_IDENTITY`（full_slot/60/10/10/raw） |
| Window/silence 默认值 | ✅ | `demo/window_planning.py` `build_silence_aware_window_plan` 参数默认字面量 |
| Hash 序列化机制 | ✅ | `baseline_identity.py` `canonical_identity_json`+`identity_digest`；`run_state.py` `canonical_hash` |
| B4 参数→代码映射 | ✅（大部分） | 上表 |
| B4 真 non-slot 复现 runner | ⚠️ 需核实 | 需确认 serial runner 的 request_mode / serial 主循环 |
| decoder official vs raw 映射 | ⚠️ 需核实 | frozen 用 `decoder_view=raw`，B4 文档用 `decoder_kind=official` |
| compress_silence_audio / skip_silent_windows 接线 | ⚠️ 需核实 | 未直接见 |
| commit/provisional 位置 | ✅ | `demo/karaoke.py`(hard-commit/committed prefix)、`demo/inline_realign.py`(precommit/cursor)；`run_state.py` 为状态机 |
| research_v7/canonical_mapping.py hash 契约 | ⚠️ 需核实 | 未读源码 |

### 下一步建议
1. 读 `scripts/demo/align_qwen_fa_serial_demo.py` / `run_inline_realign_pipeline.py` 主循环，确认其 `request_mode`（full vs non-slot/pre-slot）来源，定 B4 runner 是否可独立复现。
2. 读 `demo/karaoke.py` build_serial_windows 的 committed cursor 语义 + `gpu_boundary_decoder` raw vs official 判据，敲定 decoder 映射。
3. 基于 `FROZEN_BASELINE_IDENTITY` + window 参数 dict 生成 `CURRENT_BASELINE_RESOLVED.json`（复用 `baseline_identity.identity_digest`），并解析 compress_silence_audio / skip_silent_windows 的连线位置。
