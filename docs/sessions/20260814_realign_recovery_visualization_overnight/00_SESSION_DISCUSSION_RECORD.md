# 会话记录：Unit Realign 结果复核 → Recovery 机制探索 → 可视化与挂机计划

日期：2026-08-14（本轮讨论起于 2026-08-13 深夜，跨至 08-14）

本文件忠实记录从用户要求 review `unit_realign_evidence_2m_20260813.tar.gz` 与 `LyricAlignment_202608132319_after_unit_realign_overnight_p1p13.zip` 开始，到本次要求形成下一轮 patch 为止的讨论过程。用户的意见、疑问和决定尽量保留原话；后续实验解释不反向伪装成用户原始观点。

---

## 1. 用户要求 review 当前工作目录和实验记录

用户原话：

> “review当前工作目录和实验记录，陈述实验结果”

审阅重点包括：P1–P13 实际完成状态、P1 四象限样本构成、unit-level realign 的 target/context 行为、oracle、perturbation、fixed-point、consensus、no-GT gate、Test Demo 与 provenance。

本次 review 得到的关键判断：

- 主 screening 的 P1 已按 S1/S2/S3/S4 各 25 个独立 region 构成，修复了上一轮样本不均衡问题；
- 后续 formal 的 strata 并未维持这一构成，因此不能把 formal 当作四象限正式验证；
- R-S sparse/fixed 对 fixed context 的保护非常强，但对真正 bad target 的 `>200ms -> <=200ms` strong recovery 在主 screening 中为 0；
- R-U 的 target accuracy 在 confirmation/heldout 的同口径 paired comparison 中优于 R-S，但 collateral safety 更差；
- oracle 也无法修回所有困难区，特别是 catastrophic bucket 0/15；
- fixed-point 与 multi-view consensus 证明的是自洽/稳定，不证明正确；
- evidence-only `p_bad` proxy 基本随机，不能替代真正的 raw/official/entropy/margin/hidden detector 信号；
- Test Demo 已实际运行 local R-U/R-S forward，但当前更多证明 production-like 路径能执行，不能证明无 GT correctness；
- context k=1 vs k=3 只有 request 构造，没有完成 forward/比较；
- 当前 artifact 中还有旧 R-B adapter/provenance 与旧 aggregate 口径，需要避免扩大解释。

---

## 2. 用户质疑：困难区“再来一次”是不是其实没有效果

用户原话：

> “看起来模型对于困难区再来一次也没有特别好的效果？还是有其他结论或者方法？”

讨论形成的判断：

- 目前证据确实不支持“发现困难区后，把几乎同一个问题再跑一次就能可靠修好”；
- 更准确的现象是：模型经常能把几秒级大错拉近到约 0.5–1s，但很少稳定进入 100/200ms 的精确 recovery；
- oracle、fixed-point、consensus 共同提示：模型可能落入一个**错误但稳定的吸引域/解释**；
- 因此后续重点不应只是增加相同 forward 次数，而要让下一次看到**本质不同的问题**。

提出并讨论的方向：

1. 改 audio observation：重新 crop、移动 audio-left、扩大/缩小局部音频、多尺度 window；
2. coarse recovery 与 fine alignment 分离：先找回大致区域，再重新构造小局部精对齐；
3. R-U 与 R-S 不再只竞争 winner，而考虑 `R-U proposal -> sparse/fixed refinement`；
4. 对 catastrophic case 可能需要把任务改为 coarse localization / retrieval，再交 forced aligner 精对齐。

---

## 3. 用户新增三条探索，并要求挂机期间可以一直推进

用户原话：

> “我觉得还可以看看多次realign能否纠回、将难段分成更细粒度分开、或者合并引入其他线索能否实现。另外我要挂机了，有什么可以一直跑的东西，不限于当前路线。”

用户明确希望新增：

- **多次 realign**：验证是否存在逐次纠回，而不是一次失败就结束；
- **难段细粒度拆分**：把较大的困难 region 拆成更小 unit/子段；
- **融合其他线索**：不仅重复同一个 request，而是改变 observation、加入 anchor/context/多视角/真实 detector 信号；
- **挂机持续探索**：主计划完成后不能自动停机，允许扩展到当前 realign 路线之外的相关研究。

据此讨论出的候选实验：

- writeback-chain：candidate 作为下一轮输入，跑 1/2/3/5 次并记录完整误差轨迹；
- re-crop-chain：每次根据上一轮候选重新构造 audio crop；
- perturb-and-retry：对同一困难区使用少量不同 audio views，避免重复完全相同的问题；
- 1/2/4 unit 固定粒度、自适应 detector 边界、stable-anchor/静音/gap 分割；
- left→right、right→left、独立小段后 merge 的方向性实验；
- `R-U coarse proposal -> re-crop -> R-S/fixed refinement`；
- recovery-basin atlas、hard-case mining、串行 accumulated-error stress test、detector 数据扩张。

用户希望 agent 在主实验结束后自动进入自由探索，并通过递归 todo 保持继续探索。

---

## 4. 用户询问当前可见的最优设置，希望开始做可视化

用户原话：

> “另外当前能看出来的最优设置是什么？我想跑一些可视化看看了。”

讨论中把“最优”拆成两个目标：

- **target recovery**：当前 R-U unit-local 更适合观察是否把大错拉近；
- **context safety**：R-S sparse/fixed 最稳定地保护 fixed context。

当前 R-U builder 的代码默认：

```text
audio_margin_sec = 0.5
context_neighbors = 1
target span = 连续 1–3 units
```

R-S 保持完整 local window，并只激活 target slot，其余作为 fixed slots。

因此建议可视化至少把 baseline / R-U / R-S 并排，而不是宣布一个不存在的“全维度 winner”。

---

## 5. 用户指出旧 baseline 没有加入，要求查 slot 之前的优选

用户原话：

> “旧baseline没有加入，找一下旧的优选有什么（在slot方案之前）”

回溯工作目录和旧会话后确认：

- slot 之前的 historical baseline 不是当前 full-slot Base；
- formal GT 上曾有 B2（30s silence-aware official）略优；
- 但真实 Test Demo 里 60s 路线明显更稳，用户当时根据 Demo 行为把 **B4 60s silence-aware official serial/non-slot** 选为主线；
- 后续冻结的 `b4-60-silence-official-shadow-v1` 明确定义了 60s core、10s 左/右 context、official、silence snap、skip silent、shadow-only realign、actual_writeback=0；
- 因此当前历史对照最有意义的是 B4，而不是重新拉入整个 B0–B4 矩阵。

---

## 6. 用户冻结可视化比较方式

用户原话：

> “直接B4和现在的baseline比就好了。这个可以单独做。然后现在的消融可以做另一个四路画面。现在总结一下要做的事情。”

用户明确决定：

### 可视化 A：B4 vs Current baseline

- 单独双路；
- 不掺 realign；
- 目的：回答 slot/transition 等复杂机制引入以后，当前基础系统在真实 Demo 上是否超过旧 B4。

### 可视化 B：Current 内部四路消融

讨论冻结为：

1. Current baseline / no realign；
2. R-U unit-local；
3. R-S sparse/fixed；
4. R-U coarse proposal -> bounded/sparse refinement。

第四路如果尚未实现，不能拿无意义的重复 forward 或别的 family 偷换；应先实现/验证后再称“四路”。

---

## 7. 用户要求说明“到底怎么渲染”，以核对理解

用户原话：

> “告诉我怎么渲染可视化，从原先的会话与代码中看出我需要什么，让我确认你是否理解了。”

回溯历史会话与 renderer 后，确认用户要的不是普通成品 KTV，而是**带原曲声音、歌词、播放进度和多个 alignment track 的动态诊断 timeline**。

用户历史要求与当前冻结理解：

- 视频宽屏，当前旧 renderer 已使用约 `3840×1080`；
- 视频按真实时间分页（典型 30s/page），但横轴必须保持真实连续时间；
- 一根竖直播放线随真实音频时间匀速扫过 timeline，不沿整张 PNG 错位移动；
- 底部保留两行 KTV 歌词，使用原曲/mix 作为试听音频；
- 字符/序号不使用冗余冒号；空间不足时可从“序号+字”降级到“只显示字”，再降级到只显示 interval；
- 零时长/近零时长应聚合，形式类似 `[120-124,130,132-134]`，避免纵向堆几十行；
- 显示各方案自己的 core/input-context/window 边界，不得把 Current window plan 强行套给 B4；
- Current realign 四路需要显示 detector ACCEPT/REJECT/uncertain、realign target、fixed context、proposal/candidate 等，但 overlay 必须克制，不能遮住 timeline；
- collection 必须在 visualization 前，presentation 不能反过来成为 evidence collection 的依赖；
- static/video rerender 应能直接消费 frozen cache，修改画面不得重新跑 Qwen forward；
- 首个 smoke 继续使用用户过去反复观察的 `Side by Side.mp4`，确认后再批量多语言 Test Demo。

同时确认一个当前实现缺口：旧 `inline_realign` renderer 可以复用，但最新 unit-realign schema 与旧 visualizer 的输入结构不同，需要一个薄的 visualization adapter，而不是重做整套 renderer。

---

## 8. 用户最终要求形成下一轮 patch

用户原话：

> “可以，给我一个相对于当前实验目录的patch包，包括会话记录与实验结论、下一轮实验设计。会话记录需要记录完整会话过程，我的意见和疑问需要忠实记录。实验需要记录好实验原因、设计、目的、预期结果与结果能说明的结论。实验设计使用工作目录中一个新的session文件夹。实验也包括可视化那一部分。”

据此本 patch：

- 新建 `docs/sessions/20260814_realign_recovery_visualization_overnight/`；
- 不覆盖 `20260813_unit_level_realign_overnight` 的既有证据；
- 单独记录当前结论与其可信度/局限；
- 下一轮实验按“问题/原因/目的/设计/指标/预期结果/结果解释”组织；
- 可视化作为正式实验的一部分，而不是附属展示；
- 提供 Codex handoff，要求先做实现方案和 provenance 核实，再交 OpenCode/agent 运行；
- 主实验结束后自动进入自由探索循环。

---

## 9. patch 之后的执行与讨论（2026-08-14 晚 – 08-15）：B4 vs Slot 对比、Current 基线纠正、日文 Plan A、strict/compress 定案

本节补记第 8 节（形成 patch）之后、第 10 节（架构讨论）之前的会话内容。
本节为执行期记录：重点保留用户的纠正、决定与对比设计，实验中间过程的细节以
`RUN_STATE.md` 与各 run 目录为准。

### 9.1 打包与证据包

用户要求：

