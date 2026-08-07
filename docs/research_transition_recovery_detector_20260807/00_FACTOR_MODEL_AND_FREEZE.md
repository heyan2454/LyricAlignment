# 系统分层与冻结设置

- 日期：2026-08-07
- 状态：设计冻结；实现 agent 必须先做 existing-implementation mapping，再 formal

## 1. 为什么重新分层

本轮讨论确认：此前把 slot、serial、stable-window、detector 和 recovery 混成“串行系统”会导致实验解释不清。

正确分层为：

1. **Audio preprocessing**：原曲是否压缩超长静音；
2. **Window planner/handling**：窗口在哪里、静音如何吸附、纯静音/前导静音/短尾窗怎么处理；
3. **Window input construction**：实际送入模型的左右上下文与 core；
4. **Align query**：模型查询时间戳的方式，slot 与 non-slot；
5. **Decoder**：raw / official 等如何把模型输出转为对齐行；
6. **Transition**：当前窗结果怎样形成下一窗状态，包括是否串行、提交边界和推进规则；
7. **Detector**：无 GT 风险判断；
8. **Recovery/control**：检测到危险后是否仅 shadow、局部重做或整窗回退。

Slot 是 **Align query**，不是串行方式；Commit policy 与“下一窗从哪里继续”高度耦合，因此并入 Transition/串行策略，不再单列为主实验轴。

---

## 2. Audio preprocessing

### A0 Original

不修改原始时间轴。用于少量对照，尤其检查长静音压缩是否与 silence snap 发生不良交互。

### A1 Long-silence compression — 主线

用户当前倾向：压去过长静音，但不压成 0，保留约 3–5 秒作为结构和重新入声的上下文。

首版规则：

- 仅压缩超过阈值的长静音；阈值不得在 formal 后看结果临时调整；
- 被压缩的静音保留长度先 pilot `3 s` 与 `5 s`，若无实质差异冻结一个中值/更稳值；
- 必须输出 original time ↔ compressed time 的单调映射；
- 所有最终对外 timestamp 必须能恢复到 original timeline；
- 不能因压缩导致歌词活动区被切除；
- 对长前导静音同样适用，但仍需保留足够的静音 anchor。

A0/A1 只在少量代表 Transition 上做对照，不进入全矩阵。

---

## 3. Window planner / handling

### 主 planner：silence snap

- nominal core = 60 s；
- 在 nominal boundary 附近有限搜索静音/低活动区；
- 吸附不能跨过明显歌词活动区；
- 不能为了吸附制造过短 core；
- 保存 nominal boundary 与 actual boundary。

### 小对照：fixed window

仅用于分离 silence-aware planning 的收益，不作为大矩阵。

### 必须统一处理

- `skip_silent_windows`：纯静音窗不做无意义 align；
- `leading_silence`：长前导静音不强迫首个有效 core 从 0 开始；
- `tail_window`：尾窗过短时重分配/合并，避免极短尾窗；
- 英文不得把单词切断；日文不得切断 processor 的最小对齐 unit。

Strict / forced silence boundary 只做少量困难 case，不作为主 planner。

---

## 4. Window input construction

正式主线固定：

```text
left acoustic context = 10 s
core                  = 60 s
right lookahead       = 10 s
```

即典型最多约 80 秒音频观察区。

语义：

- left 10 s 是声学前文，不代表可再次覆盖已永久提交歌词；
- core 是当前主要 ownership 区；
- right 10 s 是 lookahead / 边缘判断信息，不应自动永久写回；
- 每个 request 必须保存实际 left/core/right 边界。

除专门 context sensitivity 研究外，不再变化此结构。

---

## 5. Align query

### Q0 Full-slot — 主线

正式绝大多数实验使用 full-slot。含义必须以当前实现的 canonical slot mapping 为准，并在 P0 mapping 中写清：给定 query text/context 后，当前目标 region 的所有目标 units 均有 timestamp slots。

必须保存：

- canonical unit id；
- slot id；
- occurrence id（若可定义）；
- query text span；
- timestamp output row 映射。

### Q1 Non-slot — 少量对照

只在以下位置使用：

