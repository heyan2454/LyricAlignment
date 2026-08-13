# Codex Implementation Plan — 2026-08-14 Unit Realign Recovery + Visualization

> 生成依据：`05_CODEX_HANDOFF.md`（先核实再实现）+ `00`–`06` 会话文档。
> 代码现状已由 4 个并行 subagent 核实（provenance_notes/ B/C/D/E），本计划所有"已核实"项均给证据路径，
> "未知/需核实"项不做文档猜测，列为前置 gate 或已知 unknown。
> 状态：**plan（未实现）**。实现前必须先把所有 phase 的 gate 走完；formal 只有 smoke 全通过后才启动。

---

## 0. 目标与本轮范围

回答 02 文档 E1–E10 九个问题，并把两个可视化（B4-vs-Current 双路、Current 四路消融）作为正式实验。
所有 realign 保持 `actual_writeback=0`（shadow/evaluator-only）；GT 只进 evaluator；collection 先于可视化；
rerender 不重复 model forward；GPU target ≤10h / hard cap ≤12h，随后进入 free-exploration loop。

不存在"全维度 winner"：目标按 target recovery（R-U）与 context safety（R-S）两轴分别报告，不做单一排序。

---

## 1. Codex 核实结论（facts 1–10 → 已核实/需核实）

| # | Fact | 结论 | 证据 |
|---|---|---|---|
| 1 | Current baseline exact resolved | ✅ | `FROZEN_BASELINE_IDENTITY`(realign_recovery/frozen_baseline.py)：request_mode=full_slot, 60/10/10, decoder_view=raw, 双阈值, real_gt_source=m4singer_overlay_slur_time_v1；window 参数均与 B4 冻结一致(window_planning.py build_silence_aware_window_plan 默认字面量)。B_note §1 |
| 2 | B4 pre-slot runner 可复现性 | ✅（可复现，但需独立 runner） | `scripts/demo/align_qwen_fa_serial_demo.py` 支持 `decoder_kind="official"`（第257/354/376/417行）且为 serial/non-slot 语义（build_serial_windows + committed cursor），非 full-slot。B_note §3（主 agent 追加核实） |
| 3 | R-U/R-S artifact schema vs 旧 visualizer | ✅（需新 adapter） | v2 request `unit_realign_request_v2`(request_families.py L15)；forward evidence=`{canonical_unit_id,start_sec,end_sec}`(run_forward_real.py L157/178)；visualizer 无 `ComparisonTrack` 类，实际用 `(label,rows[,window_trace])`(visual_diagnostics._unpack_track L222-229)+`window_trace`+`pages`。C_note §2 |
| 4 | reusable timeline projection / ComparisonTrack | ✅（可最小改动；缺失 overlay spans + 顺序冲突） | renderer 已具备 3840×1080、30s/page、播放线、KTV 两行、Noto Sans CJK SC、零时长聚合 `_group_collapsed_rows`(L385-440)、文字降级 `_adaptive_row_label`(L318-325)、多 track。缺 detector/target/fixed/proposal overlay span kind。**pipeline 现顺序 visualization→collection 与 03 V4 冲突**。D_note §A/B |
| 5 | cache identity 能否表达 parent iteration/recrop/split | ⚠️（recrop/split 已隐式覆盖；**parent_candidate_iteration 需新增显式维度**） | realign_recovery/forward_cache.py(26字段含 model/checkpoint/audio_sha/text hash/code/schema)；unit_realign 用 `build_request_identity`(request_families.py L50-62) 8+key。recrop/split 改变 canonical_ids/payload/audio_range，identity 自动变化；parent_iteration 缺 → 必须扩展。C_note §3 |
| 6 | k1/k3 manifests 兼容性 | ✅（不兼容 v2，仅 no-GT 参考） | k1/k3 REQUESTS 为旧 research_v7 schema（input_variant/workflow_mode/parent_request_id），无 family/active_target_unit_ids/request_identity；compare_context_padding.py 也按旧结构读。C_note §4 |
| 7 | genuine R-B/anchor provenance | ✅（unit_realign R-B 为 genuine；旧 E5/compat 不同轨不可混用） | region_sampling 从 detector ACCEPT 取 anchor_candidates + request_families R-B 强制最近邻(非 nearest 即 NULL)。C_note §5 |
| 8 | 可导出 no-GT 信号 | ✅（raw/official posterior/entropy/margin 可导出；hidden 仅 collect_evidence_v3） | infer_slice(align_qwen_fa_serial_demo).output.logits → raw=argmax/official=decode/per-step softmax/topk/entropy/margin；hidden 需 `research_evidence_config` 且当前 unit_realign 生产路径未接线。E_note §2 |
| 9 | Test Demo 33/3 状态 | ✅（33 成功/3 失败均"Format not recognised"；118/118 可 cache-only resume） | `unit_realign_test_demo_formal_20260813/04_test_demo/TEST_DEMO_DETECTOR_SUMMARY.json`：ranking=33，failed=3（Side by Side.mp4/祈愿花开.mp4/夜苏打.mp4）；RUN_MANIFEST item_count forward=118 failed=0。D_note §C |
| 10 | GPU 预算 | ✅（screening+expansion ≈500–1000 forward ≈ 分钟级 warm GPU，远 <10h） | 实测 forward ~0.2–0.75s/forward(warm)；账本 RUN_MANIFEST.runtime_budget。E_note §5 |

