# D-note：renderer 现状核实 + Test Demo 33/3 状态（Codex 07 前置）

> 会话：`docs/sessions/20260814_realign_recovery_visualization_overnight/`
> 覆盖事实4（ComparisonTrack/timeline projection）与事实9（Test Demo 33 success / 3 failure）。
> 结论基于**代码/产物实读**，非文档推测。证据仅记录事实与路径；是否/如何改造交由 07 计划判断。

---

## A. renderer 输入接口与 ComparisonTrack 现状（事实4）

### A.0 一句话结论
**已有 reusable 多 track timeline 投影，可最小改动做双路/四路。**
统一中间结构并非一个新类，而是 `render_timeline_page(tracks=[...], windows=...)` 的
`track = (label, rows [, window_trace])` 元组约定：
- `rows`（歌词 unit）= canonical_visual_row 投影后的 dict（含 `start_sec/end_sec`、`global_character_index`、
  `display_text/character/alignment_unit`）；
- `window_trace`（可选第 3 元素）= 该路自己的窗口边界（`core_start_sec/core_end_sec/input_start_sec/input_end_sec` 等）；
- 每路共享同一 `start/end` 全局时间轴、按 `y_top` 自上而下堆叠。

这正好对应 03 文档建议的 `ComparisonTrack{label, canonical_units, window_trace, detector_spans, target/fixed/proposal_spans}`。
其中 `canonical_units(rows)` 与 `window_trace` 现成；detector/target/fixed/proposal **overlay spans 需新增 kind 扩展**（见 B.5）。

关键文件：
- `src/lyricalign/demo/visual_diagnostics.py` — `render_timeline_page`(p541-681)、`render_duration_pmf`(p684)、
  `render_inconsistency`(p720-791)。
- `src/lyricalign/demo/timeline_video.py` — `render_page_video`(p111-229) 固定尺度 page → MP4。
- `src/lyricalign/demo/media_render.py` — `render_alignment_comparison`(p568-704)、`render_composite`(p504-565)、
  `build_bottom_ass`(p274-395)。
- `scripts/demo/analyze_inline_realign_visuals.py` — 建 track/分页驱动方。
- `scripts/demo/render_inline_realign_demo_batch.py` — 把 page groups 逐项渲染成 MP4。

### A.1 输入接口逐项
| 条目 | 现状 |
|---|---|
| rows 时间字段 | `canonical_visual_row`(p33-57) 依次取 `start/end_sec`、`selected_*`、`fixed_global_*`、`official_fixed_global_*`、`raw_global_*`，缺完整对则抛错。`ordered_rows`(p60-62) 按 `global_character_index` 排序。 |
| track 结构 | `_unpack_track`(p222-229)：2 元 `(label,rows)` 或 3 元 `(label,rows,windows)`。 |
| 多路 | 现成。`decoder_tracks`=4 路、`comparison_window` 最多 4 路、`realign_execution_tracks_for_page` 每个 case 追加多路；`render_duration_pmf`/`render_inconsistency` 均收多 track。 |
| 页面/windows overlay | `draw_windows`(p201-220)、`draw_track_windows`(p232-311)（每路独立核心/输入/静音边界、`silence_compression_mapping` 移除区）。 |
| 返回 | `render_timeline_page` 返回含 `path/start_sec/end_sec/width/height/timeline_axis_px/track_geometry`；`timeline_axis_px` 供播放线定位。 |

