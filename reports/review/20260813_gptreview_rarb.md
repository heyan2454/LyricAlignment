请 review 当前 LyricAlignment 工作目录、最近一次 detector→realign gate P0/P1 的实验代码、实验记录和 evidence。你的任务不是直接执行完整实验，而是：

1. 核实当前代码与现有 evidence 的真实状态；
2. 针对下面列出的问题，给出完整、可执行的代码修改与实验实现方案；
3. 明确哪些当前代码已经修复、哪些只是部分修复、哪些仍需修改；
4. 给出 OpenCode 可以直接照着实施的文件级 implementation plan、测试方案和实验执行顺序。

后续由 OpenCode 负责真正修改代码与运行实验，因此方案需要足够具体，不要只给原则性建议。

# 一、背景与当前已发现的问题

最近一次 P1 evidence 确实执行了真实 GPU realign forward，但实验设计和评价存在多项问题，不能沿用旧的 `ACCEPT_WRITEBACK` 结论。

目前 review 得到的主要事实如下，请你逐项核实，不要直接假定全部正确。

## 1. P1 样本构成严重失衡

旧正式 P1 大约只有：

* S1 correct + detector accept：1
* S2 correct + detector reject：2
* S3 bad + detector reject：22
* S4 bad + detector accept：0

同时还排除了不少处于中间误差区域的候选。

这不足以评价 detector→realign gate。

### 新要求

P1 正式样本目标改为：

* S1：25 个
* S2：25 个
* S3：25 个
* S4：25 个

即理想情况下至少 **100 个有效 P1 cases**。

这里的 25 个必须指：

* case 合法；
* 有真实 baseline；
* target region 合法；
* 至少能够执行一个真实 realign intervention；
* 不是因为 request 与 baseline 完全相同而形成的 null intervention。

不能把只是进入 case pool、最后无法 realign 的样本计入 25 个。

请设计合理的 sampling / replenishment 机制，使每组最终尽量达到 25。

优先顺序建议为：

1. 扩大当前歌曲中的 region 数量；
2. 扩大 baseline 数据和歌曲覆盖；
3. 使用更多现有数据集 / Test Demo 的真实样本；
4. 如果某些 quadrant 天然极难获得，再考虑受控扰动产生相应 case。

但天然 case 和 synthetic / injected case 必须分别记录和汇报，禁止静默混合。

如果最终某一类仍无法达到 25，需要：

* 明确说明 scarcity；
* 给出搜索过多少候选；
* 为什么不能达到；
* 实际数量；
* 不能简单降低目标后继续而不报告。

同时不要因为为了凑 25 个而重复高度相似的同一歌曲/同一局部 region。需要考虑 song-level diversity 和 region overlap。

---

# 二、重新明确 S1–S4 的定义

请首先从现有实验代码和文档中核实 S1–S4 当前冻结定义，不要自行重新发明。

预计语义为：

* S1：baseline 正确 / detector accept
* S2：baseline 正确 / detector reject
* S3：baseline 错误 / detector reject
* S4：baseline 错误 / detector accept

但请核实：

* “correct / bad”的 GT metric 和 threshold；
* detector accept / uncertain / reject 的定义；
* uncertain 如何处理；
* 以前被排除的中间误差区为什么被排除。

本轮不要再无理由丢掉中间误差样本。

如果 correctness 目前实际上是两个极端阈值，中间区域没有定义，请设计一个清晰方案：

* 主 S1–S4 仍保持冻结的 high-confidence correctness 定义，用于主要 gate 分析；
* 中间区域额外作为 boundary / ambiguous cohort 单独报告；

不要把不同 correctness 口径混在一起。

---

# 三、Realign 方案需要按新代码重新正式评价

旧 evidence 中：

* R-B `safe_anchor_bounded` 23/23 实际与 baseline input 相同，是 null intervention；
* R-A 中也存在部分 null intervention；
* 旧 target scope 经常覆盖整个 window，而 realign 实际只处理较窄文本范围，造成大量 covered→missing 假象或合同错配。

当前工作目录似乎已经向以下方案演进：

* R-U：unit-local
* R-A：local unsafe range
* R-B：bilateral safe-anchor bounded
* R-S：sparse / fixed-context realign

请核实实际实现。

本轮 P1 应围绕这些方案重新设计。

## 要求

### 1. 所有 strategy 必须检查 intervention 是否真实发生

为每一个 candidate × strategy 保存：

* baseline audio range
* candidate audio range
* baseline text/unit range
* candidate active units
* fixed/context units
* input hash 或等价 identity
* 是否为 null intervention
* null 原因

如果 candidate request 与 baseline 等价：

* 不得把它当作 realign 成功或 neutral safety evidence；
* 在 strategy coverage 中单独计为 `null / not-applicable`；
* 如果是代码 bug，应阻止正式 run 或修复 request 构造。

