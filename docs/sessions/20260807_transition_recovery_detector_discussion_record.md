# 2026-08-07 Transition–Recovery–Detector 讨论记录

## 1. 会话任务与输入

本轮从“review 当前工作目录和实验记录、陈述实验结果”开始，随后围绕 Detector V2、stress、CNN1D、serial propagation、异常构造、Transition/Align/Audio/Recovery 分层逐步收敛为下一阶段实验计划。

输入：

- `LyricAlignment_202608061251_alignandslot3.zip`；
- `EVIDENCE_PACK_20260806_BACKLOG25.tar`。

用户最终要求：形成 patch，**使用全新的 session 目录执行**；patch 中保留完整讨论过程，尤其用户的观点、疑问、纠正和所有提出过的想法；实验计划可拆多份，但必须把具体设置和行为写清楚，避免 Agent 误解，并要求 Agent 不得因局部失败或负结果中途停止。

---

## 2. 初始 review：当前结果状态

对工作目录和 BACKLOG25 evidence 的复审确认：

1. Detector V2 的最终状态应是 `completed=false, partial_exploratory=true`，不能引用中间旧快照中的 `completed=true`；
2. 早期 M4 unsafe rate 约 91.4% 主要受标签错误污染；修复 segment-local→global time 与 sparse-view missing 误标后，unsafe rate 降到约 7.2%；
3. 修复后 `raw_end_entropy` 成为强单信号，AUROC 约 0.954，说明模型 raw posterior 中确实存在与 alignment correctness 相关的无-GT 信号；
4. 高保护 frozen detector 能得到约 99%+ unsafe protection，但 safe accept 很低（official heldout 约 8%，raw 约 12%），更像高置信 safe-commit whitelist；
5. GBDT 等 Pareto 端点显示 safe accept 可以高很多，但这并不等于 SA80 已正式完成；
6. isotonic calibration 显著改善 ECE，但高保护点 safe accept 没改善，说明主要瓶颈是 discrimination / Pareto，不是概率刻度；
7. stress 18 family × 53 feature 的直接分布分析中，多数最佳 AUC 仅约 0.58–0.60，repeated_section 约 0.664，说明现有静态单点 feature 对大量异常信号弱；
8. sequence CNN1D 的旧实验是 sequence-level any-unsafe 标签，验证只有 6 条 sequence（5 unsafe + 1 safe），AUC=1 不能解释为已具备窗口级错误检测能力；把 sequence score 广播到 unit/window 后评价退化；
9. hidden 实际 availability=0，不能结论“hidden 无增益”；
10. cross-view full posterior 未保存，`posterior_distance=0` 不是一致性结果；
11. serial 中只提交约 86/1774 units，且绝大多数提交是正确的，`propagation=0` 主要意味着错误没有真正进入 carried state，不能当作 detector 成功阻断传播；
12. 最新 request identity audit 已闭合 1440/1440，Family-LOO 错串数字也已修正，这些不应在新阶段重复做。

---

## 3. 用户第一轮追问：W95/SA60/SA80、calibration、stress、CNN1D、未做实验、Serial

用户提出六个问题：

1. “detector 不是还补了 w95、sa60、sa80 吗？怎么没有看到结果？”
2. “isotonic calibration 是什么？”
3. “Stress / 文本扰动当前设置足够模拟产品异常吗？当前信号不够强，还有什么新信号和方法？”
4. “CNN1D 是什么？AUC=1 意味着已经能验证窗口级错误吗？它能预测怎样的危险？”
5. “这些当前没做的实验又在做什么？”
6. “Serial 就是没有产生足够跨窗异常？”

讨论后的澄清：