### A.2 具体能力逐项确认
| 03 要求 | 已有？ | 证据 |
|---|---|---|
| 输出 3840×1080 | **已有** | `timeline_video.py` `OUTPUT_WIDTH=3840, OUTPUT_HEIGHT=1080`；video page 用 `pixel_width=3840,pixel_height=1080,video_layout=True`（analyze p510/519/530）。 |
| 30s/page 按真实时间分页 | **已有** | `page_ranges(duration,page_seconds)`(analyze p189-191)，`timeline_page_seconds=30.0`（pipeline 默认 p211；config 两处也=30），behavior page=30s `--behavior-page-seconds`。尾页按真实时长。 |
| 播放线沿时间轴匀速扫 | **已有** | `render_page_video` 用 `_progress_x_expression`(timeline_video p39-59) + `_axis_geometry`(p22-34)：外黑/内橙两色线逐帧评估 x，只沿 axis、每页重置、尾页按真实时长。`--behavior-page-seconds>5` 约束。 |
| 底部两行 KTV 字幕 + 高亮 | **已有** | `build_bottom_ass`(media_render p274-395)：两行 `rows_y=[band*0.38, band*0.78]`，每字符 `\kf{duration_cs}`（p348-367），Preview 行先行、`\an5` 居中。 |
| 原曲/mix 音轨 | **已有** | `render_page_video` 的 `audio_track` 即原曲；用原曲作最终 MP4 音轨（音频布局探测 p94-108）。 |
| 字体 Noto Sans CJK SC | **已有** | 默认 `font="Noto Sans CJK SC"`（pipeline p199）；`detect_font`(media_render p175-222) 强校验 SC face（拒绝 JP 替代、TTC index 提取）。 |
| 零时长/负时长聚合 | **已有** | `_group_collapsed_rows`(visual_diagnostics p385-440) + `_collapsed_group_label`(p368-382)：按 kind(负/零)+120ms 时间聚类，`_compress_index_ranges`(p334-347) 连续 index 压缩 + `_collapsed_text_runs`(p350-365) 文字连写。 |
| timeline 文字降级（序号+字→只字→interval） | **已有** | `_adaptive_row_label`(p318-325)：`width_px>=34` → `"{index} {text}"`；`>=14` → 只字；`<14` 或 overflow → 空（只留色块 interval）。 |
| 多 track 共用同 global time scale | **已有** | `render_timeline_page` 单 `ax.set_xlim(start,end)`；同页所有 track 同 x 时间轴。 |
| 直接在一条 ffmpeg 里渲染 2/4 路旁路视频 | **已有** | `render_alignment_comparison`(media_render p568-704)：layout `two`/`four`，一次解码 + 每 panel 独立 ASS + `hstack`/`xstack`；`render_composite`(p504-565) 支持 two/three/four。 |

**注意**：`render_alignment_comparison`/`render_composite` 是“对齐产物直接旁路”路径（输出给纯对齐比较）；
而本会话渲染主路径是 `analyze→render_timeline_page(多track 纵向堆叠)→render_page_video`。
双路/四路按 03 需求“同页各 track 同尺度”应**优先复用纵向多 track 页面**；若需要“左右 panel 元视频”可另用
`render_alignment_comparison`（但那是 2/4 对齐产物旁路，非 4 机制 track 叠加 + window overlay 画面）。

### A.3 缺失/需新增点（renderer 之外）
- **B4 historical pre-slot/non-slot runner**：本文件不涉及其可复现性，但当前 renderer 的 track 来源是
  `branches/*/alignment.json`；B4 若需 adapter/compat runner 生成同 schema alignment 才能喂 track。**未知/需核实**。
- **detector/target/fixed/proposal overlay span kind**：`render_timeline_page` 现有 spans 支持
  `stable_candidate/stable_selected_*/realign_accepted/realign_rejected`(p580-588)。03 新增
  detector ACCEPT/REJECT/uncertain、target、fixed、proposal、iteration/split identity → 需新增 kind 样式 + 注解。
- **R-U coarse→sparse refinement 第四路产物 schema**：第四路若未实现则先三路；本文件不判定其实现状态。**未知/需核实**。

---

## B. 旧 inline-realign 批量可视化入口（scripts/demo/）

- 主编排：`scripts/demo/run_inline_realign_pipeline.py`
- 批次封装（.sh）：
  - `scripts/demo/run_inline_realign_smoke.sh`
  - `scripts/demo/run_inline_realign_formal.sh`
  - `scripts/demo/run_inline_realign_render_only.sh`（resume 渲染：`RENDER_MODE=after FROM_STAGE=render RESUME=1`）
  - 环境 `scripts/demo/inline_realign_env.sh`
- 阶段顺序（pipeline `stages`，L422）：`manifest → experiment → summary → visualization → collection → video_pages → render`
  - visualization = `scripts/demo/analyze_inline_realign_visuals.py`（L505，`--video-pages-mode off` 先静态）
  - collection = `scripts/demo/collect_inline_realign_evidence.py`（L523，`--out-root`）
  - video_pages = `analyze_inline_realign_visuals.py --video-pages-mode on --video-pages-only`（L565）
  - render = `scripts/demo/render_inline_realign_demo_batch.py`（L590）
