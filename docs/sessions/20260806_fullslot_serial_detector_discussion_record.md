# 2026-08-06 Full-slot 串行 Detector、错误恢复与 Test Demo 自动化讨论记录

## 1. 会话任务与输入

用户要求 review 当前工作目录、分析实验数据并给出详细结论。输入为：

- `LyricAlignment_202608060412_alignandslot2.zip`；
- `EVIDENCE_PACK_20260806_research_v7_detector_v2.tar`。

本轮随后从结果复审逐步转入下一阶段设计，用户要求最终生成独立 patch 包，分别包含：

1. 完整忠实的会话纪录，保留用户反馈、纠正和讨论过程；
2. 实验计划，明确问题、实验目的、设计、预期结果及结果能说明的结论。

用户最后补充：新计划应独立拆开，不继续接在 v7 编号后，以免文档过长；可以在新文档中指向 v7 作为上游证据。

---

## 2. 初始工作目录与实验结果复审

审查首先确认：收到的是代码快照和压缩证据包，而不是完整运行目录与全部原始 evidence。能够核查代码、汇总 JSON、标签和评价逻辑，但不能从完整逐 unit 输出独立重算所有指标。

初始复审形成的主要判断包括：

### 2.1 可复核范围

- 证据包可支持代码、schema、汇总 JSON 和内部一致性审查，但缺少完整 raw evidence、checkpoint、逐 unit 输出和人工复核，不能独立重算全部指标；
- Detector V2 聚焦测试共 167 项通过；完整 research-v7 测试在审查环境运行到约 49% 时因外部命令时限中止，未见测试失败，但不能据此独立确认全套通过；
- ZIP 无 `.git`，不能确认真实 commit 和 dirty state；README/AI entry 引用的 v7 18–22 号文档在该 ZIP 中不完整。

### 2.2 标签与信号

- M4 标签汇总约有 252,202 个有效标签 unit，其中 safe 199,706、unsafe 19,032、grey 23,108、ambiguous 10,356，另有 22,768 个 GT unavailable 输出；
- safe+unsafe 二分类子集约 218,738 units，unsafe 比例约 8.70%；报告中的 7.55% 使用了不同分母，后续必须明确口径；
- `n_requests_labeled=1429`、signal atlas requests=1440、conversion error=51 之间未闭合，需要逐 request 审计；
- raw end entropy 是最强单信号：raw target AUROC 约 0.954，official target 约 0.936；raw start entropy 也约 0.905/0.912；
- margin 的 AUC 方向相反主要因为 safe margin 更大，不能据此误判 margin 无效；
- 这些是 pooled unit AUC，不等于 accuracy，也可能受同歌/同请求相关性和 GT 时间标签定义影响。

### 2.3 冻结工作点与 heldout

- 当前 small MLP 的冻结点保护率很高，但所有最终点都违反预定 safe-accept 下限；validation safe accept 仅约 3%–5%；
- M4 song-heldout 中 raw unsafe protection 约 99.63%、safe accept 约 12.52%、safe reject 约 57.00%；official unsafe protection 约 99.81%、safe accept 约 8.06%、safe reject 约 77.50%；
- 因此当前成果更接近高置信 whitelist/safe commit gate，而不是覆盖整个窗口的实用 detector；
- M4→MIR 固定迁移中 raw protected recall 约 99.43%、safe accept 约 20.85%；official protected recall 约 99.62%、safe accept 约 13.51%，没有旧 assessor 那种完全跨域崩溃，但标签轴不同，不能直接混合解释；
- 95% 和 99% 在当前冻结代码中没有真正形成两套独立 operating points，而是复用了同一 achieved 值。

### 2.4 报告与 evaluator 缺陷