- SA60、SA80、R95/W-R95 已经进入后续实验计划，但 BACKLOG25 中没有正式结果；旧 `protected_recall_95` 与新 R95 不同，后者要求 **REJECT 本身**覆盖 ≥95% unsafe，UNCERTAIN 不能算；
- isotonic calibration 是对风险分数做单调非参数概率校准，解决“0.8 是否真代表约 80% 风险”的问题，不解决 safe/unsafe 本身重叠；旧结果证明 calibration 有效，但不能救 safe accept；
- 现有 stress 足够做第一轮单窗压力测试，但不充分模拟“正确歌曲+正确歌词，前窗 state 错后把下一窗 cursor/occurrence 带错”的产品型串行异常；
- 当前 replace/missing/extra 大量属于窗尾人工文本修改，repeated_section 也更像 text/audio mismatch，不是真正 occurrence ambiguity；
- 新信号优先考虑 cross-window consistency、posterior 多峰/竞争路径、sequence trajectory、hidden sequence、轻量 counterfactual stability probe；
- 旧 CNN1D 不能说明窗口级定位，只能说在极小 sequence validation 上出现“整段是否含任何 unsafe”的探索性排序现象；后续应该改为 per-unit sequence supervision/output；
- 当前没做的 full-slot serial/recovery、SA60/R95、hidden/cross-view 等实验主要想回答真实 carried-state 传播、route 一致性、hidden 增量、工作点和 test-demo 自动化；
- Serial 的核心缺口确实是“没有足够错误进入 committed/carried state”。

---

## 4. 用户关于高提交工作点与前窗异常构造的观点

用户指出：当前 Serial 没产生足够传播，看起来是 detector 太严格、提交太少；如果换后续 W95/SA80 是否会好一些？同时用户质疑简单异常构造：

> 如果只是简单地在前窗尾部多提交若干个零时长，感觉太简单，反而会带偏。

讨论后形成：

- SA80 会显著增加 commit，因此更容易暴露真正 propagation episode；这不等于 detector 更安全，而是实验更有信息量；
- R95/W-R95 仍偏保护，主要用来验证高保护闭环能否截断传播，不一定增加传播样本；
- 主要异常不应直接伪造“明显坏输出”，而应尽量构造**模型会相信的错误 state**。

提出并保留的异常来源：

1. **Natural propagation**：关 detector/放宽工作点，自动找到第一个真实错误 commit 后继续 2–5 窗，不 GT reset；
2. **Model-native forced commit**：从 raw/official disagreement、posterior 第二候选、alternate occurrence 等模型原生候选中选一个 GT 事后确认错误的候选，只人为让它通过一次 commit；
3. **Canonical state corruption**：直接在统一 state 上做 lyric cursor、time cursor、二者协同、wrong occurrence、partial boundary/tail 错误，再让各 transition 自己转换成下一窗输入；
4. 简单零时长/随机文本改动只保留 sanity，不作为主要训练/评价数据。

用户的核心担忧被记录为：异常构造必须尽量贴近“模型自然可能犯的错”，不能让 detector 最后只学到 synthetic artifact。

---

## 5. 提出的后续传播/恢复研究想法

讨论中提出并保留以下想法：

- **错误可恢复性**：区分 self_recover、slow_recover、persistent、amplifying、occurrence_jump；
- **拦截时机**：同一错误在 t-1、t、t+1 才恢复，比较损失和成本；
- **commit/recovery granularity**：whole-window、局部 gap、连续 safe prefix 等；
- **Oracle recovery upper bound**：GT 只做 trigger/anchor，上界拆分 detector limitation、recovery limitation、aligner intrinsic limitation；
- **Propagation phase transition / stability basin**：研究 cursor/time 初始误差多大开始从可自恢复进入持续传播；
- **错误类型 × 传播能力**：不再只看 stress AUC，而看哪类错误真正有“传染性”；
- **Occurrence ambiguity benchmark**：真实重复副歌 + mechanical audio/lyrics/GT 同步复制；
- **Context sensitivity / wrong-context vs no-context**：错误 context 是否本身是传播媒介；
- **silence 作为 recovery anchor**：长静音是否天然提供重置点；
- **raw-only / official-only / disagreement-only 小型消融**；
- **propagation-family leave-one-out**：验证 detector 学通用 instability 还是记异常类型；
- **同一个错误 state 换 decoder/route**：公平比较自恢复；
- **test demo 自动 failure mining**：无 GT 下自动排名可疑片段，而不是只生成结果等待人工看；
- **precursor signal**：在实际错误发生前 5–20 units 是否已有 entropy、posterior、hidden、cross-window 前兆；
- **propagation-risk detector**：预测“如果 commit 会不会让后续变差”，而不只是当前是否错。

