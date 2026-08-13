# 下一轮实验设计：Unit-level Realign Behavior / Sparse Requests / Overnight Exploration

## 0. 总体目标

本轮不再以“哪个 candidate 整体更好”为中心，而以 unit 为主回答：

> **什么状态的 unit，在什么 realign request 下会被修复、保持或破坏；这些结果是否能从无 GT 的多视角行为中被可靠判断。**

允许 overnight 8–12h 级探索。由于当前 forward 相对较快，可明显扩大 region 数，但仍禁止笛卡尔积。

执行采用两阶段：

1. **Family Screening**：40–60 个独立 GT regions，对机制不同的 request family 做初期比较；
2. **Adaptive Expansion**：淘汰明显无效/no-op/高害低收益 family 后，保留约 3–4 个 production-capable family，自适应扩大到约 200–300 个 GT regions。

Oracle、request perturbation、fixed-point 只在 subset 上跑。

---

# P0 — 评价与 schema 重构：以 unit 为主要分析实体

## 原因

现有 candidate harm 把一个 candidate 内的复杂 unit 行为压成单一标签，无法区分真正 recovery、mixed repair、collateral harm 与 catastrophic collapse。现有 no-GT feature 也大多为 candidate-level change magnitude。

## 目的

建立不混淆 frame/window/candidate/unit 的统一评估 schema，使后续所有 request family 使用同一口径。

## 设计

每个 `(song, region_case, request_family, unit_id)` 保存至少：

### GT outcome（评价侧；禁止进入 no-GT feature）

- original onset error ms；
- original offset error ms；
- original max-boundary error ms；
- candidate onset/offset/max-boundary error；
- signed `delta_error_ms = after - before`；
- original / after quality bucket：
  - <=100ms；
  - 100–200ms；
  - 200–500ms；
  - 500ms–1s；
  - >1s；
  - missing/unpaired。

### Detector state

- original ACCEPT / UNCERTAIN / REJECT；
- original p_bad / margin / entropy 等现成信号；
- after 对应 detector 状态与信号（若可安全、低成本计算）。

### Unit role

- target active unit；
- fixed/safe anchor；
- target 外 safe context；
- target 外 uncertain/reject context；
- request 外 unit（若能够观测）。

### Temporal behavior

- onset displacement；
- offset displacement；
- center displacement；
- duration change；
- left/right local gap change；
- local order/inversion；
- pile-up/zero-duration；
- local compression/expansion。

## Unit 状态转移指标

必须至少报告：

- <=200ms -> <=200ms：safe preservation；
- <=200ms -> 200–500ms：mild harm；
- <=200ms -> >500ms：severe harm；
- <=200ms -> >1s：catastrophic harm；
- >1s -> <=500ms；
- >1s -> <=200ms：strong recovery；
- 500ms–1s -> <=200ms；
- missing/new missing；
- coverage / pairing rate。

## Candidate / region 聚合

仍可输出 candidate summary，但必须由 unit outcome 聚合，并至少分开：

1. target recovery；
2. target harm；
3. safe-context collateral harm；
4. catastrophic harm；
5. net error change；
6. coverage change。

不得再使用“任意一个 unit >200ms 即 candidate=harm”作为唯一 outcome。

## 预期结果

若大量旧 candidate harm 实际属于 mixed-repair：说明此前候选级标签过度悲观，需要基于 unit/局部 writeback 重新理解 realign。

若 unit-level 下仍显示大规模 correct->catastrophic：说明 realign 本体确实具有严重稳定性风险。

---

# P1 — Reject-Safe / Accept-Safe / Bad-Unsafe unit-region population

## 原因

用户特别关心：

> **detector 判 REJECT 的内容如果 GT 实际正确，realign 会不会特别容易把它打坏？**

这不能用 whole-window S2 回答，必须按 unit/local region 采样。

## 主要 strata

### RS — Reject-Safe（主 hard negative）

- target unit GT <=200ms；
- detector REJECT；
- 可允许连续 1–N 个 unit 形成小 region。

### US — Uncertain-Safe

- target unit GT <=200ms；
- detector UNCERTAIN。