- Family-LOO master conclusion 把 official `crop_late/end_late` 写成约 0.832/0.485，但 authoritative JSON 中 protected recall 实际约为 1.0；属于指标串列或旧数字残留；
- 顶层 provenance 曾写 Logistic，而 target 内部实际使用 small MLP；
- no-GT stress cohort 被硬编码使用 Logistic，导致 replace/missing/extra/repeated 的 state distribution 与冻结 small MLP 无关；
- serial propagation 只在整窗零提交时记录未提交 unsafe，部分提交窗口会漏记传播，因此 `propagated=0` 无效；
- 所谓 30 次 extra requests 只是重复使用同一窗口已有 raw evidence 评分，不是真正模型 forward；
- `delayed_commit` 也没有真正统计 unit 延迟或等待时间。

### 2.5 其他实验解释

- 旧 Full Replace 的“完全检出”来自 canonical original unit 缺失即标 unsafe，不是 detector 在无 GT 下发现换词；用户此前认为该结论荒诞，这一判断得到确认；
- 正确 prefix 恢复后 tail 回到 baseline，只能说明模型没有不可清除的跨调用内部状态，属于 oracle-prefix recoverability；
- full/sparse matched-view 主要比较 GT-derived 标签一致性，不是 detector 三态一致性；
- slot 与串行不是互斥概念：slot 是单次请求查询哪些 canonical units，串行是请求间如何传递 cursor/prefix/commit。

### 2.6 Hidden 与输出粒度

- hidden 全部 blocked 并不表示 hidden 无效，而是实际提取、generated-token/output-row/canonical-unit 映射、层选择和 hook 数值等价审计尚未完成；
- 当前 detector 本身已经是 unit/子区间级三态输出；真正的问题是 serial route 没有一致、连续地使用这些输出。

---

## 3. 用户对复审结论的第一轮反馈

用户逐项修正和收敛研究方向：

1. **不再执行旧 detector**。下一步没有继续涉及旧 detector 的必要；
2. 重复段和多答案可以主动构造，Agent 应智能分析副歌等结构，机械构造可模仿 `ABCD -> ABCABD`；
3. 必须验证 slot 在各种串行方式中的性能和准确率，并主动构造错误，不能全是 easy case；
4. “修正 prefix 后可以恢复”只能说明给对的 prefix 后可恢复，不能保证系统会自行产生正确 prefix；
5. 标签覆盖差异要求 Agent 复核；
6. raw 无 GT 特征与 GT 派生时间错误标签的粗粒度相关性已经比较充分，下一步应做语义细化；
7. hidden 为什么被 block 需要深入研究；
8. official 产生过程已经基本清楚且直接来自 raw，后续 detector 可以不再重点考虑 official 信号，继续 raw、hidden，并考虑简单新 decoder；
9. 95% 和 99% 工作点必须分开；还应观察固定 safe acceptance 时的 unsafe 拒绝/漏放；
10. Family-LOO 与最终报告错误要求复核；
11. sparse/overlap 不必继续作为主线，主要使用 full slot。

用户同意其余 P0 修复和补充项。

---

## 4. 对重复段、slot 串行和 hidden 的进一步修正

用户随后纠正了初始重复段设计的产品假设：

- 主假设应是给定歌词和歌曲正确对应；
- 音频重复但文本缺失、文本重复但音频缺失属于输入鲁棒性，可以暂缓；
- 核心是前面失误后看串到后面的同一副歌/相似段，随后出现严重坍塌。

用户提出在 slot 串行实验中加入 stable 分窗。讨论后区分：

- stable-window 是正常工作制度；
- S3 detector-triggered rollback 是异常路径；
- 两者相关但不完全相同。

用户要求 S3 使用约 95% unsafe reject 的 detector 工作点，统计时间和推理次数；若后续找到更好的 detector，可在同一机制上替换。

用户补充控制变量：可以随机替换前文或当前 prefix 的字，让模型产生错误判断并构造累计错误。

用户指出 hidden 也应有 hidden-derived sequence 特征，不能只使用单 unit norm/cosine。

用户要求新 decoder 的实际耗时不能太长，理论上不超过 official 的 150%；全序列 Top-K 可能有风险，应避免直接进入主线。

工作点方面，用户纠正此前对 SA10/20 的误解：用户原意是较高的 safe acceptance。最终认为 SA80 可能较难，SA60 和 SA80 更合理。

