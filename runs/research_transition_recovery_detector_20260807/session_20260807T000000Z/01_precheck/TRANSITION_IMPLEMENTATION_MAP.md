# TRANSITION_IMPLEMENTATION_MAP

- 阶段：research_transition_recovery_detector Phase 0 inventory
- 日期：2026-08-07
- 依据：`00_FACTOR_MODEL_AND_FREEZE.md`（T0–T3 定义）、`07_REVIEWED_IMPLEMENTATION_PLAN.md` §2/§3.2/§3.4
- 方法：纯只读调查（worktree `/tmp/opencode/wt-inv`），未改任何运行语义。
- 结论总览：**T2=mapped（行为真实存在，但耦合在 demo runner，缺 contract/adapter/equivalence fixture）；T3=partial（只有 stable diagnostics，无稳定提交状态机）；T1=missing；T0=missing（`full_alignment` 是单窗全曲，不是 per-window independent 轨迹，不能冒充 T0）**。

## 1. T0 – oracle_independent / product independent

- 状态：**missing**
- 07 §2.2 原文确认：`T0 deployable independent | 未发现`。00 §7 明确：现有实现需 GT/canonical oracle 决定每窗 query start 时才可称 `oracle-independent`，不得为凑 T0 自造规则。
- 相关代码（**都不是** T0 实现）：
  - `scripts/demo/align_qwen_fa_serial_demo.py::full_alignment`(645)：单次全曲非串行对齐（`character_start=0..len`），属一次性基线，不是按窗独立构造 query 的轨迹，也不是 GT/canonical-oracle 驱动的 per-window independent planner。
  - `windowed_alignment`(733) 中的 `planned_input_character_start`（plan 里可预置每窗 query 起点）与 `research_state_injections`（cursor_set/cursor_units）：这些是**研究注入钩子**，语义上能制造"不读上一窗预测 state"的独立起点，但未冻结为 T0 策略，也未绑定 canonical timeline/GT binding；在 Phase 1 实现 `oracle_independent` 前不能宣称已实现。
- 真实行为：无。没有任何"每窗 query span 由冻结 canonical timeline/GT 独立构造、不读上一窗预测 state"的冻结实现。
- decoder：不适用（无实现）。
- 测试：无 T0 测试。
- 与 07 §3.2 差异：`T0_oracle_independent` 整体缺失；`full_alignment` 不能作为替代。

## 2. T1 – direct serial

- 状态：**missing**
- 07 §2.2 原文确认：`T1 direct serial | 没有独立、冻结的 commit policy`。T1 要求"把 input 观察区内所有 uncommitted、合法且连续的 decoded rows 提交到 `input_end` ownership boundary；right lookahead 也可直接提交"。
- 相关代码（**都不是** T1）：`windowed_alignment` + `karaoke.split_core_commit_prefix`(435) 明确把 rows 分为 context/committed/lookahead，lookahead（`start >= core_end_sec`）**永不提交**（除非 final_core），与 T1 的 "right lookahead 也可直接提交" 相反。
- 真实行为：无独立 direct-serial commit policy；现有唯一提交路径是 core-boundary（T2 型）。
- decoder：不适用（无实现）。
- 测试：无 T1 测试。
- 与 07 §3.2 差异：必须新增纯状态策略，**不得把 T2 重命名**。

## 3. T2 – core + boundary serial（现有实现主体）

- 状态：**mapped**（真实行为存在，非改名；但按 07 §2.2，需抽取 contract/adapter + equivalence fixture 才能正式宣称已映射）
- 代码位置：
  - `scripts/demo/align_qwen_fa_serial_demo.py::windowed_alignment`(733)：串行驱动循环。每窗按计划取 windows（fixed / silence-aware / strict-silence / precomputed），`skip_silent_windows` 跳过纯静音 core（final core 永不跳过），startup 前导静音裁剪（`startup_vocal_preroll_sec`），逐窗做 attempt/expansion（`future_character_range` + `infer_slice`），`split_core_commit_prefix` 拆分后提交，`next_window_transcript_start` 推进下窗 input cursor；提交经 `append_strict_core_commits`（详见 karaoke）；含 `research_state_injections`（cursor_units/cursor_set/previous_end_sec/previous_end_set）与 `research_initial_committed_rows/cursor` 状态注入钩子。
  - `src/lyricalign/demo/karaoke.py::split_core_commit_prefix`(435)：ownership = 字符 **start time 位于 `[core_start, core_end)`**；index < committed_cursor 的 rows 为 context-only（已冻结，永不重提交）；`final_core` 时 uncommitted 全提交；越界/倒序/不连续行抛错（非连续即停止，无跳过后继续）。
  - `src/lyricalign/demo/karaoke.py::append_strict_core_commits`(529)：不可变前缀 + forward-only overlap compression（`start=max(predicted_start, previous_end)`，`end=max(predicted_end, start)`）；owner_window_index/owner_core_*、ownership_rule 等写入每行；seam_tolerance 仅作诊断，不限制压缩。
  - `src/lyricalign/demo/karaoke.py::next_window_transcript_start`(492)：下窗 input cursor = 首个 `start >=` 下窗 `input_start_sec` 的完整字符；跨界字符被排除（`crosses_input_start: True`）。
  - `src/lyricalign/demo/karaoke.py::build_serial_windows`(371)：fixed 10+60+10 等价窗（默认 left/right 15s），作为 fixed control。
  - `src/lyricalign/research_v7/real_executor.py::RealAligner`(45)/`make_real_executor`(195)：真实 forward 执行器（`AlignmentRequest -> AlignmentAttempt`），`input_variant=="strict_serial_committed_prefix_all_slots"` 时过滤掉 committed 前缀行（`source_text_start_index` 之前不重查）；所有 `*_global_*` 坐标按 `audio_start_sec` 平移。
