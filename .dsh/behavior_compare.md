# B4 (pre-slot serial) vs Current (full-slot serial, batch) —— 模型行为对比

> 代码行为分析。任务只对比"各自怎么跑/怎么推进状态"，不对比输出指标。
> 范围：
> - **B4** = `scripts/demo/align_qwen_fa_serial_demo.py`（occurrence-aware full + serial-window；`B4_60_silence_official` 对应 60s core/silence snap/official 控制串行/跳过静音窗）。
> - **Current** = `scripts/demo/run_qwen_fa_batch.py --individual r2:vocal:windowed`（full-slot serial）。

## 0. 最高层关键结论（先讲清楚，避免后续重复）

**Current 的 windowed 路径根本没有自己实现窗口/串行逻辑，而是从 B4 的 `align_qwen_fa_serial_demo.py` 直接 import 并调用 `windowed_alignment`（还有 `full_alignment`、`load_model`、`WINDOW_POLICY`）。**

- `run_qwen_fa_batch.py` L56–61：`from scripts.demo.align_qwen_fa_serial_demo import (WINDOW_POLICY, ..., full_alignment, ..., windowed_alignment)`。
- `run_qwen_fa_batch.py` L590：`mode != "full"` 时调 `windowed_alignment(...)`（同一函数，两份调用点一份在 batch、一份在 serial_demo main，代码相同）。
- 底层串行/窗口原语也全部共享，都来自 `src/lyricalign/demo/karaoke.py`（`build_serial_windows`、`future_character_range`、`split_core_commit_prefix`、`next_window_transcript_start`、`append_strict_core_commits`）与 `src/lyricalign/demo/window_planning.py`（`build_silence_aware_window_plan`、`build_strict_silence_boundary_window_plan`、`compress_silence_audio`、`project_*`）。

所以：**只要传入相同参数，B4 与 Current 的核心状态机完全一致**。真正的机制差异集中在两处：
1. **被测模型/请求范围的差异**：B4 串行 demo 依次跑 r0/r1/r2 × mix/vocal × full/windowed 共 12 个请求（L1704–1729、L1785–1800 模型循环）；Current 默认 preset 只跑 `r2:vocal:windowed` 一个（`build_output_plan` batch.py L199–200，`default` preset）。
2. **可配置行为开关是否被透传**：B4 的 CLI 暴露了 silence-aware / skip-silent / strict-silence-boundary / compress-silence / decoder-kind / serial-control-decoder-kind 等全部开关（`build_parser` L1585–1672）；Current 的 batch CLI **没有这些开关**，且 `_alignment_args`（run_qwen_fa_batch.py L445–464）**只转发固定子集**，导致 `windowed_alignment` 里这些字段全部落到 `getattr(..., default)` 默认值（多为 False / "official"）。

下列各维度按上面这份结论展开，行号/函数均为实测依据。

---

## 1) slot 查询语义 —— 单次请求查询多少 canonical units？

**B4 = Current（共享同一 `infer_slice`）。**

- 单次模型请求把所有 `selected = document.characters[character_start:character_end]` 全部一起喂进去，每个单元作为一条独立 text content item（`prepare_pretokenized_aligner_inputs` L194–218：`{"type":"text","text": unit} for unit in alignment_units`），然后一起 decode。
- slot 数断言必须等于 `2 × len(selected)`（L342 `slot_logits.shape[0] != 2 * len(output_meta)` 抛错），即**一单元两头两个 timestamp slot**，整段一次 forward。
- windowed 版：`infer_slice` 被 windowed_alignment 的每个 attempt 调用，传入 `char_start..char_end`（= `future_character_range` 从 `input_cursor` 起算、扩展到整行 `future_line_padding`），所以**一次请求查一整个 future candidate slice（若干整行），不是逐单元，也不是按 occurrence 子集**。
- 只在 `timestamp_slot_indices` 非 None 时才做 sparse slot 保留（L349–354 走 `research_v7.sparse_slots.retain_timestamp_slots`）——这是 research 专用，B4/Current demo 均不设置，无需展开。

**结论：相同。** 也不是"整窗所有单元一起喂"的严格理解——喂的是 `future_character_range` 给出的按行对齐的 future slice，而非几何 60s 窗内的全部歌词；当前窗左 overlap 里已提交的字会作为 context 重复喂入（见第 2 点）。

