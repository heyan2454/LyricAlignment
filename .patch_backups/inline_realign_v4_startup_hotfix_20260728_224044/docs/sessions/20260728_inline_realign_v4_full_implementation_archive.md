# 2026-07-28 Inline Realign v4 全机制实现与讨论归档

## 0. 文档角色

本文记录本轮从 formal v3 数据审查、问题发现、用户讨论、路线取舍到 v4 代码实现的完整过程。它不是只列最终结果的变更日志，而是保留：

- 原始问题与观察；
- 数据证据；
- 被否定、采用和仍待实验的方案；
- 实验目的、假设、替代解释和预期结果；
- 实现映射；
- 运行、恢复、渲染和证据收集协议；
- 当前尚未由服务器 GPU smoke 验证的边界。

当前执行手册见：

```text
docs/manual/inline_realign_smoke_formal.md
```

完整实验设计见：

```text
docs/experiments/20260728_inline_realign_full_mechanism_design.md
```

## 1. 起点：formal v3 数据审查

本轮首先审查了 formal v3 compact evidence。该次运行包含 98 个 item：

- Demo 35；
- MIR-1K 13；
- M4Singer native 32；
- M4Singer synthetic-long 18。

运行本身完整，98/98 item 成功，Demo 视频也均记录为生成。但数据揭示了几个路线级问题。

### 1.1 窗口 baseline

B0/B1/B2 在 MIR-1K 和 synthetic-long 上的 GT 差异很小。B2 silence-aware 未显示出强 MAE 优势，但在较长 synthetic 序列上的窗口规划更稳定，因此只能暂定为“不劣的 reference”，不能宣称已经证明优于固定窗。

### 1.2 Demo 的结构失败

Demo 中出现大范围零时长，日文最严重，部分高语速、英文和粤语歌曲也有明显坍塌。不同窗口策略会让相同歌词进入完全不同的时间路径，最大移动可达几十秒甚至上百秒。这说明主要问题不是普通几十毫秒误差，而是离散路径选择、窗口传播和文本上下文干扰。

### 1.3 Automatic detector 评测无效

自动候选集中在无 GT Demo；GT error case 集中在有 GT 数据。两者没有共同评测人口，因此 precision/recall 为 0 并不代表 detector 真正失败，而是“不可评估”。用户进一步判断 GT 大体可靠，自动 detector 当前科研价值有限，因此将其降级为 Demo 导航和候选生成工具。

### 1.4 Local realign 有恢复能力但 gate 召回低

GT-oracle 的局部 realign 在可评测 case 中多数改善，说明短区间重新对齐有实际恢复能力。然而旧非 GT gate 只接受极少 case。进一步分析发现，旧结构分数要求严格下降；若原结果只是整体时间偏移但仍单调、无负时长、无重叠，结构分数本来就是 0，即使 GT 显著改善也无法继续下降。

### 1.5 Stable cursor 的旧实现定义错误

旧 stable trial 将歌词起点跳到 stable 附近，但音频仍从原窗口更早的位置开始。例如音频从 20 秒开始，而歌词从 27 秒对应字符开始，导致 20–27 秒音频没有对应文本。固定回退 8 字也不能保证在不同语言、语速下与音频对应。

因此 formal v3 中 S1–S3 的负结果不能用来否定 stable 思想，只能否定“音频与歌词不同步裁剪”的错误实现。

### 1.6 Future-text expansion 的强负面信号

给输入增加 1.25×/1.5× 的未来歌词会造成长尾时间扰动，P90 接近 4 秒，最大可达近 60 秒，而且扩张量与偏移不单调。这支持新的研究方向：减少冗余未来歌词，测试少量多次、逐步提交，而不是默认“更多文本上下文更安全”。

### 1.7 Raw 值得重新审视

同一 official-controlled 窗口中，raw argmax 在 GT 上略优于 final official，零时长也更少。但 raw 的 start/end 槽独立 argmax，机制上允许负时长、回退和重叠；同时 B3 raw-controlled serial 与“official cursor 下观察 raw 时间”不是同一问题。因此需要逐阶段消融，而不能直接把 raw 设为生产 decoder。

## 2. 用户观察与讨论形成的修订

### 2.1 渲染不应阻塞实验推进

推理时间可接受，真正慢的是视频渲染。用户要求 Demo 和数据集可大量运行，但渲染必须后置或独立执行。由此形成双完成状态：

```text
analysis_complete.json
render_complete.json
```

模型推理、指标、静态诊断和适量 evidence 完成后即可进入分析；视频可以随后独立补齐和 resume。