### 关键 unresolved unknowns（不作为阻塞，记入 plan 尾）
- U1：B4 exact 语义(serial cursor/commit version)是否需专门对照 run 与历史 B4 artifact 对账（B_note）。
- U2：detector/target/fixed/proposal 的 overlay span 精确样式与注解规格（D_note A.3，实现时冻结）。
- U3：第四路"R-U coarse→sparse refinement"为**本轮新实现**，暂无既有 schema；E4 实现前需先冻结其 request/cache/proposal schema。
- U4：3 个 mp4 "Format not recognised"具体是文件损坏还是缺解码器（D_note C.1）；不影响 118/118 resume，但影响 3 个 song 的重跑补漏，Smoke 前可用 ffprobe 判定。

---

## 2. 冻结原则（本轮全部实现必须遵守）

1. `actual_writeback = 0`；所有 realign 系列只在 isolated research state 模拟 candidate-as-next-input。
2. GT 只进 `evaluate_*`；no-GT runner/ranker/stop-rule 不接 GT path、不读 evaluator artifact、不用 `delta_error_ms`。
3. 不把 fixed-point / multi-view consensus / context displacement 当 correctness 充分条件。
4. 不把旧 R-B/E5/compat adapter 当 genuine bilateral-anchor（C_note §5）；R-B 只承认 unit_realign 最近邻+provenance 路径。
5. `parent_candidate_iteration` / `recrop_view_id` / `split_slot_id` 必须并入 request identity，输入变化禁止复用旧 forward。
   - `build_request_identity`（unit_realign/request_families.py）显式新增 `parent_request_identity`/`iteration`/`recrop_view_id`/`split_slot_id` 四个 key（含回归测试）。
   - B4 走 `align_qwen_fa_serial_demo.py --decoder official` 时，其独立 serial forward cache
     （`research_infer_cache_root`，identity `serial_infer_actual_input_cache_v1`）**也须**并入这些新键，否则跨迭代/recrop 会错误命中旧 forward；
     或在 B4 冻结为单程基线时明确"B4 不参与迭代/recrop rerender 的 cache-only 承诺"，二选一，G0/G1 前敲定并写入 WP2。
   - `realign_recovery/candidate_bank.py`（request-content hash, ≠ forward_digest）与 `research_transition_recovery_detector/identity.py`（另一套 forward_cache_key）为独立/历史 cache，本轮**明确不进**可视化 cache-only 断言范围（记入 §11 anti-scope 与 WP2）。