---

## 2) 串行光标 / provisional / commit 推进

**B4 = Current（共享同一 `windowed_alignment` 状态机）。**

- **cursor 变量**：`input_cursor`（给模型读的 future transcript 起点）与 `committed_cursor`（已冻结字符数）两条独立光标。
  - `input_cursor` 是"下一窗喂给模型的字序列起点"，可能早于 `committed_cursor`（因为 10s 左 overlap 里的已提交字会被重复作为 context 喂入）。
  - 初始化：`inferred_cursor = initial_rows[-1].global_index + 1`；`committed_cursor` 来自 `research_initial_committed_cursor`（默认 = inferred），并要求 `initial_rows` 覆盖 `[0, committed_cursor)` 连续前缀（L970–1004，不含校验抛错则直接运行）。
  - `future_character_range` 每次从 `input_cursor` 起算，故**窗口间通过 input_cursor/committed_cursor 传递状态**。
- **每次请求内部**：对每个 window 做多候选 expansion 循环（`max_candidate_expansions+1` 次，L1123–1302），每次把请求结果用 `split_core_commit_prefix` 切成 **left context / core committed / lookahead** 三块（karaoke.py L435）。accepted 条件 = `boundary_observed = core_boundary_observed and next_input_boundary_observed`（L1246–1248、L1338）。失败则扩大 candidate（`target_count` ×1.8 或 +min_forward），最后仍失败抛 `SerialWindowAlignmentError`。
- **commit**：accepted 后走 `append_strict_core_commits`（karaoke.py L529）——**只追加，永不该写已有 core**：
  - `start = max(predicted_start, prev_committed_end)`；`end = max(predicted_end, start)`。
  - → 与前一 core 重叠的左侧被压缩前移；整段落在已冻结区间内的字符会被压成**零时长**（`allows_zero_duration_after_compression = True`，batch.py L505）。
  - `seam_tolerance_sec` 只是 diagnostics 阈值，从不拒/限 compression（`append_strict_core_commits` L561 docstring）。
- **overlap 语义 = context-only + forward-compress，不是覆盖**：left acoustic extension 里的已提交字重新喂入只为 context（`split_core_commit_prefix` 把 `< committed_character_start` 的行全归入 context），已提交 core 永远不被后窗改写（`windowed_alignment` docstring L805+；batch `overlap_resolution` = "forward_compress_to_previous_committed_end" L503）。
- `windowed_alignment` docstring L804–810 明确："strict serial cores, committed units context-only, never overwrite preceding core"——这就是任务简述里 windowed_alignment 的定义。**B4 与 Current 都走它。**

**结论：相同（同一函数，行级一致）。**

---

## 3) occurrence / 重复词处理

**B4 = Current。**

- 重复词按**歌词中出现的顺序**天然保留 occurrence：`parse_lyrics_text` 为每个 token 建独立 `LyricCharacter(global_index=len(characters), ...)`（karaoke.py L340–348），同一字符串重复多少次就有多少个不同 `global_index`。
- 串行推进 `future_character_range`/`split_core_commit_prefix`/`next_window_transcript_start` 全部按 `global_character_index` 连续推进 (`expected = expected_input_character_start + offset`, 严格连续断言 karaoke.py L449–458)，所以每次出现的 slot 都是独立、按序查询的。
- B4 头部声明 "occurrence-aware"（serial_demo L7）指的就是这种按词序保序推进；由于 Current 复用同一 `windowed_alignment`/`infer_slice`/`parse_lyrics_text`，**机制上完全相同**。重复路径上没有出现一个函数只在 B4 走、Current 不走。
- 是否"按歌词出现次数上限推进"（超出实际出现次数截断）？没有单独逻辑；`future_character_range` 只按字符数量 max 到 `total_characters`，cursor 到 `total` 即 `(total,total)` 终止（karaoke.py L422–428）。最终窗由 `committed_cursor >= total_characters` 提前 break（windowed_alignment L1008–1012）。

**结论：相同。**

---

## 4) silence 处理 —— 是否 silence-aware / skip silent windows？

**这是 B4 与 Current 唯一的实质机制差异，且是"默认值/开关透传"差异，不是代码分支差异。**