---

## 5. Prefix mutation 必须形成真实串行因果链

用户进一步指出：

> 随机替换前文或 prefix 字符时，需要修改的是未提交前文，或上一窗口推理时使用的 prefix。若只修改已经提交的历史文字而当前 cursor 仍正确，测到的更像上下文噪声，不是真正串行误差。

因此最终冻结的因果链为：

```text
窗口 t-1 的未提交 prefix/provisional 被修改
-> t-1 实际完成模型推理和 decoder
-> 正常 route 产生真实错误 committed/provisional/cursor
-> 窗口 t 使用该 carried state
-> 后续继续串行，不恢复 GT
```

只修改远处已提交文字但继续给予正确 cursor 的实验降级为辅助上下文敏感性对照。

讨论还明确：所有 mutation 尝试都应保存用于计算诱发率；但不能因为大部分 no-effect 就不做后续实验。Agent 必须通过扩大候选池、提高强度、选择重复/相似区等方式，收集到预注册数量的有效累计错误 episode。

---

## 6. Detector 输出粒度与 safe reject 的讨论

用户提出疑问：当前 detector 是否只判断整个提供区间 safe/unsafe，而不能拆成子区间；若如此，工作效率低且 safe reject 高是显然的。

核查后修正认识：Detector V2 的原始输出已经是：

- 每 canonical unit 一个风险分数；
- 每 unit 的 ACCEPT/REJECT/UNCERTAIN；
- 合并得到接受、拒绝和存疑子区间。

因此现有 safe reject 高不能简单归因于“整窗判定”。真正的问题是执行层语义不一致：

- `window_decision` 可能把局部 reject 升格为整窗 reject；
- `simulate_route` 却可能忽略整窗决策，提交所有 accept units；
- 甚至可能越过 unresolved gap 提交后方 accept，破坏连续 cursor。

讨论曾提出“最大连续安全前缀”的实现，但用户随后明确要求：

> `window_decision` 和 `simulate_route` 必须一致。不管是串行过程中直接否定整个窗口向前重对齐，还是保留可信区域、对 unsafe 单独重对齐，都可以；可以作为两种方案都试，但各自必须一致。

最终形成两个正式 route：

- W：整窗否决并向前重对齐；
- L：保留可信连续前缀，对危险子区间局部重对齐，gap 后方 accept 只能 provisional，不能直接推进 cursor。

两种 route 必须使用同一 detector 输出和阈值，由 route policy 生成唯一执行计划，simulator 只执行。

---

## 7. Base 模型行为的讨论与修正

用户询问下一阶段模型基本行为如何定义，包括 decoder 和串行工作方式。

初始建议包括：冻结模型、full slot、60 秒 core + 10 秒 lookahead、stable-window、raw/official decoder qualification、W/L route。

用户随后修正：

1. Base 中不只是后向 10 秒，还必须包含前面的 10 秒音频上下文；
2. 需要静音吸附；
3. decoder 暂时先保留 raw 和 official，decoder 实验在 Base 基础上单独消融，避免笛卡尔积；
4. 错误注入必须保证产生足够数量的累计误差，不能全是 no-effect 后停止。

最终 Base 冻结为：

```text
full slot
+ 左 10 秒声学上下文
+ core 60 秒
+ 右 10 秒 lookahead
+ silence-aware boundary snap
+ skip silent windows
+ short-tail redistribution / minimum core
+ raw/official 暂时保留
+ decoder 消融单独运行
+ stable-window 作为无 detector 共同基线
```

Official 可作为主执行时间轴和历史对照，raw 作为 posterior evidence 与配对 decoder 对照；official 不再作为 detector 的独立特征家族。

---

## 8. SA60 与 R95 能否共同使用

用户询问 SA60+R95 是否能一起使用以及如何使用。

讨论明确，二者可以作为同一个三态风险分数的两端：

```text
p_bad <= T_accept -> ACCEPT
p_bad >= T_reject -> REJECT
中间 -> UNCERTAIN
```