### AS — Accept-Safe control

- GT <=200ms；
- detector ACCEPT；
- 与 RS/US 尽量匹配歌曲、位置、region 长度、静音/重复结构等。

### BR — Bad-Reject（正常 recovery target）

- detector REJECT/UNCERTAIN；
- 至少一个 target unit >500ms，主 severe/catastrophic subgroup 为 >1s。

### BG — Moderate / Grey GT

- 200–1000ms；
- 单独保存，避免从 population 静默消失。

### BA — Bad-Accept

- GT bad 但 detector ACCEPT；
- 主要用于 detector failure analysis，realign 只需少量 exploratory cases。

## Region 构造

- contiguous target 默认 1–8 units；
- 优先从真实 detector interval 中切出；
- 过长 interval 必须进一步切分，不允许直接退化到整 60s window；
- 对单个 reject safe unit，可和相邻同类/上下文组合为最小可运行 region；
- 保存完整 source baseline，不改变 GT 语义。

## Screening 样本

第一阶段 40–60 regions，建议优先包含：

- RS：12–15；
- AS：8–10；
- BR：15–20；
- BG/US/BA：其余。

不是硬配额。若某类不足，必须先扫描完整 eligible population，并执行补样策略。

## Overnight expansion

淘汰 request family 后，目标总计约 200–300 独立 GT regions：

- RS：约 50–70；
- AS：约 30–40；
- BR：约 70–100；
- US/BG/BA：约 20–40；

以实际可用数据为准；优先跨歌，限制单歌最大贡献。

## 主要比较

核心 preservation 对比：

> `P(after safe | original GT-safe, detector REJECT)` vs `P(after safe | original GT-safe, detector ACCEPT)`

同时比较 catastrophic transition：

> `GT<=200ms -> >500ms / >1s`

## 可支持结论

A. RS 显著比 AS 更易被打坏：支持“detector false-positive 中含内部不稳定 alignment”假设；Attempt Gate 应把这种情况视为特殊风险。

B. RS 与 AS 同样稳定：说明 detector false-positive 并不天然意味着 realign 风险，问题更多在 request family。

C. Sparse 明显改善 RS preservation：支持 selective active-unit realign。

---

# P2 — Request Family Screening（机制比较，不做笛卡尔积）

## 总原则

所有 production-capable candidate 必须通过 `EFFECTIVE_INTERVENTION_CHECK`：

- forward-affecting audio/text/slot mask 至少一项相对 baseline 有真实变化；
- no-op 必须标记 `R-NULL`，不能计入 family 正式统计；
- 同一 case family 比较使用同 checkpoint/decoder/baseline/target definition。

---

## R-U1 — 极小 contiguous unit-local

### 设计

- target：1–N detector target units；
- text：target + 左右各约 1 个可信邻近 unit；
- audio：围绕 target 当前时间或最近可靠 anchor 边界的小范围；
- 禁止整窗/整首 text。

### 目的

测试最小 local request 是否能降低 collateral damage。

### 预期解释

- preservation 高、recovery 尚可：支持局部主线；
- recovery 很差：说明 context 太少。

---

## R-U3 — 稍宽 contiguous unit-local

### 设计

- target 相同；
- 左右各约 2–3 unit context；
- 只比 R-U1 多少量 context，不再额外乘多个 audio margin。

### 目的

判断 R-U1 是否因 context 不足失效，并初步刻画 local context sensitivity。

---

## R-S — Sparse / slot-local（新增重点）

### 定义

必须是真 sparse，而不是“删除 safe text 后重新跑”。

- detector REJECT/UNCERTAIN target units = active / free units；
- 附近稳定 ACCEPT units = fixed/reference slots；
- 其他 stable units 尽量不重新分配时间；
- 必须保留原始文本身份和顺序；
- forward 输入或 slot mask 必须真实体现 sparse active set。

### 如果当前接口不支持

