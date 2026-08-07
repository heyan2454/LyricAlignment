# 下一阶段总实验计划：Transition–Recovery 主线 + 旧缺陷补齐 + Detector 研究

- 日期：2026-08-07
- 目标预算：约 10 h GPU，硬上限 12 h（不含纯 CPU 文档/审计时间）；若已有缓存可显著降低实际成本
- 原则：阶段筛选、共享 forward、先机制后闭环、禁止大笛卡尔积

## 1. 三条研究线

### 主线 A：Transition → Propagation → Recovery

先回答“Aligner 在不同推进方式下本身如何工作”，再研究错误如何传播，最后研究 recovery。**不预设必须串行，也不预设某一种串行是‘真实系统’。**

### 基础线 B：旧实验缺陷补齐

只补会影响现有结论可信度或新实验复用的数据缺口：stress evaluator、旧 serial propagation、hidden extraction、cross-view posterior、repeated occurrence、CNN1D 旧协议纠正等。已经闭合的 identity/audit 不重复跑。

### 研究线 C：Detector

正式完成 SA60、SA80、R95；研究 cross-window、posterior competing path、per-unit sequence、hidden sequence 和 propagation-risk。Detector closed-loop 只在 A 线选出的少数 Transition 上做。

---

## 2. 总执行顺序

```text
Phase 0  New-session precheck + existing implementation mapping
Phase 1  Unified baseline/cache + T0/T1/T2/T3 Transition formal
Phase 2  Select product candidate + mechanism candidate
Phase 3  Natural/model-native/controlled propagation benchmark
Phase 4  Transition stability basin + recoverability + oracle recovery
Phase 5  Old experiment gap completion (parallel where possible)
Phase 6  Detector SA60/SA80/R95 + signal research
Phase 7  Closed-loop L/W on selected transitions
Phase 8  M4 formal summary + MIR fixed transfer + Test Demo auto mining
Phase 9  Final report / negative results / implementation handoff
```

任何单一阶段得到负结果都不能自动结束整个 session；见 `06_AGENT_EXECUTION_CONTRACT.md`。

---

## 3. Phase 0：实现映射与基础审计

### 目标

避免 Agent 重新发明已经实现过的串行方式，或把不同旧脚本的语义混在一起。

### 必须完成

1. 映射 T0–T3 当前代码实现；
2. 映射 full-slot/non-slot 当前 query 接口；
3. 确认 raw/official 从同一 forward 复用的可行性；
4. 确认 silence snap、skip silent、leading silence、tail redistribution/merge 当前实现；
5. 确认 long-silence compression 是否已有；若无，仅实现最小可逆 preprocessing + timeline map；
6. 生成 resolved config，formal 后不得按结果调参；
7. 建立新 SESSION_ROOT，旧 OUT_ROOT 全部只读。

### 通过条件

- 每个 transition 的实际状态机有行为测试；
- 相同 request/cache identity 可复现；
- output timeline 能映回原曲；
- session root 不覆盖任何旧 evidence。

---

## 4. Phase 1：Transition 主实验

固定主 baseline：

```text
Audio        = long-silence compressed（保留值 pilot 后冻结；主倾向 3–5 s）
Planner      = silence snap
Window       = left 10 + core 60 + right 10
Silent       = skip
Leading      = handle/skip to first useful region
Tail         = redistribute / merge short tail
Align        = full-slot
Decoder data = raw mandatory, official secondary/reference
Recovery     = none
```

比较：

- T0 independent / non-serial；
- T1 direct serial；
- T2 core+boundary serial；
- T3 stable-boundary serial。

若 T0 当前只能用 oracle start，应在结果中标为 diagnostic upper bound，同时保留任何已有的真正 non-serial implementation；不得将两者混成一项。

### 主问题

- 哪种方式单窗准确？
- 哪种方式最少累计漂移？
- 哪种方式会自然恢复？
- 哪种方式最易 occurrence jump？
- 串行相较 non-serial 的收益是否值得传播风险与成本？

### 输出决策

选择：

- **Product candidate**：综合准确率、稳定性、成本最有希望；
- **Mechanism candidate**：最适合暴露传播机制，不必是最终产品。

若 non-serial 胜出，允许它成为 Product candidate；不得为了继续 serial 故事而排除。

---

## 5. Phase 1b：少量 Align / Audio / Planner 消融

只在 Product candidate（必要时 Mechanism candidate）上运行。

### Align

- full-slot；
- non-slot。

### Audio / Planner

最少三项：

1. original audio + silence snap；
2. compressed audio + silence snap；
3. compressed audio + fixed window。