- 真实行为：严格 core-boundary serial；left context 已提交行只作上下文；right lookahead（start ≥ core_end）不永久写回；commit 必须是从 0 开始的连续 prefix，非连续即报错；跨窗 overlap 只做 forward 压缩不重估已冻结前缀。串行推进由"下窗 input cursor（字符索引）"驱动，同时保存字符级 evidence。
- decoder：默认 `official`（`decode_forced_alignment`）；`serial_control_decoder_kind` 可投影为 `raw`（argmax）或 research decoders 重跑（`project_rows_for_decoder`(458)）；单次 forward 同时产出 raw 几何、official、top-k posterior、entropy/margin（`infer_slice`(221)）。
- 测试：间接覆盖（`tests/test_qwen_fa_serial_demo.py`、`tests/test_inline_realign_v4_full_mechanism.py`、`tests/test_inline_realign_pipeline.py`、`tests/test_demo_realign_diagnostics.py`、`tests/test_qwen_fa_batch_demo.py` 等）；**无**针对 07 §3.1/§3.2 contract 的 T2 equivalence fixture。
- 与 07 §3.2 一致性：**基本一致**——"只提交 start time 位于 `[core_start, core_end)` 的连续合法 prefix；left context 只供上下文；right lookahead 不永久写回"全部命中。
- gap_to_07_spec：
  1. 实现耦合在 demo runner 脚本内，未抽 `transitions.py`/contract adapter，无 `TransitionState`/`WindowRequest` 不可变合同；
  2. cursor/commit 以**字符索引**表达，07 §3.1 要求 `committed_end_exclusive == len(committed_ids)` 的 model-clock + original-clock 双时钟语义未接线（原曲与压缩时钟映射只在 `_remap_compressed_alignment` 输出层做）；
  3. 无 `shared_prefix_request_count`/`divergence_window` 追踪；
  4. 无 equivalence fixture 证明与 07 §3.2 一致（需 Phase 1 补）。

## 4. T3 – stable-boundary serial

- 状态：**partial**（存在 stable diagnostics 与跨窗 reproduction 计算，但无"仅永久提交稳定前缀、其余 provisional、下一窗重新观察"的延迟提交状态机）
- 代码位置：`windowed_alignment`(733) 内 `stable_segment_min_units`、`stable_segment_confidence_quantile`、`stable_raw_official_tolerance_sec`、`stable_context_tolerance_sec`、`stable_prefix_reproduction_tolerance_sec`、`stable_prefix_minimum_observed_units/ratio`、`previous_stable_suffix`（`research_initial_stable_suffix`）等参数与稳定段诊断计算。
- 真实行为：只计算/记录稳定段诊断（含 raw vs official 一致性、跨窗 reproduction），**未发现**以稳定性门控提交、未提交部分进入 provisional、下窗重新晋升的状态机（提交仍按 T2 的 core-boundary 全量提交）。
- decoder：同 T2（official 默认）。
- 测试：无 T3 测试。
- 与 07 §3.2 差异：07 要求 stability 至少绑定**两次真实观察**（或预注册等价证据），且"不得只凭同一 forward 的 raw/official 一致就称 cross-window stable"——当前 `stable_raw_official_tolerance_sec` 恰好是单 forward 内 raw/official 一致性度量，只能算诊断输入，不能直接作为 stability predicate。

## 5. 附加映射（Phase 0 要求）

