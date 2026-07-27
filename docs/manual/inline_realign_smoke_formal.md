# Inline Realign Follow-up：Smoke / Formal 一条龙执行说明

## 1. 这轮实验回答什么

本入口不直接启用自动写回，而是先回答五个具体问题：

1. 旧版“找不到稳定段”是否主要来自异常区间定位错误；
2. 已知错误段两侧的连续稳定段，能否支持 local realign；
3. 稳定段能否帮助确定下一窗口从哪里重新输入歌词、当前窗口安全提交到哪里；
4. 增加未来歌词后，原有区域是否发生大片重排、堆积或坍缩；
5. raw 与 official 是否真的在窗口推进上产生不同决定，以及差异是否影响 GT 或 Demo 听感。

当前 local realign 仍是 **shadow-only**：会实际执行局部推理、比较 exact 与 `+2` 上下文、计算 GT/结构变化，但不会修改正式串行结果。

## 2. 相比上一版的关键修正

### 2.1 异常区间不再等于整窗提交范围

自动检测只把以下连续局部范围作为候选：

- 连续零时长；
- 连续同时间边界堆叠；
- 当前核心区末端、且本窗实际准备提交的字符大量堆积；
- 核心区有明显人声但歌词完全没有推进。

未来歌词在右侧输入上下文末端的自然堆积不再触发 realign。异常范围会从真实连续异常开始和结束，不再从整窗第一个字开始，因此不会机械地产生 `no_left_stable_segment`。

### 2.2 GT 错误段主动测试 local realign

M4Singer 和 MIR-1K 有 GT。除自动候选外，程序会主动选择边界误差明显的连续区域作为 `gt_oracle` 候选，并实际运行 local realign。

两类结果必须分开解释：

- 自动候选：回答检测器是否能找到可修问题；
- GT oracle：回答即使检测器暂时不完善，稳定段约束下 local realign 本身有没有修复能力。

Oracle 改善不能报告成自动生产效果。

### 2.3 稳定段真正参与窗口分配实验

程序不再只统计“稳定段准确率”，还会针对相邻窗口计算：

- 基线下一窗歌词起点；
- 基于下一窗左侧可听范围内稳定子段建议的歌词起点；
- 基线提交终点；
- 基于当前窗核心区内最后稳定子段建议的安全提交终点；
- 在有 GT 时，两种决定距离 GT 理想位置各差多少字。

若稳定段建议与基线不同，程序会按建议起点实际重新运行下一窗口，检查稳定前缀是否复现以及重跑结果的 GT/结构表现。

稳定段只使用下一窗左侧音频实际可听到的局部连续子段，不会因为某个稳定段很长就从很早的歌词位置重新输入大量旧歌词。

### 2.4 强制未来歌词扩展对照

不再等待自然运行偶然触发扩展。每个选中窗口主动运行：

- 基础候选歌词；
- 未来歌词增加到约 125%；
- 未来歌词增加到约 150%。

只保留有限探针行，比较原有区域最大/中位边界移动、零时长和 GT，不保存三份完整逐字重复结果。

### 2.5 构造 fail-closed 未完成结果

清单会选择一个 Demo 和一个 GT 样本，构造明确标注的 incomplete 输出：

- 仅保留异常前已完成前缀；
- 记录首个未解决字符、剩余字数和触发原因；
- 不把剩余歌词强行塞入尾窗；
- `constructed_for_validation` 明确说明这是失败保护演练，不是自动判断该歌曲必然未完成。

## 3. 数据集和默认规模

### Smoke

| 数据 | 默认上限 | 用途 |
|---|---:|---|
| Demo | 2 | 真实全曲、听感、尾部和传播 |
| MIR-1K development | 3 | 自然长音频 GT |
| M4Singer native | 4 | 干净短片段 GT、稳定段与 local oracle |
| M4Singer synthetic-long | 2 | 多窗口和人工接缝压力 |

Smoke 中除 M4Singer native 外，长音频样本运行 B0–B3 基线矩阵。

### Formal