用户要求后续计划最终收敛，不做这些想法的全组合；可按优先级执行，并保存未执行/负结果。

---

## 6. 用户关键纠正：“真实串行系统”本身并不稳定

用户指出：

> 问题在于“真实串行系统”也是不稳定的。且不说是否要使用串行，如果使用串行，也有很多种且已经实现了几种串行的方案。

这是本轮计划结构上的关键转折。

讨论后不再把某一个 stable-window serial 预设为真实产品系统，而是先研究 execution regime / state transition policy。本阶段先回答：

- 是否需要串行；
- 不同串行推进方式的稳定性；
- slot 与 serial 的层次关系；
- 哪种 transition 天生更抗 state error。

随后才在少数 candidate transition 上研究 detector/recovery。

---

## 7. 用户重新定义系统层次：slot 属于 Align，分窗推进属于 Transition

用户进一步明确：

> slot 应该和 non-slot 并列，是模型对齐的查询方式，归于 Align；而分窗推进更像 Transition 中的行为。

用户列出当前已有设计：

### Align

- slot；
- non-slot。

### Transition / 推进

- 直接串行；
- 核心+边界串行；
- 提交到 stable 边界串行。

### Window planner

- 直接/fixed 分窗；
- 静音吸附；
- 强制静音边界。

### Audio preprocessing

- 不处理；
- 去除/压缩一定长度以外的静音区。

讨论补充了此前容易漏掉的维度：

- non-serial/independent 也应是 Transition 正式成员；
- skip silent windows；
- leading silence handling；
- short tail redistribution / merge；
- left context + core + right lookahead 的 Window input 层；
- raw/official Decoder 单列；
- boundary ownership、text/query span 等作为实现细节/次级轴；
- Commit 与 Transition 高度耦合，可并入串行策略；
- complex provisional-tail 并非必须，如果 stable-boundary 当前实际语义只是“stable 后不提交、下一窗重算”，就按真实实现描述。

---

## 8. 用户进一步收敛主实验轴

用户明确当前偏好和优先级：

1. **Align**：slot 可以直接用 full；full-slot 看起来更有优势，non-slot 只少量尝试；
2. **Decoder**：先 raw 和 official；raw 主要研究，official 需要时作为输出和次选；
3. **Window input**：固定左右上下文，即 left 10s + core 60s + right 10s；
4. **Commit policy**：更像针对串行的策略，可以归入 Transition；
5. **Planner**：主要 silence snap，只少量 fixed；并保留 skip silent、leading silence、tail-window；
6. **Audio preprocessing**：个人倾向压去过长静音，但要保留约 3–5s，且注意与 silence snap 相关；
7. **Transition**：行为本身已经计划要实验，是接下来主线。

由此正式收敛为四个核心维度：

- Align 2 种（full-slot 主，non-slot 小对照）；
- Transition 4 种（independent、direct serial、core+boundary、stable-boundary）；
- Audio preprocessing 2 种（original、compress long silence）；
- Recovery/control 4 种（none、shadow、L、W）。

但明确**不能做 2×4×2×4 全排列**。

---

## 9. Provisional tail 的讨论与最终处理

用户问 provisional tail 是怎么做的。

讨论解释了概念：stable prefix 永久 commit，尾部暂存 provisional、下一窗重新观察并可覆盖。

随后进一步收敛：如果当前“提交到 stable 边界串行”的真实实现只是：