> “先review两遍，每遍使用2个以上子agent，有问题就修。之后将工作目录使用pack_lyricalign打包，
> 然后另外打包一个打包后3M大小多退少补的本次实验证据包。”

执行：两轮 review（每轮 ≥2 子 agent）后打包工作目录，并另打一个约 3M 的本次实验证据包。

### 9.2 KTV 字幕版渲染需求

用户要求在同一位置额外渲染 KTV 字幕版本，且全部对比都要可视化：

> “另外在帮我在同样位置，渲染一下k歌字幕版本的...我想看B4 vs current slot”

> “全都要跑可视化”

### 9.3 用户质疑：slot 与 B4 必须真有差异（不是配置 artifact）

用户连续追问 slot 的历史结论与差异来源：

> “过去实验结论中，对slot的行为的最终决定是什么？”

> “有无slot印象中也是有区别的”

> “B4作为无slot的查询，和current作为有slot的，应该是不一样的结果才对”

### 9.4 重大纠正：我误用的"Current"基线是错的

排查确认：我之前把 demo batch（`run_qwen_fa_batch.py --individual r2:vocal:windowed`）当作
"Current"，但该路径与 B4 **共享同一段 `windowed_alignment` 代码**（同样的 silence-aware
分窗、同样的 pre-slot 串行查询），给它加静音后得到 Current==B4 的假象——差异为零是配置
artifact，不是真实结论。

真正的 Current 是 research_v7 的 **full-slot**（`request_mode=full_slot`、`long_slot_60s`、
`decoder_view=raw`）。此后所有"Current"一律指 full-slot，不得再用 demo batch 冒充。

### 9.5 用户冻结 20260806 Base，并指定输出视图

> “按照20260806 冻结 Base去做。full slot + 左10秒 + core60 + 右10秒lookahead +
> silence-aware boundary snap + skip silent windows + short-tail redistribution/minimum core。
> 重新渲染。”

> “slot这次使用official作为输出，先不用raw”

冻结内容：窗口=左10s + core60s + 右10s；静音吸附边界；跳过静音窗；短尾再分配/最小 core；
输出时间线以 official 解码为主（raw 保留但非主输出）。

### 9.6 日文不回避：方案讨论与 Plan A 执行

用户要求不得跳过日文：

> “不要避开日文，我们讨论一下怎么解决，给出不同的方案”

讨论出的方案：

- 方案 A：**直接调 `infer_slice`**，用与 B4 完全相同的 document（行文本解析、nagisa 词单元），
  不经过 RealAligner 的重分词——彻底规避日文重分词不稳定；
- 方案 B：沿用 RealAligner（会重分词，日文窗口子集重解析会失败，不公平）。

用户拍板"执行"方案 A。Plan A 的关键实现点：

- document = `parse_lyrics_text("\n".join(各行 display_text))`，与 B4 单元空间完全一致；
- 每窗用窗口文本范围（`character_start/end = 窗口单元区间`），音频用 `audio[crop]`，
  `global_audio_offset_sec = input_start`，`timestamp_slot_indices = range(窗口单元数)`（真 full-slot）；
- 窗口单元按 `owner_window_index`（B4 实际提交归属）选取，不用 input span 匹配。

Plan A 修复过程（期间我承认过实现错误并逐一修正）：

1. 初版把全曲文本 + 窗口音频一起喂 → 产生假差异（乙女 47% 相同），改为窗口文本范围；
2. 窗口单元按 input span 归属会把整首歌喂进一个窗（>200 单元，全部塌缩到 input_start，
   冬之花 208/222 全塌），改为按 `owner_window_index`（B4 提交集合），验证冬之花 208/222 与 B4 一致；
3. 输出缺 `summary.audio_duration_sec` / `lines` → 渲染器崩溃，补齐。

### 9.7 三组对比设计（用户确认）

- **A 组：B4 vs full-slot**——窗口、单元空间、解码器与 B4 完全一致，唯一差异是查询语义
  （full-slot 一次查询窗口全部单元 vs B4 pre-slot 串行 cursor 推进）；文本提供方式对比也并入
  此组（用户接受这可能是额外的不公平对比）；33 首全跑；
- **B 组：R-U / R-S / R-CF 机制 vs full**（core 5 首）；
- **C 组：strict / compress 变体**（slot 为基础，不需要 B4；strict 与 compress 形成 2×2）。

用户原话（C 组）：

> “strict&compress中应该是slot为基础，不需要b4，而且是否strict、compress形成2*2”

### 9.8 strict/compress 设计定案（用户最终版）

- **strict** = 静音 ≥5s 为硬边界；每个活跃区内部**单独跑 soft 逻辑**（target core 等距 +
  区内静音吸附 + 短尾再分配 + leading/trailing 裁剪）；小孤岛（短活跃区）独立成窗，不参与
  其他活跃区的分割；不需要"子 profile"概念（直接复用全曲静音证据并按活跃区过滤）；
  边界窗（贴近静音的窗）沿用现有"裁剪开头静音"的做法（input clamp 到活跃区，不跨 ≥5s 静音）；
- **compress** = 纯音频后处理：静音 ≥2s 裁到 2s（`trim_to_sec=2.0`），**strict 之后**应用；
  可能过度缩短的窗口接受即可；词不能落到被裁掉的静音区上（映射保证）；
- 用户最后澄清 strict 实现方式：

> “反正只要我们strict分割时，严格地单独在每一个活跃区进行soft，就不会产生跨静音区，
> 小孤岛作为活跃区不参与其他活跃区的分割，也无关什么子profile的概念。边界窗的话，
> 当前裁剪开头静音怎么做现在就怎么做。”

### 9.9 执行进度（截至架构讨论前）

- Plan A full-slot 对齐：33/33 首完成（`run_slot_vs_b4_batch.py`）；
  公平口径（owner-window 单元）对比 B4：slot 更差(>1pp)=10、持平=11、更好(<-1pp)=11，
  一致率 0.40–0.94（详情以 run 内 JSON 为准）；
- B4-vs-Slot 渲染：曾完成 16/33 后因实现修复被中断（`render_slot_vs_b4.py`），需基于最终
  Plan A 输出重渲染全 33 首；KTV 字幕版同步渲染；
- strict/compress 的 window_planning.py 改动与自检已落地（见 10.8 节代码状态）。

---

## 10. 窗口输入/装配层架构讨论（strict/compress 实现前的架构整理）

日期：2026-08-15。本节忠实记录在 strict/compress 2×2 实现过程中转入的架构讨论。
讨论尚未结束（接口清单未细化），先落盘以防会话上下文丢失。

### 10.1 起因：实现 strict/compress 前先整理架构

strict/compress 的窗口规划与音频压缩已经实现并自检通过（见 10.8），但用户要求先停下实现，
把架构讨论清楚再继续。用户原话：

> “现在分窗和compress分开了，compress和后面的对齐又是分开的。但是分窗前面还有一些东西耦合。
> 整理一下。比如说core-非core”

> “先别管这些，先讨论好了再说。现在有什么机制还是耦合的”

> “不要管当前的组和对比，我们在讨论整个项目的结构”

随后用户纠正我的表述方式并指向既有记录：

> “你的黑话突然变得好多，别用黑话。另外我们过去记录中已经有现成的机制总结讨论，看一看”

### 10.2 既有机制分层（20260806/20260807 讨论记录，本讨论的基础）

- 20260806 记录：**slot 是“单次请求查询哪些歌词单元”，串行是“请求之间怎么传状态
  （cursor/已提交前缀）”**——两者不是互斥，是两个不同机制；
- 20260807 记录第 7 节把系统拆成：**对齐方式**（slot/non-slot）、**推进方式**（独立/直接串行/
  核心+边界/稳定边界，commit 归入这里）、**分窗**（固定/静音吸附/强制静音边界）、**窗口输入**
  （左10s+core60s+右10s）、**音频预处理**（不处理/压缩长静音）、**解码器**（raw/official）、
  **恢复/控制**（none/shadow/L/W）。

### 10.3 用户判断：窗口输入这一层耦合最重

用户原话：

> “分窗 和 窗口输入 缠在一起：相对分开一点。窗口输入耦合还挺严重的，和推进方式也有关系，
> 和分窗也有关系，和预处理也没太分清。”

对照代码确认的耦合点：

- **音频装哪段**（input 范围）由分窗器算（core±10s，strict 时还 clamp 到活跃区）——裁剪策略长在分窗器里；
- **文本装哪段**（文本起点）由推进层算（`input_cursor`，且 `next_window_transcript_start` 拿上一窗
  对齐结果 + 下一窗 input 起点一起算）——文本起点同时依赖推进状态和分窗几何；
- **两者对上**（时钟）由预处理/压缩负责（投影 + `_remap_compressed_alignment`）——同一件事被切成三块分在三个地方；
- “音频边界落在字符中间/静音里怎么处理”这条规则 B4 里只有一份、藏在串行循环里，其它路径没有。

### 10.4 用户决定：分窗只决定 core，装配合成音频输入

用户原话：

> “我也理解，分窗只决定core，这样的话左右上下文（曲）就只是一个可选项。预处理可以和左右
> 上下文（曲）装配放在一起，形成给对齐的音频输入。”

即：

- 分窗器只交付 **core 区间**（几何），不再算 input、不碰文本；
- 左右上下文（曲）是**装配层的可选项**；
- **预处理 + 左右上下文装配**合成“给对齐的音频输入”（含时钟映射）。

### 10.5 用户问题与结论：如何避免“是否有上下文”成为推进方式的笛卡尔积（×2）

用户原话：

> “但是我还没想好怎么样避免是否有上下文成为推进方式的一个笛卡尔积部分，造成*2。”

讨论结论：

- **上下文拆成两回事**：曲的上下文（音频多给几秒，装配参数）与词的上下文（已提交字符重输，
  串行推进的机制必需，不是选项）；两者必须配套（音频有声音处文本必须有字）；
- 判定新维度看“是否改变另一机制的规则”：上下文的有无不改变 cursor/commit 规则 → 不是维度；
- 串行下“词的上下文”是状态的一部分，独立下天然为空，都不产生叉；
- 主轴仍是 推进方式 × 恢复控制；装配参数（如 10/60/10）冻结为配置；
- “有无上下文”的影响研究放**装配层内部**（选定 1 个推进方式，比较 10/60/10 vs 0/60/0），不展开全排列。

### 10.6 用户新想法：层式且双向（装配 ↔ 推进 反向交还）

用户原话：

> “我想到了，或许做成层式且双向的，我本来只想到，它是单向的，即只有装配影响后面推进，
> 而没想到影响推进的部分可以反向地交还给它，类似逆运算。你可以理解吗”

