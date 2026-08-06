# Full-slot 串行 Detector 与恢复：下一阶段实验计划

- 日期：2026-08-06
- 状态：冻结设计，待实现与执行
- 上游：`docs/research_v7_align_behavior/` 及 `EVIDENCE_PACK_20260806_research_v7_detector_v2.tar`
- 会话依据：`docs/sessions/20260806_fullslot_serial_detector_discussion_record.md`
- 默认运行预算：正式 GPU 推理目标 10 小时，硬上限 12 小时；若实际预算另有书面覆盖，以新合同为准

---

## 1. 研究背景与当前问题

Detector V2 已经说明 raw posterior 中存在与 GT 派生时间错误明显相关的无 GT 信号，也已经形成 unit 级风险分数和 `ACCEPT / REJECT / UNCERTAIN` 三态输出。但是，当前证据还没有完整回答生产型串行问题：

1. 歌曲与歌词完全正确对应时，前一窗口的一次局部失误是否会让模型在重复副歌或相似文本中看串，跳到错误 occurrence，并形成累计坍塌；
2. full slot 在 hard serial、stable-window、整窗回退和局部危险区重对齐中分别如何工作；
3. Detector 的 unit/子区间输出怎样转化为唯一、合法、连续的 route，而不是 `window_decision` 与 `simulate_route` 各自解释；
4. raw 与 hidden，尤其是它们的 sequence-derived 特征，能否识别 stable-but-wrong、occurrence 跳错和累计传播；
5. 在安全提交和明确拒绝之间，SA60、SA80、R95、R99 能达到怎样的真实折中；
6. 无 GT 的 test demo 能否被自动转化为长期客观回归数据，而不是只生成结果等待人工观看。

本阶段不再执行旧 detector。旧结果只作为历史背景，不占用训练、推理或对比预算。

---

## 2. 研究问题、实验目的与可声明结论

### Q1：正确歌词条件下，串行错误怎样产生和传播？

**问题**：产品假设是歌词与歌曲正确对应。真正危险的不是人为给错整份歌词，而是窗口 `t-1` 的未提交 prefix、provisional tail 或 occurrence 判断发生局部错误，随后系统按实际输出生成窗口 `t` 的 cursor/prefix，使错误自然累计。

**目的**：建立具有清晰因果链的串行错误样本，区分当前窗口错误、carried-state 错误、occurrence 跳错、持续传播和自主恢复。

**可说明的结论**：

- 若 mutation 改变了 `t-1` 的 carried state，并在后续窗口持续，可说明该状态变量会造成真实串行传播；
- 若 mutation 常被模型吸收且不改变 carried state，只能说明模型对该扰动具有局部鲁棒性；
- 若重复段附近显著更容易跳错，可说明 occurrence ambiguity 是串行系统的关键困难机制；
- 若错误在没有 GT reset 的情况下重新与 clean trajectory 汇合，才可称为自主恢复。

### Q2：Stable-window 是否优于 hard serial？

**目的**：检验左/右上下文、provisional tail 和静音吸附能否减少边缘错误永久提交，同时避免过度停滞。

**可说明的结论**：

- 若 B2 相对 B1 降低 duplicate/missing commit、传播长度和严重坍塌，同时成本可控，可说明 stable-window 本身有效；
- 若只减少提交而没有改善已提交内容的错误率，需要说明它只是更保守；
- 若收益仅来自窗口计划差异，需要通过共享窗口计划的消融分离。

### Q3：整窗回退 W 与局部重对齐 L 哪种 route 更合理？

**目的**：在完全相同的模型、decoder、窗口计划、detector 和阈值下，只比较 detector 输出到执行动作的策略。

**可说明的结论**：

- W 若显著减少错误传播但重推理和正确内容阻塞很高，说明它适合作为保守安全基线；
- L 若在不越过 unresolved gap 提交的前提下保持更高正确提交率、相近保护率和更低成本，说明子区间 route 有实际价值；
- L 若依赖错误右 anchor 或产生边界不连续，则不能因提交率高就认定更好。

### Q4：Hidden 是否提供 raw 之外的增量信息？