6. 不做全笛卡尔积：每问题 3–5 branch；screening 40–60 独立 regions；仅 1–2 有效方向扩到 ≥200。
7. sample 不足先主动扩 pool（放宽每歌 cap / 更多 M4 songs），仍不足才报告真实 denominator；禁止重复同一 region 伪造样本。
8. collection 先于 visualization；presentation rerender 只消费 frozen cache，不触发 Qwen forward；scientific hash 不被 renderer 改动污染。
9. 指标按 target correctness / context safety / region-event / no-GT 四类分别报告，不合并成单一 accuracy。
10. ray non-monotonic 判定、zero/near-zero duration、structural violation 按既有 canonical schema(character_interval_metrics_v3_tolerant)报告。

---

## 3. 数据流与 schema 总览

### 3.1 共享中间结构（本轮新建：visualization adapter）
不使用旧 visualizer 的 `ComparisonTrack` 命名假设（代码中不存在）。新 adapter 生成本轮统一的可视化中间结构
`TrackView`（schema `track_view_v1`），再把各 runner 产物投影进去，喂给既有 renderer：

```yaml
TrackView:
  schema: track_view_v1
  label: str                     # "B4" / "Current" / "R-U" / "R-S" / "R-U->sparse"
  rows: []                       # canonical_visual_row(global_character_index, start_sec,end_sec, text) → 直接喂 visual_diagnostics
  window_trace: []|null          # 各轨自己的窗口边界(core/input start-end)
  detector_spans: []|null        # (canonical index range, ACCEPT/REJECT/UNCERTAIN)
  target_spans: []|null          # target unit ids
  fixed_spans: []|null           # fixed context unit ids
  proposal_spans: []|null        # R-U coarse proposal / candidate region
  metadata: {...}                # request_identity, family, iteration/split annot
```

- 输入源 adapter：
  - **Current baseline**：从当前 full-slot pipeline 产物（`run_inline_realign_pipeline.py` 或 equivalent `branches/*/alignment.json`）投影。
  - **B4**：跑 `align_qwen_fa_serial_demo.py --decoder official`（B4 参数）→ 产物投影。
  - **R-U/R-S**：从 unit_realign v2 request + `run_forward_real` evidence 投影。
  - **R-U->sparse（第四路）**：本轮 E4 新实现产物。
- **R-U/R-S 反向映射（F-review P1，G1 前必须落实）**：unit_realign forward evidence 每行只有
  `{canonical_unit_id, start_sec, end_sec}`，**不含 global_character_index / text**，且 `canonical_unit_id ≠ global_character_index`。
  adapter 必须用 v2 request 的 `canonical_to_local`（反查 `canonical_unit_id → global_character_index`）与
  `text_units`（注入 display text，含零/负时长语义，供 `_group_collapsed_rows`/`_adaptive_row_label` 消费），
  为每行补全 `(start_sec, end_sec, global_character_index, text)` 完整四元组（`canonical_visual_row` 缺对即 KeyError）。
  `test_track_view` 首条断言：每条 R-U/R-S 投影行含完整 pair + global_character_index + text。

### 3.2 科学 runner 产物 schema（沿用既有 + 新增）
- 既有：`unit_realign_request_v2`、`unit_realign_outcome_v2`(unit_outcome.py)、`unit_realign_forward_execution_v1`。
- 新增（E1 multi-iteration / E2 split / E4 combo）：
  - `multi_realign_dynamics_v1`：per-iteration trajectory 行（iter, initial_err, error@iter best_err, first_hit_ms_iteration{100,200,500,1000},
    monotonic_improvement_ratio, improve_then_regress, fixed_point_iter, oscillation_divergence,
    **target_displacement_ms 与 fixed_context_displacement_ms 分开**（04 §7 target vs context），collateral_harm,
    forward_count, wall_time）。

    > 指标口径（02 E1 §130-146）：monotonic / improve-then-regress / fixed-point/oscillation/divergence 用 `oscillation_divergence`；target 与 fixed-context displacement 分别报告。

  - `split_realign_v1`：partition mechanism(1-unit/2-unit/adaptive/anchor-gap) + direction(L2R/R2L/independent) +
    **全部 8 项指标**（02 E2 §205-214）：strict 100/200ms recovery、coarse 500/1000ms recovery、context_preservation、
    **split_boundary_harm、merge_collision/overlap、non_monotonic、recovered_unit_fraction、region_all_hit 与 region_ge75_hit、extra_forward_cost**。

    > 缺一不可：E2 主结论（拆小是否扩大 basin）依赖 harm/fraction/forward-cost 维度，不能只报 strict/coarse。

  - `coarse_fine_v1`：stageA R-U proposal + stageB recrop+sparse refine + **全部 7 项指标**（02 E4 §311-319）：
    target_100/200/500/1000ms、fixed_context_displacement、catastrophic_regression、constructibility/coverage、
    forward_cost、no_gt_safety_signals、test_demo_structural_regressions。

    > E4 第四路无指标无法与 E5 no-GT 衔接，必须在 G5 前把 7 项全部落地并 feed 进 WP6 报告。

  - 每类都携带完整 request identity（含 parent_* / recrop_view_id / split_slot_id）。

