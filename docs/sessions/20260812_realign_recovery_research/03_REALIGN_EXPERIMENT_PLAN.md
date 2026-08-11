# 下一轮 Realign / Recovery 实验设计

- 日期：2026-08-12
- GPU 目标预算：约 10 h；硬上限 12 h。用户会挂机，允许充分利用预算做更多真实轨迹与 candidate inference。
- CPU 分析不受 GPU 硬上限约束；达到 GPU 上限后继续基于缓存分析和自由探索。
- 核心原则：**先上限、再真实输入构造、再质量判断、最后串行闭环；不做笛卡尔积。**

---

# 0. 总研究问题

本轮必须回答四个主问题：

1. **Repairability**：如果给模型正确的短范围音频和正确歌词，它能否把原先严重错位重新对齐正确？
2. **No-GT proposal**：生产环境没有 GT，系统能否自动给 realign 足够正确的音频范围和歌词范围？
3. **Quality judgement**：realign 产生新结果以后，Raw detector 能否判断它是真的修好、没变化还是修坏？
4. **Closed-loop recovery**：把 detect → propose → realign → judge → writeback 连起来以后，能否阻断串行累计错误并恢复后续轨道？

Oracle 结果是能力上限，不是生产结果。No-GT closed-loop 是最终主结果。

---

# 1. Phase 0 — 新 session、baseline mapping 与 GT 隔离审计

## 原因

当前仓库经历过多轮 correction，不能让 Agent 因文件命名变化误用旧 synthetic-GT、旧 detector 或旧 transition runner。

## 目的

只确认“本轮实际继承哪一个 baseline implementation/config”，不重新比较 baseline 性能。

## 设计

必须生成：

```text
BASELINE_IMPLEMENTATION_MAP.md/json
GT_ACCESS_CONTRACT.md/json
RESOLVED_SESSION_CONFIG.yaml/json
CACHE_IDENTITY_SPEC.md
```

核对：

- exact model/checkpoint；
- full-slot query path；
- current product serial baseline（预期 T2 core-boundary nominal product）；
- 60/10/10 + silence-aware 参数；
- Raw view 与 detector artifact/threshold；
- real-GT loader；
- no-GT execution path中不得 import/read GT timing；
- same request cache identity；
- fresh SESSION_ROOT。

## 预期结果

所有 inherited baseline 行为可映射、可测试、无需重新实验选择。

## 结果能说明什么

- 通过：下一阶段所有差异可归因于 realign/control；
- 不通过：只做最小 compatibility repair 后继续，不能借机重新展开旧消融。

---

# 2. E1 — Exact Oracle Repairability：正确音频 + 正确歌词时能不能修

## 原因

旧 recovery 14–16% 被 synthetic-GT 污染。必须重新测真实上限，否则不知道后续失败来自模型本身还是自动 proposal。

## 目的

估计 catastrophic error 在“request 被纠正”后的真实可修复上限。

## 样本

优先覆盖所有 real-GT 中确认的自然 bad regions / unsafe clusters：

- 重复元音/衬词；
- 重复歌词/occurrence；
- 普通整体错位；
- head/start 错位；
- silence/boundary 附近；
- 已观察到的 serial propagation 起点。

不得只挑《绒花》成功案例。按 song/failure family 报告。

## 设计

GT 只用于：

- 找到真正目标 unit span；
- 得到其真实 audio coverage；
- 最后评分。

Aligner 输入：

- 正确目标歌词；
- 正确目标音频；
- **不提供字符 GT timestamp**。

首轮候选：

```text
O0 exact target range
O1 exact + 2 s left/right acoustic context
O2 exact + 5 s
O3 exact + 10 s
```

若某些 region 极短，context 仍按合法 audio boundary clamp；只写回/评分目标 unit span，context unit 单独标记 ownership。

## 主指标

- 原 unsafe → safe / grey / unsafe；
- repair success rate；
- start/end 100/200/500 ms；
- MAE；
- >1/2/5/10s catastrophic residual；
- order violation / pile-up / invalid；
- 原 safe context 被破坏率（若对 context 也产出预测）。