确认与展开：

- 单向视角：推进（状态）→ 装配（拼输入）→ 模型 → 结果；
- **双向视角**：装配层把推理输出整理成“结果行”，交还给推进层；推进层**自己反算**状态更新
  （下一窗文本起点、commit 哪些字符、是否跳过）——这就是“逆运算”；
- B4 现成实例：`next_window_transcript_start`（结果行 → 下一窗文本起点）、commit、skip-silent；
- 装配参数（如左上下文秒数）因此可以是**响应反向信息的函数**（如上一窗尾部未稳 → 自动加长
  左上下文），从而“是否有上下文”从根上不是穷举维度；
- **风险**：反向通道传的是推理结果的反算，推理错则状态错（20260807 已记录“真实串行系统本身
  不稳定、前窗 state 错把下一窗带错”）；需给反向信息标注可靠度（stable 已提交前缀可信 /
  provisional 暂定结果不可信），推进层按标注决定是否采信。

### 10.7 一次窗口的简单模型（用户要求“先从简单的一段考虑”）

用户原话：

> “我们先从简单的一段考虑吧，确定好装配和分窗怎么互动，另一端和推进怎么互动就更好理解了。”

一次推理的生命周期（简单版，固定上下文、无压缩、无 strict）：

```
分窗器 ──core区间──> 装配层 ──音频+文本──> 模型 ──字符时间──> 装配层整理 ──结果行──> 推进层
                        ^                                                    |
                        └──────文本起点/已提交前缀（正向）────────────────────┘
                        └──────下一窗起点/commit/跳过（反向，推进自己反算）──────┘
```

接口（当前共识）：

- **分窗 → 装配**：只交付 `core_start ~ core_end`（可带可选的区域边界约束，待定）；装配负责
  展开 input、找文本、裁剪；
- **推进 → 装配（正向）**：文本从哪个字符开始、已提交前缀到哪；
- **装配 → 推进（反向）**：整理好的结果行；反算在推进那边（推进消费结果行，装配不替推进决策）；
- 压缩 = 装配展开时用哪把时钟；strict = 装配展开时的裁剪规则；跳过 = 推进反算时的一个决策——
  三者都不改变接口形状。

180s 例子（60s core，10/10 上下文）已走通：窗1 input=[0,70] 文本从0开始；推进反算提交 start<60
的字符、下一窗起点=50s 处第一个完整字符；窗2 input=[50,130] 文本从窗1算出的起点开始（含已提交
字符作词的上下文）；以此类推。

### 10.8 当前代码状态（已落地，供续跑）

- `src/lyricalign/demo/window_planning.py`（已改）：新增 `_soft_plan_in_span` 共享逻辑；
  `build_silence_aware_window_plan` 改走共享逻辑（行为与重构前逐位一致）；`build_strict_
  silence_boundary_window_plan` 改为“每活跃区独立 soft”（strict 阈值 5s，小孤岛独立成窗，
  input clamp 到活跃区不跨 ≥5s 静音）；`compress_silence_audio` 新增 `trim_to_sec` 模式
  （≥2s 静音裁到 2s，legacy 移除行为不变）；
- 合成音频自检（/tmp/verify_strict_compress.py）全部通过：soft 行为不变、strict 每活跃区 soft
  与小孤岛独立、compress trim、strict+compress 投影；真实歌曲（冬之花/Immortals/祈愿花开/
  月半小夜曲）窗口规划检查通过；
- `scripts/realign_recovery/visualization/build_testdemo_slot_variant_manifest.py`（新，未验证）：
  C2/C3/C4 manifest 构建；`run_testdemo_slot_infer.py`（已改，未验证）：支持压缩变体回映射。
- 注意：上述代码改动是讨论前的产物，**尚未按本节的接口共识重构**；接口共识落定后再决定
  改哪些。

### 10.9 待续事项

- 细化三个接口的输入/输出清单：分窗是否带“区域边界”可选约束；结果行里推进反算需要哪些字段；
- 决定装配层“边界落在字符中间/静音里”的统一处理规则（现在只有 B4 串行有）；
- 决定这段架构讨论是否落成正式设计文档、是否影响 strict/compress 实验的实现顺序；
- strict/compress 2×2 实验本身（对齐 + 渲染）仍在待办。

### 10.10 三个接口的输入/输出清单（草案，讨论中）

基于 10.7 的简单模型，细化三个接口。标记：✅=已定，❓=待讨论。

**接口 1：分窗 → 装配（交付 core）**

| 字段 | 说明 | 状态 |
|---|---|---|
| core_start_sec / core_end_sec | core 时间区间 | ✅ |
| window_index | 窗口序号（trace/归属用） | ✅ |
| 允许展开的边界（下界/上界） | input 不许越过的时间范围；soft=曲首/曲尾，strict=活跃区边界 | ❓ |
| 是否最后一窗 | 几何事实（推进反算 commit 时要用） | ❓ |

**接口 2：推进 → 装配（正向状态）**

| 字段 | 说明 | 状态 |
|---|---|---|
| 文本从哪个单元开始 | 装配据此拼文本（串行时=上一窗反算值，独立时=固定值） | ✅ |
| 已提交前缀到哪 | 装配据此把更早的字符标为"词的上下文"（重输但不重新提交） | ❓ |
| 目标字符数 / 未来行数 | 装配自己控制的 lookahead 参数（默认配置） | ✅ |

**接口 3：装配 → 推进（反向结果行）**

| 字段 | 说明 | 状态 |
|---|---|---|
| 每个查询单元的 id + 起止时间 | 推进反算的原材料 | ✅ |
| 时间的时钟 | 统一回原始时钟交还（压缩只活在装配内部，推进无感） | ❓ |
| 窗口活动摘要 | 这窗音频的活动统计（skip 判定输入之一） | ❓ |

**开放问题（待讨论）**：

1. "input 不跨静音"由谁保证：分窗在接口 1 里给"允许展开的边界"，还是装配自己持有静音证据判断？
2. 结果行时钟：倾向统一原始时钟（压缩对推进透明），确认？
3. skip 判定输入：装配在结果行附带活动摘要，还是推进自己从音频层取证据？
4. 音频开头允许"短暂无词区间"（文本起点对应时间可略晚于 input_start，B4 现状如此），确认接受？
5. "词的上下文"标注（哪些字符已提交、只重输不重提交）归装配（收到 committed_prefix_end 后自己标），确认？

### 10.11 用户再定义：分窗器是"被驱动的窗尾计算器"（2026-08-15）

用户对分窗器的输入输出给出更精确的定义（原话大意）：

> 分窗需要的信息：分窗的区域（strict 中的某一活跃区，或 soft 中的区）、这一次需要分的窗的
> 头的位置、曲的信息；然后给装配区提供这一次的分窗尾。文字端另说，目前实现是比较简单地
> 少量多次。

即：

- 分窗器**不是**一次算完全部窗的离线规划器，而是被驱动的、有状态的"窗尾计算器"：
  - 输入：区域（strict 活跃区 / soft 全曲区间）、这一次窗的头（从哪开始切）、曲的信息（静音证据，吸附用）；
  - 输出：这一次窗的尾（core 结束位置）；
  - 交付给装配：这一个窗 = [头, 尾]；
- 文字端（文本装配）暂不展开，保持现状的简单实现（少量字符、多次请求 = B4 future slice 方式）。

待对齐的小点：

1. "头"的来源：倾向推进层给（串行时来自上一窗 commit 边界/稳定边界；独立时=0 或固定值），
   分窗器只算尾；另一种是分窗器自己维护游标（头=自己上次的尾）；
2. "区域"的传递：strict 活跃区列表一次算好由分窗器持有，调用时带"当前在哪个区域"；
   还是每次重算。

### 10.12 系统形态探索：循环式 vs 终端式；"还原/解码层"方向（2026-08-15，搁置项）

用户对分窗器的定位与系统整体形态提出探索性想法（原话大意，均暂缓决定）：

1. **分窗器当前定义下只被动**：被问"这个窗尾在哪"才回答，没有主动工作；
2. **可能的演进**：分窗器（或其所在层）未来可能被抽象出"从窗口的对齐结果还原内容"的职责
   （把分散在多个窗口的字符时间拼回完整时间线），可能和 decoder 合成一层——即
   "模型输出 → 最终完整时间线"整段（解码 + 窗口还原/拼接）划为一层，与"窗口怎么切"彻底分开；
3. **系统形态两种候选（未定）**：
   - 循环式：整个系统是一个循环（分窗→装配→推理→还原→推进→分窗…），仅需 init 与终结条件；
   - 终端式：分窗器仍是纯被动的终端，不参与驱动；
4. 以上全部暂时搁置，不影响接口 1 按"被动窗尾计算器"定稿。

补充观察（记录）：

- "从窗口结果还原内容"目前散在两处：B4 推进层的 committed_rows 累积 + overlap 压缩
  （karaoke commit），Plan A runner 的按 id 合并；职责已存在但未独立成层；
- 循环式 vs 终端式的实质差别是"谁驱动循环"：循环式 = 推进层/控制器主动发起下一轮；
  终端式 = 分窗器永远被调用；B4 现状是"预计算全部窗的循环"，与两者均不同，改造成循环式最接近；
- 接口 1 的定稿方向（待用户确认后冻结）：分窗器 = 被动窗尾计算器，输入=区域+头+曲信息，
  输出=尾；"头"的来源暂时留空（推进层给 vs 分窗器自维护游标）。

### 10.13 接口 1 收敛：区域由分窗器自行推导，不额外传递（2026-08-15）

用户确认（原话大意）：区域不需要外部传递——分窗器自己依据曲元信息（静音证据）和本次窗的
开头（头）即可定位当前区域（strict 活跃区 / soft 全曲区间），自行计算。

接口 1 收敛为：

- 输入：头 + 曲元信息（分窗器自己持有）；
- 分窗器内部：由头定位当前区域 → 区域内算尾（等距 + 静音吸附 + 尾重分配）；
- 输出：尾 + 所在区域边界（供装配展开 input 时 clamp）——同时解决 10.10 开放问题 1
  （"input 不跨静音"由分窗器给的区域边界保证，装配不持有静音证据）。

待定边界情况：**头落在静音区中间**时的行为，三种候选：

1. 跳过：定位到下一个活跃区开头（倾向，与现有 strict"活跃区起点即窗起点"语义一致）；
2. 报空：返回"无区域可分"，由推进层/控制器决定下一步；
3. 吸附：把头吸到最近静音边界再定位。

