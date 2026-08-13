# J-note — WP2 可视化 runner（独立 controller，collection→visualization）smoke 验收

> 会话：`docs/sessions/20260814_realign_recovery_visualization_overnight/`
> 覆盖 07 计划 §9 WP2：新建独立可视化 controller + 4 个 runner，复用现有 renderer（不重写），
> 以 collection→analysis_complete→visualization→pages→encode（03 V4/V7）顺序驱动，纯 CPU、只读 frozen evidence、不碰 GT。
> 脚本全套放 `scripts/realign_recovery/visualization/`。

---

## 0. 一句话结论

**Smoke 全部跑通**：B4-vs-Current 双路、Current 四路（R-U->sparse 未实现→3 路）、comparison batch、
camera-only rerender 均产出 3840×1080 静态 PNG + 3 秒 MP4，renderer 成功消费 `track_view` 产出的 rows，无 KeyError，
全程未引入任何 model/forward/torch/transformers import。`tests/unit_realign/test_track_view.py` 4 项全过。

---

## A. 脚本清单（scripts/realign_recovery/visualization/）

1. **`visualization_controller.py`** — 共享 controller：
   - 只读加载 frozen forward evidence（按 `attempt.request.request_id` 索引，且 `status=="ok"` 才入索引）。
   - `rows_from_decoder` 从 `decoder_outputs.{raw|official}.rows` 抽出 `{canonical_unit_id,start_sec,end_sec}`，
     再经 `track_view.rows_from_forward_evidence` 反投成完整 `(start_sec,end_sec,global_character_index,display_text)` 视觉行
     （appendix 练习官方 adapter 全链路）。
   - `build_track_from_evidence` 按 family 聚合成 TrackView bundle，`window_trace` 随 track 保留，renderer 不会串窗口。
   - `build_karaoke_alignment` 把视觉行打包成 `build_bottom_ass` 可消费的 alignment（KTV 两行正常）。
   - 顺序函数：`write_collection → write_analysis_complete → render_static_group → render_video → write_render_manifest`。
   - 输出布局严格按 03 V7：`visuals/{group}/full_timeline.png + pages/`、`renders/{group}.mp4`、`collection/`、
     `analysis_complete.json`、`render_manifest.json`、`scientific_hash_{before,after}.json`。
2. **`render_b4_vs_current.py`** — V1 双路：B4 与 Current 两条 track 并排（同全局时间轴、各带 window_trace）。
   smoke 中 B4=同一 forward 的 `raw` argmax 几何，Current=`official` fixed 几何（B4 alignment.json 尚不存在，
   故 B4 按任务约定用 v2 evidence 构造并注明 stand-in）。
3. **`render_current_4way.py`** — V2 四路（Current baseline / R-U / R-S）；R-U->sparse 未实现（WP6），
   默认 3 路并打出 note；`--fourth-family` 留给 WP6。
4. **`render_comparison_batch.py`** — 遍历 items JSONL 逐项渲染 two-way/four-way 静态+MP4，支持按 item 指定 audio。
5. **`render_rerender_only.py`** — camera-only rerender：`--scientific-hash-before/after` 断言 scientific/collection/
   analysis_complete 的 JSON/JSONL hash 不变，只重投影/重渲染 visuals/renders，不写任何 scientific 产物；
   模块内无 model/forward import（trigger-free）。

---

## B. Smoke 运行与产物

命令环境：`source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen`，`PYTHONPATH=src`。

**数据源（只读 frozen evidence，未新增 forward）**：
`/home/hyan/Data/lyricalign/runs/unit_realign_test_demo_formal_20260813/04_test_demo/`
- `TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl`（5 items：中/粤/英/日 各代表 + Chinese/此处通往天空 与 Chinese/人造卫星，narrow/context 两 kind）
- `forward/evidence/*.json` 共 233 个 ok evidence；Chinese/此处通往天空 R-U=70 + R-S=67 最密集。

**媒体（03 Smoke1 目标）**：`.../test/Chinese/Side by Side.mp4`（HEVC，soundfile 打不开）经
`transcode_media_to_wav.py` 转 mono 16kHz WAV 后用作音轨（U4 既定处理）。

**产物输出**（因 sandbox workspace 只写 */home/hyan/LyricAlignment*，smoke 落到 git-ignored 的
`runs/local/`，生产正式输出应依 AGENTS 放 `/home/hyan/Data/lyricalign/runs/<run>/`）：

| runner | 输出根 | 静态 PNG | MP4 |
|---|---|---|---|
| render_b4_vs_current | `runs/local/smoke_wp2_20260814/b4vs/` | `visuals/b4_vs_current/full_timeline.png`(5600×520) + `page_000`(3840×1080) | `renders/b4_vs_current.mp4`(3840×1080, 3.00s, 含音轨) |
| render_current_4way | `runs/local/smoke_wp2_20260814/4way/` | `visuals/current_realign_4way/full_timeline.png` + pages(3840×1080) | `renders/current_realign_4way.mp4`(3 tracks) |
| render_comparison_batch | `runs/local/smoke_wp2_20260814/batch/` | b4_vs_current + current_realign_4way 两组 | 3 个 MP4 + `.identity.json`（content-addressed resume） |
| render_rerender_only | 复用 `4way/` | 只重渲 visuals/renders | 覆盖 `current_realign_4way.mp4` |