**目的**：完成 hidden token/row/unit 映射和数值等价审计，比较 unit-level 与 sequence-level hidden 特征。

**可说明的结论**：

- 只有在 source-song heldout、family-separated 和跨域口径中稳定提升，才能声称 hidden 有增量价值；
- 特别关注 `raw 低风险 / hidden 高风险 / GT 实际错误`，它能支持 hidden 发现 raw 的盲区；
- hidden hook 若改变 logits 或 decoder 输出，整个 hidden 实验无效。

### Q5：可用工作点在哪里？

**目的**：分别回答“至少接受 60%/80% 的 safe 时漏放多少 unsafe”和“至少明确拒绝 95%/99% 的 unsafe 时还可接受多少 safe”。

**可说明的结论**：

- 联合 SA60+R95 若可行，可形成统一三态工作点；
- 联合不可行时，实验不能停止，必须分别完成 SA60-primary 与 R95-primary；
- 只有串行闭环中的错误提交、传播、恢复和成本才决定工作点是否实用，离线 AUROC 只作辅助。

### Q6：Test demo 能否自动形成客观长期证据？

**目的**：自动发现并处理全部 test demo，计算结构、跨窗一致性、串行轨迹、重复段、route 差异和成本指标，自动进入回归门和困难 case 挖掘。

**可说明的结论**：

- 无 GT demo 不能声称 MAE 或真实 accuracy；
- clean-relative mutation、跨窗重复观察、结构合法性和路线配对差异可以形成客观代理证据；
- 代理指标必须以少量人工抽查验证，不能完全替代 GT 数据。

---

## 3. 执行前 P0 修复与审计

以下问题未修复前，不得开始 formal：

1. **标签覆盖闭合**：解释 1440 requests、1429 labeled requests 和 51 conversion errors 的关系，输出逐 request 审计；
2. **Family-LOO 与报告复核**：修复 protected/reject/interval/safe-accept 串列，统一 model、feature、threshold provenance；
3. **Stress evaluator 模型一致性**：GT 与 no-GT cohort 必须使用同一冻结模型、scaler、combo 和阈值；
4. **Serial propagation**：按 unit 跟踪部分提交窗口的未提交 unsafe，禁止仅在整窗零提交时记录；
5. **跨 request 后处理**：threshold、light merge、interval merge 必须逐 request 执行；
6. **真实 extra request**：只有真正重新调用模型并产生新 evidence 才计入 forward/request；
7. **Route 唯一解释**：`window_decision` 不再返回一套语义、`simulate_route` 再自行提交；
8. **文档自动生成**：关键 Markdown 数字必须由 authoritative JSON 生成并做一致性测试。

必须生成：

```text
LABEL_COVERAGE_AUDIT.jsonl
LABEL_COVERAGE_SUMMARY.json
P0_FIX_AUDIT.json
METRIC_SCHEMA.json
PROVENANCE.json
```

---

## 4. 冻结 Base Alignment Protocol

### 4.1 模型与运行环境

使用当前项目冻结的 Qwen forced aligner checkpoint，不重新训练。正式运行记录：

- checkpoint 路径和内容 hash；
- processor/config hash；
- dtype、device、CUDA/Torch/Transformers 版本；
- timestamp class 定义；
- generation 参数；
- vocal/mix 输入身份；
- unitizer 版本；
- random seed；
- hidden hook 层和 schema。

Hidden hook 必须通过等价 gate：相同输入下 hook on/off 的 logits、posterior、raw/official decoded rows 和 serial cursor 完全一致，或只存在预先冻结的数值容忍度内浮点差异。

### 4.2 Full slot

主实验只使用 full slot：

- 当前请求拥有连续完整 canonical slots；
- cursor 指向第一个尚未永久提交的 canonical unit；
- provisional units 仍属于未提交区域，下一窗口必须重新观察；
- 同时保存 `canonical_slot_id`、`occurrence_id` 和 decoded timestamp；
- 时间看起来合理但 occurrence 选错，仍判为严重错误。

Sparse/overlap 不进入正式矩阵，只保留为后续局部诊断工具。

### 4.3 窗口与上下文

每个 nominal core 使用：