### 10.14 用户观察：词曲元到最初级分窗尚无完全隔离抽象（2026-08-15）

用户观察（原话大意）：除了分窗器需要歌曲元信息，装配器由于涉及非 core 上下文的装配，
也需要曲元信息；目前"词曲元到最初级的分窗"之间还没有构成完全隔离的抽象。

现状数据流：

- 曲元（音频/profile/静音证据/时钟）→ 分窗器（定位区域、吸附、算尾）与 装配器（展开 input
  需碰音频边界/压缩时钟/活动信息）两个消费者；
- 词元（歌词/单元）→ 装配器（拼文本）；分窗器不碰词元（纯时间）。

"完全隔离"的三种候选含义（讨论中）：

- A：曲元统一入口（"歌曲上下文"对象），分窗与装配都经它取子集，不直接摸原始数据——
  隔离访问路径，曲元仍多消费者（倾向）；
- B：分窗独占曲元，装配零曲元——分窗输出完整"窗规格"（input 建议/活动摘要/时钟），
  装配纯拼装；代价是分窗重新背负"input 怎么装"的决策（10.3 想拆开的耦合）；
- C：曲元多消费者但装配只消费窄接口（"上下文元信息"：活动摘要、时钟、区域边界）。

另确认：分窗器目前只用曲元、不碰词元——"词元不进分窗"这条已经满足。

### 10.15 用户引入分层隔离模型（类计算机网络分层）（2026-08-15）

用户提出用计算机/计网式的层级抽象进行隔离（原话大意）：

> 考虑到整个系统的输入是词曲，输出是时间戳，系统外可视为"输入词曲获得时间戳"的黑盒；
> 它接触的第一层就是：词曲变成窗，然后将窗变成时间戳给系统外。

分层模型（本讨论的共识）：

```
系统外视角：输入词曲 → 输出时间戳（黑盒）

第一层：
  ① 词曲 → 窗      （词曲元的第一次抽象：分窗器在此段工作）
  ② 窗 → 时间戳    （装配/推理/推进/还原全部在此段）

更深层全部包在"窗 → 时间戳"内部。
```

推论：

- **"窗"对象是第一层内部的中间产物，也是隔离的载体**：词曲元只进"词曲→窗"段，
  "窗→时间戳"段（装配/推理/推进）只消费窗对象，不再接触词曲元；
- 这正面解决 10.14 的问题：装配器不需要接触完整曲元——它需要的曲元子集
  （活动摘要、时钟、区域边界）由"词曲→窗"段加工后封进窗对象；
- 窗对象契约成为关键：候选字段 = 头、尾（core 区间）、区域边界（装配 clamp 用）、
  活动摘要（skip 判定用）、时钟标记（压缩与否/映射）、是否最后一窗；
  带齐后装配层即纯拼装。

### 10.16 修正分层：中间产物是"模型输入"，不是"窗"（2026-08-15）

用户指出 10.15 的问题（原话大意）：把装配需要的曲元信息（活动摘要/时钟/区域边界）封进
窗对象，等于把装配决策提前拉进"词曲→窗"层——装配器又被装进这一层了。

修正设计（共识方向）：

```
系统外：词曲 → 时间戳

第一层：
  ① 词曲 → 模型输入
     - 分窗器 + 装配器同层；曲元信息层内自由共享；
     - "窗"只是分窗器的内部输出，不是对外契约；
  ② 模型输入 → 时间戳
     - 模型推理 + 解码 + 还原拼接；
  推进 = 循环驱动者：消费 ② 的结果行，反算给 ① 下一轮的头/已提交前缀。
```

要点：

- **层间契约 = 模型输入**（音频片段 + 文本片段 + 时钟说明），完整自足、无规划内部细节；
- 装配器与分窗器同层（"词曲→模型输入"段）——曲元多消费者是层内事务，不再是跨层泄漏；
- "窗"降级为层内实现细节，不再承担契约职责（10.15 的窗对象字段清单作废）；
- 推进横跨两段是循环的固有属性（吃 ② 结果、驱动 ① 下一轮）。

### 10.17 层内解耦清单（2026-08-15）

用户提醒：目前就是在解耦，层内耦合也很麻烦。确认分层（10.16）只是外壳，层内解耦
才是主要工作量；层内解耦任务在分层框架下整理如下：

**层①"词曲→模型输入"内部**（分窗器 / 装配器 / 预处理，共享曲元）：

- 接口 1：分窗器（被动窗尾计算器）→ 装配器：尾 + 区域边界（头来源=推进，待定项保留）；
- 接口 2：推进 → 装配器：文本起点、已提交前缀；
- 预处理 = 曲元加工（压缩音频 + 时钟映射），层内取用，不作为独立层。

**层②"模型输入→时间戳"内部**（推理 / 解码 / 还原）：

- 模型输入 → 推理 → 解码（raw/official）→ 还原（窗口结果拼完整时间线）→ 时间戳；
- "还原与 decoder 合成一层"（10.12 搁置项）在此落位；
- 接口 3：装配/层② → 推进：结果行 + 活动摘要；推进反算（commit/下一轮头/终结判定）。

**推进 = 系统控制面**：消费 ② 的结果行，驱动 ① 的下一轮（头/文本起点/已提交前缀），
判定终结。

层内待定接口：接口 1 / 2 / 3 + 推进终结判定规则（复用 10.10–10.13 讨论成果）。

### 10.18 层①再拆：分窗层（纯几何）+ 装配层（物化）（2026-08-15）

用户要求把层①（词曲→模型输入）拆成至少两层。拆法（讨论方向）：

```
曲元层（最底，可选）：音频 → 曲元对象（静音证据/活动/压缩时钟）
  ├→ 层①a 分窗层：曲元 → 窗（纯几何：头/尾/区域边界；不碰词元、不碰上下文决策）
  │       ↓ 窗（纯几何契约）
  └→ 层①b 装配层：窗 + 曲元 + 词元 → 模型输入（音频片段+文本片段+时钟说明）
          ↓
  层② 模型输入 → 时间戳（推理/解码/还原）
```

要点：

- 分窗层输出只剩几何（"分窗只决定 core"字面成立）；装配层负责一切物化
  （上下文展开、时钟选择、文本拼装）；
- "窗"作为分窗层→装配层的契约是纯几何的——10.16 反对的是"窗带装配决策"，
  纯几何窗与之不矛盾；
- 曲元层（音频→曲元对象）若独立，分窗层与装配层都从曲元对象取子集
  （10.14 含义 A 落位），不直接摸音频。

### 10.19 逆向过程的处理：推进作控制面，层间保持单向（2026-08-15）

用户指出：推进影响下一个窗的开始（头），分窗层因此也要接受装配层（经推进）的输入——
这个逆向过程怎么考虑？

结论（讨论方向）：

- **逆向过程收进推进（控制面），层间保持单向**；推进是唯一折返点：

```
推进（控制面，持有全部状态）：
  init: 头 = 0 / 区域起点
  loop:
    ① 头+曲元 → 分窗层 → 尾 + 区域状态
    ② 窗(头,尾) → 装配层 → 模型输入
    ③ 模型输入 → 层② → 结果行
    ④ 反算：commit / 新头 / 终结判定 ← 结果行 + 区域状态
```

- 分窗层不直接依赖装配层：装配层的结果行只回流到推进（④），推进把"新头"传给分窗层；
- 所有层 = 无状态纯函数（可测、可重放）；状态单点 = 推进；循环 = init + 终结条件
  （呼应 10.12 的"循环式"形态）；
- 细节：推进算"新头"需要区域知识但无曲元 → 分窗层输出扩展为"尾 + 区域状态"
  （是否区域末窗、下一区域起点）；推进的新头 = 策略（等距=上一尾 / 稳定边界=commit 边界）
  + 分窗层给的区域信息。

### 10.20 异常/重试路径也走推进（2026-08-15，存档）

确认补充 10.19：逆向不止"下一窗的头"，还包括异常路径——装配层发现模型输入超长（>200
单元会塌缩）、或层②推理失败需重新分窗时，同样走推进：推进收到失败标记后重新调用分窗层
（带重试参数）。保持"层间单向、控制面唯一"不变形。

### 10.21 strict 边界窗的上下文装配语义：截断 vs 不装配（2026-08-15）

用户问：strict 在静音区边界的窗，能否实现"不装配对应侧上下文"。

两种语义：

- A. clamp（截断，当前实现）：input = core±10 再 clamp 到区域边界；core 离边界 <10s 时
  上下文被截短（能装多少装多少）；core 贴边时上下文=0；
- B. 不装配（显式 0s）：core 贴着区域边界/leading 裁剪后活跃起点的那一侧完全不装上下文
  （input_start=core_start），不是"能装多少装多少"。

技术：可行——装配层收到窗（带区域边界）即可判定哪侧贴边，作为"上下文装配策略"
（每侧可选：标准 10s / 截断 / 不装）。历史：20260807 讨论中用户提过"边界窗无需对应侧
上下文"，9.8 定案为沿用当前裁剪（即 A）。**待用户决定 C2/C4 用 A 还是 B。**

### 10.22 "纯静音侧上下文不装配"的普遍规则（2026-08-15）

用户观察：soft 首窗的左上下文常常是纯静音——leading 裁剪后 active_start 之前全是静音，
input_start=max(0, core_start-10) 落在被裁掉的静音里；尾窗右上下文同理。

推论：这不是 strict 特有，是普遍问题。候选统一规则：

> 哪一侧上下文区间纯静音就不装配那一侧（0s）；有活动就正常装（10s 或截断）。

- 落位：装配层向曲元层查询"区间是否有活动"（窄接口），无活动 → 该侧上下文=0；
- soft/strict 统一，C1–C4 同一套策略（10.21 的 A/B 之争被此规则吸收：贴边+纯静音=不装，
  有活动=装）。

影响面：B4 冻结基线也是 soft——若此规则全局生效，B4 行为改变、冻结基准被打破。
三个选项（待定）：1) 只对 C 组用，B4/现有 soft 保持 clamp；2) 全改（需重跑 B4）；
3) 先不动手，等架构定稿一起改。

### 10.23 历史证据：前置静音对模型对齐的影响（2026-08-15 查证）

用户要求查证"前面插 10s 静音会发生什么"。找到 20260725 A3"时间平移等变性"实验
（runs/20260725_qwen_fa_immediate_diagnostics/r2/shift）：M4Singer 最短样本前插
0/30/60/120/180/240s 静音，扣除 offset 后测 raw/fixed 误差。

结果：