| 数据 | 默认上限 | B0–B3 矩阵上限 |
|---|---:|---:|
| Demo | 12 | 4 |
| MIR-1K 全部非 held-out 角色 | 最多 16（当前通常 13） | 8 |
| M4Singer native | 24 | 0，只运行主分支 B2 |
| M4Singer synthetic-long | 12 | 4 |

Formal 默认不使用 MIR-1K held-out。只有规则和阈值冻结后才显式追加：

```bash
--include-heldout
```

M4Singer native 使用跨歌曲均匀选择，避免大量样本都来自同一首歌。Synthetic-long 只使用同歌材料，但人工接缝必须单独报告。

可通过参数进一步扩大或缩小：

```bash
--demo-cap 16 \
--mir1k-cap 17 \
--m4-native-cap 40 \
--m4-long-cap 16
```

扩大数据量时，优先增加歌曲数量和不同错误类型，而不是重复增加同一歌曲的相邻短片段。

## 4. Demo 输入发现

默认递归搜索 Demo，并识别以下已有准备目录：

```text
_qwen_fa_decoder_realign
_qwen_fa_raw_guarded
_qwen_fa
```

每个 Demo 需要能够配对：

- 歌词文本；
- 原始媒体或音频；
- 已准备的人声 `work/audio/vocals.wav`。

Smoke/Formal 默认传入 `--require-demo`。没有找到 Demo 时会直接失败，而不是悄悄生成一个不包含 Demo 的 formal 结果。


## 4.1 MIR-1K 元数据行自动物化

历史 `mir1k_subset_v1` 为了冻结 held-out 和节省空间，只物化了 development、held-out 以及后来显式提升的 quick-v2-extra；`spare` 行只存在于 `selection.jsonl`，默认没有：

```text
items/<item_id>/lyrics.txt
items/<item_id>/ground_truth.characters.jsonl
items/<item_id>/audio/official_vocal.wav
items/<item_id>/audio/mix.wav
```

Formal 为扩大设计数据会读取所有非 held-out 角色：

```text
development,quick_v2_extra,spare
```

清单构建阶段现在会先审计所选 MIR-1K 样本。若发现 metadata-only 行，会读取：

```text
<subset_root>/selection.json
  source_characters
  mir1k_root
  units_per_line
```

然后自动补齐缺失歌词、字符 GT、official vocal、mix 和 accompaniment，再写实验 manifest。修复记录保存在：

```text
input_audit.json -> mir1k_asset_repair
```

字段包括修复前后缺失数量、被物化的 item_id 和原始数据路径。若源字符标注或原始 MIR-1K 路径已经移动，程序会在模型加载前给出明确路径错误，不会再到样本推理阶段才报 `lyrics.txt` 缺失。

需要只审计而禁止自动写入子集目录时，可运行：

```bash
bash scripts/demo/run_inline_realign_formal.sh --no-materialize-missing-mir1k
```

正常恢复本次失败只需重新执行原 formal 命令。已有成功分支按 request hash 复用；manifest 阶段会先补齐 spare 数据。

## 5. 一条龙运行

### Smoke

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/run_inline_realign_smoke.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v2_20260728
```

### Formal

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/run_inline_realign_formal.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v2_20260728
```

环境路径位于：

```text
scripts/demo/inline_realign_env.sh
```

常用覆盖：

```bash
DEMO_ROOT=/home/hyan/LyricAlignment \
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v2_custom \
  bash scripts/demo/run_inline_realign_formal.sh
```

## 6. 强制执行顺序：全部 align 后统一 render

流水线顺序固定为：

```text
01_manifest
→ 02_experiment：所有 Demo/MIR-1K/M4Singer 全部完成 align 和补充推理
→ 03_render_demo_after_all_alignments：只渲染 Demo
→ 04_summarize
→ 05_collect
```

`03_render_demo_after_all_alignments` 只有在 `experiment_summary.json` 已存在后才启动。因此不会出现每完成一首 Demo 就立刻渲染、GPU/CPU 反复切换的情况。

### Demo 文件夹不重复

每个 Demo 只使用一套实验目录：

```text
items/<demo_item_id>/
├── branches/B2_30_silence_official/alignment.json
├── incomplete_guard/alignment.json          # 仅构造/触发时存在
└── render/official.mp4
```