```text
左侧音频上下文 10s + core 60s + 右侧 lookahead 10s
```

即通常最多观察约 80 秒音频。规则：

- 左侧 10 秒只提供前文声学上下文，不能覆盖已永久提交结果；
- core 是当前主要所有权区域；
- 右侧 10 秒只作为 lookahead/provisional，不直接跨越当前稳定边界永久提交；
- 所有实际 window/core/input 边界写入 manifest，禁止只记录 nominal 60 秒。

### 4.4 静音吸附

静音吸附是 Base 的组成，不作为 detector 实验的额外维度：

- `silence_aware_window_plan = true`；
- 在 nominal boundary 附近有限范围寻找静音/低活动边界；
- 不使用 strict-silence boundary；
- 不压缩静音音频；
- 跳过纯静音窗口；
- 前置长静音、短尾窗和 minimum core 使用冻结参数；
- 不允许吸附跨过明显歌词活动区或制造过短 core；
- 英文不能切断单词，日文不能切断 processor 最小对齐 unit。

### 4.5 Decoder

本阶段先保留：

- `raw`；
- `official`。

主串行路线默认使用 frozen official decoder，raw 作为 posterior evidence 和配对对照。Decoder 实验固定在同一 Base、同一数据、同一 route 上单独消融，不能与所有 route/阈值/family 全交叉。

后续若提出新 decoder，必须先通过独立 qualification，且：

```text
decoder-only p90 wall time <= official decoder 的 150%
```

同时记录总请求耗时。全序列 Top-K DP 暂不进入主线；如 pilot，只能使用局部、小 K、硬节点预算和超预算回退。

---

## 5. 历史对照：B4-60-silence-official-shadow-v1

必须补充一个历史对照，完整定义见 `02_B4_60_SILENCE_OFFICIAL_SHADOW_V1.md` 和 YAML profile。

核心语义：

- core 60 秒，左右各 10 秒；
- official decoder 同时控制 serial；
- 普通 silence snap；
- 不 strict、不压缩；
- 跳过静音窗口；
- local realign 只运行 shadow；
- `actual_writeback = 0`；
- shadow 不能改变 baseline rows、cursor、prefix、window trajectory；
- baseline 与 shadow 成本分开统计。

该路线在 M4、MIR 和全部 test demo 上作为历史参照，但不得与新 Base 的所有维度形成笛卡尔积。

---

## 6. 串行路线

### B0：Oracle-start independent

每窗使用正确 canonical start，只用于单窗上限。它不能证明系统有实际恢复能力。

### B1：Hard serial

- 上一窗实际提交决定下一 cursor/prefix/occurrence；
- core 内结果直接提交；
- 无 provisional、无 detector、无回退；
- 用于观察最直接的累计错误。

### B2：Stable-window serial

- 共享 Base 窗口计划；
- 仅永久提交可确认的连续稳定前缀；
- 右侧边缘和 lookahead 保留 provisional；
- 下一窗重新观察 provisional；
- 不使用 detector 触发额外动作；
- 不允许 GT reset。

### W：整窗否决与向前重对齐

Detector 生成 unit 三态后，由 W policy 生成唯一计划：

- 可提交区域有 REJECT：整窗零提交，回到最近稳定边界重跑；
- 无 reject 但有 uncertain：整窗暂缓，扩大观察或下一窗重试；
- 全 accept：提交允许的稳定区域。

硬断言：W 判 REJECT 时 `committed_count == 0`。

### L：可信前缀保留与危险子区间局部重对齐

- 从当前 cursor 开始的连续 ACCEPT 前缀可提交；
- REJECT/UNCERTAIN 形成 unresolved gap；
- gap 后方 ACCEPT 只能作为 provisional/right-anchor candidate，不能越过 gap 推进主 cursor；
- 局部请求由左 committed anchor、右可信 provisional anchor、有限音频上下文和中间完整 full slots 定义；
- 限制重试次数和额外 forward；
- 不使用 GT prefix/cursor。

硬断言：任何 committed canonical IDs 必须连续，且 cursor 等于第一个未提交 canonical unit。

### 唯一 route 接口

实现应类似：