- 输入：`--config <yaml>` + demo/prepared 媒体根 + `--demo-root`（默认 `$REPO_ROOT/夜苏打`）+
  model env（`MODEL_REVISION`/`R2_CHECKPOINT`，见 inline_realign_env.sh）。输出根 `OUT_ROOT`。
- 逐项产物：`<out>/items/<item_id>/branches/{variant}/alignment*.json`、
  `visuals/visual_analysis.json`（`pages` 各 page-group 列表）、`renders/*.mp4`；
  顶层 `visualization_summary.json`、`analysis_complete.json`、`render_complete.json`、`demo_render_summary.json`。
- 命令示例：
  ```bash
  source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
  bash scripts/demo/verify_inline_realign_v4.sh
  RENDER_MODE=skip bash scripts/demo/run_inline_realign_smoke.sh        # 跳过渲染
  bash scripts/demo/run_inline_realign_render_only.sh smoke <OUT_ROOT> # 只补渲染=resume
  ```

### B.1 关键：现有 pipeline 顺序与 03 V4 合同冲突
现有 `<out>` 下顺序是 **visualization(analyze) → collection → video_pages**（A 阶段先于 collection）。
03「可视化设计」V4 冻结顺序要求 **collection / evidence → analysis_complete → static visualization → pages → encode、
禁止 visualization→collection**。**已确认现有顺序与合同相悖，07 计划需调整阶段顺序或新增 adapter 阶段。**

---

## C. Test Demo 33 success / 3 failure（事实9）

### C.0 结论
数据源：`/home/hyan/Data/lyricalign/runs/unit_realign_test_demo_formal_20260813/04_test_demo/`
内的 `TEST_DEMO_DETECTOR_SUMMARY.json`：
- **ranking（成功过筛、无 GT，不报 MAE）n=33**
- **failed n=3**，reason 均为 `Error opening '<path>': Format not recognised.`（ffmpeg/ffprobe 无法打开媒体）

`formal=true, result_status=ok`。这就是“33 success / 3 failure”的精确来源。

### C.1 失败项清单 + 原因
| item | reason | 备注 |
|---|---|---|
| `.../test/Chinese/Side by Side.mp4` | Format not recognised | `.mp4`；也是 Smoke1 参考视频 |
| `.../test/Chinese/祈愿花开.mp4` | Format not recognised | `.mp4` |
| `/home/hyan/LyricAlignment/夜苏打/夜苏打.mp4` | Format not recognised | 在 repo 内 `夜苏打/`，非 test 媒体目录；`夜苏打` 是 standalone demo |

三个都是 **`.mp4` 文件打不开**，而成功项几乎全是 `.mp3`。可能原因（未进一步排查）：mp4 容器/编码不被当前 ffmpeg
支持或文件损坏/占位。**未知/需核实**是文件本身坏还是缺解码器。失败发生在 detector 的媒体打开阶段（pre-request），
因此这三个 song 没有进入 REALIGN_REQUEST_PLAN / executor manifest。

### C.2 目录结构与 resume 状态
`unit_realign_test_demo_formal_20260813/04_test_demo/`：
- `TEST_DEMO_DETECTOR_SUMMARY.json`（ranking 33 / failed 3 / suspects / suspicious_score）
- `TEST_DEMO_SUSPICIOUS_WINDOWS.jsonl`、`TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl`、
  `TEST_DEMO_REALIGN_BEHAVIOR.jsonl`、`TEST_DEMO_R_NULL.jsonl`、`TEST_DEMO_EXECUTOR_MANIFEST.jsonl`
- `forward/`：`RUN_MANIFEST.json`、`FAILURES.jsonl`、`items/`、`cached/`、`evidence/`
- pipeline 描述字段（summary）：`n_windows=60, n_requests=120, n_executable_realign_requests=118`

