# 长范围 Inline Realign：Smoke / Formal 一条龙说明

## 1. 目标与当前边界

Qwen Forced Aligner 被视为一个短范围内效果良好的对齐工具。本实验研究如何通过窗口、串行 decoder、stable anchor、detector 和局部 realign，把短范围可靠性扩展到完整歌曲。

所有 realign 仍为 **shadow experiment**：会实际推理、生成完整对比 alignment、图片和 Demo 视频，但不会覆盖正式 B2 输出。

当前三个研究主体：

1. raw decoder 与 official decoder 的行为差异；
2. detector 对零时长、极短时长、结构坍塌和时间漂移的探测能力；
3. immediate / deferred local realign 以及 stable anchor 的使用方式。

## 2. 数据与选择

### Demo

Formal 递归发现并使用 `DEMO_ROOT` 中全部可配对的已准备 Demo。当前 17+6+6+6 只是数据状态，不写死在代码中。Smoke 默认每种发现到的语言取一首。

Demo ID 保留语言和歌曲名，并附相对源路径的 8 位短哈希。运行时把发现结果冻结到 `experiment_manifest.jsonl`；汇总和证据收集只接受该 manifest 中的 item，旧目录仅报告为 stale，不参与当前结论。

### GT 数据

- MIR-1K：自然长音频；formal 默认使用全部非 held-out 角色，held-out 仍需显式启用。
- M4Singer native：短范围 GT。
- M4Singer synthetic-long：60/120/180 秒长范围传播和接缝诊断。

全部 long-serial 样本运行 B0–B3。M4Singer native 只运行主分支，因为短片段通常不能有效比较 30/60 秒窗口。

## 3. 基线与实验分支

### 窗口基线

- `RAW_B2`：B2 每窗原始模型输出。
- `B0_60_fixed_official`：60 秒固定切窗 baseline。
- `B1_30_fixed_official`：30 秒固定切窗。
- `B2_30_silence_official`：30 秒 silence-aware 当前主方案。
- `B3_30_silence_raw_control`：raw cursor 控制，仅作行为诊断。

`fixed` 按目标时间直接切窗；`silence-aware` 在目标切点附近优先选择静音边界，并保留尾窗重新分配规则。

### Stable-anchor 消融

- `S1_stable_inclusive`：下一窗从 stable 区起点开始，输入包含 stable 本身。
- `S2_stable_left_overlap`：包含 stable，并保留少量 stable 前文本上下文。
- `S3_stable_frozen_overlap`：输入同 S2，shadow splice 时冻结 stable 对应。

此前“直接 stable cursor”负结果不能代表这三个纠正后的设计。

### Realign 消融

- `R0`：B2，不 realign。
- `R1_immediate_inline`：对当前已具有足够约束的异常区做即时 inline shadow realign。
- `R2_deferred`：等待后续恢复右 stable anchor 后，对被两侧锚点夹住的困难区 realign。
- `R3_inline_deferred`：R1 与 R2 组合。

当前实现是**完整串行 trace 上的可复现 shadow 模拟**，用于公平比较和生成全曲视频；它尚未把 realign 写回正式在线串行 cursor。目标算法是“即时修复 + 锚点恢复后的延迟修复 + 结束时只处理剩余 bounded 区间”，不是整首重新对齐。

## 4. 可视化与 Demo 视频

### 每个 item 的静态图

`items/<item_id>/visuals/` 包含：

- 分页多轨时间轴：GT（若有）、raw、B0/B1/B2、stable 和 realign 分支；
- GT unit 两端的延长虚线；
- 窗口、stable、detector 等模型行为标记；
- onset/offset signed error 图；
- 正时长直方图和 ECDF，零时长比例单独标注；
- B2 相对其他尺度/阶段的不一致图；
- `visual_analysis.json` 中的时长分位数、局部时长比、zero burst 与 GT timing metric。

不使用 waveform / vocal-energy 主轨。

### 每个 Demo 的视频

不会生成无对比的普通单路视频。每首 Demo 生成：

1. `comparison_main_2x2.mp4`：RAW / B0 / B1 / B2 四路同步 K 歌对比；
2. `comparison_stable_2x2.mp4`：B2 / S1 / S2 / S3；
3. `comparison_realign_2x2.mp4`：R0 / R1 / R2 / R3；
4. `behavior_current.mp4`：B2 K 歌字幕，同时显示当前窗口、输入/提交 cursor、raw/official 文本、detector、stable、零时长和播放进度。