### 2. Strategy 可构造性需要单独统计

例如 R-B 可能因为左右 anchor 不存在而无法构造。

因此对每种 strategy 汇报：

* selected cases
* constructible
* executed
* null
* failed
* valid evaluated

不能因为某个 strategy 无法构造就删除整个 case，其他 R-U/R-A/R-S 仍应正常执行。

### 3. 尽量使用 paired case 比较

同一个 P1 case 尽量在多个适用的 realign strategy 上运行，这样可以直接比较：

* R-U vs R-A
* R-A vs R-B
* R-A vs R-S
* R-U vs R-S

但避免为了形式完整再与所有 detector threshold、decoder、window policy 做笛卡尔积。

本轮冻结 baseline / detector / decoder，只研究 realign behavior 和 gate。

---

# 四、修复 target / evaluator 合同

这是本轮最重要的 correctness 问题之一。

旧实验中 `target_unit_ids` 经常是一整个 window，例如一百多个 unit，而 realign request 实际只覆盖其中一小部分。

于是 evaluator 把 request 根本不负责输出的 context unit 判成：

`covered_to_missing`

这种评价合同不正确。

请检查当前 `_localize_target_ids()`、`MAX_LOCAL_TARGET_UNITS` 等修改是否已经完全解决。

## 新合同至少需要区分

### active target units

本次 realign 真正允许修改、需要重新预测和评价的 unit。

### fixed context units

只是用于提供上下文，但不应该要求模型重新负责输出，或者在 sparse 模式下最终应恢复 baseline。

### outside units

完全不属于这次 intervention。

对于每个 strategy，要明确：

* model 实际看到哪些文字；
* 哪些 unit 有 timestamp slot；
* 哪些 unit 允许变化；
* 哪些 unit 必须保持 baseline；
* writeback region 是什么。

Evaluator 的 improve / harm / missing 必须严格只根据该 strategy 的责任范围解释。

禁止再次用“整个 window target”评价“局部 realign”。

---

# 五、修复 missing harm 被 headline 指标漏掉的问题

旧 `FINAL_REPORT` 得到：

* improve 45
* harm 42
* neutral 4405
* net≈0

但 GT 原始结果里还有大量 `covered_to_missing / catastrophic_harm`，因为这些 row 没有 finite `delta_error_ms`，被汇总逻辑排除了。

请检查当前 `report.py`。

正式指标不能使用：

`delta_error_ms is not None`

作为 harm 是否存在的前提。

至少需要把 outcome 拆成：

* improved finite pair
* degraded finite pair
* unchanged finite pair
* covered → missing
* missing → covered
* extra prediction
* invalid / unpairable
* context-only change（如果适用）

并生成两个层次的评价。

## A. Unit-level outcome

对 active target units 统计：

* target coverage before / after
* missing rate before / after
* improve rate
* harm rate
* catastrophic harm rate
* neutral rate
* MAE / median
* ≤100 / 200 / 500 / 1000 ms
* large improvement，例如 ≥200ms / ≥1s
* large harm，例如 ≥200ms / ≥1s

### 注意

missing 不允许因为没有 `delta_error_ms` 就消失。

## B. Candidate / region-level outcome

每个 realign candidate 至少标注：

* beneficial
* neutral
* harmful
* catastrophic harmful
* mixed

并明确 classification rule。

不要把一个 candidate 内：

* 修好了 5 个 unit
* 但弄丢了 10 个 unit

简单平均成“略有改善”。

需要同时报告 benefit 与 harm。

---

# 六、Gate feature / label 对齐问题

当前还有一个潜在 bug：

GT unit row 与 `NO_GT_FEATURES` 如果按 new-output unit key 直接 inner join，那么“target 完全 missing”的 unit 可能没有 new feature，从而在 gate label 构造前再次被丢掉。

请检查这一点。

Gate 数据集最好以：

`candidate / active target unit definition`

为主索引，而不是“new prediction 是否存在”为主索引。

即使 realign 把 target unit 弄丢，也必须：

* 保留该 GT outcome；
* 保留 candidate-level no-GT features；
* 将 missing harm 纳入 candidate harm label。

请设计不会 silently drop missing failures 的 join schema。

---

# 七、Gate 禁止使用 GT outcome 作为输入 feature

旧 evidence 出现：

* AUROC(delta)=1.0
* `harmful_risk_writeback_holdout=0`
* `ACCEPT_WRITEBACK`

这是无效结论，因为 `delta_error_ms` 本身就是 GT outcome。

当前代码似乎已经修改为：

`DIAGNOSTIC_ONLY_NO_WRITEBACK`

请核实，并正式冻结以下原则：

> GT 只能定义训练/评估 label，不能作为 deployment / no-GT gate feature。

请明确整理 gate features：

## 可以使用

例如：

