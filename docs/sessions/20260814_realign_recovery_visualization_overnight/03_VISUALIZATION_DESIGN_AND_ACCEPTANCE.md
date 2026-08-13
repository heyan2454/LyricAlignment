# 可视化实验设计与验收合同

## 1. 定位

本轮可视化是**诊断实验**，不是简单 presentation。它必须帮助人工听/看：系统在哪个字、哪个窗口、哪个困难区开始漂，以及不同机制如何改变 timeline。

需要生成两套互相独立的比较视频。

---

# V1. Historical B4 vs Current Baseline 双路

## 目的

只回答一个 system-level 问题：

> **从 pre-slot B4 到当前 full-slot/current transition baseline，真实 Demo 行为是否有明确进步？**

不加入 realign，避免把 baseline 演进和 repair 机制混在一起。

## Track

```text
B4 legacy pre-slot / serial / non-slot
Current baseline / current full-slot serial semantics
```

### B4 冻结参考

使用现有文档：

`docs/research_fullslot_serial_detector/02_B4_60_SILENCE_OFFICIAL_SHADOW_V1.md`

核心 resolved 目标：

```text
core_sec = 60
left_context_sec = 10
right_context_sec = 10
decoder_kind = official
silence_aware_window_plan = true
strict_silence_boundary_plan = false
compress_silence_audio = false
skip_silent_windows = true
silence_boundary_min_sec = 0.8
strong_silence_anchor_sec = 1.5
silence_boundary_search_sec = 6.0
leading_silence_min_sec = 2.0
tail_min_core_sec = 18.0
minimum_core_sec = 12.0
actual_writeback = 0
```

但“B4 historical baseline”必须复现 **pre-slot/non-slot** 行为；不能仅把当前 full-slot runner 配成同样 60/10/10 参数后冒充 B4。

### Current baseline

不要在 patch 文档里凭印象硬编码 route id。Codex/agent 必须从当前实际 pipeline 解析：

- exact transition/state machine；
- full-slot semantics；
- decoder；
- window/silence resolved values；
- commit/provisional behavior。

输出 `CURRENT_BASELINE_RESOLVED.json` 后才能跑 A/B。

## 公平性

两路使用：

- 同一 song/audio；
- 同一已知歌词文本；
- 同一 model/checkpoint；
- 同一 audio preprocessing；
- official decoder，除非核实历史 B4 需要不同冻结项；
- 同样的可视化投影与时间坐标。

但不要强行共享：

- window trajectory；
- cursor；
- committed/provisional state；
- slot/non-slot internal state。

这些正是要比较的系统差异。

## 客观伴随统计

有 GT 数据：

- unit/frame/event 指标按既有 canonical schema；
- zero/near-zero duration；
- non-monotonic / overlap；
- cursor/occurrence drift；
- window-boundary localized error；
- full-song coverage。

Test Demo 无 GT：

- zero/near-zero duration；
- structural violation；
- skip/jump/repetition；
- raw/official disagreement（若已有）；
- detector reject/uncertain density（仅描述）；
- runtime/forward count。

---

# V2. Current Realign 四路机制消融

## Track 冻结

```text
1. Current baseline / no realign
2. R-U unit-local
3. R-S sparse/fixed
4. R-U coarse proposal -> bounded/sparse refinement
```

第四路若尚未实现：

- 先做三路 smoke；
- 实现并通过 scientific smoke 后补四路；
- **不得**拿 R-A/R-B、重复相同 R-U 或旧 pseudo-local 结果代替第四路。

## 每路必须共享/对齐的信息

- 同一 baseline detector result；
- 同一 target unit identity；
- 同一 global canonical index；
- 同一原曲音频时间轴；
- 各自 candidate timeline；
- 各自实际 request audio crop/fixed context。

---

# V3. 画面规格：沿用旧 renderer 的优点，不重新发明 UI

## 3.1 输出尺寸与分页

- video page：约 `3840 × 1080`；
- 默认 `30s/page`，按真实时间分页；
- static whole-song timeline 保持超宽横轴；
- 同页各 track 共用同一 global time scale。

## 3.2 播放进度

必须有一根清晰竖线按真实播放时间匀速移动：

- 只沿 timeline axis 扫；
- 不沿整张图片宽度错误移动；
- 页面切换后以该页真实 start/end 继续；
- 尾页按真实时长，不人为拖满 30s。

## 3.3 音频与 KTV