---

## 4. Code change map

### 4.1 新增核心模块
| 新文件 | 职责 |
|---|---|
| `src/lyricalign/unit_realign/multi_iteration.py` | E1：direct chain / re-crop chain / perturb-and-retry 的 request 构造 + trajectory 记录（identity 含 `parent_request_identity`/`iteration`/`recrop_view_id`） |
| `src/lyricalign/unit_realign/split_variants.py` | E2：1-unit/2-unit/adaptive detector span/anchor-gap split builder + 方向性(L2R/R2L/independent-merge)；**携带 `split_slot_id` identity** |
| `src/lyricalign/unit_realign/coarse_fine.py` | E4：R-U proposal → recrop → sparse/fixed refinement 组合；fail-closed not_constructible |
| `src/lyricalign/demo/track_view.py` | 可视化统一中间结构 TrackView + 各 runner→TrackView 投影 adapter |
| `src/lyricalign/demo/track_span_kinds.py` | detector/target/fixed/proposal overlay span kind 样式与注解（新增到 visual_diagnostics 调色/绘制） |

### 4.2 修改既有模块（最小改动 / adapter 优先）
| 文件 | 改动 |
|---|---|
| `src/lyricalign/unit_realign/request_families.py` | `build_request_identity` 显式增加 `parent_request_identity`/`iteration`/`recrop_view_id`/`split_slot_id` 四个 key（含回归测试）；新增 R-U->sparse family 标志（复用时） |
| `src/lyricalign/demo/visual_diagnostics.py` | 注册新增 span kind 的绘制分支（detector/target/fixed/proposal） |
| `scripts/unit_realign/run_unit_realign.py` | 新增 `--iterations`/`--split`/`--recrop`/`--combo` 子命令开关；将 multi/split/combo 纳入 RUN_STATE resume |
| `scripts/demo/run_inline_realign_pipeline.py` | **不篡改旧 pipeline 阶段**；在 unit_realign 侧新增独立可视化 controller（WP2），显式以 collection→analysis_complete→visualization→pages→encode 顺序驱动（03 V4）。旧 pipeline 的 visualization→collection 顺序只留作历史/其他用途的兼容，不在本轮可视化路径复用 |
| `scripts/unit_realign/compare_context_padding.py` | 仅为 no-GT structural 保留；不为 k1/k3 接 v2 可视化（C_note §4） |

### 4.3 新增命令行入口（scripts/）
- `scripts/unit_realign/run_multi_realign.py` — E1 runner（direct/re-crop/perturb）
- `scripts/unit_realign/run_split_realign.py` — E2 runner
- `scripts/unit_realign/run_coarse_fine.py` — E4 runner
- `scripts/realign_recovery/visualization/`（或 `scripts/unit_realign/visualization/`）：
  - `render_b4_vs_current.py` — V1 双路 static+video
  - `render_current_4way.py` — V2 四路 static+video
  - `render_comparison_batch.py` — multilingual/hard-case batch 封装
  - `render_rerender_only.py` — cache-only rerender（断言 scientific hash 不变、不触发 forward）。
  - **B4 cache 契约（F-review P1，G1 前敲定）**：B4 档的 `render_rerender_only` 只对 unit_realign/Current 档做 forward-cache-only 断言；
    B4 若冻结为**单程基线**（不参与 multi-iteration/recrop），则明确其 rerender 只是重投影已定位串行产物（不新增 forward）并单独说明，
    不宣称 B4 使用扩展了 parent/iteration 键的 serial cache。两者在 G1 smoke 后由实测选中其一并在 WP2 记录。