```python
plan = route_policy.build_plan(detector_output, serial_state, window)
new_state = apply_route_plan(plan, serial_state)
```

`apply_route_plan` 只执行，不重新判定。

---

## 7. Detector 工作点

### 7.1 三态定义

```text
p_bad <= T_accept  -> ACCEPT
p_bad >= T_reject  -> REJECT
otherwise          -> UNCERTAIN
```

且要求 `T_accept < T_reject`。

### 7.2 必做工作点

#### SA60-primary

硬约束 `safe_accept_rate >= 60%`。在满足约束的阈值中：

1. 最小化 unsafe accept；
2. 最大化 unsafe reject；
3. 最小化 safe reject；
4. 控制 uncertain 与预期额外推理成本。

#### R95-primary

硬约束 `unsafe_reject_recall >= 95%`。在满足约束的阈值中：

1. 最大化 safe accept；
2. 最小化 safe reject；
3. 控制 uncertain。

#### SA60-R95-joint

尝试同时满足 SA60 与 R95。若存在合法双阈值，完整执行；若不存在，记录 Pareto 边界，但**不得停止实验**，必须继续分别完成 SA60-primary 和 R95-primary。

### 7.3 第二层工作点

主线跑通后再增加：

- SA80-primary；
- R99-primary；
- 可行时的 SA80-R95、SA60-R99 等联合点。

不预先全排列。

### 7.4 闭环使用

- R95-primary 重点用于 W/L 的明确 reject 与回退；
- SA60-primary 重点用于提交覆盖、unsafe 漏放与累计误差；
- 联合点存在时，作为统一三态路线；
- 首轮主比较优先 B1、B2、W-R95、L-R95、L-SA60；联合点存在时补 W/L-joint。

必须报告 safe/unsafe × accept/reject/uncertain 六格完整计数与比例。

---

## 8. 错误构造：正确歌曲与正确歌词条件下的累计串行误差

### 8.1 产品假设

主实验中音频与歌词必须正确、完整对应。只修改音频或只修改歌词造成不匹配的 repeated/no-match 方案暂缓为鲁棒性实验。

### 8.2 自然重复段

Agent 自动分析：

- 完全重复副歌；
- 只改少数字的副歌；
- 连续两遍副歌；
- bridge 后再次出现副歌；
- 主歌尾句与副歌开头相似；
- 重复段靠近静音、间奏、伴唱或窗口边界；
- 不同演唱速度、伴奏密度下的相同歌词。

每个 case 记录选择理由、正确 occurrence、易混淆 occurrence、窗口边界和预期错误。

### 8.3 机械重复构造

音频、歌词、canonical labels 必须同步修改，例如：

```text
ABCD -> ABCABD
```

同时复制对应音频 AB、歌词 AB 和独立 occurrence IDs。使用必要但很短的 seam 处理，避免拼接噪声成为 detector 捷径；保存完整 provenance 和时间平移。

### 8.4 Prefix/provisional mutation 的正确因果链

Mutation 必须发生于窗口 `t-1` 的实际推理输入：

```text
t-1 未提交 prefix/provisional 被扰动
-> t-1 实际 forward + decoder
-> route 生成真实错误 committed/provisional/cursor
-> t 使用该 carried state
-> 后续连续运行，不恢复 GT
```

优先 mutation：

- 随机替换未提交 prefix 1/2/4/8 units；
- 替换 prefix 的 5%/10%/20%；
- 相邻句替换；
- 另一遍副歌的近似 prefix；
- 低编辑距离、同音或相似词替换；
- 删除、重复、交换 provisional tail；
- 修改 occurrence identity；
- cursor 附近局部替换。

只修改遥远已提交文字但保持正确 cursor 的方案仅作为上下文敏感性对照。

### 8.5 必须收集足量累计错误，不能因 no-effect 停止

所有 mutation 尝试都保存，以计算诱发率；同时为有效累计错误设置硬配额。

默认配额：

- 每个主要 GT mutation family 至少 64 个有效累计错误 episode；
- 至少覆盖 8 个 source songs；
- 单一 source song 不超过该 family 有效 episode 的 25%；
- 自然重复 occurrence 至少 32 个有效 episode；不足时由正确对应的机械构造补至 64；
- test demo 每种已发现语言至少收集 24 个 clean-relative 有效轨迹偏离 episode，若候选数量允许。