## 预期结果与解释

### A. Oracle repairability 很高（例如大多数 catastrophic region 可明显恢复）

说明：

> 模型本身不是主要瓶颈；错误主要来自原 request 太长、位置/配对错误。后续重点应放在 no-GT audio/text proposal 与 quality gate。

### B. 只在增加 anchor/context 后显著恢复

说明：

> 位置歧义而非纯长度是关键；safe-anchor realign 应成为主候选。

### C. Exact 仍大量失败

说明：

> 这一 failure family 存在 aligner intrinsic limitation；不能把所有希望押在 planner/retry 上。后续 no-GT 实验需按 family 分流，避免无意义反复 realign。

---

# 3. E2 — Oracle Tolerance：realign 输入需要多准确

## 原因

生产系统无法获得 exact GT range。即使 E1 上限高，也必须知道 proposal 可以容忍多大误差。

## 目的

拆分 audio range 与 text range 的容错，确定 planner 应“宁宽勿漏”还是“必须很紧”。

## 设计原则

不做完整 audio×text 笛卡尔积。先分别单轴，再挑 2–3 个代表组合。

### E2-A Audio tolerance（text 始终正确）

多给 audio：

- ±1 / ±2 / ±5 / ±10 / ±20 s；
- left-only +5/+10；
- right-only +5/+10。

少给 audio：

- start late 0.5/1/2/5 s；
- end early 0.5/1/2/5 s。

### E2-T Text tolerance（audio 始终正确）

多给 text：

- ±1/2/5/10 units；
- +5/+10/+20%；
- left-only / right-only 少量代表点。

少给 text：

- -1/2/5 units；
- -5/-10/-20%。

### E2-C Selected combinations

根据 E2-A/T 的趋势只选少量：

- 宽 audio + 宽 text；
- 宽 audio + 少 text；
- 少 audio + 宽 text；
- 一个接近预计生产 proposal 误差的点。

## 指标

同 E1，另外报告：

- input audio coverage / excess seconds；
- input text coverage / extra/missing units；
- repairability 相对 exact oracle 的下降。

## 预期结果与解释

- 多给容忍、少给敏感：支持 conservative wide proposal + central writeback；
- text 缺失比 audio 误差更致命：优先保证 lyric coverage；
- audio 左侧 context 特别重要：支持稳定 head/left anchor；
- 容错极窄：说明自动 proposal 必须非常精确，no-GT closed-loop 难度显著增加。

---

# 4. E3 — Natural No-GT Error Trajectories：让系统自然失败

## 原因

直接对当前窗口 ±文字只能研究局部输入异常，不能代表真实串行错误传播。

## 目的

建立真实自然错误轨迹，作为 closed-loop 的最高真实性基准。

## 设计

运行冻结 Raw serial baseline：

```text
detector scores may be logged in shadow
recovery = off
no GT used for control
```

对长歌一直运行；GT 只在离线阶段找：

- 第一个真正 catastrophic error commit；
- 后续 1/2/3/5 windows 的传播；
- 是否自然恢复；
- cursor/text/audio request 如何偏离。

保存可 replay 的 state checkpoint：

```text
state_before_first_error
first_bad_output
all subsequent requests/states
```

## 预期结果与解释

- 大量自然 propagation：可直接支持真实 recovery 研究；
- 多数错误自然自恢复：realign 应只针对 persistent/amplifying family，避免过度干预；
- 自然 bad case 太少：E4 controlled upstream perturbation 负责补足有效 episodes。

---

# 5. E4 — Upstream Single-Point Propagation：前面只扰动一次，后面自然传播

## 原因

用户明确要求构造比“当前窗直接加减字数”更自然的错误。

## 目的

研究一次早期错误怎样通过正常 transition state 影响后续，并形成足量、可控、真实感更强的 recovery episodes。

## 强制原则

**只在错误源头人工干预一次。**

从下一窗口开始：

- 不再人工 ±歌词；
- 不再人工移动窗口；
- 完全按照冻结 baseline 根据被污染 state 自然生成 request。

