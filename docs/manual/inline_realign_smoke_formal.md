# Inline Realign v4：全机制 smoke / formal 运行手册

## 1. 这套入口解决什么问题

本版本用于同时研究以下问题，而不是只生成一套 KTV 字幕：

1. 30 秒与 60 秒核心窗口的差异；
2. 固定窗口、静音吸附、严格静音边界和全静音压缩诊断；
3. Raw、processor decoded、window selected、final committed 各阶段发生了什么；
4. Stable 是否能作为同步音频—歌词裁剪边界或冻结锚点；
5. Exact、前后各加 2 字、前后各加 4 字的局部 realign 是否一致；
6. 结构异常必须下降、结构异常不升、零时长宽松门和中位融合的差异；
7. Immediate 与 Deferred realign 的区别；
8. 少给、恰好给足和多给歌词时模型的反应；
9. 如何在推理、静态分析和慢视频渲染之间正确 resume。

所有 realign 仍为 shadow-only：默认不会修改 resolved primary alignment；当前默认 primary 为 B2。

## 2. 输出阶段

流水线顺序固定为：

```text
manifest
→ model experiment
→ numerical summary
→ static diagnostics
→ compact evidence collection
→ analysis_complete.json
→ slow Demo rendering
→ render_complete.json
```

因此：

- `analysis_complete.json` 出现后，模型推理、指标、静态图和证据包已经可用；
- 视频仍在渲染时，不影响前述结果；
- `render_complete.json` 单独记录视频状态；
- `pipeline_complete.json` 汇总两部分状态。

## 3. 首次运行

### 3.1 Smoke

```bash
cd /home/hyan/LyricAlignment

bash scripts/demo/run_inline_realign_smoke.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728
```

Smoke 并非只跑一两首：它按语种选择代表 Demo，并包含 MIR-1K、M4Singer native 和 synthetic-long，同时运行完整机制链。

### 3.2 Formal

仅在 smoke 的 `analysis_complete.json` 为 complete 且失败项已处理后运行：

```bash
cd /home/hyan/LyricAlignment

bash scripts/demo/run_inline_realign_formal.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728
```

Formal 使用当前发现的全部 prepared Demo；Demo 数量是运行时发现结果，不写死为某个固定数量。

## 4. 渲染后置

推理与静态分析完成后再渲染：

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728 \
RENDER_MODE=skip \
  bash scripts/demo/run_inline_realign_formal.sh
```

此时应先得到：

```text
analysis_complete.json
inline_realign_evidence.tar.gz
followup_analysis_summary.json
visualization_summary.json
```

之后只补视频：

```bash
bash scripts/demo/run_inline_realign_render_only.sh \
  formal \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728
```

也可以把 render-only 命令放到另一终端或共享同一存储的机器执行，但应避免两个进程同时写同一个 Demo item。

## 5. 正确 resume

### 5.1 普通中断

不要执行 cleanup，不要使用 `--force`。直接重跑同一入口：

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728 \
RESUME=1 \
  bash scripts/demo/run_inline_realign_formal.sh
```

Resume 只有在以下身份完全一致时才被接受：

- resolved config；
- manifest/input selection；
- model/revision/checkpoint；
- 输入音频、歌词和 GT hash；
- 关键实现代码 hash；
- item 和 stage 的预期产物。

身份不一致时会拒绝 resume，避免把不同实验混在同一目录。

### 5.2 只重试失败项

```bash
OUT_ROOT=... \
RESUME=1 \
RETRY_FAILED_ONLY=1 \
  bash scripts/demo/run_inline_realign_formal.sh
```

### 5.3 重启指定 item

```bash
OUT_ROOT=... \
RESUME=1 \
RESTART_ITEM='demo_Chinese_xxx,m4singer_long_xxx' \
  bash scripts/demo/run_inline_realign_formal.sh
```

### 5.4 从某个 stage 继续

```bash
OUT_ROOT=... \
RESUME=1 \
FROM_STAGE=visualization \
  bash scripts/demo/run_inline_realign_formal.sh
```

可用 stage：

```text
manifest experiment summary visualization collection render
```

### 5.5 仅使某 stage 失效

例如只重画图和重渲染：

```bash
OUT_ROOT=... \
RESUME=1 \
INVALIDATE_STAGE='visualization,collection,render' \
FROM_STAGE=visualization \
  bash scripts/demo/run_inline_realign_formal.sh
```

## 6. 进度观测

另一终端执行：

```bash
/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  scripts/demo/watch_inline_realign_status.py \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728
```

一次性打印：

```bash
python scripts/demo/watch_inline_realign_status.py OUT_ROOT --once
```

状态文件：

```text
state/run_state.json
state/stages/*.json
state/items/*.json
state/render_items/*.json
pipeline_status.jsonl
experiment_live_status.json
analysis_complete.json
render_complete.json
pipeline_complete.json
```

## 7. 窗口与静音条件

长序列运行以下条件：