“有效累计错误”至少满足一项：

- carried cursor 发生错误变化；
- occurrence identity 错误；
- 下一窗口仍存在错误；
- 错误持续至少 3 units；
- 传播到至少一个后续窗口；
- duplicate/missing commit；
- 严重时间坍塌。

若配额不足，Agent 必须自动扩大 candidate pool、优先重复/相似区、提高强度或换 mutation 类型，直到达到配额或硬运行预算。达到预算仍不足时，必须报告尝试数、诱发率和不足原因，但不能把“没有产生错误”当作实验已经完成。

---

## 9. Raw、Hidden 与 sequence-derived 特征

### 9.1 Raw

保留 unit-level：

- start/end entropy；
- top1-top2 margin；
- top-k 时间与概率；
- posterior 边缘质量；
- raw start/end/duration；
- 双峰距离；
- decoder 修正前后的时间位移。

Raw sequence：

- 相邻 entropy/margin 差分；
- 局部 3/5/9-unit 均值、方差与变化点；
- 连续高风险 run；
- 时间推进一阶/二阶变化；
- 局部压缩率、零时长 cluster；
- 重复 occurrence 之间 posterior 峰结构相似性。

### 9.2 Hidden 提取审计

先完成：

- generated token -> output row；
- output row -> canonical unit；
- start/end timestamp token index；
- 选择的层；
- hook on/off 数值等价；
- shape、dtype、hash、cache identity。

### 9.3 Hidden unit 与 sequence

Unit：norm、start/end cosine、跨层变化、linear probe 风险等。

Sequence：

- 相邻 cosine；
- 一阶/二阶差分；
- 3/5/9-unit 局部方差；
- hidden change-point；
- 连续异常 run；
- start/end 与相邻 unit 连续性；
- 重复 occurrence hidden trajectory 相似性；
- mutation 前后 hidden shift；
- raw entropy 与 hidden 突变的交叉模式。

主消融：

```text
R-unit
R-unit + R-sequence
H-unit
H-unit + H-sequence
R + H
R + H + sequence
```

Official 不作为 detector 独立特征家族。

---

## 10. 数据集与切分

### 10.1 M4Singer

- 按 `source_song_id` 分组；
- development 内拆 train/calibration/threshold-validation；
- formal M4 test 只在模型、特征、阈值、route 冻结后运行；
- test song 的构造样本仍属于 test，不能回流训练；
- 报 pooled unit、per-song macro、source-song cluster bootstrap CI 和 worst-song。

### 10.2 MIR-1K

- 使用 M4 训练的模型、scaler、feature schema 和阈值；
- 不在 MIR test 上重新校准或调阈值；
- weak GT 与 M4 precise GT 分开报告，禁止 pooled；
- 重点报告跨域 SA/R achieved、unsafe accept、传播和 route 成本。

### 10.3 正确对应的构造数据

- 继承 source split；
- 保存 source audio/text/label hashes；
- 保留未见 mutation 类型、强度和重复结构作为 mechanism-heldout；
- 训练、阈值与正式 test 的构造模板不能泄漏。

### 10.4 Test demo：全量自动利用

Test demo 是无 GT 自动行为与回归数据集，不是主要依赖人工听看的展示集合。

自动流程：

```text
扫描 test 根目录
-> 匹配音频/视频/歌词/vocal
-> 推断语言并调用统一 unitizer
-> 更新 active manifest、内容哈希去重
-> 生成 silence-aware full-slot windows
-> 运行 B4、B2、W、L 与指定 decoder 对照
-> collection
-> 客观分析与回归门
-> 自动困难 case 挖掘
-> 仅少量抽查/可视化
```

新增歌曲自动纳入，不固定中文 17、其他语言各 6。

自动统计：

