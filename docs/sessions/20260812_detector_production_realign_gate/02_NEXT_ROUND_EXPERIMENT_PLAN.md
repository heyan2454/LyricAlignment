# 下一轮实验设计：Detector Production Audit + Realign Behavior Gate

- 日期：2026-08-12
- 研究定位：小规模、机制优先、直接利用当前机器已有数据/cache。
- 运行规模：**detector 尽量广覆盖，realign GPU 推理适度采样**。
- 预算建议：GPU 目标约 4–6h，硬上限 8h；若实现评估预计超过 6h，优先缩减 realign candidate 数，不缩减可由缓存/CPU完成的 detector production audit。不得超过项目此前 12h 总实验上限。
- 禁止：重新训练模型、重新做 decoder/slot/transition/silence planner 大消融、重新做 detector 大 feature search、笛卡尔积。

---

# 0. 本轮总问题

本轮必须直接回答三个问题：

1. **Detector production behavior**：Raw detector 在接近真实生产窗口 population 中，是否仍能保持较高 safe accept，而不是像 recovery 困难子集那样几乎全报？
2. **Realign harm / behavior**：当 realign 用在 bad region、普通正确 region、尤其是“GT 正确但 detector 判坏”的 region 时，会产生什么不同表现？
3. **Realign gate**：不用 GT，只观察 original→candidate 的行为变化，能否找到足够有用的信号来判断“应该写回 / 不应写回 / 存疑”？

本轮**不要求真正完成 stateful closed-loop E9**。先把 detector prevalence、realign harm 与 gate signal 研究清楚，再决定下一轮是否恢复 closed-loop 主线。

---

# 1. 冻结 baseline 与数据 inventory

## 原因

上一轮 recovery cohort 只有 5+5 首主要 real-GT song，并且 natural 30-window 子集明显偏困难，不能代表 production distribution。用户认为已有数据集应支持明显更大的 song coverage，同时要求本轮不要做大。

## 目的

先弄清机器上当前**实际可合法使用**的数据规模，再决定 sampling；不再写死“5+5”。

## 设计

Codex/OpenCode 实现必须先输出：

```text
DATA_INVENTORY.md/json
DETECTOR_BASELINE_IDENTITY.md/json
TEST_DEMO_INVENTORY.md/json
```

### M4Singer / real-GT inventory

自动枚举当前 accepted real-GT lineage、可构造 long/product-style serial windows 的 source songs：

- song identity；
- split/role；
- duration；
- GT unit count / coverage；
- 是否已有 alignment/cache；
- 是否满足 60s core + 10/10 context production baseline；
- 是否可安全进入 detector audit；
- 是否可进入 realign GT sampling。

不得因为旧 cohort builder 只输出 5+5 就继续固定 10 首。

建议目标：若数据允许，realign sampling 的 source-song pool 至少扩大到约 20 首以上；理想 20–40 首。**这是采样池，不是要求每首都做大量 realign。** 若真实可用数量更少，必须记录约束原因，不得静默回到 5+5。

### Test Demo inventory

动态扫描当前机器上全部 Test Demo，不硬编码历史“12首/23首/35首”等数量：

- 中文、英文、日文、粤语等当前实际存在的语言；
- 文件 identity / duration；
- 现有 baseline/cached alignment 是否可复用；
- 可用 raw/official/detector evidence。

Test Demo 无真实 GT 时，不得生成准确率结论。

## 预期结果

能明确回答“为什么上一轮只有 5+5；当前实际上还能合法扩到多少”。

## 结果能说明什么

- 若可用 song 明显 >10：上一轮规模主要是 cohort 选择限制，不是数据集本身限制；下一轮应扩大 song coverage。
- 若确实受 GT/long-timeline/identity 限制：后续报告必须明确瓶颈，不再模糊写成“数据集不够”。

---

# 2. E1 — Detector Production Audit

## 原因

上一轮 recovery natural 30 windows 中 detector 约 29/30 被触发，与此前 Raw retrospective safe accept ≈0.8320 的印象冲突。最可能原因之一是 recovery cohort selection bias，但必须用 production-style population 核实。

## 目的

核实当前冻结 Raw detector 在更自然生产分布上的：

- ACCEPT / UNCERTAIN / REJECT prevalence；
- safe accept；
- catastrophic/error protection；
- false-positive 正确区域的性质；
- Test Demo 上是否出现整首/长段持续报警。

## 冻结项

- Raw 为主；Official 仅同 forward/cached 情况下 shadow；
- 使用 `light_merge` 修复后的当前冻结 detector artifact；
- threshold/provenance 原样记录；
- **主实验先测不调**；不得看到本轮 GT 后重新调 threshold 再汇报为 production audit。