### 2.2 渲染必须直接表现机制

旧视频主要显示最终字幕，存在：

- 英文标签过多；
- 模型行为挡住说明；
- timeline 没有字符；
- raw/official 文本被省略或互相遮挡；
- stable 候选数量和选中过程不清楚；
- realign 的 exact/+2/+4、gate 和写回区间没有表现；
- 不同窗口方案没有显示自己的实际窗口边界。

用户要求模型行为位于视觉中心，字幕压缩到底部，时间轴固定比例，指针匀速移动，并通过图片化字符轨迹表现 raw、official、stable 和 realign。

### 2.3 时长分布必须使用完整离散 PMF

时长本质上按模型输出形成离散样本。把正时长条件分布单独归一化会丢失零时长在全部单位中的占比。最终采用同一分母的完整 PMF：

```text
<0, =0, (0,20], (20,40], (40,80], (80,120],
(120,200], (200,400], (400,800], >800 ms
```

其中 raw 的负时长和所有阶段的零时长必须是真实柱子，不再只在图注中显示。累计分布不再作为主图。

### 2.4 Inconsistency 改为三层可读结构

用户提出利用整体基本单调的性质，使用歌词序号—起止时间二维折线。最终设计为三子图：

1. 歌词序号与 onset/offset 折线；
2. 每字跨窗或跨阶段最大差；
3. 窗口/阶段 × 歌词序号热力图。

### 2.5 静音策略

旧 silence-aware 只是把窗口边界吸附到静音中，模型输入仍可能跨越静音。用户希望至少实现：

- 严格静音边界：强静音两侧成为不同 active region，模型输入不能跨越；
- 全静音压缩：作为诊断对照，删除长静音内部并映射回原时间轴。

同时公平比较 core 30/60 秒。

### 2.6 Gate 修订

旧 gate 要求结构异常分数严格下降。用户指出只要不恶化即可。最终保留两种口径：

- `strict_decrease_gate`：历史严格控制；
- `structure_nonincrease_consensus`：实际 shadow 接受主规则。

对原区间含零时长的 case，增加专用宽松 gate：只要零时长减少、不新增负时长/回退/重叠、anchor 保持且结构分数不升，即使三条完整路径不一致，也可选择最安全候选进行 shadow 接受。

### 2.7 `would_write` 拆分

旧字段把 GT-oracle 改善和自动 gate 接受混在一起，容易被误解为系统自动修复成功。最终拆为：

```text
gt_oracle_improved_shadow
automatic_gate_accepted_shadow
manual_gate_accepted_shadow
deferred_gate_accepted_shadow
actual_writeback
```

本版本 `actual_writeback` 仍必须为 0。

### 2.8 Stable 必须同步裁剪

用户明确要求，无论从 stable 开始，还是向前 2/4 个单位开始，音频和歌词都必须对应。由此废弃固定回退 8 字和异步输入，改为：

- anchor-only：使用原窗口音频和歌词范围重新运行，仅冻结稳定区；
- sync exact：音频与歌词均从 stable 起点开始；
- sync −2；
- sync −4。

裁剪边界来自 baseline 中相同歌词单位的时间范围，因此至少在实验定义上保持一一对应。

## 3. 当前决策表

### 3.1 已否定

| 方案 | 否定原因 |
|---|---|
| 旧 S1–S3 音频/歌词异步 stable cursor | 输入不对应，实验定义不成立 |
| 固定回退 8 字 | 无法适配语速和语言 |
| 结构异常必须下降作为唯一 gate | 召回过低，无法接受结构不变但时间更好的结果 |
| 正时长条件分布 | 丢失零时长总体比例 |
| 所有模型混在一张 duration/inconsistency 图 | 无法回答具体机制问题 |
| `would_write` 单字段 | 混淆 oracle 与自动决策 |
| 自动 detector 作为当前主研究指标 | formal v3 没有共同 GT 评测人口，且 GT 大体可靠 |
| 渲染失败使全部分析不可用 | 渲染是慢后处理，不应否定已完成实验 |

### 3.2 已采用

| 方向 | 当前用途 |
|---|---|
| B2 30 秒静音吸附 | reference，而非已证明最优 |
| 30/60 × 固定/吸附/严格静音 | 主窗口矩阵 |
| 全静音压缩 | 机制诊断对照 |
| Stable 同步裁剪 exact/−2/−4 | 新 stable 实验 |
| 结构分数不升 | 非 GT 主 shadow gate |
| 零时长宽松 gate | 解决大量零时长未纠正问题 |
| exact/+2/+4 + 中位融合 | 显式研究文本上下文敏感性 |
| 少给/正确给/多给歌词 | 文本剂量实验 |
| raw→processor→selected→final | decoder 分阶段消融 |
| 分析完成与渲染完成分离 | 正式执行协议 |
| run/stage/item/visual/render strict resume | 中断恢复协议 |