| 前置静音 | r1 fixed | r2 fixed | raw fixed |
|---|---|---|---|
| 30s | ~0.04s | ~0.02s | ~0.04s |
| 60s | ~0.02s | ~0.10s | ~0.06s |
| 120s | ~0.10s | ~0.12s | ~0.06s |
| 180s | ~0.04s | ~0（完美） | ~0.04s |
| 240s | 118.2s 崩溃 | 118.3s 崩溃 | 84.3s 崩溃 |

结论：

- 前置静音 ≤180s：几乎完美平移等变（head 重建，误差 <0.12s）——插 10s 静音无影响；
- 240s：彻底失去校准（raw 101–147s、fixed 84–118s，修复也救不回）——模型输入位置/
  时长上限问题，与静音本身无关；
- 对 10.22 的含义：soft 首窗左上下文是纯静音 **无害**（模型鲁棒）——"纯静音不装"规则
  不是正确性需求，是输入精简/架构干净性选项；窗口场景（core 60s）不触及 240s 上限。

### 10.24 C 组设计与执行状态（2026-08-15）

C 组渲染设计定稿（用户逐条确认）：

- 结构同 B 组：每首 1 图 + 2 视频（静态 4 行 timeline 图、timeline 4 行视频、KTV 2×2 视频）；
- 4 路 = C1 Base（soft）/ C2 strict / C3 compress / C4 strict+compress；
  布局：timeline 上→下 C1/C2/C3/C4；KTV 左上 C1/右上 C2/左下 C3/右下 C4；
- KTV 音频 = 原始 vocal（压缩变体输出已回映射原始时间线，"实现复原"）；
- 每行/每面板画该变体自己的窗口边界（core/input），不套用别的变体；
- 33 首全量，无页面小图；命名 C_variants_<song>.png/.mp4/KTV.mp4 平铺 DELIVER/{images,videos}。

执行中发现的基线数据问题（已记录，选项 1 接受现状）：

- B4 基线 33 首健康检查：冬之花严重塌缩（w1 全 112 单元压到 input_start，B4 喂了 157
  日文词单元超安全线）；皱鳃鲨/p.h 部分塌缩；Past Lives 正常（歌词早结束）；其余 29 首正常；
- C 组归属用 B4 字符时间 → 塌缩歌的 strict/后续窗无单元（no_units 跳过，冬之花 w1–w3）；
- 冬之花 C 组 w0 因塌缩时间堆叠 201 单元 → 超限塌缩 → builder 加 MAX_WINDOW_UNITS=150
  截断保护（status=ok_truncated_units，runner 接受）；截断后 strict 正常、
  compress 仍塌缩（150 单元在压缩 59s 音频中密度过高）——作为 C3 真实实验结果呈现，
  不特殊处理；mu130/mu110 实验确认降低单元数可缓解，但不作为默认。

执行状态：run_slot_variants_batch.py（新）全量 33 首 × 3 变体后台运行中；
渲染脚本 render_slot_variants.py（新）已写（4 行 timeline 经 render_full_song 多 baseline
lane + 每 lane 注入 window_trace；KTV 2×2 经 render_alignment_comparison layout="four"）。

### 10.25 采样率 bug 与修复（2026-08-15，重要教训）

C 组首轮全量对齐后覆盖率检查发现严重缺失（I See Fire 只有 24/311 字符）。根因：

- builder 用 `sf.read(vocal_path)` 读音频，但 vocals.wav 是 **44100Hz**；profile/窗口规划
  按 16000Hz 计算（B4 用 `decode_audio` 会重采样到 16k）——采样率不匹配导致静音检测全错
  （I See Fire 前 183.5s 被误判为静音，窗口全部错位）；
- 修复：builder 改用 `decode_audio`（16k mono，与 B4 完全一致）读音频；压缩音频也按 16k 写盘；
- 首轮 strict/compress/strict_compress 结果全部作废，重跑。

修复后覆盖率：strict 93%、compress 96%、strict_compress 93%（no_units 集中在已知 B4
塌缩歌：冬之花/皱鳃鲨/炉心融解/初音未来的消失/I See Fire/月半小夜曲/红日/乙女解剖；
截断 27–29 窗）。另发现 I See Fire 的 B4 基线本身质量差（201/311 字符落在 vocals
-54.5dB 的静音区 150–180s）——同冬之花一类，接受现状。

### 10.26 A 组文本方式③与渲染进度（2026-08-15）

- textmode3（13 §4.3 历史最佳文本提供）：每窗 slot 区 32 单元（查询）+ 历史文本
  （B4 committed cursor 起，不查询）+ future 16 单元 lookahead（不查询）；
  新 builder `build_testdemo_textmode_manifest.py` + runner 支持显式文本范围与稀疏 slot
  （slot 单元过滤：song_slots 合并修 bug——曾只保留最后一窗 slot）；
  33 首全量完成（118 请求），输出字符 = Σ每窗 min(32, 窗单元数)，覆盖率约 27%（稀疏查询设计使然）；
- A 组渲染脚本 `render_a_group.py`：timeline 2 lane（B4|Slot）+ KTV 2+1 三面板
  （上排 B4|Slot、下排 textmode3）；`media_render.render_alignment_comparison` 新增
  layout="three"（xstack 0_0|w0_0|0_h0）；
- C 组渲染：vocal 音频版重跑中（首轮误用 mix——resolve_audio 优先 mix，改 resolve_vocal）；
  KTV 用 vocal、timeline 视频也用 vocal（用户确认 C 组设计）；
- 教训记录：pkill -f 匹配自身命令行导致后台任务自杀（bash-77），重启时避免 pkill 模式含自身。

### 10.27 C 组渲染完成；A 组渲染重跑（2026-08-15）

- C 组渲染 33/33 完成（33 图 + 66 视频）：4 lane timeline（每 lane 各自窗口边界，
  track_geometry has_track_windows=True）+ KTV 2×2；PNG 160px/s 4 lane 尺寸验证通过；
- A 组渲染首轮发现 Slot lane 的 window_trace 为空（runner 不写）→ timeline 上 Slot lane
  无窗口边界；修复：注入 B4 window_trace 副本后重跑（C1 窗口==B4 窗口，manifest 复用
  B4 window_trace）；KTV 2+1 三面板（B4|Slot 上排、textmode3 下排，layout="three"）。

### 10.28 B 组：Detector V2 困难区 + 三机制（2026-08-15）

用户选 Detector V2（research_v7 冻结族）作为 B 组困难区来源。实现：

- **关键发现**：C1（full-slot）alignment 输出已含完整 R/O 特征（raw entropy/margin/
  topk 概率、official 几何）——无需重跑推理即可打分；
- **训练**：run2（修正口径，unsafe 7.2%）evidence + official-target labels →
  O 特征（official 7 + official neighborhood 12 = 19 键）standardized_logistic
  （凸优化可复现）；阈值用 FROZEN_OPERATING_POINTS official view（T_accept/
  T_reject≈0.1107）不重挑；
- **打分**：33 首 C1 → proba → tri-state（accept 11969 / reject 1766 / uncertain 0）；
- **聚合**：reject 连续段 + merge-gap=2 合并 → 963 个困难区（33 首全覆盖，
  每首 ~29 个），E1 manifest 格式（target_unit_ids/units/audio/identity_context）；
- **三机制**：run_multi_realign.py --family R-U/R-S/R-CF --iterations 1
  （smoke 验证通过，全量 963×3 后台运行中）；
- 脚本：scripts/unit_realign/build_bgroup_regions.py。

### 10.29 C 组分窗图问题 review 与修复（2026-08-15）

用户指出 C 系列分窗图"窗口一个叠一个越叠颜色越深"，review 发现两个问题：

1. **渲染错位（manifest 缺原始时钟字段）**：compress 变体 manifest 行未保存
   original_* 字段，渲染把压缩时钟的 core/input（audio_start/end）画在原始时钟
   timeline 上；修复：builder 输出 original_core/input_start/end（投影窗自带），
   渲染 load_window_traces 优先 original_*（对齐结果不依赖这些字段，无需重跑）；
2. **边界叠加（visual_diagnostics.draw_track_windows）**：每窗各画一遍边界——
   相邻窗共享 core 边界、input 虚线撞 core 实线、strict region 粗线压 core 线都
   叠加变深；core 填充还按奇偶窗用不同 alpha（0.075/0.14）。修复：边界位置去重
   （core/input/region 各画一次，重合时优先实线）、填充统一 alpha=0.06。

两处修复后 C 组渲染重跑（bash-86）；A 组（B4|Slot timeline 窗口边界）同问题，
待 C 组完成后用新代码重跑。

### 10.30 分窗图问题二轮修复（2026-08-15，用户指正）

用户指出 Camelia 窗 0 疑似横跨四 lane。根因：`render_full_song` 把全部 track 的
window_trace 并集成**全局 windows**，用 draw_windows 横跨整图绘制（窗框+窗N标签），
与每 lane 自己的 draw_track_windows 叠加。修复：`render_full_song` 加
`--no-global-windows`（全局 overlay 关闭，track 级边界保留）；C 组与 A 组渲染脚本
均传该开关。验证：Camelia pages 全局 windows=0、4 lane has_track_windows=True。
另：A 组（B4|Slot timeline）同样问题，脚本已修，待 C 组渲染完重跑。

### 10.31 C 组修复链（2026-08-15，两子 agent 审查 + 用户逐条定夺）

两子 agent 审查结论：窗口规划算法本身正确；C 组表现差源于实现偏差与交互层缺陷。
用户定夺后的修复链（按"统一规则、数据无关"原则）：

1. **归属改歌词顺序切片**（用户："B4怎么算自己的窗需要什么词，C系列就用同样方法"）：
   C 组窗口词 = B4 同款预算规则（target=max(min, ceil(cps×budget_support×1.35))，
   cps=max(全曲密度, 上窗密度)，budget_support=min(input覆盖, sustained活动)，
   全部在**原始时钟**），从歌词顺序 cursor 连续切片 + line_padding lookahead；
   **完全不依赖 B4 时间/owner**；
2. **P0-B 回映射负时长修复**：压缩时钟塌缩点（start==end）两侧同侧映射；
3. **compress 守卫撤销**（用户："静音压缩发生在推理之前，词不可能掉进被切掉的静音"——
   词时间戳在压缩时钟永远落在 kept segments，回映射绝不进入移除区间；按用户设计
   compress 纯音频后处理）；
4. **strict 截断上限放宽到 250**（用户定；cap150 下 strict 窗少×容量不足丢词，
   cov@250 全歌 >1.0）；compress 保持 150；
5. **audio 时钟分离 bug**：预算用原始 input、runner 裁剪 audio 用压缩时钟
   （曾误把 original 值写入 audio_start/end → 压缩变体 empty audio crop FAIL）。