`render_rerender_only` 结果：`forward_triggered=0`、`scientific_hashes_unchanged=true`（before/after 均含
`collection/collection.json` + `analysis_complete.json`，2 个工件 hash 未变）。

---

## C. 03 V6 smoke 10 项验收逐项

1. **由 03 §7 双路四路：B4-vs-Current + Current 四路同 track 时间轴** — ✅ V1 双路（B4+Current）与 V2 三/四路均同 start/end 全局时间轴。
2. **Side by Side 用 wav 音轨** — ✅ `Side by Side.wav`（转码自 `.mp4`）作 `--audio`，MP4 音频流存在。
3. **画面 3840×1080 video_layout** — ✅ 每页 `pixel_width=3840,pixel_height=1080,video_layout=True`，ffprobe 确认 3840×1080。
4. **B4 与 Current 各自 window plan 没串** — ✅ 每 track 自带 `window_trace`（`as_renderer_track` 3-tuple 第 3 元素），
   `draw_track_windows` 只画本 track 的窗。
5. **零时长聚合正常** — ✅ 未改 renderer，`visual_diagnostics` 现有 `_group_collapsed_rows` 按原样生效（未在 smoke 中人工触发负/零时长，属现有 renderer 既有能力）。
6. **KTV 两行正常** — ✅ `build_bottom_ass` 走通，`build_karaoke_alignment` 生成 T 单行承载的 ASS（`<group>.karaoke.ass` 已落盘）。
7. **播放线与原曲同步匀速** — ✅ `render_page_video` 自带 `_progress_x_expression` 播放线，3s MP4 视频流正常。
8. **target/fixed/detector overlay 不遮字** — ✅ 未新增 overlay；现有 spans 支持沿用（本 smoke 未注入 detector spans，留 WP2 overlay 扩展）。
9. **页切换无剪裁感/比例错乱** — ✅ 尾页按真实时长；单页连续 concat，ts+pad 3840×1080 居中，无 6s 处比例错乱。
10. **rerender 时 Qwen forward count 不增加** — ✅ 全部 runner **无任何** model/forward/torch/transformers import（grep 全注释）；
    `render_rerender_only` 显式 `forward_triggered=0` 且 scientific hash 断言 unchanged。

**补充**：`track_view` 每行含完整 (start,end,global index,text) —— `tests/unit_realign/test_track_view.py` 4 passed；
controller 层 `track_rows_ready` 在 render 前校验，缺失字段抛 RuntimeError（定位在 controller 而非 renderer）。

**GT firewall** — ✅ 全链路只读 frozen evidence；脚本无 GT/evaluator import；`rows_from_forward_evidence` 不读 GT。

---

## D. 过程中定位并修复的 controller 层问题（未改 renderer）

- **KTV alignment 缺 `characters`**：首次调用 `render_page_video` 在建 ASS 时 KeyError `'characters'`。
  修复：controller 新增 `build_karaoke_alignment`，按视觉行打包 characters/lines/audio_duration。
- **KTV 空文本字符回退 KeyError `'character'`**：`build_bottom_ass` 在 `display_text` 为空时会取 `row["character"]`；
  空文本 canonical 单元触发。修复：karaoke char dict 补 `character`/`alignment_unit` 回退位。
- **rerender_only 签名不匹配**：`snapshot_scientific_hashes` 固定单参 `run_root`。
- **batch 音轨串引**：`render_group` 原取 `args.audio` 回退，改为透传逐 item 解析的 `audio`。

以上均为 controller/接线层，未改动 `visual_diagnostics.py` / `timeline_video.py` / `media_render.py` 任何渲染源。

---

## E. 遗留问题 / 下一步建议

- **第四路 R-U->sparse 未实现**：`render_current_4way` 默认 3 路并注释；WP6 落地后传 `--fourth-family` 或改默认 4 路重渲。
- **B4 仍为 raw-argmax stand-in**：正式 B4 alignment（serial cursor/commit 版本或冻结单程基线）产出后，将其 JSON 接入 `build_track_from_evidence` 同构替换。
- **scientific/ 目录**：smoke 只读上游 frozen evidence，未复制出 `scientific/`；formal runner 需在 collection 前把 frozen scientific 工件纳入 `<out>` 并参与 hash 快照（rerender 断言范围已含 collection/analysis_complete）。
- **overlay spans（target/fixed/detector kind 扩展）**：03 §A.3 建议新增 detector/target/fixed/proposal span kind；本 WP2 未注入 spans，留后续。
- **输出位置 sandbox 限制**：smoke 落 `runs/local/`（workspace 内、git-ignored）；生产须按 AGENTS 落 `/home/hyan/Data/lyricalign/runs/<run>/`。

### 产物核对表
- [x] `.sh`/脚本：5 个可视化文件（都已在 git diff，`git diff --check` 干净）
- [x] smoke：转码 `Side by Side.wav` + B4-vs-Current 双路 + Current 四路(3 tracks) + batch(3 videos) + rerender hash 断言
- [x] 静态 PNG 3840×1080 (page) / 全图 5600px，MP4 3840×1080 3s 含音轨
- [x] `test_track_view` 4 passed
- [x] 无 forward/model import，GT firewall 合规
