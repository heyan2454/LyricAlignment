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