结果：strict/strict_compress 覆盖率 1.00（13735/13735）、无负时长；compress 0.97
（3 首 cap150 容量不足：权御天下 613/762、难念的经 611/680、伊卡洛斯 457/537）。
MAE vs C1 16-22s 为"顺序切片 vs C1 时间"的固有差异（词序与音频时间不完全对应）。

### 10.32 二轮 review 与 compress 收尾修复（2026-08-15）

二轮 review（2 子 agent）结论与修复：

- **修复正确性审查**：P0=compress 丢尾部词（final 窗 target=N-cursor 被 cap150 截断后
  无后续窗承接；且 global_rate 误用压缩时钟 active_span 致密度虚高）。修复：
  ① final 窗不截断（保留全部剩余词）；② global_rate 用投影前原始 active_span。
  修复后 compress 每歌 union 全覆盖。
- **渲染审查**：P0=祈愿花开"缺失"——实为渲染排序靠后未完成（误报）；P1=Camelia KTV
  2×2 面板音频时长不一（strict/compress 变体时间线短于 C1，属设计产物，backlog）。
  验证通过：窗口注入与 manifest 逐字一致、4 track/无全局 track、PNG 尺寸=160px/s、
  KTV 2×2 正常、已知 B4 脏词/塌缩如实呈现。
- **最终质量**：strict/strict_compress/compress 三变体全部 13735/13735=1.00 全覆盖、
  无负时长（compress 重跑后）。

---

## 11. 串行 vs 独立、短窗实验与 B4 依赖核查（2026-08-15 晚 – 08-16 凌晨）

本节记录 10.32 之后直至本节的会话内容。主线：3 首中文歌 full-slot 串行 vs 独立对比 →
短窗（时间聚类）实验 → 用户连续质疑（字幕重叠、short 串行重叠窗、B4 依赖、纯音频短窗、
"长窗短窗同一逻辑"）→ 最终修正概念：短窗不是"独立完整方案"，是同一逻辑下的精度增强，
粗定位来自第一遍 60s 对齐而非 B4。

### 11.1 3 首中文歌：full-slot 串行 vs 独立（2026-08-15 晚）

用户要求对比"slot 方式串行 vs 非串行"，并指出我之前看错了对象（看了 B4 pre-slot 而非
full-slot 串行）：

> "我要你看slot方式串行和非串行，你怎么看起来非slot了。重新看文档。"

实现 `run_testdemo_slot_serial.py`（full-slot + 串行 commit 状态机，窗口=lyric-order
切片 + B4 budget 规则），在 祈愿花开/人造卫星/本草纲目 3 首上跑：

- 串行 vs C1（独立）MAE：0.36 / 0.40 / 0.16s；两 lane 均为 `decoder_kind=official`；
- 窗口输入连续无 gap 时，串行与独立几乎一致（MAE <0.4s）；串行 commit 的收益只在
  strict（gap）窗口下显现；
- 渲染：`serial_compare_DELIVER/`（3 首 timeline + KTV）。

### 11.2 用户质疑"怎么到这里变成这样了"，短窗实验启动（2026-08-15 晚）

用户回忆 slot 32ms 级效果、08-13 unit-realign 812ms，对比当前 60s 长窗 full-slot 的
10s 长词/堆叠，问"812的实现我印象中slot效果还不错啊，怎么到这里变成这样了"。

核实历史：

- sparse-slot 32.43ms vs full 32.69ms 只在 MIR-1K 短歌（57-87s）上有效，未验证 90s+；
- 08-13 unit-realign 812ms 来自**短窗**：audio crop mean 8.9s、文本 0-5 units；
- 20260804 模型舒适度排序：短上下文最佳、cropped-serial-complex 次之、full-context 最差。

推断：当前 C1/Current（60s 长窗 full-slot，100+ 单元/窗）超出模型舒适区 → 复刻 08-13
短窗机制验证。

### 11.3 短窗实验 v1：行级窗口（失败）与 v2：时间聚类（部分成功）

- **v1 行级窗口**（`build_testdemo_shortline_manifest.py`，每行一个窗口）：MAE vs B4
  1.96s、重叠 46。失败根因：B4 时间戳把同一行拆到两个重复 occurrence（祈愿花开 L14：
  g105-107@62s、g108-110@73.6s），行级音频裁剪跨两个 occurrence → 模型漂移；
- **v2 时间聚类**（`build_testdemo_shortcluster_manifest.py`，按 B4 start_sec 聚类、
  ≤8 单元/窗）：先按时间排序切簇失败（把跨 occurrence 的字符连在一起），改为按 **id 序 +
  时间连续性**切簇；音频裁剪发现 B4 end_sec 也被污染（g107 end=73.62 落在第二
  occurrence），裁剪只信 start_sec；pad=3s 时模型把文本压向窗口开头（46% 字符落在
  窗口头 10%）→ pad 改 0.5s（对齐 08-13 `audio_margin_sec=0.5`）→ MAE vs B4 降至
  0.10-0.17s、最大时长从 10.8s 降至 1.04-1.60s（10s 长词消失）。

### 11.4 用户质疑：official 不可能出现字幕重叠（2026-08-15 晚，重要）

用户："怎么做到这次反而出现了连字幕都重叠的，official的设计上不可能出现这种情况。"

核查 transformers `_fix_timestamps`（qwen3_asr processing）：官方对**单次 forward**
输出用 LIS 修复保证非严格单调（`data[prev] <= data[current]`，允许相等、绝不逆序）。
**用户正确**——单窗口内官方不可能重叠。

根因：短窗是**多窗口独立 forward 后 merge**，跨窗口无单调保证。证据：g146（窗口 C19，
audio 89.44-94.92）输出 93.60-94.08；g147（窗口 C20，raw_local_start=0.0）输出
93.60-94.40；两窗音频重叠（93.6-94.92），merge 后 g147.start < g146.end → 字幕堆叠。

修复：`run_testdemo_slot_infer.py` merge 阶段加**跨窗口全局单调化**（官方 snap 语义
扩展到整首歌：按 global id 序把每行 span 推到 ≥ 上一行 end），identity 记录
`monotonic_fix`。修复行数 59/73/117，重叠 46/44/73 → **0/0/0**；未触碰行 MAE
0.039-0.053s（被推行的位置恰是 B4 参考本身重叠处，B4 有 9/7 处跨行重叠）。

### 11.5 用户看到 short 串行大量重叠窗（2026-08-15 晚）

用户："我看到short串行出现很多重叠窗，怎么回事？把之前几个slot的行为详细列出来，
我感觉我们的理解出现了偏差。"

核查 `shortcluster_serial`（`run_testdemo_shortline_serial.py`）window_trace：**100 窗、
core 时间回跳 7 处**（wi=21 core_end=71.4 → wi=22 core_start=62.0，回跳 9.4s）、
22 窗 committed=0。三层根因：

1. **窗口顺序 bug**：runner 按 manifest 行序（=id 序）处理窗口，但 B4 时间戳重复歧义
   导致 id 序 ≠ 时间序 → 渲染时窗口框重叠；
2. **旧 manifest**：shortcluster_serial 是 20:28 跑的（当时 manifest 还是 290 行旧版，
   聚类按"簇首 gap"每 2s 切簇的 bug 版），20:50 聚类修复后才重建为 212 行；
3. **committed=0 的 22 窗**：cursor（按 id）与窗口 core 时间乱序冲突。

同期列出各 slot 方案行为（详细对比写入 `short_window_DELIVER/SLOT_BEHAVIOR_COMPARISON.md`）：
B4（4 窗时间序）/ Current 60s 串行（4 窗 core 衔接，无回跳）/ Short 独立 v3（68 簇）/
Short 串行（100 窗，id 序，回跳 7 处）——**串行 commit 状态机依赖窗口时间单调推进，
短窗簇不满足**。

### 11.6 strict/compress 行为线核查：单元-音频错位（2026-08-15 晚，重大发现）

用户："还要再之前，从我们开始渲染strict和compress开始。"

核查 strict/compress/strict_compress（60s 长窗变体，`build_testdemo_slot_variant_manifest.py`）
发现**设计性错误**：窗口（严格静音硬切/压缩时钟）与单元归属（lyric-order budget）
互不约束 → 窗口音频装不下自己的单元：

| strict 窗口 | 单元 B4 时间范围 | 窗口音频范围 | 音频外单元 |
|---|---|---|---|
| wi=0 | 14.7-67.6s | 14.64-47.64s | 27 |
| wi=1 | 61.9-177.2s | 54.5-121.08s | 94 |
| wi=2 | 174.8-252.5s | 101.08-146.68s | **170（全部）** |

wi=2 的 170 个单元全部唱在 174.8s 之后，但窗口音频只有 101-146.7s → 模型听不到歌词、
把 170 字符全压到窗口末尾 → MAE vs B4 32.5s（235/463 字符 Δ>10s）。compress 另有
65.6s 伪长词（压缩时钟回映射）。**当时只渲染未做 MAE 评估，问题被掩盖**——教训：
任何方案先定量评估再渲染。Current 60s 串行无此问题（core 严格衔接覆盖全歌）。

### 11.7 用户质疑 B4 依赖（2026-08-15 晚，概念纠正）

用户："所以和B4到底有什么关系，从来都没有会需要用b4的时候，这是独立的。"

核查代码确认（用户正确）：

- **shortcluster 完全依赖 B4**：聚类、音频裁剪、单元时间全部来自 B4 `selected_start_sec`
  → "MAE vs B4 = 0.04s"是循环论证（窗口按 B4 切，模型在 B4 附近细化）；
- **serial3（我一直当 Current 用）也读 B4 文件**：`run_testdemo_slot_serial.py` 直接
  `b4d.get("window_trace")`——虽然 B4 的 window_trace 本就是纯音频计划的产物（数据流
  上没引入模型信息，行为等价），但数据流上确实依赖了 B4 文件；
- **strict/compress builder 的窗口是独立的**（vocal activity 驱动），只有单元 start_sec
  字段带 B4 值（仅诊断）。

### 11.8 纯音频驱动短窗（失败，验证了"需要粗定位"）（2026-08-15 晚）

用户："什么叫纯音频驱动短窗，为什么短窗就需要b4时间戳"

实现 `build_audio_short_manifest.py`：窗口=音频活动静音间隙切分，单元=歌词顺序+活动
时长占比分配，全程无任何对齐时间戳。修复 active 数组时间原点 bug（索引 i 对应
i*hop_sec 而非 first_sustained_activity_sec）后重跑：**MAE 15-45s，失败**。

