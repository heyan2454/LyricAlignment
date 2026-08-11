# 冻结 Baseline 与本轮实验边界

- 日期：2026-08-12
- 状态：强制冻结。除明确列出的 Realign / Raw detector 变量外，Agent 不得重新展开旧大消融。

## 1. 用户最终决定

用户明确：

> “除了我们要实验的realign部分和已经有成果的raw的detector，你应该沿用之前的决定好的baseline。”

因此本轮不是重新选择系统架构，而是在已有系统上研究 recovery。

---

## 2. 必须继承的基础行为

### 模型

- 沿用当前已冻结/正在使用的 Qwen ForcedAligner checkpoint 与 processor；
- 不训练、不微调、不换模型；
- model identity 必须写入 resolved config 和 candidate cache key。

### Align query

- 沿用此前选定的 **full-slot 主线**；
- slot 与 serial 不是互斥概念；本轮不得重新做 slot vs non-slot 全矩阵；
- 若现有 baseline wrapper 有更精确命名，以当前仓库已冻结 config/implementation mapping 为准，但不得借 mapping 重新做性能筛选。

### 正常串行 baseline

沿用此前决定的 60 s silence-aware serial 基线。预期配置语义为：

```text
core_sec                  = 60
left_context_sec          = 10
right_context_sec         = 10
silence_aware_window_plan = true
strict_silence_boundary   = false
compress_silence_audio    = false
skip_silent_windows       = true
silence_boundary_min_sec  = 0.8
strong_silence_anchor_sec = 1.5
silence_boundary_search   = 6.0
leading_silence_min_sec   = 2.0
tail_min_core_sec         = 18.0
minimum_core_sec          = 12.0
```

此前 transition 结果中 `T2_core_boundary_serial` 是 nominal product candidate；本轮执行应使用当前仓库最新 correction layer 中实际已决定的 product baseline。若名称/配置有轻微演化，OpenCode 只做 **implementation mapping** 并记录 exact config，不重新跑 T1/T2/T3 选择实验。

### Decoder / 主输出

本轮的明确变化：

```text
main output / detector view = Raw
```

原因：

- 后续 decoder 可能变化；
- Raw 更接近模型基础输出；
- 当前 Raw detector 的 safe accept / protection 平衡更好；
- Raw 提供 entropy、margin、pile-up、order 等 no-GT 信号。

Official：

- 若同一次 forward 可低成本导出则保存；
- 仅作 shadow/reference；
- 不进入主实验矩阵，不作为 route/control decoder 的新主轴。

### Raw detector

- 使用 `light_merge` 修复后的当前冻结版本；
- 不重新训练 detector，不重新做大 feature search；
- threshold/provenance 必须记录；
- 允许研究它在 **realign quality judging** 上的能力，因为这是 recovery 闭环问题，而不是重新研究 detector 特征。

### 数据 / GT

- 继承当前 accepted real-GT lineage、source-song identity、metric schema；
- synthetic-uniform timeline 不允许再作为 real-GT correctness；
- formal correctness 至少保存 start/end 100/200/500 ms、MAE、labeled/unlabeled denominator；
- catastrophic error 另报 >1s / >2s / >5s / >10s、window/song/episode 级统计。

### 缓存 / resume / provenance

- 新 session 必须使用新的 SESSION_ROOT / OUT_ROOT，旧 evidence 只读；
- 相同 request identity 共享 forward/cache；
- 每个 realign candidate 有稳定 identity/hash；
- detector threshold、writeback policy、ranking 分析改变时不得重复模型推理；
- 每个阶段可 resume；单个 case failure 不得拖垮独立分支。

---

## 3. 模型/系统基础行为假设（本轮作为研究前提）

1. Forced Aligner 在给定 audio + text request 内做对齐，不负责从整首歌词自动重新找正确 occurrence。
2. 正常 request 下多数窗口可工作；主要风险是少量 catastrophic misalignment。
3. 正常主线仍使用长窗（60 s core + context）；不能把“所有窗口都缩短”偷换成 recovery。
4. 串行状态会把前一窗口的错误传播到后续 request。
5. 产品侧整首歌词通常被视为正确；核心困难是当前音频对应整首歌词中的哪一段，而不是用户随机输入错误歌词。
6. same model + same audio + same text 的原样 rerun 不是有意义 recovery；realign 的本质是构造新的 request。
7. Raw catastrophic failure 往往有可观察异常，因此 detector 可在 no-GT 环境中工作。
8. recovery 的价值包括把 cursor/后续 request 拉回正确轨道，而不仅是修当前几个字。

这些不是需要再次证明的 baseline 大轴；但 E1/E3/E9 会用数据检验它们对 recovery 研究的适用范围。

---

## 4. 本轮允许变化的变量

仅允许围绕以下四类变化：

### A. 何时触发 realign

- Raw detector unsafe island / bad window；
- trigger 聚合与最小/最大 repair region；
- 不把 detector feature search 本身扩成新大矩阵。

### B. realign 得到什么 audio/text request

- oracle exact；
- oracle tolerance；
- old Raw timestamp proposal；
- safe-neighbor anchor proposal；
- current cursor / unsafe unit span / anchor-bounded text；
- bad-window subdivision；
- selected silence snap。

### C. realign 怎样执行

- selected short-window size/context；
- anchor context；
- 至多 1–2 次有条件 retry / further shrink。

### D. 新结果怎样处理

- detector 判断 new vs old；
- accept/reject/rank；
- full vs selective writeback；
- harmful writeback guard；
- 后续 serial continuation。

---

## 5. 明确禁止重新打开的实验轴

除非用户后续明确要求，不得：

- 重新训练/替换模型；
- 重新大规模比较 Raw vs Official decoder；
- 重新做 full-slot vs non-slot 大消融；
- 重新做 T0/T1/T2/T3 transition formal selection；
- 重新做 fixed vs silence-aware planner 大矩阵；
- 重新展开 long-silence compression 主轴；
- 重新做 detector H/P/V/S/O/hidden 大 feature search；
- 把 baseline silence 功能包装成 realign 新贡献。