1. 结构合法性：缺失、重复、乱序、负/零/极短时长、重叠、时间越界、局部挤压；
2. 跨窗一致性：同一 provisional unit 在相邻窗口的时间差、occurrence、posterior、hidden 与 stable-prefix reproduction；
3. 串行轨迹：cursor 单调性、零/过量推进、provisional 长度、rollback、unresolved gap、恢复时间；
4. 路线配对：B4/B2/W/L 的 commit、cursor、结构异常和耗时差异；
5. 重复段：自动 n-gram/近似句检测、occurrence 稳定性、远距离双峰、重复段附近触发率；
6. clean-relative mutation：轨迹偏离、与 clean route 重新汇合所需窗口、W/L 的相对恢复；
7. 计算成本：forward、音频秒数、decoder/detector/hidden 开销、p50/p90/p99、峰值显存。

统计结果必须进入：

- 自动回归门；
- 自动困难 case 排名；
- 下一轮 mutation/hidden/decoder 候选采样；
- 分语言、时长、歌词密度、重复密度、静音比例分层报告。

人工只审计自动排名异常、路线改善/恶化样本和每语言少量随机对照。无 GT demo 不报告 MAE 或真实 accuracy。

---

## 11. 正式实验矩阵：避免笛卡尔积

### 第一层主比较

| Route | Serial | Detector/threshold | Purpose |
|---|---|---|---|
| B0 | oracle independent | none | 单窗上限 |
| B1 | hard serial | none | 累计错误基线 |
| B2 | stable-window | none | stable 制度收益 |
| W-R95 | stable-window | R95-primary | 整窗回退保护与成本 |
| L-R95 | stable-window | R95-primary | 局部重对齐保护与成本 |
| L-SA60 | stable-window | SA60-primary | 高提交覆盖下的漏放与传播 |
| B4-shadow | historical B4 | no writeback | 历史对照与 shadow 证据 |

若联合点存在，再增加 W-joint 与 L-joint。SA80/R99 只在第一层完成后追加。

### Decoder 消融

固定 B2 或一条预注册 route，在同一输入与窗口计划上只比较 raw/official。不得与全部 W/L/threshold/family 交叉。

### Hidden 消融

先在固定 decoder、B2 离线 evidence 上完成；只有表现出 heldout 增益的 feature set 才进入有限 W/L 闭环。

---

## 12. 指标

### 12.1 对齐与 slot identity

- onset/offset MAE；
- invalid/coverage；
- occurrence identity accuracy；
- duplicate/missing commit；
- severe collapse event rate；
- committed unit error rate。

### 12.2 Detector

- safe/unsafe × accept/reject/uncertain 六格；
- achieved SA、unsafe reject、unsafe accept；
- interval recall@75%、interval recall@100%；
- 最大连续 unsafe accept；
- per-song/family 指标和 cluster CI；
- threshold 前后与 light-merge 前后分开报告。

### 12.3 串行与恢复

- 第一次错误提交窗口；
- downstream erroneous units/duration/windows；
- canonical cursor accuracy；
- occurrence 跳错；
- unresolved gap 长度；
- 自主恢复率；
- 恢复所需窗口、units、秒数；
- 恢复后复发；
- 相对 clean trajectory deviation。

### 12.4 效率

- baseline/shadow/rollback/local realign forward 分开计数；
- 重算音频秒数；
- decoder/detector/hidden 时间；
- 每分钟音频 wall time；
- p50/p90/p99；
- 相对 B2 增幅；
- peak VRAM/RAM。

---

## 13. 预期结果与结论边界

### 13.1 SA60 与 R95 联合可行

若同一双阈值在 validation、M4 heldout 和有限跨域中均近似保持约束，并在闭环降低累计错误，可支持统一三态 detector。不能仅凭 validation 可行声明生产可用。

### 13.2 联合不可行

必须完整报告并运行 SA60-primary 与 R95-primary：

- SA60 说明高提交覆盖下的 unsafe 漏放与传播代价；
- R95 说明高明确拒绝下的 safe 损失与推理成本；
- 两者的 Pareto gap 说明当前单标量分数的局限，但不构成停止实验的理由。

### 13.3 W 优于 L

若 W 以可接受成本显著降低错误传播，而 L 经常使用错误 anchor 或越界提交，说明整窗回退更稳妥。仍需报告 W 的 safe 阻塞，不得只报告零错误。