## 数据

### E1-A：M4Singer / 有 GT production-style audit

尽量复用已有 cached alignment，对 inventory 中合法 source songs 做 production 60/10/10 serial/window population 统计。

如果 alignment 推理已经缓存，detector audit 可以覆盖较大的 song/window 范围；不要为了“本轮小规模”人为又缩成 10 首。

### E1-B：Test Demo / 无 GT product behavior audit

对当前**全部自动发现** Test Demo 统计：

- 每首 ACCEPT / UNCERTAIN / REJECT unit 与 window 比例；
- 最长连续 reject/uncertain；
- 每分钟 trigger 次数；
- window position（head/middle/tail）；
- raw/official disagreement（若可低成本取得）；
- top suspicious windows 自动排名。

Test Demo 只做行为/stress evidence，不声称 precision/recall。

## GT 口径

主 correctness 至少同时保存：

- start <=100ms AND end <=100ms；
- <=200ms；
- <=500ms；
- >1s / >2s / >5s catastrophic；
- unit-level 与 window-level 分开。

不得把 window 含任意 >=1s unit 的 binary GT 与 unit-level safe accuracy 混为一个指标。

## 主指标

### Unit level

- safe accept / safe uncertain / safe reject；
- unsafe accept / uncertain / reject；
- protected recall；
- catastrophic miss rate。

### Window level

- ACCEPT/UNCERTAIN/REJECT prevalence；
- 含 catastrophic unit 的 window trigger recall；
- 完全正确/高质量 window 的 false-trigger rate；
- 每首分布与 pooled 分布都报告。

### 与历史结果比较

只做 apples-to-apples 的口径比较：

- Raw retrospective-after-fix safe accept ≈0.8320、protected recall ≈0.9567 作为历史参考；
- 明确标记它不是 untouched formal baseline；
- 新 audit 若 population/metric 不同，不强行直接比较单一数字。

## 预期结果与解释

### A. Production-style safe accept 恢复到约 70–85%，且 catastrophic protection 仍高

支持：

> 上一轮 29/30 trigger 主要是困难 recovery cohort selection bias；detector 仍可作为生产 realign trigger。

### B. M4 production-style 仍大面积 reject

支持：

> detector 当前实际过保守，需要重新审视 threshold/feature 或 unit→window aggregation；realign gate 不能掩盖 trigger 层问题。

### C. M4 尚可，但 Test Demo 大量持续 reject

支持：

> 存在跨域/真实产品输入分布问题；需要按语言/录音条件/窗口位置定位，而不能仅依赖 M4 GT 指标。

---

# 3. E2 — Realign Behavior Dataset：重点加入正确但 detector 判坏的 hard negatives

## 原因

过去 recovery 主要围绕 bad regions，不能回答产品最危险的问题：

> 原 alignment 已经正确，但 detector false positive 触发 realign，是否会把它改坏？

同时上一轮 realign 只依赖 5+5 song cohort，song diversity 不够。

## 目的

构造一个**比上一轮更广 song coverage，但 GPU 总量仍受控**的 realign behavior dataset，供后续 gate feature exploration。

## 样本规模

目标总量：约 **60–100 个 GT region/window**。

从更大的 source-song pool 按 song 分层抽取；不要让少数困难歌曲占满样本。建议至少覆盖约 20 首 source songs（若 inventory 支持）。

不要追求所有歌曲、所有错误全跑 realign。

## 四类核心 strata

### S1 — correct + detector ACCEPT

普通正确 control。

### S2 — **correct + detector UNCERTAIN/REJECT**

本轮最重要 hard negative，建议占总样本约 25–35%。

重点回答：detector FP 触发 realign 后会不会伤害正确 alignment。

### S3 — bad + detector UNCERTAIN/REJECT

正常 recovery case。

### S4 — bad + detector ACCEPT

Detector false negative；样本可能较少，主要用于机制分析，不要求强行平衡。

## correct/bad 定义

不要只设单一 threshold。保留多层：

- strict correct：start/end <=100ms；
- usable-like：<=200ms；
- loose：<=500ms；
- catastrophic：任一主要边界 >1s（另报 >2/5/10s）。

Sampling label 可用 200ms/1s 做主层次，但 raw table 必须保留连续 error。

## Realign variants

默认每个 region 只跑 **2 个代表性 request**，避免 O0/O1/O2/O3 全矩阵：

1. **Narrow/local proposal**：当前最合理的 no-GT local repair request；
2. **Anchor/context variant**：在相同目标附近增加少量稳定 anchor/context 的版本。