两边的 `windowed_alignment` 都有同一份 silence 逻辑（L815–993 全局窗口规划，L1047–1066 每窗 silent-skip 判定），是否启用由下列 `getattr(args, ...)` 决定：
- `skip_silent_windows = bool(getattr(args, "skip_silent_windows", False))`（L1046）
- `use_silence_plan = bool(getattr(args, "silence_aware_window_plan", False))`（L868）
- `use_strict_silence_plan = bool(getattr(args, "strict_silence_boundary_plan", False))`（L869）
- `compress_silence_audio = bool(getattr(args, "compress_silence_audio", False))`（L814）

**差异来源（实测）：**
- **B4** 的 `build_parser`（serial_demo L1585–1672）**暴露全部四个开关及全部默认参数**（`--silence-aware-window-plan` default=False、`--skip-silent-windows` default=False、`--strict-silence-boundary-plan`、`--compress-silence-audio`、`--silence-boundary-min-sec=0.8`、`--strong-silence-anchor-sec=1.5`、`--tail-min-core-sec=18`、`--minimum-core-sec=12` 等）。`B4_60_silence_official` 即用 `--silence-aware-window-plan(或 strict) + --skip-silent-windows + --decoder-kind official` 启动 → 全局按静音 snap 窗口、跳过静音 core，behavior 与记录 L292 一致。
- **Current** 的 batch CLI **完全没有这些开关**，且 `_alignment_args`（run_qwen_fa_batch.py L445–464）只转发 `timestamp_segment_sec, core_sec, left/right_context_sec, future_line_padding, minimum_forward_characters, future_character_ratio, max_candidate_expansions, boundary_start_tolerance_sec, seam_tolerance_sec` 这 9 个字段。silence 相关字段**未转发** → `windowed_alignment` 全部回落默认值：
  - `silence_aware_window_plan`=False → 走到 `build_serial_windows`（固定 core_sec=60 的均分网格，karaoke.py L371，不做静音 snap）。
  - `skip_silent_windows`=False → **不跳过静音 core**。
  - `strict_silence_boundary_plan`=False、`compress_silence_audio`=False → 不顺声/不压缩。

> 说明：L292 说"Current 与 B4_60_silence_official 核心行为一致"，其成立前提是 Current 用**与 B4 相同的开关参数**调起串行核心；而 batch `run_qwen_fa_batch.py` 现役默认并不透传这些开关，**默认行为不挂静音 snap / 不 skip silent**。若历史"Current"是经由其他入口（如 `align_qwen_fa_decoder_realign_comparison.py` 默认 `silence_aware_window_plan=True`，L226；`run_decoder_realign_comparison_batch.py` 默认 True，L144）跑的，那那些入口才与 B4_60_silence_official 一致。就**本任务指定的入口 `run_qwen_fa_batch.py --individual r2:vocal:windowed` 而言，默认机制与 B4 的 silence_aware 分支不同**。

**结论：不同（默认情况下）。** B4 可选静音 snap + skip silent；Current batch 默认 = 固定 60s 网格 + 不 skip。skip-silent 本身的行为（非 final core 且 `essentially_silent` → `status=skipped_silent_core`，且 final core 永不 skip，L1047–1066）两边代码相同，只是 Current 默认不开。

---

## 5) decoder：official vs raw

**B4 = Current（同一默认，开关透传不同）。**

- `infer_slice` 里 `decoder_kind = str(getattr(args, "decoder_kind", "official"))`（L354/L1210/L1313 等），默认 **official**。official → 取 `item["start_time"]/["end_time"]`（`processor.decode_forced_alignment` 的返回值）为 `fixed_*`（L396–400、L447–450）；raw → 用 timestamp class 直译 `class × segment`（L467–472）。raw 只影响 `fixed_*`，**行的 raw 类/概率/熵等证据始终照算**（即使 decoder=official 也存 raw 特征），仅"最终定线时间"由 decoder_kind 决定。
- 另外有 `serial_control_decoder_kind`（默认 "same"，serial_demo L587–588）：只用于 core ownership 切分与 next-window cursor（`project_rows_for_decoder`），与最终输出 decoder 解耦。
- **差异：**
  - B4 CLI 有两套 decoder 参数：`--decoder-kind`（choices raw/official/gpu_tcn/gpu_transformer, default official）与 `--serial-control-decoder-kind`（choices same/official/raw, default same）→ 可切 raw 或官方-for-control。
  - Current batch CLI **没有 decoder 参数**，`_alignment_args` 也不转发 `decoder_kind`/`serial_control_decoder_kind` → `infer_slice` 落默认 **official**，`serial_control_decoder_kind` 落默认 **same**（即"输出用什么控制就什么"）。