3s vs 5s 仅 pilot；若差异小立即冻结，不进入 formal 大矩阵。

---

## 6. Phase 3：Propagation Benchmark

三类来源按真实性排序：

### P-N Natural propagation

无 detector 或宽松条件下自动找到第一个真实错误 commit；不纠正，继续 2–5 个窗口。

### P-M Model-native forced commit

从模型自己产生的错误候选中选择：

- raw/official disagreement；
- top-2 / alternate posterior path；
- alternate occurrence；
- 被旧极保守 detector 阻止、但实际模型产生的候选。

只强制“让模型自己的错误通过一次 commit”，之后完全按正常 route forward。

### P-C Controlled state corruption

用于机制扫描，直接修改 canonical transition state，而不是伪造夸张输出：

- lyric cursor ahead/behind；
- time cursor ahead/behind；
- cursor+time 协同错但自洽；
- wrong occurrence；
- partial boundary/tail corruption。

“尾部塞若干零时长”只做 sanity，不作为主 propagation 数据。

### 有效样本要求

主要 family 目标 `>=64` 个真正影响下一 state 的 episodes；不足时扩大候选池/歌曲/强度，不能因为 no-effect 多就结束。达到资源上限仍不足则写 `bounded_insufficient`，但继续其他 family 和后续独立实验。

---

## 7. Phase 4：Propagation 机制与 Recovery 上界

### Stability basin / phase transition

研究初始误差大小与传播概率，而不是只报 yes/no。

建议首轮：

- lyric cursor：小/中/大，实际数值根据 unit density pilot 固定；同时报告绝对 units 与相对比例；
- time cursor：±1 / ±3 / ±6 / ±12 s；
- occurrence wrong：单独 family，不与数值误差混算。

### Recoverability 分类

- self_recover：≤1 窗；
- slow_recover：2–3 窗；
- persistent；
- amplifying；
- occurrence_jump。

### Oracle recovery

GT 只用于决定真实错误/anchor，运行：

- Oracle-L；
- Oracle-W；
- 必要时 oracle cursor reset / occurrence reset。

目的：估计 recovery 上限，拆分 detector limitation、recovery limitation、aligner intrinsic limitation。

---

## 8. Phase 5：旧实验缺陷补齐

详细见 `03_LEGACY_GAP_COMPLETION.md`。本阶段不是重新跑全部 Detector V2，而是补最小必要证据，并复用 Phase 1–4 新 corpus。

---

## 9. Phase 6：Detector

必须完成：

- SA60-primary；
- SA80-primary；
- R95-primary（REJECT recall，UNCERTAIN 不算）；
- SA60+R95 joint feasibility；联合不可行时仍继续两套独立实验。

新信号优先级：

1. cross-window consistency；
2. posterior competing coherent path / occurrence ambiguity；
3. per-unit sequence detector；
4. hidden sequence（hidden extraction gate 通过后）；
5. propagation-risk target。

不再把 calibration 细调或更多普通 classifier 作为主方向。

---

## 10. Phase 7：Closed-loop Recovery

只在 Product candidate + Mechanism candidate 的少数工作点运行，禁止全组合。

主组合：

- None baseline；
- Shadow；
- L-SA60；
- L-SA80；
- L-R95；
- W-R95。

若预算紧，优先保留：L-SA80、L-R95、W-R95 和对应 None。

Recovery 必须使用唯一 route plan；decision/simulation/execution 不得三套解释。

---

## 11. Phase 8：泛化与 Demo

### M4

主 GT formal。训练/threshold validation/test source-song 分离。

### MIR

M4 冻结模型/scaler/threshold 后直接迁移；不得在 MIR 重调后称 fixed transfer。

### Test demo

无 GT 全量自动利用：

- 扫描新增文件，不固定歌曲数；
- 计算 raw/official disagreement、cross-window jump、posterior multimodality、occurrence ambiguity、compression、route disagreement、intervention/cost；
- 每首自动输出 suspicious episode ranking；
- 人工只抽 top 异常、显著改善/恶化和少量随机对照。

不得对无 GT demo 声称 MAE/真实 accuracy。

---

## 12. 最终允许的结论

本阶段允许得到任何一种结果：

- non-serial 最合适；
- 某种 serial 最合适；
- full-slot 的主要收益只在 Align，或同时提高 transition stability；
- long-silence compression 有/无收益；
- L 比 W 更有效，或反之；
- detector/recovery 的收益不足以抵消复杂度；
- propagation-risk signal 有明显价值，或无法泛化。

不允许先假定“必须串行”“必须 detector”“必须 local recovery”，再只保留支持该故事的结果。
