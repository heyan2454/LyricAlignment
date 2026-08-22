# Slot 模式配置一致性审计（window / silence / skip-silent / decoder）

审计员：LyricAlignment 配置一致性审计员（STEP BUDGET=12）
日期：2026-08-15
目标：核对所有 slot 模式/机制 forward 时使用的「窗口规划 + silence + skip-silent + decoder」配置，找出与 B4 / full-slot Current 的配置不一致，列为 P0/P1 修复项。

> 注意：所有 slot 模式（R-U / R-S / R-CF）forward 一律经 `research_v7.real_executor.RealAligner` → `align_qwen_fa_serial_demo.infer_slice`，
> **不调用** `windowed_alignment` / `build_silence_aware_window_plan` / `build_serial_windows`。
> 它们的「窗口」来自 v2 request 的 `candidate_audio_range_sec` / `audio_start_sec` / `audio_end_sec`，本质是**局部 crop 切片**，与 B4/Current 的串行 silence-aware 全局窗口规划完全不同。

---

## 一、slot 模式 forward 全链路

### 公共 forward 入口（所有 slot 模式）

| 环节 | 位置 | 说明 |
|------|------|------|
| real 前向 | `src/lyricalign/research_v7/real_executor.py::RealAligner.align_request` (L226-279) / `align_units` (L188-224) | 直接调 `infer_slice`，窗口 = `audio[start:end]` |
| 模型 args | `real_executor.py::_ensure` (L173-184) | **硬编码** `decoder_kind="official"`、`timestamp_segment_sec=0.08`、无 `silence_aware_window_plan` / `skip_silent_windows` / 边界保护字段 |
| v2→v7 request | `src/lyricalign/unit_realign/multi_iteration.py::_to_v7_request` (L345-382) | `audio_start_sec/end = candidate_audio_range_sec`；稀疏字段透传 |
| 稀疏 tensor 剪枝 | `scripts/demo/align_qwen_fa_serial_demo.py::infer_slice` (L294-301) 调 `src/lyricalign/research_v7/sparse_slots.py::retain_timestamp_slots` | 仅当 `timestamp_slot_indices != full range` 时剪枝 marker 对 |
| R-U 编排 | `scripts/unit_realign/run_unit_realign.py` → `run_forward_real.py` (L101-103, L224) → `RealAligner` | R-U forward 走同一条真实路径 |
| R-CF 编排 | `scripts/unit_realign/run_coarse_fine.py` (L209-211) → `run_coarse_fine` → `_execute` (coarse_fine.py L394-407) → `RealAligner` | A/B 两阶段都走同一真实路径 |

### 窗口构造（各 slot 模式的 `candidate_audio_range_sec`）

- **R-U**：`src/lyricalign/unit_realign/request_families.py::build_family_request` (L117)；
  窗口 `start/end` = context 展开后 `min/max(unit.start/end) ± audio_margin_sec`（L187-193，`audio_margin_sec` 默认 0.5）。
  即以「目标 unit ± context_neighbors」的**几何时间跨度**为音频窗口，无 silence 感知，无 skip-silent。
- **R-S（sparse/fixed-slot）**：同一 `build_family_request`，`sparse=True` 时
  `active_local = target±active_neighbors`，`fixed_slot_rows` 填充 context（request_families.py L162-210）；
  `slot_constraint_schema="realign_sparse_fixed_v1"`，`timestamp_slot_indices=active_local`。窗口构造与 R-U 相同（几何跨度）。real_executor 收尾 `remerge_fixed_slots`（L277-278）。
- **R-CF**
  - Stage-A（coarse proposal）：`coarse_fine.py::build_coarse_stage` (L123-145) → 几何上即 R-U（family 标 R-CF）。
  - Stage-B（re-center + sparse/fixed refinement）：`coarse_fine.py::build_refinement_stage` (L182-267)，
    `recrop_context_ids` = 以 proposal 中心最近的 `STAGE_B_CONTEXT_NEIGHBORS=2` 单元（L151-179），
    窗口 `[start,end]` = recrop 内 active unit 的几何跨度（L228-229, L250）；`active_neighbors=0` → 仅 target active。

---

## 二、对账表

| slot 模式 | forward 窗口规划函数 | silence_aware | skip_silent | decoder | 边界保护(leading/tail/min) | 与 B4 是否一致 |
|-----------|----------------------|---------------|-------------|---------|---------------------------|----------------|
| **B4 pre-slot（基准）** | `align_qwen_fa_serial_demo.windowed_alignment` → `build_serial_windows`/`build_silence_aware_window_plan`（karaoke.py L371 / window_planning.py L129） | `--silence-aware-window-plan` **默认 False**；batch 显式开 True | serial 默认 **False**（L1646） | `official`（默认） | core=60 / ctx=10/10；leading≥2.0、tail_min≥18、minimum_core≥12（L1658-1670） | —— |
| **full-slot Current（batch）** | `run_qwen_fa_batch.py` → `windowed_alignment`（batch L608） | `--silence-aware-window-plan` **默认 False**（L983），命令行可开 True | `--skip-silent-windows` **默认 False**（L987） | `official` | core=60/ctx=10/10（L937-939）；边界参数转发到 `_alignment_args`（L445-481） | 与 B4 同机制，仅默认关闭 silence/skip（可开成一致） |
| **机制 current runner** | `run_inline_realign_experiment.serial_args` (L262-308) → `SERIAL.windowed_alignment`（L539） | `= (variant.silence_mode=='snap')`（L296）；fixed/strict/compressed 对应不同的 strict/compress | **硬编码 `True`**（L290） | `official`（L288），`serial_control_decoder_kind=variant` | boundaries 全传（L302-307） | **skip_silent=True 与 B4 默认 False 不一致**（cascade 已记录） |
| **R-U（unit-local realign）** | **无串行窗口规划**；`request_families.build_family_request` 几何跨度 →`RealAligner.align_units→infer_slice` | **无（不设字段）** | **无（不设字段）** | **硬编码 `official`**（real_executor L180） | **无（无 leading/tail/min 边界保护）**；仅 `audio_margin_sec=0.5` | ❌ 不一致：无 silence/skip、无边界保护 |
| **R-S（sparse/fixed-slot）** | 同上 `build_family_request(sparse=True)` → `infer_slice`，额外 tensor 剪枝 `retain_timestamp_slots` | 无 | 无 | 硬编码 `official` | 无（仅 audio_margin_sec） | ❌ 不一致 |
| **R-CF** | Stage-A=上面 R-U；Stage-B=re-center recrop 几何跨度 → `infer_slice` + sparse | 无 | 无 | 硬编码 `official` | 无（仅 audio_margin_sec=0.5，recrop 固定邻居） | ❌ 不一致 |