### 5.1 full-slot query 接口
- **mapped**。`research_v7/requests.py::AlignmentRequest`(24)：`timestamp_slot_indices: tuple[int,...] | None`（None = 全 slot，即 full-slot；指定索引 = sparse slot）；`infer_slice`(221) 经 `research_v7.sparse_slots.retain_timestamp_slots` 保留指定 unit 的 timestamp slots；`real_executor.align_request` 把 request-local 索引映射到 document 空间，`input_variant=="strict_serial_committed_prefix_all_slots"` 为 full-slot 变体。07 §4.2 content-addressed identity 已部分满足（request 含 canonical_ids/canonical_timeline_*_sha/view_id/hidden_schema 等 content 字段）；`infer_slice` 另有 `research_infer_cache`（audio SHA + 输入 + decoder 参数 + model identity）。

### 5.2 raw / official 是否同 forward 派生
- **是（mapped）**。`infer_slice`(221) 单次 `model(**batch)` 后：`raw_classes = slot_logits.argmax`（raw）、`decode_forced_alignment(...)`（official）、`topk/entropy/margin`（posterior evidence）全部出自**同一 forward**；`real_executor.py:247` raw 的 availability 明确写 `derived_from_official_decoder_raw_geometry`（v7 中官方 decoder 输出由同一 logits 反解），weighted_isotonic 为 posthoc（`posthoc_from_raw_geometry`）。符合 00 §6"一次 forward 低成本同时得到 raw/official 应共享 forward"。
- 缺口：posterior 仅 top-k（`POSTERIOR_REASON_TOPK_ONLY = "topk_only_full_posterior_unavailable"`，见 `detector_v2_evidence_converter.py`），exact JS/L1/L2 不可用（07 §2.2 一致）。

### 5.3 silence snap / skip silent / leading / tail
- **mapped**。`window_planning.build_silence_aware_window_plan`(129)：boundary_search_sec=6.0 内吸附、min_silence 0.8 / strong 1.5、minimum_core_sec=12、tail_min_core_sec=18 尾窗重分配、leading_silence_min_sec=2.0 跳过前导静音；`skip_silent_windows` 在 `windowed_alignment` 中跳过纯静音 core（final core 不跳）；startup 前导静音裁剪（`startup_vocal_preroll_sec`）；尾窗重分配在 planner 层。strict silence boundary（`build_strict_silence_boundary_window_plan`(267)）按 07 §2.1 仅作困难 case，不进首轮主矩阵。

### 5.4 long-silence compression（A1）
- **partial（语义不达标）**。`window_planning.compress_silence_audio`(366) 删除超阈值静音中段，**只保留两侧各 0.20s padding（`keep_edge_padding_sec=0.20`）**，不是 07 §3.4 要求的 `retained_total_sec ∈ {3.0, 5.0}` 总保留时长；映射函数 `map_original_time_to_compressed`(451) / `map_compressed_time_to_original`(583) 单调可逆（boundary_side left/right），`project_silence_aware_plan_to_compressed_timeline`(507) 投影窗计划，`windowed_alignment`(751-786) 压缩模式下递归调用并在输出层用 `_remap_compressed_alignment`(674) 把全部时间戳（start 右连续/end 左连续）还原到 original clock。07 §3.4 的 retained-total、leading/trailing 单侧 guard、splice 连续性测试均需新增。

## 6. 结论与下一步

| 项 | status | 一句话差异 |
|---|---|---|
| T0 | missing | 无 oracle-independent 实现；`full_alignment` 只是单次全曲基线 |
| T1 | missing | 无独立 direct-serial commit policy；不得用 T2 改名 |
| T2 | mapped | 行为真实（core ownership/context/lookahead/forward-compression 全命中 07 §3.2），但耦合 demo runner，缺 contract/adapter/equivalence fixture |
| T3 | partial | 只有 stable diagnostics（含单 forward raw/official 一致性），无延迟提交/provisional 状态机 |
| full-slot 接口 | mapped | `AlignmentRequest.timestamp_slot_indices` + `retain_timestamp_slots` + real_executor 全 slot 变体 |
| raw/official 同 forward | mapped | `infer_slice` 单 forward 派生；仅 top-k posterior（full posterior 不可用） |
| silence snap/skip/leading/tail | mapped | planner + skip_silent_windows + startup trim 齐备 |
| 长静音压缩 A1 | partial | 只留两侧 0.20s padding，非 retained-total 3–5s；映射框架可复用，需重写 retain 语义 |

- 下一步（Phase 1，接 07 §6）：实现 `oracle_independent`（T0，绑定 canonical timeline）；新增纯状态策略 T1；实现 T3 provisional/stable-prefix 状态机；把 `windowed_alignment` 抽成薄 adapter 并做 T2 equivalence fixture（07 §2.2/§9 最低测试）；实现 `retained_total_sec` 静音压缩语义；接线 `TransitionState`/`WindowRequest` 双时钟合同。