## Family

### P1 real model error forced commit

选模型自然产生的真实错误结果，故意绕过 detector 让它 commit 一次；之后正常运行。

### P2 lyric cursor corruption

在前窗 transition state 一次性使 cursor ahead/behind：

- small / medium / large；
- 同时报 absolute units 与相对文本密度/比例。

### P3 audio/time cursor or boundary corruption

一次性提前/延后：

- 代表点 ±1/±3/±6/±12 s（如 baseline implementation 有等价 state）；
- 不在后续每窗继续加偏移。

### P4 repeated occurrence jump

在重复副歌/相似段落附近制造一次 wrong occurrence state，然后让系统自然继续。

### P5 silence/boundary mistake

一次性错误吸附/提前/延迟 boundary，随后正常运行。

## 有效 episode gate

一个 perturbation 只有在**实际导致至少一个后续窗口 real-GT correctness 明显下降/unsafe propagation**时，才进入 recovery-effectiveness 主 denominator。

同时必须报告：

```text
attempted perturbations
no-effect perturbations
effective propagation episodes
```

不得因为大量 no-effect 就声称 recovery 很好/很差。

## 规模

主要 family 目标至少积累约 64 个 effective episodes；挂机允许扩大 song/position/seed，直到达到 quota 或 GPU/数据上限。达到上限仍不足标 `bounded_insufficient`，继续其他 family。

## 结果能说明什么

- 哪类 state error 最容易传播；
- 传播是否 amplifying / persistent / self-recover；
- realign 后续真正需要修的是当前 alignment、cursor、occurrence 还是 window boundary。

---

# 6. E5 — No-GT Realign Proposal：系统自己给 audio/text

## 原因

E1/E2 只说明“给对了能不能修”。生产环境真正困难的是不知道该给哪段音频、哪段歌词。

## 目的

在 no-GT 条件下评估 proposal 的 coverage、excess 与最终 repair success。

## 候选方法（先少量，不做大矩阵）

### R-A Unsafe-old-range baseline

Audio：unsafe units 的旧 Raw time span ± selected context。

Text：unsafe unit span ± selected K units。

这是最便宜、也可能最脆弱的现实 baseline。

### R-B Safe-anchor bounded — 主候选

寻找危险区域左右最近的连续可信 safe anchors：

- audio 由两侧可信时间 + context 定界；
- text 由两侧可信 unit / current cursor 定界；
- 可在限定范围内吸附附近静音；
- anchor 主要帮助定位，默认不全量写回。

### R-C Bad-window subdivision

如果 unsafe Raw timestamp 已经 pile-up/倒序，不再信任它自身时间；直接把当前 bad 60s window 按冻结规则切成少量 15–30s 子窗，结合 cursor/anchor 估计 lyric budget。

## Proposal 事后评分（GT 只在这里出现）

### Audio proposal

- true target audio coverage；
- missing seconds；
- excess seconds；
- 是否完整覆盖真实 target。

### Text proposal

- true target unit coverage；
- missing units / %；
- extra units / %；
- 是否包含正确 occurrence。

## 结果能说明什么

将最终 failure 分解为：

```text
oracle 能修 + proposal 不覆盖正确输入 -> proposal bottleneck
proposal 已覆盖 + realign 仍失败 -> aligner/ambiguity bottleneck
proposal 与 realign 均好 + 后续仍坏 -> quality/writeback/transition bottleneck
```

---

# 7. E6 — Shared Realign Candidate Bank：一次推理，多轮分析复用

## 原因

挂机可以安排较长推理，但后续 detector threshold/ranking/writeback 不应重复模型 forward。

## 目的

为 oracle、proposal、quality ranking、writeback、retry 共享同一个可复现 candidate bank。

## 每个 bad episode 目标候选

典型 10–20 个，不要求每个 family 都完全一样：