**补充确认**
- 全 repo 内 `unit_realign/` 与 `research_v7/` forward 路径**无任何 `windowed_alignment` / `build_silence_aware_window_plan` / `skip_silent_windows` 调用**（grep 仅命中文档注释 build_resolved_baseline.py）。
- `retain_timestamp_slots` 只在 `infer_slice` 被接线（真正的稀疏 tensor 剪枝），`sparse_slots.py` 非独立 forward 入口。
- `run_unit_realign.py` 是编排器，把真实 forward 委托给 `run_forward_real.py`（L415）。
- Cross-checks：run_multi_realign.py (L171-172)、run_split_realign.py (L180-181)、run_forward_real.py (L101-103)、run_coarse_fine.py (L209-211) 全部用 `make_real_executor(RealAligner(...))`。
- smoke executor 与 real 行为一致（都从 offset 几何排布），无 silence 概念。

---

## 三、结论：需要统一的不一致项

### 核心差异
R-U / R-S / R-CF 三者 forward 走**独立于 B4/Current** 的 `RealAligner→infer_slice` 局部 crop 路径：
**没有任何 silence-aware 窗口规划、没有 skip-silent、没有 leading/tail/minimum-core 边界保护、decoder 硬编码 official 且不可配**。
而 B4/Current 依据 full-slot 的全局 silence-aware 串行规划。因此这些 slot 模式与 B4/Current 的对比会混入「窗口/silence/边界」配置差异。

### P0（必须修，否则对比结论无效）
1. **R-U / R-S / R-CF 无 silence-aware 窗口规划**：它们直接把 target±context 的几何跨度当窗口喂 `infer_slice`。若要与 B4/Current 对齐，需在 forward 入口引入可选 `silence_aware_window_plan`（复用 `window_planning.build_silence_aware_window_plan` 语义）或显式声明「局部 crop 无 silence 规划」为独立维度，禁止直接并表。
2. **R-U / R-S / R-CF 无 skip-silent**：`RealAligner._args` 未设置 `skip_silent_windows`；机制 current runner 却硬编码 `True`。三个 slot 模式与 Current(机制) 对比必须统一（要么都开要么都关），否则活跃/静音差异混入。
3. **R-U / R-S / R-CF 无边界保护**：无 leading/tail_min/minimum_core 保护。B4/Current 有 `leading_silence_min_sec=2.0 / tail_min_core_sec=18.0 / minimum_core_sec=12.0`。slot 模式的首尾窗口可能过小，需补边界保护或显式声明不适用。

### P1（应统一，语义清晰）
4. **decoder 不可配**：`RealAligner._ensure` 硬编码 `decoder_kind="official"`（real_executor L180），而 B4/Current 支持 `raw`/`official`/gpu_*。若对比需要 decoder 维度，slot 模式需透传 decoder_kind。
5. **skip_silent_windows 历史不一致（B4 内部）**：`build_resolved_baseline.py` 已记录 —— serial runner B4 默认 `False`（align_qwen_fa_serial_demo L1646），而机制 current runner 硬编码 `True`；B4 基线当前 unresolved（记 backlog/P1-1 对比实验确认），避免当作已冻结事实。

### MINOR（backlog，不阻塞）
- `audio_margin_sec=0.5` 与 R-CF 的 `STAGE_B_CONTEXT_NEIGHBORS=2` / `ACTIVE_NEIGHBORS=0` 在 recrop 时未参与 silence 信号 → 建议统一为可配置并可写进 request identity。
- `run_adaptive_expansion.py` 无 real forward（只读缓存/纯 CPU 规划），不在此表 forward 链路中，无需对齐。

---

## 四、建议统一的最小契约（供实现）
在 `RealAligner._ensure` 的 `SimpleNamespace`（real_executor L173-184）与 `_to_v7_request`（multi_iteration L355-382）间增加透传字段：
`silence_aware_window_plan(bool) / skip_silent_windows(bool) / strict_silence_boundary_plan / compress_silence_audio / leading_silence_min_sec / tail_min_core_sec / minimum_core_sec / decoder_kind(str)`，
默认值与 B4/Current 对齐（`existing: silence_aware=False, skip_silent=False, decoder=official`），并强制把这些字段并入 `request_identity`（research_v7 内容寻址），避免配置差异被 cache 吞掉。