- stable boundary 前永久提交；
- stable boundary 后不提交；
- 下一窗重新求解；

则不需要为了术语额外实现一个复杂 provisional-tail state。正式实验必须以当前真实实现为准，避免因为名字引入额外状态和实验维度。

---

## 10. 最终三条实验线

用户总结：下一步存在三件事：

1. **先 Transition–Recovery 的主线**；
2. **先前实验缺陷的补充**；
3. **Detector 的研究**。

随后要求整理并形成 patch。

最终计划结构：

### 主线 A — Transition → Propagation → Recovery

- 统一 full-slot + 10/60/10 + silence-aware baseline；
- 先比较 T0–T3，不接 detector；
- 选 product candidate 和 mechanism candidate；
- 构建 natural/model-native/canonical-state propagation benchmark；
- 研究 stability basin、recoverability；
- 先做 Oracle-L/W 上界；
- Detector 工作点冻结后再做 L/W closed-loop。

### 基础线 B — 旧缺陷补齐

- stress evaluator 同 frozen model；
- 旧 serial propagation 结论用新 benchmark 补齐；
- hidden extraction 真正执行；
- cross-view full posterior targeted re-forward；
- repeated-section 改成 occurrence benchmark；
- CNN1D 旧 AUC=1 结论纠正；
- isotonic calibration 不再作为主优化方向；
- 已闭合 1440/1440 identity 等不重复。

### 研究线 C — Detector

- 正式完成 SA60、SA80、R95；
- joint SA60+R95 不可行也不能停止；
- cross-window consistency；
- posterior competing path；
- per-unit CNN/TCN；
- hidden sequence；
- propagation-risk detector；
- 最终只在 selected Transition 上做 L/W closed-loop。

---

## 11. 用户关于 Agent 执行方式的最终要求

用户最后明确：

> 形成 patch，要求 agent 以新的 session 目录执行。patch 中要包括讨论记录与实验计划。讨论记录总是记录讨论过程，尤其是我的观点与疑问。提出的想法也都要纪录留存。实验计划可以分多份，要求 agent 不能中途停止，写清具体设置与行为以免 agent 误解。

因此本 patch 将：

- 新建独立 `docs/research_transition_recovery_detector_20260807/`；
- 新建本完整讨论记录；
- 不覆盖旧 v7/fullslot 计划，而是标为上游历史；
- 规定新 SESSION_ROOT；
- 规定 formal 前 existing implementation mapping；
- 明确 negative result / bounded insufficient / joint infeasible 都不能让整个 session 提前结束；
- 只有会污染全部结果的全局基础设施阻塞可以停止，且必须留下 resume 命令和完整证据；
- 明确 12h 预算与优先级裁剪，不允许为了“跑完”扩大成笛卡尔积。

---

## 12. 当前结论强度与待验证内容

### 已有较强证据

- raw posterior 存在 correctness signal，尤其 raw end entropy；
- isotonic calibration 能改善概率校准但不能解决 safe/unsafe 分离；
- 旧极保守 detector safe accept 太低，导致 serial propagation 难以观测；
- 旧 stress 单点 feature 对多数 family 辨别力弱；
- hidden/cross-view 旧实验并未真正完成；
- CNN1D 旧 AUC=1 不足以支持窗口级检测能力。

### 当前研究假设，尚未验证

- SA80 会更容易产生有信息量的真实传播 episode；
- stable-boundary 或 full-slot transition 天生拥有更大的自恢复 basin；
- occurrence/cursor 协同错比明显零时长错误更危险且更难检测；
- cross-window consistency / competing posterior path 能发现低 entropy stable-but-wrong；
- propagation-risk detector 比 correctness detector 更适合产品；
- long-silence compression 保留 3–5s 比完全不处理更稳，同时不破坏 silence snap；
- L 可以在接近 W 保护能力下减少重跑和正确内容阻塞。

这些都必须由新 session 实验验证，不能在实现前写成结论。