| ID | Core | 静音策略 | 解释 |
|---|---:|---|---|
| B0 | 60 s | 固定 | 旧长窗参考 |
| B1 | 30 s | 固定 | 短窗参考 |
| B2 | 30 s | 静音吸附 | 当前主 reference；音频上下文仍连续 |
| B3 | 30 s | 静音吸附 | Raw 自己控制串行 cursor |
| B4 | 60 s | 静音吸附 | Core 长度对照 |
| B5 | 30 s | 严格静音边界 | 模型输入不跨越强静音 |
| B6 | 60 s | 严格静音边界 | 长 core 的严格边界 |
| C0 | 30 s | 全静音压缩 | 诊断对照，不作为生产方案 |
| C1 | 60 s | 全静音压缩 | 诊断对照，不作为生产方案 |

严格静音边界保留原始全局时间轴，但将强静音前后划为不同 active region，左右输入上下文都不能跨越静音主体。

全静音压缩会删除长静音内部、保留少量边缘 padding，再把预测通过 piecewise mapping 映射回原时间轴。该条件只用于理解模型机制。

## 8. Stable 同步裁剪

旧实现曾保持早期音频起点，却把歌词起点跳到 stable 附近，导致音频和歌词不对应。该实现已废弃。

当前条件：

- `S0_stable_anchor_only`：按原窗口音频和歌词范围重新运行，仅冻结稳定锚点；
- `S1_stable_sync_exact`：音频与歌词均从 stable 起点开始；
- `S2_stable_sync_minus2`：音频和歌词均从 stable 前 2 个单位对应位置开始；
- `S3_stable_sync_minus4`：同理，向前 4 个单位。

裁剪音频起止来自 baseline 中相同歌词单位的时间范围，输出中 stable 本身被冻结，不允许 rerun 改写。

## 9. Realign gate

每个目标区间执行：

```text
Exact
前后各加 2 个单位
前后各加 4 个单位
三上下文逐字中位融合
```

同时记录四类 gate：

1. `strict_decrease_gate`：结构异常分数严格下降，仅作旧控制；
2. `structure_nonincrease_consensus`：三上下文一致、硬安全通过、结构分数不升；
3. `zero_duration_relaxed`：原区间含零时长，候选减少零时长且不新增负时长、回退或重叠；允许三条完整路径不一致；
4. `context_median_fusion`：对三次边界逐字取中位数后做最小单调投影。

输出字段严格拆分：

```text
gt_oracle_improved_shadow
automatic_gate_accepted_shadow
manual_gate_accepted_shadow
deferred_gate_accepted_shadow
actual_writeback
```

不再使用含义混乱的 `would_write` 作为主汇总字段。

## 10. 文本剂量实验

固定声学窗口，仅改变歌词范围：

- 文本终点：`-8,-4,-2,0,+2,+4,+8,+16`；
- 文本起点：`-4,-2,0,+2,+4`；
- 继续保留 `1.25×/1.5×` 未来歌词扩张作为历史对照。

负终点偏移可能删掉窗口内实际唱到的歌词；正偏移增加未来歌词。两类结果必须分开解释。

## 11. Raw / decoder 消融

同一 B2 窗口和 cursor 下保存：

```text
D0 raw argmax
D1 processor decoded
D2 window selected
D4 final committed
D5 raw nonnegative only
D6 raw minimal monotonic
```

Raw 的 start/end 独立 argmax，因此可以出现负时长、零时长、回退和重叠。主汇总同时报告这些结构指标和 canonical v3 tolerant GT 指标。

B3 则是另一问题：Raw 自己控制下一窗歌词推进。不能将 D0 的局部时间质量与 B3 的串行稳定性混为一谈。

## 12. 图和视频

### Timeline

- 每个字符都画出，并按全局歌词序号使用稳定彩虹色；
- 零时长画竖线；负时长画反向虚线箭头；
- 重叠字符使用 lane packing；
- 固定时间比例，长歌分页；
- 输入范围、核心范围、静音区和严格边界明显区分；
- Realign 显示目标区间、左右锚点、Exact/±2/±4、融合结果和接受/拒绝原因。

### Duration PMF

完整离散分布使用同一个分母：

```text
<0, =0, (0,20], (20,40], (40,80], (80,120],
(120,200], (200,400], (400,800], >800 ms
```

负时长和零时长均为真实柱子，不使用只对正时长重新归一化的条件分布，也不生成 cumulative 图。

### Inconsistency

每张图包括：

1. 歌词序号—起点/终点二维折线；
2. 每个字符的 onset/offset 最大差；
3. 窗口或阶段 × 歌词序号热力图。

### Behavior / Comparison 视频

- 中央区域为窗口字符 timeline；
- 底部为压扁字幕带；
- 指针按固定时间比例匀速移动；
- 机制说明使用中文；
- Raw、official、stable 和 realign 不使用会省略的长文本列表；
- 视频由静态 PNG 页面复用生成，单个 Demo 可独立 resume。

## 13. 指标口径

主指标：

```text
character_interval_metrics_v3_tolerant
```

它对 invalid/missing 单位进行惩罚，并报告 coverage。旧的匹配单位 signed-error 只保留在：

```text
matched_only_diagnostic
```

不得把 matched-only MAE 当作主结果，否则漏掉困难字符可能造成虚假改善。