**执行层本身完整且可 resume**：
- `RUN_MANIFEST.json` → `item_count={requests:118, written:118, cache_hit:0, forward:118, failed:0}`；`failures=[]`；
  identity/cache 齐全（`requests_identity/cache_keys/evidence_inventory` 均为 long_slot recovery 字段）。
- `TEST_DEMO_EXECUTION.json` → `returncode 0`，executor=real，`{"ok":true,rows:118,written:118,failed:0,...}`。
- 3 个失败不在执行 manifest 中（那是媒体打开失败被前置滤掉），因此“可 resume”指的是：
  **重新跑 detector/summary 阶段（或修复媒体后重新规划 request）即可补上失败 song**；
  已完成 118 request 的 realign forward 走 cache-only（`cached/` 按 sha256 内容寻址）不重算。
- **不会因这 3 个失败卡死**：按 AGENTS 纪律它们是 item 级失败，不是全局阻塞；当前 118/118 已完成。

### C.3 媒体路径
- 源 manifest 中 `audio_path` 用 `/home/hyan/Data/lyricalign/test/<lang>/<name>.mp3`。
- **`/home/hyan/Data` 是符号链接 → `/root/autodl-tmp/AST_storage/Data`**（同 inode），两套路径等价：
  `readlink -f /home/hyan/Data` = `/root/autodl-tmp/AST_storage/Data`。
- 即 03 文档 Smoke1 写的 `/root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/Side by Side.mp4` 与
  summary failed 里的 `/home/hyan/Data/.../Side by Side.mp4` 是**同一文件**。
- 语言目录文件数（test 下）：Chinese=17、English=6、Cantonese=6、Japanese=6，共 35 个媒体文件。
  （另 `夜苏打/夜苏打.mp4` 在 repo 内。）

---

## D. 零时长聚合与 timeline 文字降级实现定位（供 07 引用）

全部位于 `src/lyricalign/demo/visual_diagnostics.py`（无需新增）：
- 统计：`duration_pmf`(p77-103) `duration_bin_labels`/`<0,=0,...>`；`structural_counts`(p106-124) negative/zero/regression/overlap。
- 聚合：`_group_collapsed_rows`(p385-440)（正时长隔开，零/负按 kind+≤120ms 聚类）→
  `_collapsed_group_label`(p368-382)（`坍缩/零时长 [idx-ranges] text-runs`）→ `_compress_index_ranges`(p334-347) +
  `_collapsed_text_runs`(p350-365)。
- 文字降级：`_adaptive_row_label`(p318-325)（`序号+字 → 只字 → 空(仅 interval)`）。
- 相关统计聚合（alignment_artifacts.py p114-145,338-339：`zero_duration_count/rate/collapsed_to_zero_count`；
  realign_diagnostics.py p256,379）。这些是**计数**，非可视化聚合。
- `karaoke.py` `overlap_compression_collapsed_to_zero`(p600-603)、`raw_guarded.py` `collapsed`(p67) 为压缩标记，
  非渲染聚合。

---

## E. 关键缺口/已知未知（07 需处理）
1. 现有 pipeline 顺序 visualization→collection 与 03 V4 合同（collection→visualization）相悖 → 需调整/新增 adapter 阶段。
2. `ComparisonTrack` 是对多 track+window_trace 约定的**包装**；无现成类名，投影逻辑（从各 runner 产物读取 rows）
  目前只按 inline-realign schema 写死字段。B4/R-U/R-S/第四路的 schema 适配需新增 adapter。
3. detector/target/fixed/proposal/iteration overlay span kind 需新增样式与注解。
4. B4 historical runner 可复现性、第四路 R-U coarse→sparse 实现状态：**未知/需核实**。
5. 3 个 mp4 失败（Side by Side / 祈愿花开 / 夜苏打）具体是文件损坏还是缺解码器：**未知/需核实**（不影响 118/118 resume）。

### 本 note 产出核对表
- [x] renderer 输入接口 / 统一中间结构 / 多 track 现成 / 尺寸 / 30s / 播放线 / KTV / 零时长聚合 / 字体
- [x] 旧 inline-realign 批量可视化入口 + 调用
- [x] Test Demo 目录 / song 数 33+3 / 失败原因 / resume / 媒体路径
- [x] 零时长聚合与文字降级函数定位
```