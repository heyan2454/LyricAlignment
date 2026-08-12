# 会话记录：上一轮 Realign/Recovery Review → Detector Production Audit & Realign Gate

- 日期：2026-08-12
- 记录目标：完整保留本次 review、用户疑问、纠正、下一阶段范围收缩过程。
- 原则：用户意见与疑问尽量按原话记录；Assistant 的回复记录结论与推理要点，不把后续推断倒灌为用户原意。

---

## 1. 用户要求 review 当前工作

### 用户原话

> review当前工作目录和实验记录，陈述实验结果。

### Assistant review 过程与主要结论

Assistant 对当前工作目录包与 `realign_recovery_evidence` 进行了交叉检查，重点核对 session 文档、实现日志、`FINAL_REPORT`、自由探索 FE-01～FE-17、oracle/e5/e7/closed-loop 原始证据与 real-GT unit 结果。

Review 中得到并随后持续修正的主要判断：

1. 本轮实际从 oracle、proposal、quality/ranking 一直推进到 closed-loop 决策与自由探索；不是只完成单个 oracle 小实验。
2. 旧“real-GT recovery 上限约 14–16%”不能继续成立，因为旧结论受 synthetic-uniform GT 污染；新的 oracle evidence 表明在更正确 request 下 aligner 确实存在明显的重新对齐能力。
3. 但这不能等价为 no-GT recovery 已经成功。主要未知转向：
   - request/proposal 是否构造正确；
   - candidate 是否真的优于 original；
   - writeback 是否安全。
4. 当前 R-B natural proposal 并未带来整体改善，并且 synthetic perturbation episode 中存在 text semantic drift：proposal 可能把后续/错误歌词纳入 request，导致内部“自洽”但相对真实歌词位置严重错误。
5. Raw detector 在本轮 recovery natural 30-window 子集上表现为高 recall 但严重 over-trigger；这个子集明显不是普通生产窗口随机样本，不能直接拿来替代此前 detector 的 production-style safe-accept 结论。
6. `score_delta` 有一定方向性信息，但 `score_delta > 0` 不能作为安全 writeback 规则；自由探索中 `n_big = count(|Δp_bad| > 0.05)` 对真实 harm/improvement 显示出较强相关性，值得继续验证，但尚不能冻结为生产规则。
7. E8 的 `net_improved` 是离散状态转移计数，不是秒级误差收益，因此不能解释为“+65 秒净改善”或等价的整体 recovery 收益。
8. E9 当前实现是 shadow policy simulation，`actual_writeback=0`；没有执行真正 stateful 的：proposal → 写回 timeline/state → 更新 cursor → 后续窗口继续推理。因此不能把 C3 的计数解释成实际 closed-loop 成功次数或“0 harmful writeback”。
9. E4 的 propagation episode 主要是 synthetic construction，不是实际让前窗错误写入状态后观察后窗 forward 的真实传播实验。
10. 当前证据更适合支持“realign repairability 与失败机制定位”，而不是“closed-loop recovery 已完成”。

---

## 2. 用户质疑 residual error、detector 与 realign harm

### 用户原话

> 1. 对齐结果<=5s感觉已经是很不可用了，<=1s也会有比较明显的感知。还是说residual error是别的意思？
> 2. 目前看来detector还是不太够用？而且这样看我们还需要考虑realign在原本正确的内容上会不会产生错误，特别是在detector认为不好的正确上。
> 3. 能否通过研究realign的不同表现，和detector类似地得到一个realign的gate？

### Assistant 核实与回应

#### 2.1 residual error 的真实含义

核实后确认：这里的 residual error 不是风险分数，而是真实时间误差；对 unit 使用预测 start/end 与 GT 的绝对边界误差（当前相关 evaluator 语义等价于取边界误差中的较大者用于 threshold 判断）。

因此：

- `<=5s` 绝不能解释为“修好”，只表示没有残留超过 5 秒的灾难错位；
- `<=1s` 对字符级歌词对齐仍明显不可用，只能作为 catastrophic recovery 的粗阈值；
- 真正产品/科研上需要重新回到 100/200/500 ms 等口径。

进一步发现：上一轮实验计划明明要求 start/end 100/200/500 ms，但当前 oracle evaluator 虽然暴露 `thresholds_ms=(100,200,500)` 参数，实际汇总没有使用这些阈值，只输出了 1/2/5/10s 级别。因此已有 evidence 应优先离线补算，不应继续把 `<=1s` 当 repair success。

#### 2.2 detector 当前角色需要降级

Assistant 同意用户判断：当前 detector 更适合定义为高召回的 **realign proposal trigger**，不能直接解释为“该处一定错误”，更不能直接授权 writeback。

下一轮必须新增关键 hard-negative cohort：

> **GT 实际正确，但 detector 判 UNCERTAIN/REJECT 的区域。**

这直接回答用户提出的产品风险：