Demo 无 GT，只支持结构和听感结论。M4Singer synthetic-long 与自然数据必须分开报告；拼接 seam 附近和远离 seam 的指标也分开。

## 14. 证据包

默认生成：

```text
inline_realign_evidence.tar.gz
```

只收集适量 JSON/JSONL/Markdown：

- 请求和 resolved config；
- run/stage/item resume state；
- 汇总与失败记录；
- 少量代表 realign/stable/text-dosage case；
- 异常字符和窗口 trace；
- 静态图/视频文件索引。

不包含音频、视频、模型权重、完整日志和大规模 decoded rows。后续若需要大量原始数据，再使用专门收集脚本，不扩大默认 evidence 包。

## 15. 清理与覆盖

正常 resume 不清理。

升级旧 v3 到本 v4 时，由于窗口、stable、gate、指标和状态 schema 都变了，推荐使用新默认输出目录。必须复用旧目录时，先完整删除：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OLD_OUT_ROOT all
```

其他清理模式：

```bash
# 只删视频，保留静态图和分析
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT render

# 删除静态图和视频，保留模型结果
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT visual

# 删除 shadow/汇总/图/视频，保留 branch 推理缓存
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT analysis

# 删除不在 manifest 中的旧 item
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT stale
```

对于代码/schema 大升级，不要使用 `analysis` 混用旧 run identity，应使用 `all` 或新目录。

## 16. 应用归档后的服务器预检

直接解压覆盖后先运行：

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/verify_inline_realign_v4.sh
```

验证包含：

- Python compile；
- shell 入口语法；
- FFmpeg/FFprobe；
- 模型、checkpoint、MIR-1K、M4Singer 和 Demo 输入；
- focused regression tests；
- `Noto Sans CJK SC` 的 fontconfig family、TTC face index 和 Matplotlib 实际 family。

以下结果均视为失败：

```text
Noto Sans CJK JP
DejaVu Sans
findfont fallback
Glyph ... missing
```

预检只确认输入和代码，不替代 GPU smoke。

## 17. Resume 的具体边界

### Experiment item

每个 item 保存 request identity、预期输出及 SHA-256 输出快照。已完成 item 只有在输入、配置、代码和输出均未变化时才跳过。

### Static visualization item

每个 item 的所有 branch、stable、realign、配置 JSON 均进入 visual request identity。修改任何上游结果后，旧 PNG 页不会被错误复用。静态图中断后重跑时，只补未完成或失效 item。

### Render item

每个 Demo 的 5 个 MP4 独立恢复。为避免 resume 时重新读取并哈希所有大型视频，渲染状态校验：

- MP4 文件状态；
- 每个 MP4 的 `.identity.json` 请求身份侧车及其 SHA-256。

如果页面、音频、字体或 profile 变化，请求身份会变化并重新渲染。

## 18. 每个 Demo 的预期视频

```text
items/<ITEM_ID>/renders/behavior_current.mp4
items/<ITEM_ID>/renders/comparison_window_mechanism.mp4
items/<ITEM_ID>/renders/comparison_realign_mechanism.mp4
items/<ITEM_ID>/renders/comparison_realign_execution.mp4
items/<ITEM_ID>/renders/comparison_decoder_stages.mp4
```

含义：

1. `behavior_current`：按时间播放当前窗口、stable 和 realign 行为；
2. `comparison_window_mechanism`：30/60 秒及不同静音策略；
3. `comparison_realign_mechanism`：baseline、immediate、deferred、combined/fusion；
4. `comparison_realign_execution`：实际 exact、前后各加 2/4 字、融合和 gate；
5. `comparison_decoder_stages`：raw 到 final 的阶段变化。

## 19. 后置与并行渲染

推荐先用 `RENDER_MODE=skip` 完成分析，再启动 render-only。出现 `analysis_complete.json` 后，后续视频渲染不会改变模型推理和主指标。

`RENDER_MODE=skip` 只跳过 MP4 视频渲染；summary、静态可视化、evidence collection 和 `analysis_complete.json` 仍会执行。上述阶段报错均应视为 pipeline 失败，而不是 skip 模式的正常行为。

可以在另一个终端或另一台共享同一输出存储的机器执行 render-only，但必须满足：

- 静态页面已经完整；
- 输入音频路径可访问；
- 同一个 Demo item 不能被两个 render writer 同时处理；
- 使用相同字体和 render profile；
- 不在渲染期间删除 visual 页面。

最安全的并行方式是把不同 item 显式分配给不同进程；当前一条龙入口默认单 render writer，避免输出竞争。

## 20. 清理模式

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT all
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT stale
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT analysis
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT visual
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT render
```

- `all`：删除完整输出目录，用于 v3→v4 或明确从零运行；
- `stale`：只删除不在当前 manifest 中的 item；
- `analysis`：保留 branch inference cache，删除 shadow、指标、图和视频；仅用于明确失效旧派生结果，不用于普通 resume；
- `visual`：保留模型和指标，删除静态图、视频及其 item state；
- `render`：只删除每个 item 的视频和 render state。

普通中断恢复时不要运行任何 cleanup。