### 3.3 仍待实验

- 30 秒和 60 秒 core 的真实优劣；
- 严格静音边界是否降低静音前后波动；
- 全静音压缩是否暴露绝对时间或连续性依赖；
- 减少冗余未来歌词是否显著稳定路径；
- 少给到实际演唱歌词时模型是尾部膨胀、漏字还是错误扩展；
- stable 应主要作为同步裁剪边界还是冻结锚点；
- 零时长宽松 gate 的 GT 改善率与误改率；
- 三上下文中位融合是否优于选单一路径；
- deferred 在正确输入和新 gate 下是否仍低效；
- raw 最小修复能否优于 current official；
- 是否值得进一步读取 language model 倒数层 timestamp hidden state。

## 4. 后续实验设计

## E1：Core × 静音策略

### 目的

区分 core 长度和静音处理对窗口传播、静音边界附近误差及计算成本的影响。

### 条件

```text
B0 60s fixed
B1 30s fixed
B2 30s silence snap
B4 60s silence snap
B5 30s strict silence
B6 60s strict silence
C0 30s silence compression diagnostic
C1 60s silence compression diagnostic
```

### 预期

- 若严格静音边界有效，静音前最后字、静音后第一字和跨静音 cursor 跳变应减少；
- 若模型依赖连续静音上下文，严格切断可能损害普通区域；
- 若全静音压缩明显改善但严格边界不改善，可能说明模型对长绝对位置或静音时长敏感；
- 若压缩在拼接点恶化，则说明人工声学边界不可忽略。

### 指标

主指标使用 canonical v3 tolerant；另报告零/负时长、重叠、回退、窗口数、推理时间，以及静音边界 ±2 秒专用指标。

## E2：歌词输入剂量

### 目的

直接测量少给、恰好给足、多给歌词和起始 cursor 偏移对路径选择的影响。

### 条件

文本终点相对理想范围：

```text
-8,-4,-2,0,+2,+4,+8,+16
1.25x,1.5x
```

文本起点：

```text
-4,-2,0,+2,+4
```

### 预期

可能存在一个很小的安全未来上下文范围，例如仅多给 2–4 个单位；超过后路径分叉显著增加。若少给到窗口中真实唱到的歌词，预计可能出现尾部字膨胀、堆积、漏词或错误 cursor。

## E3：Stable 同步裁剪

### 目的

重新验证 stable 思想，而不是复用 formal v3 的错误输入定义。

### 条件

```text
S0 原窗口范围重跑，仅冻结 stable
S1 sync exact
S2 sync minus2
S3 sync minus4
```

### 预期

- S0 若有效，说明 stable 更适合作为冻结约束；
- S1 若缺少声学前缀，可能不如 S2/S3；
- S2/S3 若优于 S0，说明同步裁剪可降低前窗错误传播；
- 若全部恶化，则需检查 baseline 时间是否足以用作裁剪边界，而不能立即否定稳定锚点概念。

## E4：Realign gate 与 deferred

### 目的

提高零时长修复召回，同时保持 clean control 安全。

### Gate

```text
strict decrease control
structure nonincrease consensus
zero-duration relaxed selection
context median fusion
```

### Deferred

等待 1–3 个未来窗口恢复右 anchor，再执行同一 realign/gate。Deferred 只解决右 anchor 尚未出现，不自动解决三上下文持续分歧。

### 预期

- structure-nonincrease 应提高召回；
- zero-duration relaxed 可能进一步修复 Demo，但存在“只是把错误摊开”的风险；
- 中位融合可能减少单一上下文路径跳转，也可能生成没有任何一次模型实际输出的折中结果；
- clean control 和 GT-oracle 必须同时报告，避免只看修复数量。

## E5：Raw 与 decoder 分阶段

### 目的

定位负时长、零时长和大边界移动首次在哪一步引入。

### 阶段

```text
D0 raw argmax
D1 processor decoded
D2 window selected
D4 final committed
D5 raw nonnegative only
D6 raw minimal monotonic
```

### 预期

若 D0 GT 较好但非法结构多，而 D5/D6 保留其 GT 优势并解决大部分非法结构，则可能形成比 current official 更轻的 decoder。B3 raw-controlled serial 单独解释，不与同一 official cursor 下的 D0 混淆。