具体 request 如何从 no-GT 信息构造，由 Codex 在当前代码基础上给实现方案，但必须：

- 保持 text identity；
- 不允许使用 GT timestamp 作为线上 request 输入；
- GT 只用于 sampling 与最后评分；
- 复用相同 forward/cache identity；
- candidate 必须保存 request text/audio range、ownership 与 provenance。

仅对少量 ambiguous/counterexample case 追加 third variant 或 second realign stability，不进入全量矩阵。

## Test Demo realign 子集

从 E1-B 自动 ranked suspicious cases 中选约 **10–20 个**，覆盖多语言/不同异常类型。

无 GT 时只观察：

- 改动规模；
- proposal consistency；
- raw/official/detector behavior；
- 结构异常；
- 必要时生成可视化/视频供人工 spot-check。

不得把 Test Demo “看起来好”记成 formal repair success。

## 预期结果与解释

### A. S2 大多数 realign 几乎不改或稳定返回相近结果

支持：realign 对 detector FP 有一定天然稳定性，gate 主要需要防少数异常 candidate。

### B. S2 经常从 <=100/200ms 被打到 >500ms/>1s

支持：realign 本身是显著产品风险，必须有强 writeback gate；detector 高 recall 不足以保障系统安全。

### C. S3 可以改善而 S2 基本保持

这是最理想机制：说明 realign behavior 本身可能存在区分 improve/harm 的 no-GT signal。

---

# 4. E3 — Realign Gate Signal Exploration（直接在机器上分析）

## 原因

用户明确希望不要只预设理论 feature，而是让 agent 在机器上直接分析 realign 不同行为，看有没有好用信号。

上一轮已经出现 `n_big` 等 seed signal，但样本太小且存在探索偏差。

## 目的

在**完全不使用 GT 作为线上 feature**的前提下，寻找 original→candidate 的 differential signal，预测：

- improve；
- neutral；
- harm；
- catastrophic harm。

## 数据隔离

按 **source song** 切分 exploratory 与 holdout，避免同歌重复段泄漏：

- discovery/dev：约 2/3 songs；
- quick holdout：约 1/3 songs。

阈值/简单组合只在 discovery/dev 上选；holdout 只评一次。样本有限时报告置信不足，不伪装 formal generalization。

Test Demo 不参与有监督 threshold tuning。

## GT 只用于标签

对每个 candidate 保存：

- original start/end error；
- candidate start/end error；
- `delta_abs_error`；
- threshold transitions；
- improve / neutral / harm / catastrophic harm label。

GT 不允许进入 feature table 的线上字段。

## 优先 feature families

### F1 — Change breadth / magnitude

已有 seed：

- `n_big = count(|Δp_bad| > 0.05)`；
- changed-unit count / ratio；
- sum/mean/max `|Δp_bad|`；
- timestamp total displacement；
- max unit displacement。

### F2 — Change locality / protect-safe-context

- detector unsafe region 内的 change magnitude；
- detector safe region 内的 change magnitude；
- `inside_change / outside_change`；
- changed-safe-unit count；
- stable anchor max displacement；
- candidate 是否扩大修改到 request 外/ownership 外。

核心假设：好的 local repair 应主要改变可疑区域，而不是大面积重写安全上下文。

### F3 — Before/after model evidence

能低成本取得时保存：

- Raw detector p_bad before/after/delta；
- Official shadow before/after agreement；
- entropy / top1-top2 margin delta；
- pile-up / duplicate-time count；
- inversion/order violation；
- compression / implausible span。

不允许只用“after detector score 更好”作为 accept rule。

### F4 — Request/candidate consistency

- text identity / edit similarity，严格防 semantic drift；
- narrow vs anchor candidate timestamp agreement；
- candidate pair unit-order agreement；
- candidate span overlap/variance。

### F5 — Conditional stability probes（只对少量 ambiguous cases）

- 轻微 boundary/context 变化后是否收敛到相近 candidate；
- second realign / fixed-point：candidate A 再 realign 后是否仍近似 A。

这些 probe 成本较高，不全量运行。

## 分析方法

先简单、可解释：

1. Spearman / AUROC / AUPRC；
2. improve vs harm distribution；
3. 单变量 threshold sweep；
4. 2–3 feature 简单逻辑组合；
5. counterexample mining。

只有明显存在互补信号时，再尝试简单 logistic / shallow tree；不要直接上复杂模型。

## Gate 输出形式

目标不是强制二分类，优先：

```text
ACCEPT_WRITEBACK
UNCERTAIN_KEEP_OR_RETRY
REJECT_KEEP_ORIGINAL
```