> detector false positive → 触发 realign → 原本正确的内容会不会被改坏？

并应区分：

- 普通正确且 detector safe；
- 正确但 detector 认为危险；
- 错误且 detector 正确触发；
- 错误但 detector 漏检。

尤其要统计从原本 `<=100/200ms` 被 realign 打到 `>500ms`、`>1s` 的 harmful transition。

#### 2.3 Realign Gate 方向

用户提出“像 detector 一样研究 realign 的表现，得到 realign gate”。Assistant 认为这是合理且应成为下一阶段主线的问题拆分：

- **Detector**：当前 alignment 看起来是否值得尝试修？
- **Realign**：产生一个 candidate。
- **Realign Gate**：candidate 是否值得替换 original？

Realign Gate 不应只看 after detector score；更应研究 before/after differential behavior，例如：

- `n_big` / changed-unit ratio；
- detector-safe context 被移动的数量与幅度；
- 改动是否集中在原 unsafe region；
- timestamp displacement / pile-up / inversion / compression；
- raw/official/detector/entropy/margin 的 before→after delta；
- 轻微 request 变化后的 candidate consensus；
- 必要时对少量 ambiguous case 做 second realign / fixed-point stability；
- text identity / semantic consistency。

强调：GT 只用于离线标注 improve/neutral/harm；线上 gate feature 不得使用 GT。

---

## 3. 用户要求重新核实 detector 的生产表现、扩大数据但限制本轮规模

### 用户原话

> 我也希望再看看detector在生产中的表现，本来safe ac是挺高的，有80还是60来着，应该不会像现在这样几乎全报了。这一轮实验规模不要太大。除了再核实一下detector，就是看realign行为，最好能直接在机器上分析一下有没有好用的信号。另外我看数据的规模好像还是不是很大，5+5？按理来说已有的数据集可以支持明显更大的数据。还有test demo我也想用。

### Assistant 核实与回应

#### 3.1 用户记忆中的 safe accept 基本正确

上一 session 的纠正记录中，`light_merge` 修复后的 retrospective A evaluation：

- Raw protected recall ≈ **0.9567**；
- Raw safe accept ≈ **0.8320**；
- Official protected recall ≈ **0.9628**；
- Official safe accept ≈ **0.7303**。

这些是 retrospective-after-fix，不是新的 untouched formal generalization；但足以说明“detector 正常生产分布中应该并非几乎所有窗口都报警”的疑问合理。

上一轮 recovery natural 30 windows 中 29/30 被触发，必须先检查样本选择偏差：这些窗口来自困难/real-GT cohort 或 recovery 流程筛选，不能直接代表 production window distribution。

#### 3.2 下一轮规模应“detector 广、realign 窄”

用户明确要求本轮不要太大，同时认为 5+5 song coverage 太小。Assistant 提议：

- Detector audit 由于可复用已有 alignment/cache，尽量扩大到当前机器上合法可用的 M4Singer production-style windows，并自动扫描当前全部 Test Demo；
- Realign GPU inference 不全量跑，只从更广 song inventory 中按类别分层抽取约 60–100 个有 GT region/window；
- 不再固定 5+5 song；先在机器上 inventory 实际可用数据，再按 song 分层采样；
- Test Demo 不硬编码历史歌曲数量，动态发现当前存在的中文/英文/日文/粤语等 demo；
- Test Demo 无 GT，只用于产品行为、稳定性、异常排序和必要的人类听看，不包装成正确率。

#### 3.3 Realign behavior 应直接在机器上探索信号

用户希望“最好能直接在机器上分析一下有没有好用的信号”。Assistant 同意不应先预设一个复杂 classifier 再跑大实验，而应保存统一 feature table，直接做：

- feature 与真实 improvement/harm 的相关性；
- AUROC / PR；
- 单变量 threshold sweep；
- 少量简单 feature 组合；
- counterexample mining；
- song-held-out 小 holdout，避免把 exploratory threshold 当正式结论。

优先检查已有 seed signal `n_big`，但必须在扩大后的独立 song 上验证，不能因为 30-window exploratory Spearman 很高就直接冻结。

---

## 4. 用户最终要求生成 patch

### 用户原话

> 可以，给我一个相对于当前实验目录的patch包，包括会话记录与实验结论、下一轮实验设计。会话记录需要记录完整会话过程，我的意见和疑问需要忠实记录。实验需要记录好实验原因、设计、目的、预期结果与结果能说明的结论。实验设计使用工作目录中一个新的session文件夹。  我将把patch包交给codex完成合并，然后要求codex给出具体实现方案交给opencode实现。

### 最终决定

新增独立 session：

`docs/sessions/20260812_detector_production_realign_gate/`

本 patch **只提供研究记录、经审计的结果结论和下一轮实验设计/交接约束**；不在本 patch 中抢先实现实验代码。Codex 合并后，应基于当前真实仓库状态给出具体实现方案，再交给 OpenCode 实现。