Codex 必须先确认已有 raw decoder / slot 接口能否复用。优先让 raw decoder 在完整 local text 上仅激活 target slot，并对所有 safe slot 做 before/after 约束审计；这不是启动 screening 或 overnight 的阻塞点。若发现 safe slot 漂移、slot mask 未真实生效、顺序交叉或固定 slot 丢失，则该 request 标记 `SAFE_SLOT_INVARIANT_VIOLATION`、禁止 writeback、保留 baseline safe rows，并记录 decoder/request-shape 后继续其他 cases/families；随后修正 adapter/constraint mapping 并加入回归测试。

若需要新增显式 fixed-reference 支持，再做最小真正 sparse 版本并写 correctness test；**禁止通过删除中间歌词、重写文本、只跑 active text 等方式伪造 sparse**。

### 目的

直接研究：

> 能否只重新解释 detector 指出的 unit，同时保护原本稳定 unit。

### 预期解释

- recovery 略低但 preservation/collateral 显著好：非常适合生产；
- 与 contiguous 基本相同：说明 sparse constraint 没提供额外稳定性；
- active slots 仍导致稳定 slot 大幅漂移：说明当前 slot mechanism 并非真正局部约束。

---

## R-A — Detector interval direct

### 设计

- 以真实 detector unsafe interval 为 target；
- 少量 safe context；
- contiguous local request；
- 明显小于 full production window。

### 目的

作为 detector-driven direct baseline。

---

## R-B — Bilateral stable-anchor bounded

### 设计

- 左右均必须存在真实 stable/ACCEPT anchor；
- anchor 必须参与实际 audio/text request 限制；
- request identity 必须与 baseline 不同。

### Coverage

找不到 anchor 不应简单 skip：

1. 扩大合理 anchor search radius；
2. 缩小 target span；
3. 重选相邻 target region；
4. 仍失败则标为 `R-B_unconstructible` 并进入 coverage 统计。

不得无 anchor 时退化成 baseline no-op。

---

## R-L / R-R — One-sided stable anchor

### 设计

初期 pilot 两者均可少量尝试，但不全量同时保留：

- R-L：左侧 stable anchor 固定，右侧为有限 local context；
- R-R：右侧 stable anchor 固定，左侧有限 local context。

尤其关注串行产品更自然的 R-L。

### Screening 后

如果左右明显有一侧更有价值，只保留最佳一侧进入 overnight expansion。

---

## R-O — Direct Oracle diagnostic

### 设计

使用 GT 给出接近正确的 target/audio/text local request。

### 约束

- 只用于研究能力上限与 request basin；
- 不进入任何 no-GT gate feature；
- 不进入 production recommendation。

### 目的

区分：

- request 构造差；
- aligner 本身即使拿到近乎正确 request 仍不稳定。

---

# P3 — Family Screening 决策

## 初期规模

40–60 regions × 约 6–7 机制 request，但不是每个 case 强制全部跑：

- R-U1 / R-U3 / R-A 作为基本主线；
- R-S 若实现可用则主线；
- R-B 仅 genuine constructible case；
- R-L/R-R pilot；
- R-O 只在 GT subset。

预计约 250–400 forwards，可利用统一 baseline/cache。

## 淘汰规则

一个 family 若满足以下任一，可不进入 200–300 region expansion：

- 大量 no-op / 无法构造；
- correct-unit catastrophic harm 明显高且 recovery 无补偿；
- 相比更简单 family 无任何稳定性/coverage/recovery 优势；
- 实际没有实现声称的机制（例如 sparse 没有真正冻结 stable slots）。

不是纯按单一 AUROC 淘汰。

## 保留目标

最终保留约 3–4 个 production-capable family，例如可能是：

- best unit-local；
- sparse；
- best stable-anchor/one-sided anchor；
- detector-direct baseline。

实际由 screening 结果决定。

---

# P4 — Overnight Expansion

## 规模

若 forward 如当前观察仍较快，正式扩大到约 200–300 独立 GT regions。

不要求每 region 跑所有 request。优先：

- 所有 region：2–3 个 surviving production family；
- anchor family：只在真实可构造 region；
- Oracle：约 40–60 个代表性 region；
- deeper perturbation：约 20–30 个 region。

预计主 forward 量约 600–1000，允许 cache/resume。

## 跨歌要求