**结论：机制相同；默认不同——B4 可 raw，Current 只能用 official（无 raw 选项，落地即 official）。**

---

## 6) 起始 / 边界 —— leading silence、short-tail / minimum core

**B4 = Current（共享 `windowed_alignment`；是否启用取决于 silence 开关，同第 4 点）。**

- leading silence / 尾部 core 都由 silence-aware 规划函数决定：
  - `leading_silence_min_sec`（default 2.0）用于 silence-aware 规划起点裁剪。
  - `tail_min_core_sec`（default 18.0）、`minimum_core_sec`（default 12.0）用于"短尾/final core 长度"保护。
  - 这些都在 `build_silence_aware_window_plan` / `build_strict_silence_boundary_window_plan`（window_planning.py L129/L267）与 `compress_silence_audio`/`project_*`（L366/L507）内，调用点在 `windowed_alignment` L815–993。
- current 分支落到 `build_serial_windows`（固定 core_sec 网格）时**没有** leading/tail/minimum-core 个性化——尾部窗口就是 `min(duration, core_start+core_sec)` 的截断 60s 或余量，无 minimum-core 保护逻辑。
- 非 silence 相关边界：每个 window 有 `final_core`（core_end ≈ duration）与 `final_region_core` 标记，final core 时 `target_count = total - input_cursor`、`char_end=total`、`next_input_candidate=total`（L1128、L1132、L1235），即末窗强制推到全部剩余字。
- `startup_vocal_preroll_sec`(2.0)/`startup_minimum_forward_characters`(24)：`committed_cursor==0` 时按 `first_sustained_activity_sec` 裁剪输入起点并提高最小目标（`has_matched_left_context`/`startup_trimmed_start`，L1067–1105）。这些只在 `activity_profile is not None` 时生效，而 activity 只在 need_activity（silence 相关开关）或 skip_silent_windows 下才构建（L886–894）。

**结论：默认不同——B4 可 silence-snap 出 leading/tail/min 保护；Current batch 默认固定网格无这些保护。代码路径相同，开关默认不同（同第 4 维）。**

---

## 7) 其它行为差异（额外发现的实质差异）

1. **请求/画像范围**：B4 main 一次跑 r0/r1/r2（分别 raw/projector/lora checkpoint）× mix/vocal × full/windowed 共 12 个 output，模型逐个加载一次、用完即加载下一个（serial_demo L1689–1800）。Current `default` preset 只跑 `r2:vocal:windowed`（batch.py L199）；模型选择/checkpoint 由 `--r2-checkpoint/--r2-run` 决定（batch L98–110 `_model_checkpoint`），且 batch 显式只用于 r2（main L1016 若 model 含 r1/r0 + --individual 会探测分离）。——机制层面是"被测单元集合"不同，B4 是 12-cell matrix 脚本，Current 是单 cell batch 子集。
2. **silence-compression 双时钟**：B4 支持 `--compress-silence-audio`（压缩音频→对齐→`_remap_compressed_alignment` / `project_silence_aware_plan_to_compressed_timeline` 映射回原始时钟，serial_demo L813–860、L744），Current batch **不能启用**（无此开关）。该双时钟映射在 Current 只能通过人工装 research args，默认不涉及。
3. **research 注入**：`windowed_alignment` 有无条件支持 `research_initial_committed_rows/committed_cursor/...`、`research_state_injections`、`research_max_windows` 等（L970–1040、L1008）。B4/Current batch 都默认不设置；但两者都能通过传 args 接入。机制相同，但 batch 的 `_alignment_args` 不转发任何 `research_*`，等于 Current 无法在 batch 直连下注入这些研究态（需外部自带 SimpleNamespace）。
4. **decoder 附加/证据**：Current batch `_alignment_args` 不转发 `decoder_top_k`、`capture_shadow_rows`、`capture_attempt_probes`、`stable_*`；B4 全部 CLI 可调并写进 request schema。这对机制影响小（都对默认值），但对"可观测/诊断模式"二者不同（B4 能开 shadow/probe/stable, Current default 全关）。
5. **请求 schema 版本**：B4 SCHEMA_VERSION=`qwen_fa_serial_demo_v7_silence_aware_windows`，Current=`qwen_fa_batch_alignment_v4_forward_overlap_compression`（batch L63）；两者 request 字段基本重叠，但 batch `_alignment_request` 无 decoder/slicing 细节镜像。identity/cache 键不同，但它们不改变 state machine。