SA60 约束 safe acceptance，R95 约束 unsafe reject。最初回答提出若无法找到 `T_accept < T_reject` 的联合点，应报告不可行。

用户明确纠正：

> 不能因为联合不可行而停止。一定要以某种方式完成实验；若联合不可行，就分开完成 SA60 和 R95。

最终规则：

- 必做 SA60-primary；
- 必做 R95-primary；
- 尝试 SA60-R95-joint；
- 联合不存在时报告 Pareto gap，但继续分别完成两套离线和串行实验；
- 后续再扩展 SA80、R99，不做预先全排列。

R95 更适合触发明确回退；SA60 更适合评价高提交覆盖下的 unsafe 漏放与累计传播。

---

## 9. 不同数据集和 test demo 的处理讨论

数据角色最终分开：

- M4 development：detector 训练、校准、threshold validation；
- M4 test：in-domain formal，不参与调参；
- MIR-1K：固定 M4 模型/scaler/threshold 的 OOD/weak-label 评价；
- 正确对应的自然/机械重复与 prefix mutation：机制和累计错误实验，继承 source split；
- test demo：无 GT 全量自动行为与回归数据，不参与阈值选择。

用户强调 test demo 的重点不是“算完后等待人工看”，而是：

> 尽量少介入人工，多计算客观数据自动利用与统计。

因此最终要求自动：

- 扫描新增 test demo，不固定歌曲数量；
- 统一多语言 unitizer，英文不切词，日文不切 processor 最小 unit；
- 生成静音吸附 full-slot 窗口；
- 运行 B4、Base、W、L 和限定 decoder 对照；
- 统计结构合法性、跨窗 provisional 一致性、cursor 轨迹、重复段 occurrence、route 差异、clean-relative mutation 和运行成本；
- 把统计结果直接用于自动回归门、困难 case 排名和下一轮采样；
- 人工只看自动排名异常、显著改善/恶化和少量随机对照。

讨论特别强调：test demo 无 GT，不能报告 MAE 或真实 accuracy；可以报告客观结构指标和相对 clean trajectory deviation。

---

## 10. B4 历史对照

用户提出需要补充：

```text
b4-60-silence-official-shadow-v1
```

并给出 profile：

```ini
core_sec = 60
left_context_sec = 10
right_context_sec = 10

decoder_kind = official
serial_control_decoder_kind = same

silence_aware_window_plan = true
strict_silence_boundary_plan = false
compress_silence_audio = false
skip_silent_windows = true

silence_boundary_min_sec = 0.8
strong_silence_anchor_sec = 1.5
silence_boundary_search_sec = 6.0
leading_silence_min_sec = 2.0
tail_min_core_sec = 18.0
minimum_core_sec = 12.0

local_realign = shadow_only
actual_writeback = 0
```

核对当前代码后，以上字段与 `B4_60_silence_official` 的核心行为一致：60 秒 core、silence snap、official 控制 serial、跳过静音窗，以及当前静音/短尾窗默认参数。

讨论补充边界：

- 它应被称为“B4 对照 + shadow”，不是纯 B4 本体；
- shadow 不能改变 baseline alignment、cursor、prefix 或后续请求；
- 必须使用 hash/计数断言 `actual_writeback_count == 0`；
- baseline 与 shadow forward/wall time 分开；
- 还应冻结 silent-active、startup、future-character 等隐含默认值；
- YAML 只作为声明式 profile，当前 patch 不接线代码，不能声称已可直接运行。

用户接受该安排。

---

## 11. 最终冻结的研究方向

### 11.1 主线

1. Full-slot 在 B1 hard serial、B2 stable-window、W 整窗回退、L 局部危险区重对齐中的准确率、传播与成本；
2. 正确歌曲/歌词条件下，利用自然重复段、正确对应机械重复和上一窗未提交 prefix mutation 构造真实累计错误；
3. Raw、hidden 及各自 sequence-derived 特征，重点研究 occurrence 跳错和 stable-but-wrong；
4. SA60-primary 与 R95-primary 必做，联合点可行时追加；
5. M4、MIR、构造数据和 test demo 分开汇报；
6. test demo 全量自动进入客观统计、回归门和困难 case 挖掘；
7. 补 B4-60-silence-official-shadow-v1 历史对照；
8. raw/official decoder 消融独立，不做笛卡尔积。