## 4.6 实现审查过程中发现并修复的阻断问题

本轮并非只按设计增加功能。代码落地后继续进行了配置、执行、状态和产物闭环审查，发现多项若不修复会让 smoke 看似启动、formal 却产生错误或不可恢复的实现问题。

1. **静音压缩分支命名不一致**：代码最初使用 `_official`，而 YAML、可视化和入口使用 `_diagnostic`。这会在运行前将合法配置判为未知 variant。已统一为 `C0/C1_*_diagnostic`，并增加配置—实现一致性测试。
2. **严格静音窗口缺少 active-span 口径**：严格窗口计划最初只保存 active regions，没有 `active_span_duration_sec`，串行文本预算会在 B5/B6 真正推理时触发 `KeyError`。现按 active region 总时长写入统一字段。
3. **部分失败被错误视为可恢复完成**：允许返回码 1 的 stage 曾被记录成 `complete`，下次 `--resume` 可能跳过仍有失败 item 的阶段。现明确写为 `partial_failure`，只有返回码 0 且预期产物完整才可整体跳过。
4. **Item 化阶段可能被全局 summary 掩盖**：experiment、visualization、render 的 summary 文件存在时，旧状态机可能不再进入 controller，无法重新校验每个 item。现这些阶段在 resume 时仍进入 controller，由 item state 和输出快照决定逐项跳过或重试。
5. **S0 控制组最初是无效复制**：最初 S0 只是复制 baseline，没有执行“原窗口范围重跑+仅冻结 stable”，无法作为同步裁剪的对照。现 S0 使用原音频/歌词范围执行 matched rerun，再冻结稳定区。
6. **可视化身份被运行参数污染**：`resume/from-stage/render-mode` 等操作参数若进入可视化 identity，会导致相同实验仅因启动方式不同而重画。现 identity 只包含语义配置和实际上游 JSON/JSONL。
7. **清理脚本遗漏 item 内视频**：旧清理只删除顶层 render 状态，可能保留 `items/*/renders` 并让新运行误认为视频存在。现 visual/render cleanup 同时删除对应 item 产物和状态。
8. **主指标聚合可能重新排除漏字**：切换到 tolerant metric 后，旧 summary 仍按 matched unit 加权，可能让漏字模型虚假变好。现按全部 GT reference unit 聚合，matched-only 仅保留为辅助诊断。

这些问题说明本轮的“正确实现”不仅是添加实验分支，也包括把配置、请求身份、逐 item 状态、预期产物和指标分母统一起来。

## 5. 代码实现映射

### 5.1 窗口与静音

```text
src/lyricalign/demo/window_planning.py
scripts/demo/align_qwen_fa_serial_demo.py
```

实现 strict silence active regions 和 reversible silence compression mapping。

### 5.2 主实验

```text
scripts/demo/run_inline_realign_experiment.py
```

包含窗口矩阵、stable 同步裁剪、文本剂量、immediate/deferred realign、gate 变体、median fusion、raw 最小修复和 item 级 resume。

### 5.3 主指标与汇总

```text
scripts/demo/summarize_inline_realign_followup.py
```

主指标统一为 `character_interval_metrics_v3_tolerant`，总表按全部 GT reference 字符聚合，避免漏字后虚假变好。Decoder 汇总使用 resolved primary variant，不硬编码 B2。

### 5.4 可视化

```text
src/lyricalign/demo/visual_diagnostics.py
scripts/demo/analyze_inline_realign_visuals.py
```

实现字符彩虹、负/零时长、lane packing、每方案自身窗口、三子图 inconsistency、stable 全候选与 realign 执行页。静态图具有 item 级 request identity 和输出快照，可独立 resume。

### 5.5 视频

```text
src/lyricalign/demo/timeline_video.py
scripts/demo/render_inline_realign_demo_batch.py
```

视频复用静态 PNG 页，只添加固定比例时间指针、音频和底部字幕。每个 Demo 独立恢复；校验 MP4 stat 和小型 request identity sidecar，不在每次 resume 时重新哈希整批大视频。

每个 Demo 预期 5 个视频：

```text
behavior_current.mp4
comparison_window_mechanism.mp4
comparison_realign_mechanism.mp4
comparison_realign_execution.mp4
comparison_decoder_stages.mp4
```

### 5.6 Resume

```text
src/lyricalign/demo/run_state.py
scripts/demo/run_inline_realign_pipeline.py
```

Run identity 包含 config、输入、model/checkpoint 和关键实现文件 hash。Stage/item 输出使用 SHA-256 快照；修改或缺失后不会错误跳过。Visualization 和 render 另有 item state。