- transition product candidate；
- 必要时再加 mechanism candidate。

目的只回答：full-slot 的优势来自单窗 Align 本身，还是对 state transition 的稳定性也有帮助。

不得把 non-slot 再与所有 Audio/Transition/Recovery 组合。

---

## 6. Decoder

### Raw — 研究主输出

- 保留原始 posterior / timestamp distribution；
- 作为 detector 新信号、sequence、cross-window、competing-path 的主要证据；
- 关键 formal 默认必须保存 raw。

### Official — 次选 / 需要时输出

- 用于与现有产品型结果、历史结果对照；
- 当 transition 当前实现依赖 official 时允许作为执行 decoder；
- 作为次选输出，不作为主要 detector 特征家族继续扩展；
- 若一次 forward 可以低成本同时得到 raw/official，应共享 forward，不重复推理。

本阶段不把 decoder 当主实验轴。新 decoder 只有在独立 qualification 后才可加入。

---

## 7. Transition：四种正式行为类别

### T0 Independent / non-serial

核心定义：当前 window 的执行不继承上一 window 的预测 alignment state。

**重要**：Agent 必须先映射当前代码中已经实现的 non-serial 行为。若现有实现需要 GT/canonical oracle 才能决定每窗 query start，则必须明确命名 `oracle-independent`，只作为诊断上界，不能伪装成可部署 non-serial 产品方案。不得为了凑 T0 自行发明未验证的 query-start 规则。

### T1 Direct serial

前窗实际输出/提交状态直接用于下一窗推进。作为最直接传播机制基线。

必须明确记录：

- lyric cursor 来源；
- audio/time cursor 来源；
- boundary ownership；
- 什么结果算永久 commit；
- 当前实现是否使用 raw 或 official 结果控制推进。

### T2 Core + boundary serial

以 core ownership / boundary 规则推进；right lookahead 不直接成为永久结果。Agent 必须绑定到已有实现的真实行为，并写清“boundary 从哪里取、跨界 unit 属于谁、下一窗文本从哪里开始”。

### T3 Stable-boundary serial

只推进到当前实现定义的 stable boundary；stable boundary 后区域下一窗重新求解。

本阶段**不要求**实现复杂独立的 provisional-tail state。若当前代码只是“stable boundary 后不永久提交，下一窗重新看”，就按此真实语义实验，不得把它包装成更复杂机制。

### Existing implementation mapping gate

Formal 前必须生成：

```text
TRANSITION_IMPLEMENTATION_MAP.md
TRANSITION_IMPLEMENTATION_MAP.json
```

逐个列出 T0–T3：

- 对应已有脚本/函数/配置；
- 实际 cursor/commit/boundary 行为；
- 使用的 decoder；
- 是否已有测试；
- 与上述语义是否完全一致。

若不一致，先报告并做最小修复；不得静默改名或混用多个旧实现。

---

## 8. Recovery / control：四种行为

### C0 None

不依据 detector/recovery 改变执行。所有 Transition 首先在 C0 下比较。

### C1 Shadow

计算 detector/recovery 建议，但 `actual_writeback = 0`。Shadow 不得改变：

- committed rows；
- cursor；
- window trajectory；
- 下一 request；
- baseline cache identity。

### C2 L — Local recovery

保留从当前 cursor 开始的连续可信部分，只重做 unresolved / unsafe gap；gap 后方结果不能越过 gap 推进主 cursor。

### C3 W — Whole-window recovery

危险窗口整体不提交，从已冻结的稳定 anchor / retry point 重跑。REJECT 触发的 W 必须满足 `committed_count == 0`（针对该 retry decision 所控制的当前待提交区域）。

Recovery 的正式 closed-loop 只在 Transition 主实验选出的少数候选上跑。

---

## 9. 当前不冻结为主轴的设计

以下保留为后续机制实验，不进入首轮正式矩阵：

- strict silence boundary；
- sparse / non-contiguous slot；
- 更多 decoder；
- context 0/5/20 s 大量组合；
- boundary unit ownership 多版本；
- 独立复杂 provisional-tail state；
- 更多 recovery variant（context reset / silence re-anchor）——只有 L/W 后发现必要才增加。