* detector p_bad before / after
* accept/reject state transition
* displacement
* number of changed units
* max / sum / quantile displacement
* monotonicity / inversion
* slot violation
* overlap / compression
* safe-context changed count
* decoder confidence
* raw / official disagreement
* hidden-derived no-GT features
* local consistency

实际字段以仓库已有内容为准。

## 禁止使用

* GT timestamp
* old GT error
* new GT error
* `delta_error_ms`
* GT improve/harm outcome
* 任何由 GT outcome 间接计算出的字段

报告中必须将：

* oracle diagnostic
* deployable no-GT feature

分开。

本轮仍保持：

`writeback_gate = NOT_FROZEN`

除非后续新的无 GT gate 实验真正证明安全性。

不要输出 `ACCEPT_WRITEBACK`。

---

# 八、区分“是否发生大变化”和“变化是否有益”

旧结果中一些 no-GT features 对 harm 看起来 AUROC 很高，例如：

* abs detector delta
* max displacement
* sum displacement
* safe context changed count

但它们可能只是很好地区分：

“这个 realign 是否真的大幅改变了输出”

而不是：

“改变以后更好了还是更坏了”。

因为旧 neutral cases 中包含大量 null intervention。

新实验必须显式消除这个 confound。

建议至少分三层问题：

1. intervention detection
   是否真的改变了结果？

2. unsafe-change detection
   是否产生了明显的大范围扰动？

3. beneficial-vs-harmful discrimination
   在真实发生 intervention 的情况下，它到底修好还是改坏？

Gate 最重要的是第 3 个。

评价 gate feature 时，至少额外给：

* all candidates
* non-null candidates only
* changed candidates only
* harmful vs beneficial/mixed

的结果。

不能再次让 null cases 抬高 AUROC。

---

# 九、重点评价 reject-safe / correct-but-rejected

我们尤其关心：

> detector reject 以后触发 realign，会不会伤害原本正确的区域？

因此 S2 `correct + reject` 必须真正收够约 25 个，并作为独立 safety cohort。

对 S2 单独报告：

* realign 后仍正确比例
* harmed candidate 比例
* catastrophic harm
* safe units 被改变多少
* safe-context change
* target missing
* 各 strategy 的比较

这是判断 realign 是否“reject-safe”的核心实验。

同时 S3 `bad + reject` 用于判断：

> 真正错误的区域，realign 能修多少？

因此不能只汇报总体 average，要同时比较：

* S2 safety
* S3 recovery

理想 realign 应在：

* S2 少伤害
* S3 有恢复

两方面同时成立。

---

# 十、S1 与 S4 也必须有足够样本

S1 `correct + accept`

主要作为负对照：

* detector 不认为危险；
* 如果强行 realign，会发生什么？
* realign 自身的扰动基线是多少？

S4 `bad + accept`

尤其重要，因为它表示 detector false negative：

* detector 没触发时错误是否会持续？
* 如果 oracle-trigger realign，是否其实能修？
* 哪些信号可能补足 detector 的漏检？

P1 样本不能再几乎全是 S3。

四个 quadrant 都需要分析。

---

# 十一、Test Demo 必须区分 plan 和真实执行

旧 evidence 里的 Test Demo：

* adapter=mock
* formal=false
* 有 request plan
* 没有真实 realign GPU outcome

但旧报告容易把它写成“stress test ok”。

当前代码似乎已经修正命名，请核实。

正式要求：

* `REQUEST_PLAN`：只代表候选生成；
* `REALIGN_BEHAVIOR`：只有真实执行后才能写；
* mock 不得计入 formal behavior；
* 未执行必须明确 `not_executed`。

如果本轮预算允许，设计一个真正的 Test Demo GPU realign stress 阶段。

不要求完整人工听感，但应自动统计：

* language
* song
* windows
* selected regions
* strategy
* detector transition
* displacement
* null rate
* failure rate
* suspicious behavior

Test Demo 数量不要写死成历史上的中文17/其他语言6；动态读取当前数据。

---

# 十二、扩大 P1 的建议方式

Realign forward 已验证比较快，因此本轮不应再只做约 23 个 case。

请设计一个可 resume 的两阶段方案。

## Phase P1-A：balanced formal behavior

目标：

S1/S2/S3/S4 各 25 个有效 case。

首先只冻结少数 realign strategy：

* R-U
* R-A
* R-B
* R-S

同一 case 尽量 paired comparison。

不要增加 decoder × detector × window policy 的笛卡尔积。

## Phase P1-B：扩大 region

如果 100-case balanced run 成本可接受，再扩 region 数，重点扩大：

* S2 correct+reject
* S3 bad+reject
* S4 bad+accept
* detector boundary / uncertain cases
* 高 reject density
* sparse reject
* isolated unit error
* contiguous multi-unit error
* large accumulated misalignment