### 5.7 一条龙与监控

```text
scripts/demo/run_inline_realign_smoke.sh
scripts/demo/run_inline_realign_formal.sh
scripts/demo/run_inline_realign_render_only.sh
scripts/demo/watch_inline_realign_status.py
scripts/demo/cleanup_inline_realign_overwrite.sh
scripts/demo/verify_inline_realign_v4.sh
```

## 6. 数据规模和角色

用户明确允许大量使用 Demo 与数据集，因为主要耗时在渲染而非推理。因此 formal 配置不再追求极小样本：

- 全部运行时发现且 prepared 的多语言 Demo；
- MIR-1K development/quick-extra/spare，cap 17；
- M4Singer validation native cap 32；
- synthetic-long cap 18，覆盖 60/120/180 秒；
- 所有长序列窗口矩阵；
- local mechanism trials 按每 item 有界抽样，避免组合爆炸。

Smoke 也不是只跑一个 item，而是每语言代表 Demo 加 MIR-1K/M4Singer 多类数据，并执行完整机制链。

## 7. 渲染与证据协议

### 7.1 推荐执行

先完成全部分析：

```bash
RENDER_MODE=skip bash scripts/demo/run_inline_realign_formal.sh
```

出现 `analysis_complete.json` 后即可分析 JSON、静态图和 compact evidence。之后：

```bash
bash scripts/demo/run_inline_realign_render_only.sh formal OUT_ROOT
```

视频可以在独立终端后置运行；若资源允许，也可在确认静态页面完整后单独启动，但不能对同一 item 同时启动两个 render writer。

### 7.2 Evidence

默认 evidence 只收集适量 JSON/JSONL/Markdown 和视觉索引，不收集音频、视频、模型权重和完整大 alignment。后续需要大量底层数据时，另行使用专门 collector，不让日常交接包无限膨胀。

## 8. 覆盖与删除规则

源代码包可以直接解压覆盖 `/home/hyan/LyricAlignment`，本轮不要求删除原源码文件。

旧 v3 输出与 v4 的实验定义、配置和指标 schema 不兼容，不能 resume 到同一目录。推荐使用新的 v4 默认输出目录。必须复用旧目录时：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OLD_OUT_ROOT all
```

普通中断恢复禁止 cleanup：

```bash
OUT_ROOT=... RESUME=1 bash scripts/demo/run_inline_realign_formal.sh
```

只删除视频：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT render
```

只重画静态图并重渲染：

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OUT_ROOT visual
```

## 9. 验证与当前未知

本归档完成了 compile、shell syntax 和 focused unit/regression tests。验证环境没有用户服务器上的 Qwen 模型、音频数据和 Noto CJK 系统字体，因此没有在本地执行真实 GPU smoke 或完整 FFmpeg 多歌渲染。

服务器必须先运行：

```bash
bash scripts/demo/verify_inline_realign_v4.sh
```

它会严格确认 `Noto Sans CJK SC`，包括 fontconfig family、TTC face index 和 Matplotlib 注册，绝不接受 JP 替代。

当前仍未知：

- 真实 strict-silence 窗口在服务器数据上的数量和质量；
- stable 同步裁剪是否实际改善；
- zero-duration relaxed 的误改率；
- C0/C1 静音压缩对 Qwen 的实际影响；
- 新渲染在极端长歌词页面中的可读性；
- formal 的总运行时和磁盘占用。

这些必须由 smoke/formal 结果回答，不能从实现本身推断。

## 10. AI 协作与依赖状态

本轮 AI 协作主要承担：

- 从 formal v3 evidence 中分离执行完整性、指标口径和算法有效性；
- 根据用户视觉观察修订实验定义；
- 将 stable、silence、gate、raw 和文本剂量转化为可执行消融；
- 实现严格 resume 和后置渲染；
- 统一文档、配置、代码和监控口径。

关键用户判断包括：

- 推理可大量运行，渲染才是主要耗时；
- stable 音频和文本必须对应；
- 结构异常不升即可，不要求严格下降；
- duration 必须让负、零、正值共享同一总体分母；
- 自动 detector 当前不应占据主线；
- 在可视化能解释机制前，不宜盲目继续扩大观察。

依赖状态：

- 真实 GPU/Qwen 数据依赖用户服务器；
- CJK SC 字体依赖服务器已有 `/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc`，代码不携带字体；
- Japanese parsing 仍依赖实际环境中的相关包；
- 最终科研结论依赖新 formal 结果和人工 Demo 观察。