---

## 5. run roots（数据目录，不放 git）

```yaml
base: /home/hyan/Data/lyricalign/runs
P0:  20260814_visualization_E0_freeze_and_preflight
PV:  20260814_visualization_E8_side_by_side_smoke
P1:  20260814_visualization_E1_multi_realign_screening
P2:  20260814_visualization_E2_fine_split_screening
P3:  20260814_visualization_E3_context_recrop
P4:  20260814_visualization_E4_coarse_fine_pilot
P5:  20260814_visualization_E5_no_gt_selector
P6:  20260814_visualization_P6_adaptive_expansion     # 只扩筛选出的 top1/2 机制到 >=200 regions + 确认 population
P7:  20260814_visualization_E6_atlas_mining
P8:  20260814_visualization_E7_serial_stress
P9:  20260814_visualization_E9_test_demo_viz_batch
```
> run root 编号与 `06_PLANNED_RUNS.yaml` phases（P0/PV/P1..P5/**P6-adaptive_expansion**/P7-atlas/P8-stress/P9/PF）**一一对应**，无遗漏。
每个 run 内布局遵循 03 文档 V7（scientific/ collection/ analysis_complete.json/ visuals/ renders/ render_manifest.json/
scientific_hash_before.json/ scientific_hash_after.json）。

---

## 6. 执行顺序与 phase gates

按 02 文档 E9 建议顺序，每个 phase 一个 gate（gate 未过不进入下一 phase）：

```
G0 (P0) 冻结 Current/B4 resolved + identities + cache schema + GT firewall + BUDGET  ✔必备
G1 (PV) visualization adapter + Side-by-Side smoke：三路(先无第四路) 静态+MP4，10 项验收 ✔必备
G2 (P1) E1 multi-realign dynamics screening（40–60 regions × 3 chain） ✔必备
G3 (P2) E2 fine-split screening（1/2-unit + adaptive + anchor-gap；catastrophic 优先）
G4 (P3) E3 k1/k3 closure + audio recrop/multi-scale
G5 (P4) E4 R-U->sparse coarse-fine pilot（实现第四路并过 scientific smoke → 补进四路可视化）
G6 (P5) E5 no-GT selector/safety（只接 E_note §2 实际可得信号）
G7 (P6) P6 adaptive expansion —— 只扩 screening 出的 top1/2 机制到 >=200 regions + 确认 population（song-held-out）
G8 (P7) E6 atlas / hard-case mining
G9 (P8) E7 serial accumulated-error stress
G10 (P9) multilingual+hard-case Test Demo 可视化 batch（collection-before-viz；含 3 个失败 mp4 补跑判定）
G11 (PF) free-exploration loop（递归 todo，auto-continue）
```

**Gate 语义**：每个 phase 产出物 + L1/L2 测试 + `compileall` + 一个简版 smoke/自检。任何 phase 的单个 item 失败 → 记 not_constructible/failed，不阻塞后续 phase（AGENTS 纪律）。
第四个 route（R-U->sparse）**实现并通过 scientific smoke 前，四路可视化只能用三路**（03 V2）。

---

## 7. 测试计划

- 新增单测（tests/unit_realign/ 或 tests/realign_recovery/）：
  - `test_multi_iteration.py`：request identity 含 parent/iteration；trajectory 字段；recrop_view 变化→新 identity；cache 不复用。
  - `test_split_variants.py`：四种 partition；方向性；merge collision/overlap/non-monotonic 检测；catastrophic 1/2-unit 可建。
  - `test_coarse_fine.py`：proposal→recrop→sparse refine 的 constructibility / fail-closed / not_constructible；writeback=0。
  - `test_track_view.py`：各 runner 产物→TrackView 投影字段完整；overlay span kinds 注册；scientific hash 稳定。
  - `test_gt_firewall_ext.py`：no-GT 路径 `assert_no_label_leak` 覆盖新 family。