- 使用原曲/mix 作为最终 MP4 音轨；
- 保留底部两行 KTV 字幕；
- 字符高亮与当前播放时间一致；
- 模型推理可使用 vocal-only，但试听视频不能只放 separated vocal，除非另有诊断副本。

## 3.4 Timeline 文字

空间足够：

```text
120 我
121 们
```

中等空间：只显示字；

空间太窄：只保留 interval/mark，不硬塞文本。

不要重新加入 `120:我` 这种冒号造成的横向冗余。

## 3.5 零时长/近零时长聚合

参考用户历史要求：

```text
零时长 [120-124, 130, 132-134] 我-他，的，给-热
```

目标是：

- 不把几十个 zero-duration unit 纵向堆成几十行；
- index 连续范围压缩；
- 非连续 index 保留；
- 文字仍可追溯。

## 3.6 Window / detector / realign overlay

B4 vs Current：

- actual core boundary；
- input context boundary；
- silence snap / skipped silent window；
- commit/provisional ownership（若当前 renderer 有稳定编码）。

Current 四路额外显示：

- detector ACCEPT / REJECT / uncertain；
- realign target；
- fixed context；
- proposal/candidate region；
- iteration/split identity（只在 relevant page 的简短 annotation 中显示）。

Overlay 必须克制，不得遮住歌词 timeline。

## 3.7 字体

中文默认 `Noto Sans CJK SC`；日文如必要可选 JP family，但 pipeline 必须做 font preflight，避免 DejaVu CJK missing glyph warnings 影响正式图。

---

# V4. Pipeline 顺序必须修正

用户此前明确要求：**collection 在 visualization 前**。

本轮冻结顺序：

```text
scientific forward / baseline / realign
-> evaluator + scientific summary
-> evidence collection
-> analysis_complete
-> static visualization
-> video pages
-> MP4 encode
```

禁止：

```text
visualization -> collection
```

也禁止 collection 为了科学证据而不断触发图片生成。

---

# V5. 必须支持 cache-only rerender

实现时复用旧思路：

- scientific artifacts hash frozen；
- renderer/字体/annotation/layout 可改变；
- rerender 不重新运行 Qwen forward；
- rerender 前后检查 scientific JSON/JSONL hash 未改变；
- 需要修改 visualization schema 时只新增 adapter/projection，不污染 evaluator artifact。

建议增加统一中间结构，例如：

```text
ComparisonTrack
  label
  canonical_units[{id,text,start,end,...}]
  window_trace
  detector_spans
  target_spans
  fixed_spans
  proposal_spans
  metadata
```

旧 B4/current/unit-realign 都投影到该结构，再复用：

- `src/lyricalign/demo/visual_diagnostics.py`
- `src/lyricalign/demo/timeline_video.py`
- `src/lyricalign/demo/media_render.py`

不要从零重写 renderer。

---

# V6. Smoke 与批量顺序

## Smoke 1：`Side by Side.mp4`

用户过去反复使用：

```text
/root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/Side by Side.mp4
```

先生成：

- B4 vs Current static + MP4；
- Current 3/4-way static + MP4。

## Smoke 验收

人工必须能确认：

1. 3840×1080；
2. 字体正常；
3. 两路/四路时间轴同尺度；
4. B4 与 Current 各自 window plan 没串；
5. 零时长聚合正常；
6. KTV 两行正常；
7. 播放线与原曲同步匀速；
8. target/fixed/detector overlay 不遮字；
9. 页切换无约 6s“剪裁感”或比例错乱；
10. rerender 时 Qwen forward count 不增加。

## Formal visualization

Smoke 通过后扩到：

- Chinese 代表性 cases；
- Cantonese；
- English；
- Japanese；
- hard-case mined cases（catastrophic、serial drift、重复歌词、window-boundary）。

不要求把每一个 dataset item 都渲染 MP4；科学统计全量，视频选择有代表性的自动 case + 用户指定 case。

---

# V7. 输出目录建议

```text
<run>/
  scientific/...
  collection/...
  analysis_complete.json
  visuals/
    b4_vs_current/
      full_timeline.png
      pages/...
    current_realign_4way/
      full_timeline.png
      pages/...
  renders/
    b4_vs_current.mp4
    current_realign_4way.mp4
  render_manifest.json
  scientific_hash_before.json
  scientific_hash_after.json
```

最终 runner 可不同，但 provenance 语义必须等价。