- 先扫描全部实际 eligible songs/windows/regions；
- 优先 song diversity；
- 记录每歌贡献上限；
- 不允许 200 个 region 大部分来自 2–3 首歌。

## Stop 条件

只有以下情况允许提前停止某 branch：

- 已确认 implementation invalid/no-op；
- 明显 harmful 且无 recovery/coverage 价值；
- exhaustion audit 证明无法构造；
- 机器资源/失败使 branch 不可继续，并已保存完整 failure provenance。

不能因为“已有几十个样本”就提前结束 overnight 主线。

---

# P5 — Unit-level no-GT Feature 重算与探索

## 原因

现有 `n_big`、max/sum displacement、abs p_bad delta 多为 candidate change-magnitude feature。下一轮要回答每个 unit 的“方向与可靠性”。

## 5.1 Signed detector evidence

每 unit 记录：

- `p_bad_before`；
- `p_bad_after`；
- signed `delta_p_bad = after - before`；
- ACCEPT/UNCERTAIN/REJECT transition；
- entropy / margin before/after（若现有 extractor 可低成本得到）；
- raw/official state/score agreement before/after。

必须区分：

- bad→better；
- good→worse；

禁止只看 `abs_delta`。

---

## 5.2 Unit temporal stability

- onset/offset/center displacement；
- duration change；
- local gap / order；
- local warp slope；
- pile-up / inversion / zero duration；
- 与最近左右 stable unit 的相对位置变化。

---

## 5.3 Safe-context protection

对每个 target unit 建立：

- nearest safe-left displacement；
- nearest safe-right displacement；
- N-neighbor safe context changed count；
- max safe-context displacement；
- safe-context p_bad degradation；
- target change / context change ratio。

核心假设：

> 好的 realign 应把变化集中在 target，保护周围 stable context。

---

## 5.4 Multi-request unit consensus（重点）

对同一 source unit，在不同 request family 的输出上计算：

- timestamp median；
- MAD / variance；
- pairwise distance；
- largest consensus cluster size；
- family agreement ratio；
- unit order agreement；
- coverage agreement；
- duration agreement。

不要只产生 candidate-level `ra_rb_agreement`。

### 目标

研究：

> 多个机制独立的 request 是否对一个 unit 收敛到近似相同时间。

如果多数 family 收敛，而 original 与 consensus 相差较大，可能是强 repair 信号；如果不同 family 四散，则应视为高风险。

---

## 5.5 Consensus-based unit writeback diagnostic

只做 shadow diagnostic，不 actual writeback。

例如研究：

- 2/3 family agreement；
- 3/4 family agreement；
- consensus variance threshold；
- consensus + safe-context protection；
- consensus + detector signed improvement。

不要预先冻结具体阈值，先用 dev song 探索，再在 song holdout / leave-one-song-out 评价。

---

## 5.6 n_big 的新定位

重算：

- candidate `n_big` 仍可保存；
- 同时保存哪些 unit 属于 big change；
- 分解 target-big / safe-context-big；
- 研究它和 recovery/harm 的关系。

但 `n_big<=k` 不作为默认 gate。

---

# P6 — Oracle Basin / Request Sensitivity Exploration

## 原因

如果 realign 本身不稳定，需要知道是：

- 正确 request 的稳定盆地很窄；
- 还是 Oracle request 本身都不可靠。

## 样本

从 screening/overnight 中选 30–50 个代表性 GT regions：

- strong recovery；
- mixed；
- harm；
- Reject-Safe；
- catastrophic bad。

## 扰动设计

以 R-O / 最优 local request 为中心，做逐轴小扰动，不做笛卡尔积：

- audio 左边界 ±0.5 / 1 / 2s 中少量代表点；
- audio 右边界类似；
- text 左/右 ±1 / 2 units；
- anchor 前后移动一档；
- local context 一档更窄/更宽。

先每 case 3–5 个 perturbations；若某一维高度敏感，再对少数 case 深挖。

## 输出

- per-unit output variance；
- request perturbation -> timestamp response；
- stability basin width；
- 是否发生 discrete jump 到完全不同歌词位置；
- 与 GT recovery 的关系。