- L1 快速层：`tests/unit_realign/` + `tests/realign_recovery/`（每 subagent 必跑）。
- L2 模块层：`tests/{unit_realign,realign_recovery,realign_gate,research_v7}`（跨模块改动必跑，~分钟）。
- L3 全量：仅 merge/阶段收尾（本机全量含 GPU/媒体类，需长 timeout）。
- 静态：`python -m compileall -q src scripts` + `git diff --check`。

---

## 8. GPU 预算投影（BUDGET_PROJECTION.json 依据）

- per-forward 假设：warm ~0.2–0.75s/forward（E_note §5.2 实测），取 0.5s/forward 保守。
- screening：40–60 regions × 3–5 branch ≈ 120–300 forward。
- expansion：1–2 机制 × ≥200 regions + confirmation ≈ 300–500 forward。
- 合计 ≈ 500–1000 forward ≈ **5–10 分钟 warm GPU**；大头在模型加载/样例缓存冷 start/evidence 写读。
- 预算账本：每个 run 在 `RUN_MANIFEST.json.runtime_budget` 登记 `{elapsed_sec, forward_count, cache_hit, cache_miss}`；主 agent 汇总到 `BUDGET_PROJECTION.json`。
- 若实际超 10h target，先停机制扩量，转 CPU evaluator/report/hard-case mining/cached selector/rerender + free-exploration（04 §3）。
- 不做 `iteration×split×audio_margin×context_k×family×language×threshold` 全排列（04 §4）。

**GT firewall 运行契约**：no-GT runner 不接 GT path；GT 只在 `evaluate_*` join；Oracle R-O 独立 evaluator-only namespace。
**Cache rerender 契约**：scientific JSON/JSONL hash frozen；renderer/字体/annotation/layout 可改；rerender 前后断言 hash 未变；改 schema 只走 TrackView adapter 投影，不污染 evaluator artifact。

---

## 9. 分批 work packages（交 OpenCode/agent）

每包完成后触发 2 个并行 review（代码正确性/契约 与 数据一致性/跨模块接线），只报 P0/P1，MINOR 进 backlog。

### WP1 — E0 冻结 + infrastructure（与 Codex 核实衔接）
- 生成 `CURRENT_BASELINE_RESOLVED.json`、`B4_BASELINE_RESOLVED.json`（复用 `frozen_baseline.FROZEN_BASELINE_IDENTITY` + window 参数 dict + `baseline_identity.identity_digest`）。
- 扩展 `build_request_identity` 显式加 `parent_request_identity`/`iteration`/`recrop_view_id`/`split_slot_id` 四 key（+ 回归测试断言 recrop/split/parent 变化→新 identity、相同→命中 cache）。
- 敲定 B4 档 cache 契约：单程基线（B4 不参与迭代/recrop，rerender 只重投影）或给 serial demo 的 `research_infer_cache` 并入新键（F-review P1）——G0/G1 前二选一。
- 落地 `BUDGET_PROJECTION.json` + `RUN_STATE`；确认 GT firewall 覆盖新 family（test_gt_firewall_ext）。
- Gate G0。

### WP2 — 可视化 adapter + three-way smoke（PV）
- 新建 `track_view.py` + `track_span_kinds.py`；Current/R-U/R-S → TrackView 投影（**R-U/R-S 用 `canonical_to_local`+`text_units` 补全 global_character_index+text**，F-review P1；`test_track_view` 断言每行完整四元组）。
- B4 用 serial runner 出 alignment → TrackView；敲定 B4 rerender cache 契约（单程 or 并入新键）。
- 独立可视化 controller 以 collection→analysis_complete→visualization→pages→encode（03 V4）驱动，不篡改旧 pipeline。
- **3 个失败 mp4 补跑决策（G1 前定）**：ffprobe 判定 Side by Side/祈愿花开/夜苏打——可打开的转码为 .wav/.mp3（脚本放 visualization/）并补进 Test Demo collection；不可开则记 failed 并确认仍不在 33 之列（G10 P9 前端完成，避免可视化漏歌；D_note §C/P1-4）。
- Smoke 1 `Side by Side.mp4`（3 路 static+MP4；媒体不可开则用转码后文件或等价 `.mp3`）。
- 10 项 smoke 验收（03 V6），含 rerender 不触发 forward。
- Gate G1。