### 11.2 移出主线

- 旧 detector；
- 不正确音频/歌词对应的重复鲁棒性主实验；
- sparse/overlap 全矩阵；
- official detector signal family；
- 全序列高成本 Top-K；
- 只靠人工听 demo 做主要结论。

### 11.3 必须先修复

- label coverage 差异；
- Family-LOO 和 master conclusion 串列；
- stress evaluator 模型不一致；
- serial 部分提交传播漏记；
- 跨 request light merge；
- 伪 extra request；
- route policy 与 simulator 不一致。

---

## 12. 讨论过程中的重要纠正记录

为避免后续误读，以下是本轮关键认知修正：

1. 初始将部分重复输入不匹配方案列入主实验，用户纠正为产品假设下音频与歌词正确对应，重点是 occurrence 看串；
2. 初始将修改已提交前文也列为主要串行注入，用户纠正为必须修改上一窗口推理中的未提交 prefix/provisional，形成 carried-state 因果链；
3. 初始误解 safe acceptance 为 SA10/20，用户纠正为 SA80/SA60；
4. 初始提出联合 SA60+R95 不可行时报告失败，用户要求无论如何分别完成两套实验；
5. 初始 Base 只强调 60 秒 core + 后 10 秒，用户补充必须有前 10 秒上下文和静音吸附；
6. 初始可能把 detector 高 safe reject 与整窗判定联系，核查后确认 detector 本身是 unit/子区间级，问题在 route 执行不一致；
7. 初始将 test demo 更多视为自动筛选后人工复核，用户进一步强调客观统计必须主动进入实验决策，人工尽量少。

---

## 13. 预期结果与结论强度

- SA60/R95 联合成功：只说明存在候选统一三态点，仍需 heldout、跨域和闭环验证；
- 联合失败：说明当前单风险轴存在 Pareto 冲突，但 SA60 和 R95 两套系统仍必须分别评价；
- Stable-window 减少错误但提交率过低：只能称为保守保护；
- W 零错误但成本极高：不能只报告安全，必须报告阻塞与推理成本；
- L 提交更多但越过 unresolved gap：实现无效，不计收益；
- hidden 无增量：应保留负结果并停止无边界调层；
- test demo 代理指标与少量人工冲突：应修正代理和回归门，不能继续自动解释为质量提升。

---

## 14. AI 协作、负结果和依赖状态

### AI 协作范围

本轮 AI 完成了：工作目录与 evidence pack 复审；代码语义核对；用户多轮反馈后的实验逻辑重构；B4 profile 与当前代码默认值核对；独立新阶段文档和 patch 组织。

### 负结果和错误认识

- 旧 detector 不再执行；
- 当前 serial propagation=0 不能作为真实结论；
- 当前 no-GT stress 部分数据不可用；
- hidden blocked 不是 hidden 负结果；
- oracle correct prefix recovery 不是实际自主恢复；
- test demo 结构指标不是 GT accuracy；
- SA60+R95 联合不可行不能成为停止理由。

### 当前依赖

- 当前冻结 Qwen checkpoint、processor 和数据路径；
- v7 authoritative JSON/evidence；
- M4 source-song split 与 MIR weak-label manifest；
- test demo 自动发现和统一 unitizer；
- hidden hook 与 token/row/unit 映射实现；
- route policy、serial state 和真实 extra forward 的修复。

---

## 15. 交付决定

本次 patch 为**文档与声明式 profile patch**，不实现实验代码。新阶段放在：

```text
docs/research_fullslot_serial_detector/
```

而不是继续增加 `docs/research_v7_align_behavior/24...`。新文档指向 v7 上游证据，但保持独立阅读和执行入口。