## 可支持结论

A. Oracle 稳定但轻微偏差崩：主要瓶颈是 request estimation / basin narrow。

B. Oracle 本身也常崩：aligner 作为 recovery operator 的内在稳定性不足。

C. 存在宽稳定 basin：可以通过搜索/consensus 进入稳定解。

---

# P7 — Fixed-point / Iterative Stability

只对约 15–25 个 ambiguous/high-value candidate：

`original -> candidate A -> same/similar local request -> candidate B`

必要时少数做第三次。

记录每 unit A→B displacement、consensus、detector evidence。

解释：

- A≈B：可能已到 stable fixed point；
- A→B 又大幅漂移：candidate 不稳定；
- 周期/跳变：强拒绝信号。

不全量执行。

---

# P8 — Attempt Gate 与 Writeback Gate 分开分析

## Attempt Gate

回答：

> 这个 detector region 是否值得花 forward 成本尝试 realign？

可用 original-only 信号：

- detector severity；
- region 长度；
- stable anchor availability；
- raw/official disagreement；
- local structural异常；
- 是否属于 RS/US 风格的高脆弱 proxy（线上不能用 GT）。

## Writeback Gate

回答：

> 已产生多个 realign views 后，某个 unit 是否有可信新时间可以覆盖 original？

优先信号：

- multi-request consensus；
- signed detector evidence improvement；
- safe-context protection；
- fixed-point/stability；
- structural sanity。

输出以 unit risk/coverage 为主，candidate 只作辅助。

---

# P9 — Real Test Demo：真正 local / sparse 多语言行为

## 当前问题

当前 Test Demo 虽真实执行 4 个 forward，但 `R-U_unit_local` 的 target 实际覆盖整首 item；4 个 anchor request 均 R-NULL。因此行为结果不成立。

## Detector stage

重新动态发现全部 Test Demo，不写死 33/36。

对全部可运行 item 使用真实 frozen detector，输出：

- per-language detector unit state；
- contiguous unsafe unit spans；
- span 长度分布；
- long reject runs；
- raw/official disagreement（若低成本）；
- suspicious local region ranking。

## Local region construction

从 detector contiguous REJECT/UNCERTAIN spans 自动切 local region：

- 默认 1–8 units；
- 过长连续 reject 必须切分；
- 结合 stable neighbor / silence / phrase boundary；
- 禁止 target=整首歌词。

## Realign subset

Overnight 可扩大到约 40–60 个 Test Demo local regions，跨：

- Chinese；
- Cantonese；
- English；
- Japanese；
- 其他实际存在语言/文件。

每种语言尽量至少若干 region。

对每 region 运行筛选后最佳的 2–4 个 production request family，例如：

- best unit-local；
- sparse；
- best anchor / one-sided anchor；
- detector direct baseline。

没有 GT，因此只做：

- unit consensus；
- signed detector change；
- stability；
- safe-context proxy；
- structural anomaly；
- request sensitivity。

自动输出：

- 最稳定 top cases；
- 最不稳定 top cases；
- request family 强冲突 cases；
- 大幅 collateral change cases。

若已有 visualization/video pipeline 可低成本复用，自动渲染约 8–12 个代表 case，供第二天人工 spot-check；人工观察不得替代客观统计。

---

# P10 — 样本不足与自动补救

任何以下情况不得直接写 `insufficient` 后停止：

- RS hard negatives 太少；
- AS control 太少；
- genuine R-B coverage 太低；
- sparse active request 不足；
- one-sided anchor 只有少数；
- 某语言 Test Demo region 太少；
- holdout song/candidate 太少。

必须依次尝试：

1. 从 whole-window 下沉到 unit/contiguous region；
2. 扫描全部 eligible songs/windows；
3. 增加同歌不同 region，但设置 per-song cap；
4. 缩小过长 target；
5. 扩大合理 anchor search；
6. bilateral 不可用时尝试 one-sided（但不要冒充 R-B）；
7. 利用 baseline/cache 只补 candidate forward；
8. 如数据集 builder 能合法产生更多 production long windows，扩大 population；
9. Test Demo 动态全量扫描，不依赖历史固定清单。