扩大时优先增加 case diversity，而不是只重复一个类别。

---

# 十三、Realign 评价应改成 unit / region 为核心

旧版过多使用 window-level：

“这个窗口只要有 reject 就 unsafe”。

但正式 detector baseline 约为：

* unit accept ~85%
* unit reject ~14%

而 window unsafe 接近 100%。

因此 window unsafe 不应该作为 realign safety 的主要评价单位。

请把正式分析至少分成：

1. unit-level
2. active-region-level
3. candidate-level
4. song-level

window-level 仅作为辅助。

特别记录：

* unsafe region 长度
* unsafe unit 数
* reject density
* 左右 safe context
* isolated vs contiguous
* region distance to boundary
* region distance to silence
* region position in serial sequence

这些特征后续可能比整个 window label 更有意义。

---

# 十四、需要重新计算 / 更新的 artifacts

请检查并规划重新生成至少以下内容：

* CASE_POOL
* balanced selected cases
* per-strategy request manifest
* forward manifest
* GT unit outcomes
* GT candidate outcomes
* no-GT features
* deployable gate dataset
* per-quadrant report
* per-strategy report
* null-intervention report
* missing/coverage report
* reject-safe report
* Test Demo plan / execution report
* FINAL_SUMMARY
* FINAL_REPORT
* STATE / handoff / session records

旧 `STATE.md`、handoff 和 report 中已经存在互相不一致的状态，需要修正。

归档文件必须明确：

* 哪些是旧 evidence；
* 哪些是本轮 rerun；
* 不要让旧 `ACCEPT_WRITEBACK` 继续出现在当前结论里而无 deprecated 标记。

---

# 十五、代码测试要求

OpenCode 修改后必须先跑 CPU/unit tests，再进行 GPU experiment。

请为实现方案列出测试。

至少包含：

1. localized target 不会扩成整个 window；
2. fixed context 不会被错误计入 target missing；
3. real target missing 会计为 harm；
4. missing row 不会因为 feature join 被丢弃；
5. null intervention 正确识别；
6. R-B 无 anchor 时不会删除其他 strategy；
7. R-S 只有 active units 可变；
8. candidate-level mixed/harm classification 正确；
9. GT 字段不会进入 no-GT gate feature；
10. formal Test Demo 禁止 mock behavior 冒充真实结果；
11. balanced sampler 能独立补齐 S1–S4；
12. resume 不会重复 forward；
13. repeated run 不覆盖已有正确结果，除非显式指定。

如当前 zip snapshot 无 `.git`，不要因为 repo_head 缺失导致核心实验测试失败；provenance 可以保存 `repo_head=null/snapshot`，但不能把这个问题混同于实验 correctness。

---

# 十六、缓存、resume 与运行成本

GPU forward 已经证明不是主要瓶颈。

实现时需要：

* baseline forward cache
* candidate request hash
* per-strategy cache
* resume manifest
* completed / failed / skipped 分开
* atomic write 或等价安全机制
* 不重复执行已完成 request
* failure 可以单独 retry

输出中记录：

* forward count
* cache hit
* wall time
* per-strategy time
* failures

不要为了 provenance 设计过度复杂的证明系统。

---

# 十七、最终需要你输出的内容

你现在不要直接开始长时间 GPU 正式实验。

请输出一份供 OpenCode 执行的 implementation plan，必须包括：

## A. Current-state audit

逐项说明：

* 已经实现
* 部分实现
* 未实现
* 旧 artifact 需要废弃/重算

## B. 文件级修改方案

明确到：

* 哪些 Python 文件修改；
* 哪些函数修改；
* 新增哪些 schema / field；
* 哪些旧字段需要兼容；
* 哪些 report 修改。

## C. Balanced P1 sampler 方案

详细说明怎样得到：

* S1 25
* S2 25
* S3 25
* S4 25

包括不足时的 replenishment 策略。

## D. Realign request / target contract

分别写清 R-U / R-A / R-B / R-S：

* active target
* context
* audio range
* text range
* writeback scope
* null 判定

## E. Evaluation schema

明确：

* unit outcome
* region outcome
* candidate outcome
* missing
* extra
* catastrophic
* mixed
* metrics

## F. Gate schema

明确：

* label
* no-GT feature
* forbidden GT feature
* join key
* null filtering
* changed-only evaluation

## G. Test plan

给出先 CPU test、smoke，再 GPU formal 的顺序。

## H. OpenCode 执行步骤

给出可以直接照做的阶段顺序。

不要要求 OpenCode 一次性跑巨大的无边界笛卡尔积。

目标是：

> 先修复实验 correctness，再用 balanced S1–S4 各约 25 个 case 正式评价 unit/region-local realign 是否能做到“错误区域有恢复、正确但被 reject 的区域少受伤”，然后才讨论 writeback gate。