1. original；
2. exact oracle；
3. exact +2s；
4. exact +5s；
5. exact +10s；
6. old unsafe range + context；
7. safe-anchor bounded；
8. safe-anchor + silence snap；
9. bad-window subdivision；
10. selected short size；
11–14. selected text expansions；
15+. 仅在前述结果需要时增加 1–2 个 retry/shrink 候选。

## Candidate identity 必须包含

```text
song_id
source_episode_id
source_window_id
target_unit_start/end
audio_start/end
text_unit_start/end
proposal_method
context
window_size
model/checkpoint
raw decoder/view version
detector version not part of forward identity
```

hash 后缓存模型输出。

## 规模

优先做大 **有效 bad episodes × candidate bank**，而不是把大量无错误普通窗也乘上所有候选。目标可以是数千次 realign forward，只要不超过 GPU hard cap。

---

# 8. E7 — Detector Judges Realign Quality：它知道修好了吗

## 原因

生产环境 realign 后没有 GT，不能无条件相信新结果。

## 目的

判断当前 Raw detector 是否足以作为 repair quality gate / candidate ranker。

## 设计

GT 只在离线阶段定义候选实际改善：

```text
better / similar / worse than old
oracle-best among candidates
```

Detector 只看 no-GT Raw 信号。

### Q1 Pairwise old vs new

能否判断 new 是否真实优于 old。

指标：

- pairwise preference accuracy / AUROC；
- 在 catastrophic improvement 上单独统计。

### Q2 Best-of-K candidate ranking

同一 episode 多候选：

- top-1 命中真实 best；
- top-2；
- detector-chosen GT correctness；
- oracle-best GT correctness；
- ranking regret。

### Q3 Accept / reject

系统不必永远选最优，只需避免把坏结果写回：

- successful repair accept；
- good repair rejected；
- harmful repair accepted；
- all candidates bad 时能否全部拒绝。

## 关键风险指标

**Harmful writeback candidate acceptance rate** 必须单独作为主指标。

允许保守拒绝一部分已经修好的候选，但不能为了 repair recall 大量主动接受更坏结果。

## 预期结果与解释

- detector 能稳定判断 improvement：可以进入真实 closed-loop；
- detector 只会判绝对 unsafe、不会比较改善：closed-loop 使用保守 acceptance，不强行 best-of-K；
- detector quality gate 明显不足：才允许后续自由探索针对性研究新的 repair-comparison 信号，不立即重开全部 detector feature search。

---

# 9. E8 — Writeback Policy：修错误，但不要破坏原来正确的地方

## 原因

一个 realign window 中常常只有局部错误。整段替换可能修少量 unsafe，却破坏大量原 safe。

## 目的

找到保守且可部署的 writeback。

## 候选（离线复用 candidate bank）

1. Full replacement — 风险对照；
2. Unsafe-only replacement；
3. Unsafe ±1/2 units margin；
4. Detector-improved units/contiguous region selective writeback。

## 主指标

### Repair

- unsafe→safe；
- unsafe→grey；
- unsafe remaining unsafe。

### Damage

- safe→grey；
- safe→unsafe；
- catastrophic new errors。

### Net

- net improved units；
- net catastrophic reduction；
- harmful writeback episode rate。

## 结果能说明什么

- selective 明显优于 full：说明 recovery 应“宽输入、窄写回”；
- full 无明显额外 damage：实现可简化；
- 所有 writeback 都高风险：quality detector 或 ownership 仍是瓶颈。

---

# 10. E9 — Full No-GT Closed Loop：真实主实验

## 原因

最终价值不是修一个独立窗口，而是让系统从错误轨道回到正常轨道。

## 目的

完整比较 detector / realign / quality gate 对串行传播的实际价值。

## 路线

### C0 Frozen baseline — no control

```text
Raw serial baseline
no detector effect
no realign
```

### C0S Detector shadow

与 C0 完全相同 trajectory，只记录 detector trigger，不改变 state。用于公平分析 trigger timing。

### C1 Detect / hold only

Detector 判危险后不正常提交，但不 realign。回答“只阻止坏 commit”能帮多少。

### C2 Detect + realign + unconditional writeback

故意作为危险对照，测“盲目 realign”会不会制造额外伤害。