### 13.4 L 优于 W

若 L 保持连续 cursor、解决 gap，并以更少 forward 获得相同保护和更高正确提交率，可说明子区间 detector 与局部恢复有系统价值。

### 13.5 Stable-window 无收益

若 B2 与 B1 相当或更差，需检查收益是否被 decoder、silence snap、provisional 定义或错误窗口 ownership 抵消。不能事后编造“更保守所以更好”。

### 13.6 Hidden 无增量

若 H/H-sequence 在 heldout、family 和 stable-wrong case 中均无增益，应保留为负结果并停止大规模 hidden 存储，不继续无边界调层。

### 13.7 Test demo 代理指标与少量人工不一致

若结构/一致性指标与人工明显冲突，应降低该代理指标在回归门中的权重，并保留冲突 case；不能继续自动把它解释为质量提升。

### 13.8 Decoder 对照

若 official 相对 raw 明显减少结构错误但隐藏 stable-wrong，不得只因 MAE 更好就将 official 视为 detector 信号；若 raw 在 occurrence identity 更敏感，可作为 detector evidence 保留。

---

## 14. 运行、缓存、恢复与产物

### 14.1 阶段顺序

1. P0 修复与审计；
2. 冻结 manifests、splits、Base、B4 profile 和 provenance；
3. raw/official Base qualification；
4. clean B0/B1/B2/B4；
5. prefix/repeat mutation candidate generation 与有效累计错误配额收集；
6. detector threshold freeze；
7. W/L 闭环；
8. hidden pilot 与有限消融；
9. M4 formal；
10. MIR fixed transfer；
11. 全量 test demo 自动运行与统计；
12. 自动汇总、回归门、bounded evidence pack。

### 14.2 缓存

缓存 identity 至少包含：

```text
model hash
processor hash
audio hash
lyrics/unitizer hash
window plan hash
decoder kind
slot schema
prefix mutation identity
hidden schema
feature schema
route policy
threshold id
```

模型 forward evidence 可被不同 decoder/detector 重用；route 改变 carried state 后必须形成新 request identity，不能错误复用旧缓存。

### 14.3 写入策略

- 原始 evidence 只追加，不覆盖；
- 汇总按 run root 重建；
- resume 以完成的 request identity 为单位；
- 失败 request 保存错误和可重试状态；
- test 输出不能用于重新选择阈值；
- collection 在 visualization 前；
- evidence pack 排除音频、视频、模型权重和大日志，只保存引用、hash 和 bounded diagnostics。

### 14.4 必须产物

```text
BASE_PROTOCOL.json
B4_PROFILE_RESOLVED.json
DATASET_SPLIT_AUDIT.json
DEMO_ACTIVE_MANIFEST.jsonl
MUTATION_ATTEMPTS.jsonl
EFFECTIVE_SERIAL_ERRORS.jsonl
RAW_HIDDEN_FEATURE_SCHEMA.json
FROZEN_WORKING_POINTS.json
ROUTE_PLANS.jsonl
SERIAL_TRAJECTORIES.jsonl
M4_FORMAL_SUMMARY.json
MIR_TRANSFER_SUMMARY.json
DEMO_OBJECTIVE_SUMMARY.json
DEMO_REGRESSION_GATES.json
RUNTIME_SUMMARY.json
FINAL_CONCLUSION.json
```

---

## 15. 完成定义

只有满足以下条件才算完成：

- P0 审计闭合；
- B4 shadow 确认零 writeback 且 trajectory hash 不变；
- B1/B2/W/L 的 route 与 simulator 一致；
- SA60-primary 和 R95-primary 均完整运行，不因联合不可行而缺失；
- 每个主要 mutation family 达到有效累计错误配额，或在硬预算下完整报告不足和尝试分母；
- M4、MIR、构造数据和 test demo 分开汇报；
- 全部 test demo 自动纳入客观统计与回归门；
- hidden 若启用，hook 等价和 token/unit mapping 审计通过；
- decoder 消融独立，不发生笛卡尔积；
- 所有结论区分假设、设置、观察、解释、替代解释、待验证内容和结论强度。