不会再次创建 `<歌名>_qwen_fa_*` 输出树，也不会复制一个同体积根目录别名视频。

默认只渲染 official B2：

- review：24 fps、CRF 28、AAC 96 kbps；
- final：30 fps、CRF 20、AAC 192 kbps。

阶段性成品使用：

```bash
bash scripts/demo/run_inline_realign_formal.sh --render-profile final
```

构造的 incomplete 默认不渲染；需要检查失败保护画面时显式加：

```bash
--render-incomplete
```

## 7. 输出结构

```text
pipeline_request.json
pipeline_status.jsonl
pipeline_complete.json / pipeline_failure.json
input_audit.json
experiment_manifest.jsonl
experiment_summary.json
followup_analysis_summary.json
followup_analysis_summary.md
demo_render_summary.json
inline_realign_evidence.tar.gz
items/<item_id>/
├── item_summary.json
├── failure.json                            # 仅失败时
├── branches/<B0-B3>/alignment.json
├── inline_realign_shadow.json
├── stable_window_assistance.json
├── stable_window_assistance_trials.json
├── forced_expansion_trials.json
├── incomplete_guard/alignment.json
└── render/official.mp4                     # 仅 Demo
```

## 8. 机器可读总表

`followup_analysis_summary.json` 汇总：

- 自动候选与 GT oracle 候选分别多少；
- 有多少候选真正执行 local inference；
- exact 与 `+2` 上下文一致多少；
- GT 改善和 shadow would-write 多少；
- 稳定段建议在多少窗口改变了输入 cursor；
- 与 GT 理想 cursor 相比，建议改善、持平、恶化多少；
- 主动重跑是否复现稳定前缀；
- +25%/+50% 文本扩展最大移动分布；
- raw/official planner 真正分歧的窗口；
- B2/B3 在分歧样本上的逐字时间、归属和 GT 差异；
- incomplete 输出数量和剩余歌词规模；
- Demo 渲染完成/失败数量。

`followup_analysis_summary.md` 是同一结果的便于阅读版本。

## 9. 证据大小控制

默认上限 8 MiB。超限时依次缩减：

```text
full → anomaly only → severe only
```

保留：

- 汇总和状态；
- 自动/GT oracle realign 决策；
- 稳定段辅助分窗和主动重跑；
- 强制扩展的有限探针；
- planner 真正分歧窗口；
- incomplete 摘要；
- 异常附近有限逐字记录。

不包含：

- 音频、视频和 ASS；
- 模型权重；
- 完整 stdout；
- 所有扩展推理的全量重复逐字输出；
- 正常区域的无限量逐字数据。

## 10. 中断恢复和失败处理

- 基线、shadow、稳定段辅助、主动重跑和扩展实验都有 request hash；相同输入与参数可复用。
- 重新执行同一命令即可恢复。
- `--force` 才会强制重算。
- 单个 item 失败时保存 `failure.json` 并继续其他 item。
- 只要 `experiment_summary.json` 已生成，后续 render、summary 和 bounded collection 仍会执行；最终状态为 `partial_failure` 并返回非零码。
- incomplete 输出是显式失败保护，不等于运行异常。

## 11. 判读顺序

1. `input_audit.json`：确认 Demo、MIR-1K、M4Singer 数量和角色；
2. `pipeline_complete.json`：确认阶段是否完整或 partial；
3. `followup_analysis_summary.md`：看总体结论；
4. GT oracle：local realign 本身是否有修复上限；
5. 自动候选：定位修正后检测器是否能找到同类问题；
6. 稳定段辅助 cursor：是否比基线更接近 GT，以及主动重跑是否稳定；
7. 强制文本扩展：是否出现大范围移动；
8. planner divergence：只有真正分歧的 B2/B3 才有解释价值；
9. Demo `render/official.mp4`：最后进行听感检查。

不能混淆：

- GT oracle 与自动生产能力；
- Demo 听感与 GT 准确率；
- M4Singer synthetic-long 与自然 MIR-1K；
- 结构异常减少与时间准确率提高；
- 构造 incomplete 与自动检测 incomplete。