### C3 Main

```text
detect
-> no-GT audio/text proposal
-> Raw realign
-> Raw quality gate
-> selective writeback if accepted
-> update serial state
-> continue
```

### C4 Selected fallback

只在 C3 仍危险时允许至多 1–2 次：

- smaller window；或
- alternate safe-anchor candidate。

不得无限 retry。

## 数据

两类都必须有：

1. E3 natural trajectories；
2. E4 effective propagated episodes。

并尽量自动利用现有多语言 Test Demo 做 no-GT regression / case mining；Test Demo 不要求人工逐个挑 case 才能进入统计。

## 后续 continuation

Realign 之后不能立刻结束 episode。至少继续：

- 1 / 2 / 3 个窗口；
- 对自然长歌尽量继续到 song end。

## 主指标

### 当前区域

- repair success；
- safe damage；
- harmful writeback。

### 串行恢复

- 后续第几个窗口恢复到正常；
- self-recover / slow-recover / persistent / amplifying / occurrence-jump；
- 首个错误后累计 unsafe 时间/units；
- lyric cursor / audio cursor 偏差随窗口变化；
- song-level success / SA 类指标；
- detector-triggered recovery 对 C0/C1 的 paired delta。

### 成本

- extra model forwards；
- extra processed audio seconds；
- wall time multiplier；
- retry count distribution；
- cache hit rate。

## 预期结果与解释

### C3 明显优于 C0/C1，且 harmful writeback 很低

说明 realign 不是单纯工程补丁，而是真正能把串行系统从错误状态恢复。

### C1 已经获得大部分收益，C3 增益小

说明 detector 阻止坏 commit 比实际修复更重要；下一步可简化 recovery，重点研究安全 hold/restart。

### Oracle 很高但 C3 低

结合 E5/E7 分解：proposal 或 quality gate 是主要损失来源。

### Oracle 本身低

说明模型 intrinsic limitation 是主因，不应继续堆 planner/retry。

---

# 11. E10 — Selected Retry / Recursive Shrink：只在主结果需要时做

## 原因

已有机制观察提示更短窗口可缓解 collapse，但“越短越好”尚未验证。

## 目的

研究第一次 realign 仍危险时，继续缩窗一次/两次是否值得。

## 设计

只对 C3 fail / uncertain episodes：

```text
first realign
-> if still unsafe
-> one smaller-window retry
-> optional second retry only if pre-registered and budget allows
```

典型候选尺寸按 E1/E2/candidate bank 结果选择，不预先全跑 60/45/30/20/15/10/5 全矩阵。

## 结果与解释

- retry 有明显边际收益且成本可控：进入 C4；
- 太短后反而下降：记录 sweet spot；
- 无收益：停止 retry 复杂化。

---

# 12. 统一结果分解：不要只报一个 recovery %

最终报告必须形成“漏斗”或 stage decomposition，例如：

```text
effective error episodes
-> detector detected
-> proposal covered correct audio
-> proposal covered correct text/occurrence
-> realign produced a truly better candidate
-> detector accepted the better candidate
-> writeback did not damage safe region
-> serial trajectory recovered
```

每一级都报 numerator / denominator。

这样才能知道损失来自：

- detector；
- audio proposal；
- text proposal；
- aligner；
- quality gate；
- writeback；
- transition continuation。

---

# 13. 公平性与口径要求

- GT 不得进入 no-GT control path；
- B/A 或其他 role 若已因历史探索不再 untouched，必须如实标 retrospective/diagnostic，不伪装成 final heldout；
- 同一 episode 的 route 比较尽量 paired；
- 相同 model forward 共享 cache；
- no-effect perturbation 不进入 recovery 主 denominator；
- failure family / song / language 分层；
- frame/unit/window/event/song 指标分开；
- start/end 100ms 不得与 legacy start-only 1s 混用；
- synthetic timeline 只可用于非 correctness 辅助构造且必须标 provenance；若会影响 correctness 解释则禁止；
- negative result 也保存，不因无收益提前终止整个 session。