失败机制：比例分配假设歌词均匀分布在活动音频上，但歌曲不均匀（前奏无词/副歌密集）——
A0 窗口 0-10.9s 活动少只分 1 字符，但 g0 实际唱在 14.7s（A1 音频里），模型找不到它。
**结论：短窗的"窗口是哪些歌词"必须精确，纯比例猜测不行。**

### 11.9 用户："过去的串行也不依赖先跑一遍，为什么这个反而依赖要先跑一个对齐出来"

回答：长窗（60s）能单遍是因为窗口大、budget 归属误差被窗口内官方 LIS 自洽吸收
（错 2-3 字符无碍）；短窗（8-21 字符）错 1-2 字符 = 20% 错配，无冗余可自愈。
08-13 unit-realign 同样依赖正式 run 输出（detector 定位），不是单遍方案。

### 11.10 用户："根本没有什么细化器，不管长窗短窗都是一样的逻辑"（2026-08-16 凌晨）

用户最终拍板：长窗短窗是同一套逻辑。据此实现 `run_independent_60s.py`（**完全无 B4**：
`build_silence_aware_window_plan` 音频窗口 + budget + full-slot + 串行 commit），并
参数化 `--target-core-sec` 验证 12s 短窗同一逻辑：

- **独立 60s 一遍**：MAE vs B4 0.36/0.40/1.17s，覆盖率 1.0（本草纲目差异来自 core
  边界提交归属，与 B4 无关）；与 serial3 差异 0.001-0.004s → 证明 serial3 读 B4 trace
  不引入模型信息，但数据流应改为直接调 planner；
- **独立 12s 一遍**（同一逻辑）：MAE 6-28s，失败。逐层修复暴露三个 60s 冻结参数在
  短窗下的问题：
  1. budget_support 用 input 跨度（22s）→ 查询密度 = cps×(input/core) 爆表（78 字符
     压进 12s 窗）→ 改 core 跨度（`--budget-covered-core`）；
  2. MIN_TARGET=64（B4 冻结，60s 窗 108>64 不生效；12s 窗 64>28 过量）→ 按 core 缩放
     （`max(4, round(64×core/60))`）→ commit 雪崩停止（w2 曾 78→117→171）；
  3. `future_character_ratio=1.35` + `line_padding=1`（60s 超查学上下文）→ 12s 窗超查
     43 字符 vs core 容纳 21 → g26-30（唱在 27-28s）被 w0 抢走压缩 → 短窗改 ratio=1.0、
     padding=0 → 每窗 21 字符稳定；
- 最终 12s 独立仍 MAE 6-28s：**重复歧义处 budget 归属错位累积**（"是贪婪的甜蜜"在
  127s 和 138s 各唱一遍，budget 按 id 顺序切片与音频时间行进冲突；60s 大窗自校正，
  12s 小窗漂移累积 g170→g410 +3.8→+30s）。

### 11.11 最终结论（2026-08-16 凌晨，本节点）

1. **长窗短窗是同一套逻辑**（音频窗口 + budget + full-slot + 串行 commit），不存在
   "细化器"特殊机制；
2. **短窗不需要 B4**：它需要"窗口与歌词的精确对应"；独立一遍（budget 按 id 顺序）在
   重复歌词处做不到精确（12s 崩）；
3. 精确对应两条路：**大窗口**（60s，窗口内自校正，一遍就好，MAE 0.36s）→ 或
   **第一遍粗对齐 + 短窗**（60s 一遍得粗时间戳 → 聚类短窗 → 0.04s）——粗定位来自
   第一遍自己，不是 B4；
4. 正确产品结构：`run_independent_60s.py`（独立 60s，0.36s）→ 可选短窗增强（0.04s）；
   B4 只作历史参考，永不作为输入；
5. 此前错误：① 把 B4 当短窗粗定位（循环）；② 把短窗包装成"独立完整方案"；③ serial3
   数据流读 B4 文件（行为等价但应改直接调 planner）。

### 11.12 交付与脚本（2026-08-16 凌晨）

- `short_window_DELIVER/`：4 泳道 timeline（B4|C1|Short独立|Short串行）+ 4 面板 KTV +
  `REPORT.md` + `SLOT_BEHAVIOR_COMPARISON.md` + `SLOT_BEHAVIOR_TIMELINE.md`；
- 新脚本：`run_testdemo_slot_serial.py`、`build_testdemo_shortline_manifest.py`、
  `build_testdemo_shortcluster_manifest.py`、`run_testdemo_shortline_serial.py`、
  `build_audio_short_manifest.py`、`run_independent_60s.py`、`compare_short_window.py`、
  `render_short_window.py`、`render_short_ktv.py`；
- 修改：`run_testdemo_slot_infer.py`（跨窗口全局单调化 + lyrics_path 支持）。

### 11.13 三组对比实现核查：B4 vs slot / mech / recover（2026-08-16 凌晨）

用户要求："核查之前代码中，对B4 vs slot、mech、recover三个不同对比的实现是否正确，
是否过度依赖。"

#### A 组（B4 vs slot）—— 正确，B4 依赖是设计使然（不是过度）

- `build_testdemo_slot_manifest.py`：**完全复用 B4 的 window_trace、owner_window_index、
  单元时间戳（selected 几何）、document**，唯一差异是查询语义（full-slot 一次查全部
  vs pre-slot 串行 cursor）；
- 这是 9.7 用户确认的公平对比设计（"窗口、单元空间、解码器与 B4 完全一致，唯一差异
  是查询语义"）——**控制变量的对比必须依赖 B4**，实现与设计一致；
- 注意：A 组的 slot lane 因此**不是独立产品方案**（依赖 B4 窗口/单元/文档）；若要作为
  Current 独立方案解读，应改用 `run_independent_60s.py`（11.10）。对比结论（slot vs B4
  差异来自查询语义）仍有效；
- 固有属性：B4 塌缩歌（冬之花等）的 slot 会继承塌缩错误——对比的必然，非 bug。

#### B 组（mech：R-U/R-S/R-CF vs full）—— 正确，主路径不依赖 B4

- 困难区来源：Detector V2 对 **C1 alignment 的 O 特征**打分（`build_bgroup_regions.py`
  train/score 全用 C1 输出，无 B4）；
- region 构造：units 时间戳来自 C1（selected_start_sec）；`owner_window_index` 从 B4
  解析但**仅用于 region_id 命名**（`w{win}:unsafe:N`），`--b4-root` 为可选参数，
  不影响机制行为（baseline/candidate 对比）；
- forward：`run_multi_realign.py` / `run_forward_real.py` baseline rows 来自 region
  自带 units（即 C1/detector 输出），candidate 来自 executor 新 forward；
- 渲染：`render_current_4way.py` / `render_comparison_batch.py` 读 frozen evidence
  payloads，按 family 分 lane，窗口 trace 各 lane 独立——正确。

#### recover 组（closed-loop / E5/E7/E8 / oracle / E4）—— 独立，不依赖 B4

- `run_closed_loop_forward.py` / `build_closed_loop_routes.py` / `evaluate_e5/e7/e8` /
  `evaluate_oracle.py` / `run_e4_episodes.py` / `report_closed_loop.py` **零 B4 引用**；
- `build_resolved_baseline.py` 只登记 B4 基线元数据（sha/role/source）供对照，不是输入；
- baseline/candidate 证据来自 region units + executor forward（`run_forward_real.py`），
  identity 内容寻址——独立且正确。

#### 核查结论

| 组 | 实现正确 | B4 依赖 | 性质 |
|---|---|---|---|
| A B4 vs slot | 是 | 窗口/单元/文档全用 B4 | 设计使然（公平对比控制变量，9.7 定案）|
| B mech | 是 | 仅 region_id 命名（可选参数） | 可接受（不影响机制）|
| C strict/compress | 是（11.6 已修） | 窗口独立（音频驱动） | 无 |
| recover | 是 | 无 | 独立 |

唯一需要修正的概念：A 组 slot lane 不是独立方案，Current 独立入口应为
`run_independent_60s.py`（11.10 已建）。所有对比的实现与设计一致，无过度依赖。

### 11.14 修正：按 20260812 Codex 框架对齐 + 0813 formal 结果对比（2026-08-16）

用户要求："现在修正，必要的时候跑0812的结果进行对比。"

#### 修正点（对照 11.13 的差别清单逐项落实）

1. **主输出视角补 Raw**：Codex 20260812 冻结 Raw 为主线主输出。给
   `compare_short_window.py` 加 `--geom raw|official|selected`，全部方案重评 raw 几何
   （同一 forward 的 `raw_global_start_sec`，未做 LIS 修复的原始解码）：

   | 歌曲 | short vs B4 (selected) | short vs B4 (raw) | C1 vs B4 (selected) | C1 vs B4 (raw) |
   |---|---|---|---|---|
   | 祈愿花开 | 0.397 | **0.122** | 0.362 | 0.372 |
   | 人造卫星 | 0.292 | **0.108** | 0.401 | 0.402 |
   | 本草纲目 | 0.487 | 0.619 | 0.161 | 0.165 |

   raw 视角下 shortcluster 在 2/3 首歌 MAE 显著更低（0.11-0.12s vs 0.29-0.40s）——
   短窗细化对 raw 原始输出的一致性比 official 修复后更好（monotonic fix 主要动
   selected/official 几何，raw 保留原值）。本草纲目 raw 仍 0.62s（重复歧义继承）。

2. **短窗定位修正**：短窗 = realign 执行方式（Codex 允许变量 C："selected short-window
   size/context"），不是独立主对齐方案。主对齐永远是 60s silence-aware 长窗；
   短窗只应在 detector 发现的 unsafe region 上执行（08-13 unit-realign 的 R-U 结构）。

3. **评估口径修正**：B4 是历史对照 lane，不是 GT；"MAE vs B4 0.04s"是"与基线一致"，
   不是 correctness。正确评估 = 四类指标（target correctness / context safety /
   region-event / no-GT），GT 只进 evaluate_*。

#### 0813 formal（M4Singer，有 GT）对比——短窗 realign 的真实能力

08-13 unit-realign formal（78 regions，R-U/R-A/R-B/R-S，GT 评估）：

- unit 级：718 rows，improved=255（39.9%）、unchanged=173、regressed=211（33.0%）；
- **region 级：beneficial=20（25.6%）、neutral=7、harmful=0、catastrophic_harmful=51（65.4%）**；
- 按 family：R-U catastrophic 13/23、R-S catastrophic 16/23、R-A 16/23、R-B 6/9；
  beneficial：R-U 7、R-S 5、R-A 5、R-B 3。

