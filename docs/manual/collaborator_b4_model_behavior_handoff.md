# 合作者接入 B4 60 秒静音吸附模型行为：Agent 执行交接

## 1. 本文用途

本文交给维护 `Volta233/AutoASSrenderer4karaOK` 的 agent 使用。目标是在暂时接受代码耦合的前提下，
让现有 GUI 尽快使用本项目已经完成真实 formal 的模型行为，避免 agent 从通用 batch 默认值、后续研究分支
或文件名猜测实现。

本次不是训练新模型，也不是采用 research-v6/v7 的实验性系统。目标行为固定为：

```text
behavior_id: b4_60_silence_official_shadow_v1

Qwen Forced Aligner 指定 revision
+ R2 step-000750
+ separated vocal
+ B4：目标 60 秒、静音吸附 window plan
+ official timestamp decoder
+ official/same serial ownership and cursor
+ per-item 多语言歌词单元
+ local realign shadow-only
+ actual_writeback = 0
```

“local realign shadow-only”只生成诊断和反事实候选，不改变最终字幕。最终 ASS/视频必须继续读取
`B4_60_silence_official` primary alignment。

## 2. 先确认一个容易误判的事实

合作者仓库当前线上历史已经包含目标实现：

- 目标变化对应提交：`0559b3c38dae53ccac05f775b4733cb36fafc851`，提交标题 `demodiag5_60s`；
- 运行证据目录名使用日期 `inline_realign_formal_v5_60main_20260729`；
- 提交日期和运行目录日期不同，不要因此寻找另一个“0729 模型”；
- 提交链接：<https://github.com/Volta233/AutoASSrenderer4karaOK/commit/0559b3c38dae53ccac05f775b4733cb36fafc851>。

问题不是仓库缺少 B4 源码，而是 GUI 默认走的是另一条入口：

```text
src/lyricalign/gui/app.py
→ src/lyricalign/gui/command.py
→ scripts/demo/run_qwen_fa_batch.py
→ preset=default
→ r2:vocal:windowed
```

`windowed` 只表示调用串行分窗函数，不等于 B4。当前 batch 的 `_alignment_args()` 没有把
`silence_aware_window_plan=True`、`skip_silent_windows=True` 和 shadow 采集参数传给串行实现。
所以不能仅凭 GUI 显示 `R2 + vocal + windowed`，或 alignment identity 中出现
`silence_aware_global_core_plan_v7`，就认定实际运行了 B4。

## 3. 正确实现只能从这些位置读取

Agent 应按以下顺序阅读，不要从 README 的简称反推参数：

1. `scripts/demo/run_inline_realign_experiment.py`
   - `VARIANTS["B4_60_silence_official"]`：B4 名称和含义；
   - `serial_args(args, variant)`：完整串行参数，是接入 batch 时的参数真值；
   - `run_inline_shadow(...)`：local realign shadow 行为；
   - parser 的 `--primary-variant`：应默认为 `B4_60_silence_official`。
2. `scripts/demo/align_qwen_fa_serial_demo.py`
   - `windowed_alignment(...)`：真正执行 window plan、官方 decoder、ownership、cursor 和 commit；
   - `infer_slice(...)`：raw、official 和 top-K 证据的来源；
   - `build_vocal_activity_profile(...)`：静音/活动检测输入。
3. `src/lyricalign/demo/window_planning.py`
   - `build_silence_aware_window_plan(...)`：B4 使用的静音吸附计划；
   - 不要用 `build_strict_silence_boundary_window_plan(...)` 替代；
   - 不要用 silence-compressed C1 替代。
4. `src/lyricalign/demo/karaoke.py`
   - `parse_lyrics_text(...)` 和 `normalize_alignment_language(...)`：多语言歌词单元真值。
5. `scripts/demo/run_qwen_fa_batch.py`
   - 这是 GUI 现有调用入口，只负责接入上述行为，不是 B4 参数真值。

本项目对应 formal 的冻结配置见：

```text
/home/hyan/Data/lyricalign/demo_diagnostics/
  inline_realign_formal_v5_60main_20260729/resolved_config.json
```

## 4. 最小接线方案

暂时允许耦合时，不要求先实现 behavior registry。直接保留 GUI → batch 结构，在
`scripts/demo/run_qwen_fa_batch.py` 中完成以下修改即可。

### 4.1 给行为一个明确 ID

新增一个 CLI 参数，推荐形式：

```text
--behavior-profile b4_60_silence_official_shadow_v1
```

GUI 默认传这个 ID。保留旧行为 ID 仅用于显式回滚，例如：