并允许未来扩展为 per-unit / sub-region selective writeback。

## 主指标

### 安全优先

- catastrophic harmful writeback rate；
- harmful writeback rate；
- strict-correct corruption：original <=100/200ms → candidate >500ms / >1s；
- safe-context corruption。

### 收益

- accepted repair precision：允许写回的 candidate 中真实 improve 比例；
- improvement capture/recall；
- total seconds error delta on accepted candidates；
- coverage / abstain rate。

必须画/报：

> **repair coverage / capture ↔ harmful writeback risk** trade-off。

不能只报一个 accuracy。

## 预期结果与能说明的结论

### A. 单一简单信号（如 n_big/locality）在 song-held-out 上仍稳定

支持：realign 自身行为确实暴露可用于 no-GT gate 的机制信号；下一轮可进入小型 rule/calibrated gate + stateful closed-loop。

### B. 单一信号不够，但少量互补 feature 组合明显改善

支持：Realign Gate 可行，但需要 before/after multi-signal，而不是 detector score 一个标量。

### C. discovery 很好、holdout 崩溃

支持：当前样本仍不足或 song/failure-family dependence 强；不能冻结 gate，应扩大多歌/多失败族而不是细调 threshold。

### D. improve 与 harm 在所有 no-GT feature 上高度重叠

支持：当前 candidate generation 本身不够可判别；应优先改 proposal/re-align execution，而不是继续堆 gate classifier。

---

# 5. E4 — Test Demo 产品行为与自动化利用

## 原因

用户明确希望继续利用 Test Demo，而且尽量少人工。

## 目的

让 Test Demo 成为长期产品 stress set，而不是“跑完放着”。

## 设计

对全部自动发现 Demo 生成：

```text
TEST_DEMO_DETECTOR_SUMMARY.csv/json
TEST_DEMO_SUSPICIOUS_WINDOWS.csv/json
TEST_DEMO_REALIGN_BEHAVIOR.csv/json
```

自动排名至少包括：

- longest reject/uncertain streak；
- highest detector risk；
- largest realign displacement；
- largest safe-context change；
- lowest candidate consensus；
- raw/official conflict；
- structural anomaly。

只对 top-N 有代表性 case 生成图片/视频/音频检查入口，避免全量人工 review。

## 结果能说明什么

- 能检查 M4 上的 gate/detector 是否在真实多语 Demo 中出现明显失真；
- 能发现无 GT 产品失败模式；
- 不能给出 formal correctness/repair accuracy。

---

# 6. 实现与执行要求

## 6.1 不做笛卡尔积

- detector：固定 Raw 主线，Official shadow；
- realign：默认 2 variants/case；
- expensive stability probe 只给少数 ambiguous/counterexamples。

## 6.2 Cache / resume

- 新 `SESSION_ROOT/OUT_ROOT`；
- 旧 evidence 只读；
- same model+audio+text+request identity 必须共享 cache；
- feature/threshold/gate 分析变化不得重复 GPU inference；
- case-level failure 可 resume，不拖垮整个 run。

## 6.3 输出 provenance

每条样本至少记录：

- source song / demo identity；
- split/GT lineage；
- window/request identity；
- model/checkpoint；
- Raw detector artifact+threshold；
- original/candidate ownership；
- GT-access flag；
- cache identity；
- code commit / dirty state。

## 6.4 失败恢复

- inventory / detector audit / realign inference / feature analysis 分阶段完成；
- 任一后续阶段失败时，已完成 evidence 仍能独立分析；
- GPU 达预算后停止新增 inference，但继续 CPU/cache analysis。

---

# 7. 本轮完成定义

必须至少交付：

1. 数据 inventory，明确实际可用 source songs 与当前全部 Test Demo；
2. production-style detector audit，解释“历史 safe accept≈0.83”与“recovery subset 29/30 trigger”的差异；
3. 60–100 个左右、跨更多歌曲的 GT realign behavior dataset；
4. 明确包含 `correct + detector bad` hard negatives；
5. 100/200/500ms + before/after delta + harmful transition 指标；
6. no-GT realign feature table；
7. 至少对 `n_big`、change locality、safe-context corruption、candidate consistency 做验证；
8. song-held-out quick validation 与 counterexamples；
9. 全部 Test Demo 自动 detector 统计，并选 10–20 个高价值 case 做 realign behavior stress；
10. 最终报告区分：观察、可能解释、替代解释、待验证内容与当前结论强度。

本轮**不以“真正闭环 recovery 成功”作为完成定义**。若 gate signal 足够好，下一轮再实现实际 stateful writeback/serial continuation。