**含义**：短窗 realign（无论哪种 family）在 M4Singer 困难区上**整体有害**（65% region
灾难性变差），只有 ~26% 改善。这与 20260812 讨论"模型常落入错误但稳定的吸引域"一致；
812ms 是 onset MAE 的**平均值改善**（2534.7→812.5），但**不能代表 region 级 correctness
恢复**——平均改善被少数大改善 case 拉低，多数 region 反而更糟。此前的"slot 效果很好"
记忆需要按此口径修正：短窗的**均值改善**真实存在，但**困难区修复成功率低**。

#### B 组机制（33 首 test-demo，无 GT，结构信号）

| family | regions | ok | not_constructible | mono_improve | collateral_harm |
|---|---|---|---|---|---|
| R-U | 851 | 1702 | 112 | 249 (29%) | **851 (100%)** |
| R-S | 426 | 588 | **801 (83%)** | 162 (38%) | **0** |
| R-CF | 800 | 1600 | 163 | 200 (25%) | **800 (100%)** |

- R-U/R-CF 全部 collateral（动了窗口内全部单元）；R-S collateral=0（fixed context 保护，
  与 0813 结论一致：R-S context safety 最好）但 83% 无法构造（non_monotonic_fixed_timeline）；
- 无 GT 只能看结构信号，不能判 correctness——B 组是机制可行性证据，不是恢复能力证据。

#### 修正后结论

1. 主输出视角 = Raw（Codex 冻结），official 仅 shadow；短窗细化在 raw 视角与 B4 一致性
   更好（0.11-0.12s）；
2. 短窗 = realign 执行方式（R-U 结构），主对齐 = 60s 长窗；不得再把短窗当独立主对齐方案；
3. 0813 formal 证明：短窗 realign 的 region 级成功率仅 ~26%、catastrophic 65%——
   "slot 效果好"只对均值成立，对困难区修复不成立；
4. B4 只作对照 lane；评估分四类指标，GT 只进 evaluate；
5. 后续正确结构：`run_independent_60s.py`（独立 60s 主对齐，raw 主输出）→
   Detector V2（unsafe region）→ 短窗 realign（R-U 式，≤3 target + 0.5s margin）→
   四类指标评估。

### 11.15 baseline 可比性核查：当前 baseline vs 0813 baseline（2026-08-16，决定性）

用户要求："去比较当前baseline和0813的baseline的结果，看看当前baseline会不会差别很大，
暗示着实现问题或者设计问题的可能性"（不是比 realign，是比 baseline 本身）。

#### 方法

在**同一首歌**（全世界失眠，M4Singer cohort_b）上用**当前仓库**复现 0813 的 3 个
full 窗口请求（固定 60s 网格：w0=[0,60]、w1=[67.64,127.64]、w2=[135.28,195.28]，
full-slot，同 R2 checkpoint），与 0813 evidence（stage3b_cohort_b_dev/evidence）逐字符
对比，并同时对比 real-GT（LONG_TIMELINE_MANIFEST）。

脚本：`compare_baseline_0813.py`。期间修复一个对比 bug：0813 evidence rows 的
`global_character_index` 是**窗口局部索引**，需经请求 `canonical_to_local` 反映射为
歌曲全局 id（w0 局部==全局碰巧正常，w1/w2 因此曾误报 MISSING）。

#### 结果（251 字符逐字符对比）

| 窗口 | audio | n_units | MAE cur vs 0813 | MAE cur vs GT | MAE 0813 vs GT | Δ>0.5s |
|---|---|---|---|---|---|---|
| w0 | [0, 60] | 87 | **0.0** | 0.439 | 0.439 | 0 |
| w1 | [67.64, 127.64] | 86 | **0.0** | 0.478 | 0.478 | 0 |
| w2 | [135.28, 195.28] | 78 | **0.0** | 0.539 | 0.539 | 0 |

#### 结论

1. **无实现漂移**：当前仓库 `infer_slice` 对同一请求的输出与 0813 evidence 逐字符
   完全一致（MAE 0.0，251/251）——同一 checkpoint 下 current 实现忠实复现 0813；
2. **差异是设计层面的**：0813 baseline = research_v7 固定 60s 网格窗口
   （semantic_window_planning + slot_planning，窗口间有 7.6s 空隙），当前
   serial3/independent_60s = silence-aware 60s+10+10（core 严格衔接）——两套窗口
   计划不同，窗口边界/单元归属/音频裁剪都不同，**结果不可直接混用**；
3. **两个 baseline 与 GT 的 MAE 相同**（cur==0813 自然相同）——这本身说明 0813 的
   baseline 质量与当前 silence-aware 在同曲上不可比（不同窗口）；若需要公平的
   baseline 对比，必须在同一窗口计划下比较（如都用固定网格，或都用 silence-aware）；
4. 20260812 冻结文档写"正常串行 baseline = 60s silence-aware serial"，但 0813 formal
   实际执行用固定 60s 网格——**冻结文档与 0813 实际执行不一致**，这是文档/实现
   跟踪问题（已记录，后续统一口径时需确认哪一个是 authoritative）。

---

## 2026-08-16 A/B/C 组重跑与渲染进展（checkpoint 后补充）

### 用户最终决定（A 组）
- A 组 4 lanes：B4 历史 | full-slot fix60 串行 | full-slot soft 串行 | full-slot strict 串行，
  全部**自行推进**（不复用 B4 alignment/window_trace/owner）；
- 正常推进 = 串行 commit（cursor + core 边界）；fix60 = 无静音吸附但有 10s 前后上下文；
  soft/strict 窗口参数沿用现有定义；textmode3 不保留；
- 推进全部用 raw 时间戳，最后 **official 全局合法化**：收集全曲 committed rows 的
  raw start/end（2N 交错数组），对整首歌一次性跑 transformers `_fix_timestamps`
  （LIS 单调修正，允许相等，保证无逆序）。
- 用户明确：official 也必须是**全局**修正，不是每个窗口局部修正（早期实现 bug 已修）。

### A 组执行与渲染（已完成）
- `runs/20260816_agroup_v2_legal/`：33 首歌 × 3 plans（fix60/soft/strict）全部完成，
  propagation_view=raw、output_view=official、legalization=global_fix_timestamps_2N，
  coverage 1.0、0 failure；
- 全局合法化验证：TH讠NK 全曲逆序对=0、正时长重叠对=0（g166/g167 由 [61.54,73.06] 重叠
  修正为 [72.04,72.38]/[72.72,73.06]；g65/g66 相等 22.64 合法保留）；
- 渲染（用户要求：只要 timeline 图 + 字幕视频，不要 raw lane、不要 timeline 视频）：
  `20260816_agroup_BC_DELIVER/` images/A_v2_*.png 33 张 + videos/A_v2_KTV_*.mp4 33 个。

### B 组（机制实验，fix60 legal 基线）
- region 池：`20260816_agroup_v2_legal/BGROUP_REGIONS_fix60.jsonl` 884 regions
  （build_bgroup_regions.py --c1-root fix60 legal baseline + --audio-map bgroup_audio_map.json）；
- 挂起根因排查：run_multi_realign 全量 884 曾挂起（当时 3 mech + render 并发抢 GPU）；
  改为 **17 × 50 regions 批次顺序执行**（独立 out-root、timeout 保护、每 batch ~1min），
  batch1 50 regions 完整成功 → 确认非代码路径问题，是资源竞争；
- 加了 per-region 进度日志（run_multi_realign.py print [progress]）；
- 3 families × 17 batches 后台顺序运行中（bgroup_R-U/R-S/R-CF_b1..17）；
- 合并脚本 merge_bgroup_batches.py + 汇总图 render_bgroup_summary.py 已就绪。

### C 组（strict/compress 2x2，保持不变）
- 对齐数据已在 `20260815_slot_v2/align/`（strict/compress/strict_compress 各 33 首）；
  C1 base = `20260815_slot_vs_b4/align`；
- render_slot_variants.py 改造：去掉 timeline 视频（render_full_song.py 新增 --no-video），
  只保留 timeline PNG + 2x2 KTV mp4；smoke（Camelia）验证通过；
- 33 首全量渲染后台运行中，输出追加到 `20260816_agroup_BC_DELIVER/`。

### 待办
- B 组批次跑完 → 合并 → BGROUP_SUMMARY.json/png；
- C 组渲染完成核对；B/C 交付核对；
- 3M evidence pack（旧请求，仍未做）。

### 2026-08-16 B/C 组执行与渲染完成（后续补充）
- B 组 884 regions × 3 families 全部完成(18 批次,每批 ≤50 regions,timeout 保护,
  全部 exit=0,0 failed);期间发现并修复:
  - 批次切分 bug:884 regions 被切成 17×50=850,漏了最后 34 个 → 补 batch18;
  - merge 脚本去重 bug:TRAJECTORY 按整行 JSON 去重会误删指标相同的 region 行
    → 改为 verbatim 拼接(batch 间 region 不重叠);
  - nc 统计口径:request_identity 是 sha256,region 级 nc 需用 RUN_STATE nc identity
    匹配 REQUESTS 行反解 song/region。
- B 组最终指标(region 级,输入 884):
  - R-U: agg=777, nc=41, ok=87.9%, collateral 100%, monotonic 27.5%, osc 22.5%,
    catastrophic 0.1%, recovered 0%
  - R-S: agg=453, nc=164, ok=51.2%, collateral 0%, monotonic 36.9%, osc 0%,
    catastrophic 0%, recovered 0%(稀疏机制保护上下文,但构造率最低)
  - R-CF: agg=734, nc=43, ok=83.0%, collateral 100%, monotonic 26.4%, osc 14.4%,
    catastrophic 6.8%, recovered 0%
- C 组渲染完成:33/33 首,images/C_variants_*.png + videos/C_variants_KTV_*.mp4,
  0 失败(render_cgroup.log RENDER_DONE=33);
- 交付目录 `runs/20260816_agroup_BC_DELIVER/`:
  - images: A_v2_*.png 33 + C_variants_*.png 33 + BGROUP_SUMMARY.png
  - videos: A_v2_KTV_*.mp4 33 + C_variants_KTV_*.mp4 33
  - BGROUP_SUMMARY.json(指标表)
- 新增/修改脚本:
  - render_full_song.py 新增 --no-video(跳过 timeline 视频)
  - render_slot_variants.py 去掉 timeline 视频输出
  - merge_bgroup_batches.py(B 组批次合并)
  - render_bgroup_summary.py(B 组汇总表 + 图)
  - run_multi_realign.py 增加 per-region 进度日志
- 遗留:3M evidence pack(旧请求,仍未做)