```text
legacy_r2_vocal_fixed60_v1
```

禁止新行为失败后静默降级到 legacy；失败应保留结构化 failure artifact。

### 4.2 让 batch 的串行参数与 B4 完全一致

对于新 behavior，batch 构造的 serial args 至少必须包含：

```python
core_sec = 60.0
left_context_sec = 10.0
right_context_sec = 10.0

decoder_kind = "official"
serial_control_decoder_kind = "same"

capture_shadow_rows = True
capture_attempt_probes = True
attempt_probe_max_rows = 48

skip_silent_windows = True
silent_active_ratio_max = 0.01
silent_peak_margin_db = 3.0
silent_min_sustained_sec = 0.40
startup_vocal_preroll_sec = 2.0
startup_minimum_forward_characters = 24

silence_aware_window_plan = True
strict_silence_boundary_plan = False
compress_silence_audio = False

silence_boundary_min_sec = 0.8
strong_silence_anchor_sec = 1.5
silence_boundary_search_sec = 6.0
leading_silence_min_sec = 2.0
tail_min_core_sec = 18.0
minimum_core_sec = 12.0

stable_segment_min_units = 2
stable_segment_confidence_quantile = 0.50
stable_raw_official_tolerance_sec = 0.16
stable_context_tolerance_sec = 0.24
stable_prefix_reproduction_tolerance_sec = 0.24
stable_prefix_minimum_observed_units = 2
stable_prefix_minimum_observed_ratio = 0.50
```

以下已有参数继续采用 formal 值：

```python
timestamp_segment_sec = 0.08
decoder_top_k = 8
future_line_padding = 1
minimum_forward_characters = 64
future_character_ratio = 1.35
max_candidate_expansions = 4
boundary_start_tolerance_sec = 0.32
seam_tolerance_sec = 0.16
```

最安全的实现方式是直接复用 `run_inline_realign_experiment.serial_args()` 中的字段集合，或将这段
函数移动到双方都能 import 的现有核心模块。即使暂时复制，也必须增加一个回归测试逐字段比较 batch
和 experiment 生成的 B4 args，防止以后再次分叉。

### 4.3 接入 local realign shadow

Primary B4 完成后，使用同一次对齐保存的 `rows`、`trace`、attempt probes 和 stable segments 调用
现有 `run_inline_shadow(...)` 逻辑。

无人工 GT 的 GUI 歌曲只能运行 automatic shadow 候选；不得伪造 GT-oracle 结论。Shadow 输出应写入
独立文件，例如：

```text
alignments/r2/vocal/windowed/inline_realign_shadow.json
```

必须满足：

```text
primary alignment 先原子写入
shadow 成功或失败均不改 primary characters
每个 decision 都有 actual_writeback=false
shadow 汇总 actual_writeback_count=0
renderer 不读取 shadow candidate 作为字幕时间
```

为降低首次迁移风险，可以分两次提交：

1. 先让 GUI primary 真正变为 B4；
2. 验证稳定后再接 shadow artifact。

第二步不会改变成品时间戳，不能因为 shadow 尚未接入而继续把旧 fixed-window 输出标成 B4。

## 5. 多语言契约

语言必须是每个 job 的输入身份。单曲 GUI 可以继续由用户选择，批量任务不得用一个全局语言覆盖
不同语言歌曲。

当前歌词单元约定：

- Chinese / Cantonese：CJK 字符为单位，连续 Latin 文本保留为 word；
- English：word 单元；
- Japanese：Nagisa 分词后的词单元直接进入 forced-aligner prompt，不再次分词；
- language、alignment unit mode 和 normalized units 必须进入 request identity；
- 选择 Japanese 而环境没有 Nagisa 时应在模型推理前明确失败。

“多语言”和“静音吸附分窗”是两个独立维度。不要把选择不同语言理解为选择另一种 window planner。

## 6. 模型与 checkpoint 身份

目标 behavior 使用：

```text
Base revision:
c07281df297b9905d24a508279258cccf987a064

R2 checkpoint:
20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
```

已知关键文件 SHA-256：

```text
model.safetensors
00568245ceca5af1991d28562a75fe1ddc9bfeb041c27fda66947ea05c47fb86

projector.pt
92d88b9b975cc51079e7e4876f2822c50b057240e047762a50e21ff20a100f4b

adapter/adapter_model.safetensors
5605b6dcaa19d1b84f587518b4bda0f3722b12c14b216801d0f4607389bc439c

adapter/adapter_config.json
fbb489d9d84dce87e6b6d3b683d002a30ef0fb5ac53814339b344b2a990f3286
```