最终若仍不足，必须输出 `EXHAUSTION_AUDIT`：

- 总 eligible；
- 各过滤步骤数量；
- 各不可构造原因；
- 已尝试补救动作；
- 实际上限。

---

# P11 — 统计与公平性

## 独立性

- unit-level metric 可以按 unit 报，但需同时按 song bootstrap / cluster-aware CI；
- gate 泛化必须 song-level holdout；
- 对 200–300 region 建议补 leave-one-song-out 或至少多 seed song split；
- 不能把同 candidate 的几十个 unit 当完全独立证据包装高置信 AUROC。

## Request fairness

同一 case family 比较：

- checkpoint/model 同；
- decoder 同；
- original baseline 同；
- target unit set 同；
- GT pairing 同；
- 只改变 request construction / slot constraint。

## Cache

必须稳定记录 cache identity，避免重复 forward；同时保证 request family identity 不碰撞。

## Resume

所有 overnight stage 必须：

- append-safe 或 per-request artifact；
- 可按 request_id resume；
- failure 不影响已完成候选；
- 记录 forward/cache_hit/fail 数；
- 失败原因结构化。

---

# P12 — 最终必须输出的结果

## 12.1 Unit transition tables

按 request family × strata：

- safe preservation；
- mild/severe/catastrophic harm；
- strong recovery；
- coverage/missing。

## 12.2 Reject-Safe 专表

比较 RS / US / AS：

- realign 后 remain <=200ms；
- -> >500ms；
- -> >1s；
- collateral safe-neighbor harm。

## 12.3 Request family 行为

- constructibility/coverage；
- active/no-op ratio；
- recovery ability；
- preservation ability；
- collateral damage；
- catastrophic harm；
- runtime / forwards。

## 12.4 Sparse 专表

- active slot 数；
- stable/fixed slot displacement；
- active target recovery；
- safe preservation；
- 与 contiguous local 的公平对照。

## 12.5 Unit-level gate signals

- signed detector changes；
- temporal stability；
- safe-context protection；
- multi-request consensus；
- fixed-point；
- feature counterexamples；
- risk/coverage；
- song holdout / leave-one-song-out。

## 12.6 Oracle basin

- oracle success；
- perturbation sensitivity；
- basin width / discrete jump behavior。

## 12.7 Test Demo

- 实际发现/成功 item 数；
- 多语言真实 detector local spans；
- 40–60 local realign regions 或 exhaustion audit；
- consensus/stability ranking；
- 可选 visualization index。

---

# P13 — 本轮预期结果与可支持结论矩阵

## 情况 A：Sparse / unit-local 显著保护 safe units，同时保留 recovery

支持：

> realign 不可靠主要来自过宽重解释；selective local/sparse intervention 是可行生产方向。

下一轮可以进入 unit-level shadow writeback / closed-loop 小试。

## 情况 B：Oracle 好、production requests 差，且 request perturbation basin 很窄

支持：

> aligner 有能力，但 request estimation 是主瓶颈；应重点做 request search、consensus、stable anchor，而非继续换 detector threshold。

## 情况 C：Oracle 本身也大量不稳定

支持：

> 当前 Qwen FA local realign 不是天然稳定 recovery operator；gate 只能减少风险，不能把它变成可靠主恢复机制。

这是有效 negative result，不应强行继续 heuristic writeback。

## 情况 D：Reject-Safe 明显比 Accept-Safe 更脆弱

支持：

> detector REJECT 即使 GT 当前正确，也携带潜在不稳定信息；Attempt Gate 需要把这类区域和普通 safe control 分开。

## 情况 E：多 request unit consensus 强，而单 signal 弱

支持：

> 使用额外 forward 换取 reliability；gate 应基于多 view 共识而非单 candidate score。

## 情况 F：所有 no-GT signal 在跨歌上都无法区分 good/harm

只有在完成预定 feature exploration、counterexample、consensus/fixed-point 后才能结论：

> 当前 observable evidence 不足以安全判断 writeback。

此时应明确停止继续堆 heuristic gate，并重新考虑模型/接口层面的 recovery 设计。