### WP3 — E1 multi-realign screening（P1）
- `multi_iteration.py` + `run_multi_realign.py`；direct/re-crop/perturb 三链 × iterations{1,2,3,5}。
- hard cohort（M4 real-GT，`derived/20260723_m4singer_overlay_slur_time_v1`，多歌分散）；screening 40–60 regions。
- 指标：initial/best/error@iter、first_hit_ms_iteration{100,200,500,1000}、monotonic_improvement_ratio、improve-then-regress、fixed-point iteration、oscillation/divergence、**target_displacement_ms 与 fixed_context_displacement_ms 分开**、collateral harm、forward count/wall time；region all-target/≥75%、catastrophic 优先。
- Gate G2。

### WP4 — E2 fine-split screening（P2）
- `split_variants.py`（携带 `split_slot_id`）+ `run_split_realign.py`；1/2-unit + adaptive detector + anchor/gap；方向性(L2R/R2L/independent-merge)。
- catastrophic cases 优先进入；指标 = 02 E2 §205-214 **全部 8 项**：strict 100/200ms、coarse 500/1000ms、context preservation、**split boundary harm、merge collision/overlap、non-monotonic、recovered unit fraction、region all-hit/≥75%、extra forward cost**。
- Gate G3。

### WP5 — E3 context/recrop（P3）
- k1/k3 closure：仅 no-GT structural（复用旧 run，不改 v2 可视化）；audio recrop/multi-scale（预注册 base±0.5s/wider/left-enriched/recentered 非网格）。
- gate G4。

### WP6 — E4 coarse->fine（P4）＋ 第四路补进可视化
- `coarse_fine.py` + `run_coarse_fine.py`；R-U proposal→recrop→sparse/fixed refinement；fail-closed not_constructible。
- 指标 = 02 E4 §311-319 **全部 7 项**：target 100/200/500/1000ms、fixed context displacement、catastrophic regression、constructibility/coverage、forward cost、no-GT safety signals、Test Demo structural regressions。
- 实现并通过 scientific smoke 后，把第四路补进四路可视化，重渲 4-way。
- Gate G5。

### WP7 — E5 no-GT selector/safety（P5）
- 只接实际可得信号（raw/official posterior/entropy/margin/p_bad/disagreement/stability）；heldout 一次评价；分 recovery-first / safety-first operating point。hidden 实验性、需 `collect_evidence_v3` 并核实（E_note §6）才接。
- Gate G6。

### WP8 — P6 adaptive expansion（扩量；前置于 atlas/stress）
- 从 screening 结果的 strict recovery + safety 选出的 **top1/2 机制**，扩到 >=200 独立 regions + song-held-out 确认 population。
- 不做全机制扩量；扩量 forward 记入账本；为主试验提供 unbiased confirmation 依据（04 §4.3）。
- Gate G7。

### WP9 — E6 atlas + E7 serial stress（P7/P8，可与 WP10 并行）
- recovery-basin atlas（每个 region 的 baseline bucket/detector state/split/iter/view/best 100/200/500/1000ms/context harm/fwd cost/oracle-rescueability）；hard-case mining。
- serial accumulated-error stress（前窗前缀错误→下一窗；downstream error area/windows-to-recover/cumulative bad units；补充 cursor recovery latency / extra forwards / false recovery on safe windows）。
- Gate G8/G9。