GUI 当前只提供目录路径，不能证明实际文件正确。Agent 应在启动或 preflight 中校验这些身份，并把
实际 SHA 写入 alignment request。路径不同没有问题，内容身份不同则不能称为同一 behavior。

## 7. 缓存必须失效

这是本次接入的强制项。

旧 batch 会在 request 中写入一个看似 silence-aware 的 `WINDOW_POLICY` 名称，但实际没有启用
`silence_aware_window_plan`。如果只补一个布尔参数而不改变 request identity，旧 fixed-window alignment
可能被错误复用。

因此必须同时执行：

1. 将 batch alignment schema 升一个版本；
2. 将 `behavior_id`、上述所有生效参数和模型内容 SHA 纳入 request hash；
3. request 中记录实际布尔值，而不是只记录一个 policy 字符串；
4. output 中记录生成的 `window_plan` 或其 SHA-256；
5. 第一次升级运行自动判旧 alignment 失效；人工测试时仍显式使用一次 `--force-align`。

禁止覆盖旧 alignment 后仍保留旧 request hash。

## 8. 不要误接入这些研究结果

本次不得把以下内容当作“更新行为”：

- `B6_60_strict_silence_official`：formal 中明显恶化；
- `C1_60_silence_compressed_diagnostic`：仅用于机制诊断；
- raw decoder 或 raw-controlled cursor：不是生产 primary；
- research-v6 weighted-isotonic / detector / E9：仍是研究结果，不是当前 GUI 默认；
- research-v7 long-slot / region assessor：研究错误歌词和区域判别，不是成品字幕替代入口；
- local realign candidate 直接写回：当前明确禁止。

如果 agent 想采用上述任一项，应另建 behavior ID 和独立 A/B，不得修改
`b4_60_silence_official_shadow_v1` 的含义。

## 9. 必须增加的测试

至少增加以下回归：

1. GUI 默认命令包含正确 `--behavior-profile`；
2. B4 batch args 与 experiment B4 args 逐字段一致；
3. `silence_aware_window_plan is True`；
4. `strict_silence_boundary_plan is False`；
5. `compress_silence_audio is False`；
6. decoder 和 serial control 均为 official/same；
7. 真实或合成活动 profile 会使窗口边界吸附，而不是固定在 60、120 秒；
8. Chinese/Cantonese/English/Japanese 的单位解析回归；
9. Japanese 缺 Nagisa 时 fail-fast；
10. 打开/关闭 shadow 时 primary characters canonical SHA 完全相同；
11. 所有 shadow decision 的 `actual_writeback` 都为 false；
12. 旧 batch cache 不会被 B4 behavior 复用；
13. renderer 仍只消费 primary alignment；
14. alignment/failure/progress artifact 在异常时保持可审计。

## 10. 真实迁移验收

使用完全相同的媒体、歌词、vocal stem、模型文件和语言设置，并行产生：

```text
legacy_r2_vocal_fixed60_v1
b4_60_silence_official_shadow_v1
```

输出到不同目录，不允许互相覆盖。至少覆盖中、粤、英、日各一首，并检查：

- 新输出 identity 中 behavior、model、checkpoint 和语言正确；
- `generated_window_plan` 确认实际使用静音吸附；
- primary 字符完整、索引连续、无负时长、无 start/end regression；
- shadow 写出或结构化说明为何没有候选；
- `actual_writeback_count == 0`；
- ASS/MP4 使用 primary B4；
- 旧版仍可通过显式 legacy behavior 回滚；
- 不存在新 behavior 失败后静默输出旧缓存的情况。

验收报告必须列出：Git HEAD、behavior ID、模型 SHA、checkpoint SHA、四语言结果路径、测试命令和
测试结果。只报告“GUI 成功生成视频”不算完成。

## 11. 给执行 agent 的最短任务描述

可以将下面这段直接作为任务开头：

```text
请让现有 GUI 真正运行 b4_60_silence_official_shadow_v1，而不是仅显示
R2 + vocal + windowed。目标源码已存在于提交 0559b3c。以
scripts/demo/run_inline_realign_experiment.py 的 VARIANTS、serial_args 和
run_inline_shadow 为行为真值，以 align_qwen_fa_serial_demo.py::windowed_alignment
为执行真值。先把 batch primary 接成 60s silence-snap + official/same，再接
shadow-only；禁止 actual writeback。升级 schema 和 request identity，强制旧缓存失效，
校验指定 Qwen revision 与 R2 step-000750 SHA，并完成中/粤/英/日 smoke。不要引入
strict-silence、silence-compressed、weighted-isotonic、E9 或 research-v7 行为。
```