没有内置人工标签。每个 item 仅创建 `visuals/HUMAN_REVIEW.md` 入口，用户可自行记录或把视频交给 AI 讨论。

## 5. Zero / short-duration 分析

零时长单独统计。极短非零时长不预设 20/40 ms 为最终阈值，而使用：

- 5 ms 细 bin 的正时长分布图；
- ECDF；
- p0.1/p0.5/p1/p2.5/p5/p10…分位数；
- 相对局部中位时长比；
- zero/low-tail 连续 burst；
- 与 GT error、窗口边界和跨尺度不一致的关系。

固定毫秒值可作为读图查询点，但 detector 阈值必须由 GT 区分能力决定。

## 6. 配置、缓存和结果身份

YAML 是规范配置源：

- `configs/experiments/inline_realign_multilingual_smoke_20260728.yaml`
- `configs/experiments/inline_realign_multilingual_formal_20260728.yaml`

wrapper 只传数据、模型和输出路径。显式 CLI 参数可以覆盖 YAML，最终有效值写入 `resolved_config.json`。

缓存分层维护：

- baseline inference identity：音频/歌词/model/checkpoint/完整行为参数；
- diagnostic identity：baseline hash、detector/stable/realign 参数；
- evaluation identity：alignment hash、GT hash、metric schema；
- render identity：alignment/audio/video/font/profile。

行为语义变化时提升 schema version。只改 GT 不应重跑模型；只改字体不应重跑 alignment。

## 7. 一条龙执行

### Smoke

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/run_inline_realign_smoke.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v3_20260728
```

### Formal

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/run_inline_realign_formal.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v3_20260728
```

覆盖路径示例：

```bash
DEMO_ROOT=/home/hyan/Data/lyricalign/test \
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v3_custom \
  bash scripts/demo/run_inline_realign_formal.sh
```

同一命令可恢复。`--force` 才强制重算匹配分支。

## 8. 实时状态

pipeline 会把子阶段 stdout 实时回显并写日志。另一个终端运行：

```bash
python scripts/demo/watch_inline_realign_status.py \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v3_20260728
```

状态页显示：

- 当前 pipeline stage；
- 当前 item 和 branch；
- manifest / complete / failed 数；
- visualization 与 Demo render 进度；
- 输出目录大小；
- 当前阶段日志尾部。

## 9. 覆盖与清理

更新代码后直接覆盖源码目录即可。输出目录建议先执行：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh <OUT_ROOT> derived
```

它删除旧 summary、visual、render 和 experimental shadow，保留可按 request hash 复用的 baseline branches。

其他模式：

```bash
# 只删除不属于当前 manifest 的旧 item
bash scripts/demo/cleanup_inline_realign_overwrite.sh <OUT_ROOT> stale

# 完全重新开始
bash scripts/demo/cleanup_inline_realign_overwrite.sh <OUT_ROOT> all
```

若 Demo ID 从旧版无哈希变为新版带哈希，旧 item 不会混入结果，但可用 `stale` 回收空间。

## 10. 阶段顺序与输出

```text
01 manifest
→ 02 全部 alignment 与 shadow experiment
→ 03 全部静态可视化
→ 03 全部 Demo 多路视频
→ 04 total + grouped summary
→ 05 bounded evidence
```

核心文件：

```text
resolved_config.json
live_status.json
experiment_live_status.json
experiment_manifest.jsonl
experiment_summary.json
visualization_summary.json
demo_render_summary.json
followup_analysis_summary.json
followup_analysis_summary.md
inline_realign_evidence.tar.gz
items/<item_id>/...
```

## 11. 分组与证据控制

同时输出总指标和以下分组：

- dataset；
- profile；
- language；
- alignment unit mode；
- duration bucket；
- variant。

GT 报告 micro 与 item-macro。Demo 只提供结构、行为和主观对比，不伪装成精确 metric。

默认 evidence 上限 8 MiB，按 `full → anomaly → severe → minimal` 自动缩减。保留汇总、状态、有限 case、visual/render 索引和实验分支摘要；不收集音频、视频、模型权重、完整日志或全部 alignment。需要深度复查时再针对指定 item 单独收集大证据。