### WP10 — E8/E9 正式可视化批量（P9）
- collection→visualization；B4-vs-Current + Current 四路，multilingual(中/粤/英/日) + hard-case 代表 cases + 用户指定 case；客观统计全量，视频选代表。
- **Test Demo 3 失败 song**：在 G9(P10) 前完成 Side by Side/祈愿花开/夜苏打 的 ffprobe→补跑判定；可开则转码补进 collection（保证 Smoke1=Side by Side 与 P9 可视化的代表性），不可开则记 failed 并确认其不在 33 之列（G-review P1-4）。
- Gate G10。

### WP11 — 收尾（PF）
- 汇总报告（04 §10：阶段/未执行项、wall time/forward/cache、每实验 hypothesis/setup/observation/alt-explanation/strength、negative results、sample accounting、failed/not_constructible、可视化路径、free-exploration todo 状态）。
- 触发 free-exploration loop（递归 todo 最后一项 = 生成下一轮 todo）。
- Gate G11。

---

## 10. resume / 失败恢复

- 每 run 用独立 `OUT_ROOT`，`RESUME=1` 重跑可续（AGENTS 约定）。
- 每个请求结果原子写入；failed request 留错误日志；formal summary 不因少数 failed 丢弃已完成。
- 内容寻址 cache：scientific identity 并入 model/checkpoint/audio SHA/code/schema/含 parent_*/iteration/recrop/split；输入变化不得复用。
- RUN_STATE.json（`completed/queued/planned/failed/null/not_constructible_identities` + `completed_region_ids`）作为 resume 依据，主 agent 按此调度。

---

## 11. 明确不做（anti-scope / 不会做的笛卡尔积）

- 不做 full 网格（iteration × split × margin × context_k × family × language × threshold）。
- 不把旧 R-B/E5/compat 当 genuine bilateral-anchor。
- 不把 consensus/fixed-point/context-displacement 当 correctness。
- 不因一条路线 negative 结束挂机 session（进入 free-exploration）。
- k1/k3 旧 run 不接入 v2 可视化（仅 no-GT structural）。
- 不在 visualization 阶段重复 model forward；不在 schema 变动时覆盖 evaluator artifact。
- 本轮 cache-only 断言范围只含 unit_realign `build_request_identity`/RUN_STATE 与（可视化的）TrackView 投影路径；
  `realign_recovery/candidate_bank.py`（request-content hash ≠ forward_digest）与
  `research_transition_recovery_detector/identity.py`（历史 forward_cache_key）为独立/历史命名空间，**不纳入本轮 rerender 不触发 forward 断言**（F-review P1）。

---

## 12. Known unknowns / 需实现期核实

- U1 B4 exact semantic 对照 run（serial cursor/commit 版本）与历史 B4 artifact 对账。
- U2 overlay span kind 精确样式规格（WP2 冻结）。
- U3 第四路 R-U->sparse request/cache/proposal schema 需在 WP6 前冻结。
- U4 Side by Side.mp4 / 祈愿花开.mp4 / 夜苏打.mp4 "Format not recognised" 原因与处理。
  - **已判定（主 agent 2026-08-14 追加核实）**：三个文件均可被 ffprobe/ffmpeg 读取（`base qwen_fa_runtime.decode_audio` 走 ffmpeg 可解码；Side by Side=HEVC+AAC，另两个容器为 mov/mp4）。失败点在 detector 媒体打开阶段 `scripts/realign_gate/test_demo.py:736` 用 `sf.read`(soundfile)——**soundfile 不支持 mp4 容器**。故非文件损坏，而是 loader 限制。
  - 处理：Smoke1 可视化若需这 3 个 mp4，先用 ffmpeg 转码为 `.wav`/`.mp3` 或改用 ffmpeg 解码路径；否则可视化 smoke 可用等价 `.mp3` 样例。转码脚本放 scripts/realign_recovery/visualization/。

---

## 13. 后续（本 plan 完成后）

本 plan 是 06_PLANNED_RUNS.yaml 的实现化映射。每 WP 完成后同步更新 `RUN_STATE.md` 与 `06` 状态字段（planned→done）。
GPU 预算到 10h/12h cap 后停止新增 formal forward，继续 CPU 分析 + free-exploration。