---

## 确认的行为差异清单（编号）

1. **被测模型集/请求矩阵不同**：B4 = r0/r1/r2 × mix/vocal × full/windowed（12 单元）；Current default = 仅 r2:vocal:windowed（1 单元）。[B4 serial_demo L1698–1800；Current batch.py L199–200]
2. **silence-aware 窗口规划默认不同**：B4 可开 `--silence-aware-window-plan / --strict-silence-boundary-plan`（按静音 snap 分窗）；Current batch 无法开，`_alignment_args` 未转发 → 恒用固定 60s `build_serial_windows`。[B4 serial_demo L1655–1662；Current run_qwen_fa_batch.py L445–464 / windowed_alignment L868–869]
3. **skip-silent-windows 默认不同**：B4 可开 `--skip-silent-windows` 跳过非 final 静音 core；Current batch 无法开后默认 False（不跳过，所有 core 都去 fetch）。[B4 serial_demo L1646；Current windowed_alignment L1046]
4. **decoder / control decoder 可配置性不同**：B4 可选 raw/gpu/official 与独立 serial-control-decoder；Current batch 无 decoder 参数 → 恒 official + control=same。[B4 serial_demo L587–588、L1596–1598；Current L445–464]
5. **leading-silence / short-tail / minimum-core 保护默认不同**：B4 可开启后由 silence 规划施加 `leading_silence_min_sec/tail_min_core_sec/minimum_core_sec`；Current 固定网格无此保护，只有 final_core 兜底推全部剩余字。[B4 serial_demo L882–896;  Current windowed_alignment L1018–1132]
6. **silence 双时钟压缩不可达**：B4 支持 `--compress-silence-audio` 原时钟↔压缩时钟映射回写；Current batch 无此开关。[B4 serial_demo L813–860、L744]
7. **可观测/研究探针字段透传不同**：B4 能开 shadow-rows、attempt-probes、stable-segment、top-K、research initial/injection/max-windows；Current `_alignment_args` 全部不转发（仅影响诊断与可注入性，不影响默认 state machine）。[B4 serial_demo L1630–1644；Current L445–464]

---

## 两者一致的部分

- **`windowed_alignment` 串行核心状态机完全共享**：B4 与 Current 调用的是同一函数，行级逻辑（cursor、context/commit/lookahead 切分、forward-compress、final_core 兜底、SerialWindowAlignmentError）完全相同。
- **slot 查询语义一致**：单次请求 = 一个 forwa`future_character_range` 按行对齐的 future slice 全部单元一起喂（每条一个 text item），slot 数 = 2×单元数，一次 forward。
- **游标/commit/overlap 语义一致**：input_cursor / committed_cursor 双光标；已提交 core 永不被覆盖，overlap 里的已提交字以 context 重喂；重叠左侧 forward 压缩（可压到零时长）。
- **occurrence/重复词处理一致**：重复词按词序逐 global_index 独立成槽，`future_character_range`/`split_core_commit_prefix` 严格连续推进。
- **skip-silent 的标准语义一致**：判定（`essentially_silent`，非 final core 才可 skip）代码相同，差异只在 Current 默认关闭。
- **full-slot 的 full 模式一致**：`full_alignment` 也是唯一同一实现（serial_demo L715–742，batch 直接复用）。
- **末窗语义一致**：`final_core` → `target_count=剩余全部字符`、`next_input_candidate=total`，两入口相同。
- 默认 `core_sec=60`、`left/right_context_sec=10`、`timestamp_segment_sec=0.08`、`future_line_padding=1`、`minimum_forward_characters=64`、`future_character_ratio=1.35`、`max_candidate_expansions=4`、`boundary_start_tolerance_sec=0.32`、`seam_tolerance_sec=0.16` 两入口一致（batch.py L930–947 vs serial_demo L1600–1614）。
