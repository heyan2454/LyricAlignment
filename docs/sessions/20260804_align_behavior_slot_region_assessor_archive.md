# 2026-08-04 Align 行为、Slot 工作方式与子区间判别器讨论归档

## 1. 会话任务

本次会话首先审查 `research_v7_compact_evidence_20260804.tar.gz` 与 `LyricAlignment_202608040823_alignbehavior.zip`，分析已有实验结果、实现与报告口径，随后围绕 head/tail 行为、静音与弱人声、posterior、sparse slots、真实串行传播、困难区隔离和初步子区间判别器反复修正下一阶段研究计划。

用户要求本记录重点保留：

- 实验结果实际说明了什么；
- 用户对结果解释的质疑与修正；
- 哪些旧实验没有真正回答问题；
- 新的研究判断、目标和期望；
- 长数据、slot、串行、判别器和 demo 自动化的完整计划；
- 后续由 agent 编写和运行代码，最终文档由 ChatGPT 复核修正。

## 2. 对工作目录和报告的审查

当前 research_v7 已具有 request/attempt/evidence、mutation、workflow、posterior、official repair 和 source-song bootstrap 等基础，能够继续正式研究，但存在文档与原始结果不一致：

1. 旧 E5 报告曾称有 807 个 item 且近似打平，但当前 artifact 缺真正 fixed baseline，paired 结果不可验证；
2. P1 一度被写成显著变差，修正后的 workflow GT 中与 P0 基本持平；
3. 人工 review 结果与标签已经存在，正式报告“未填写”的表述错误；当前 archive 仍需定位原始 artifact、审计实际填写数量并与 packet identity 对齐；
4. 旧 discussion patch manifest 已不能代表当前包含大量代码变化的工作树；
5. 当前大量 ΔMAE 使用 official decoder，而不是 raw，后续不能继续将其直接解释为模型底层行为。

这些修正应由 agent 生成机器可读清单，运行结束后由 ChatGPT 修改正式文档。

## 3. 用户对初始分析的主要纠正

### 3.1 不把常识包装为主要发现

“推理成功不代表文本与音频匹配”被用户认为是无意义的常识，不应作为本轮主要科研结论。最多保留为接口限制：模型没有自动拒绝输出机制。

### 3.2 Head 严格、Tail 宽松

用户根据已有结果提出：

> 对齐可能可以收敛为歌词与歌声的头部必须准确，尾部可以宽松。

已有证据：

- M4 短片段 extra-tail 对原正确前缀几乎无影响；
- MIR-1K 长音频也显示 tail 多给不明显伤害原前缀；
- head 错误随比例快速恶化；
- M4 extra-head 10% 约 +0.056 秒，用户认为勉强可容忍；25% 约 +0.333 秒，已经明显；
- MIR-1K 长音频 extra-head 10% 已约 +0.291 秒，25% 约 +1.833 秒，说明长/OOD 条件更敏感。

但需注意：这些正式曲线主要基于 official 输出；M4 主实验是 4–12 秒短片段，不能代替长音频结论。

### 3.3 Middle 的解释

用户认为，在 head 和中间文本均正确时，middle 理应正常。当前 middle mutation 结果说明的是插入、删除或替换会伤害错误后的后缀，并不表示正确 middle 本身不稳定。后续必须分 mutation 前、内部和后部评价。

### 3.4 数据来源必须分开

用户在旧报告中无法分辨结果来自 M4、MIR 或 demo。后续必须明确区分：

- M4 原生短片段；
- M4 同歌拼合长音频；
- MIR-1K 完整歌曲；
- 无 GT 多语言 test demo。

当前包中没有 MIR-ST500，使用的是 4 首 MIR-1K heldout。

## 4. 音频范围、静音与弱人声

“音频范围错误”实际是保留完整歌词但裁掉部分音频。start-late 会让开头歌词无声可对齐，后续一起错；end-early 开头仍正确，因此单窗平均较好。

用户指出串行风险：如果 end-early 中尚未唱到的 tail 被错误提交，下一窗文本从更后面开始，而音频先唱未提交歌词，立即形成危险的 head 错位。因此 end-early 必须在真实连续多窗中测试，并尝试依赖子区间判别器决定最后可信提交位置。

纯伴奏不符合生产主输入。正式实验应使用分离纯人声的合理退化：

- 弱人声；
- 混响；
- 分离残留；
- 局部 dropout；
- 第一处主唱削弱；
- 前置静音、低幅噪声和自然无唱前奏。

用户需先试听一个小型校准包，冻结“轻度合理”和“明显但合理”的等级。单纯音量衰减前需确认 processor 是否归一化。

前置人工静音可形成强 GT：加入 δ 秒后，正确时间应整体加 δ。需观察第一处真实主唱是否能重新建立 head，以及静音是否放大小量 head 文本错误。

## 5. Posterior 与区域判断

Posterior 表示每个边界对候选时间的分数分布。正确边界通常集中、margin 大；困难输入可能分散、多峰、margin 小或吸附边缘。

已有 request 平均 entropy 对 extra、replace、no-match 有较高 AUROC，用户认为已经值得试做二分检查。讨论后确认：当前“整条请求平均”会把少量 tail 错误被正确 core 稀释，也无法指出错误从哪里开始。

下一版应保存逐 unit：

- start/end entropy；
- top1-top2 margin；
- top-k 时间和概率；
- 边缘概率；
- raw 时间、时长和局部推进；
- 滑窗变化和变化点。

判别目标不是整条请求是否正确，而是查询范围内哪些连续子区间可信。

## 6. Official、Raw 与 Hidden

用户认为 official 最终可能被抛弃，重点应转向 raw 和底层潜表示。但当前阶段 official 仍可提供判定信号：

- official 几何本身；
- repair 位移和连续 repair；
- raw 很确定但 official 大修；
- raw 不确定但 official 修成表面平滑；
- hidden/raw 不稳定但 official 表面稳定。

判别器消融需要比较 H、R、O、H+R、H+O、R+O、H+R+O 和跨视图组合。

Hidden 不只使用原向量，还应构造：

- start/end hidden 的差、均值、cosine 和距离；
- norm、方差、极值；
- 相邻 unit 的一阶/二阶变化与局部几何；
- 最后四层的层间演化与稳定速度；
- 到正常 hidden 分布的 Mahalanobis、PCA 和 kNN 异常距离；
- 同一 unit 跨 slot mask、窗口、tail dosage 和音频变换的一致性；
- hidden 异常变化点和持续区间。

是否真正有增量信息需通过消融验证，不能预设。

## 7. Sparse-slot 已有结果

现有 sparse-slot 使用 4 首 MIR-1K 完整歌曲，音频约 57–87 秒，查询目标末尾约位于 36–52 秒，共 320 units。official GT 边界 MAE：

- 一次性完整对齐约 32.69 ms；
- sparse-slot 约 32.43 ms。

当前只能解释为在这 4 首数据上未观察到精度损失，不能说 sparse-slot 更准。它尚未验证 90 秒以后、180 秒、完整歌曲后部、非连续 slots、困难区跨越和 future 无 slot。

已有具体配置大致表现为：

```text
完整音频 + 孤立短文本
< 裁剪音频 + 串行短文本
< 完整音频 + 较完整文本上下文 + 当前 sparse slots
≈ 一次性完整对齐
```

但这个排序混合了音频范围、文本上下文和 slot 结构，不能解释为“slot 天然优于串行”。

## 8. Slot 与串行不互斥

用户进一步指出 slot 和串行并不完全互斥。最终修正：

- 串行负责多次请求如何覆盖歌曲和传播状态；
- slot 负责每次请求查询哪些歌词时间。

可组合为：

```text
≥180 秒歌曲时间线上的 fixed 60s 移动请求
+ 足够历史/未来歌词上下文
+ 当前 sparse slots
+ 历史复查的非连续 slots
+ future tail 无 slots
+ 区间判别器
```

需要研究的具体工作方式包括：

- 完整歌曲音频按顺序查询不同 slot 区；
- ≥180 秒时间线上的 fixed 60s 窗口 + 当前 sparse slots；
- 当前区 + 历史复查区的非连续 slots；
- 固定窗口只传播文本 cursor；
- 动态窗口传播文本和时间 cursor；
- 平时串行，失败时使用更大范围 sparse slots 重新入轨。

Slot 能减少重复输出、支持历史复查和困难区跨越，但如果 controller 选择了错误歌词区，slot 仍可能“准确回答错误问题”，所以仍需判别器保护。

## 9. Slot 后续行为研究

需要补充：

1. ≥180 秒和完整歌曲时间线中，使用 fixed 60s 请求进行 early/middle/late 定位；
2. 连续、两个/三个不连续区间；
3. 历史复查 + 当前区；
4. 困难区两侧；
5. 联合查询 vs 分别查询；
6. slot 密度 100%、每 2/4/8 个和仅锚点；
7. 历史文本预算和 future 无 slot；
8. 同一 unit 跨 slot mask 的 raw/official/posterior/hidden 不变性；
9. 查询区以外少量 extra/missing/replace 的污染；
10. 跨过 unresolved 区后重新定位。

当前实现理论上可支持非连续 slots，但需修 slot indices 未强制递增及输出映射风险。

## 10. Replace、Missing、Extra

单独使用百分比或单独使用绝对数量都不够。后续同时保留 1/2/4/8 units 的稀疏真实错误和 10%/25%/50% 的核心百分比曲线；更极端比例只在小型压力子集运行，避免与位置、slot 和声学条件形成笛卡尔积。

Replace 可能模拟困难区，因为文字与声音无法对应，模型可能无法判断边界；但它与弱人声不同：replace 是文字身份错误，弱人声是正确文字但声学证据不足。应进行迁移实验，验证二者是否共享 hidden/raw/official 不确定信号，不能直接等同。

旧 replace evaluator 通过字符碰巧相同评分，语义不正确，必须显式 mutation mask，并分错误前、错误内和错误后。

## 11. 真正串行与恢复

旧 cursor ±2/4/8 仍使用完整上下文，且目标随错误 cursor 移动，没有测试“系统想对齐 A 却送入 B”。旧 recovery 只是错误请求后重新送完全正确输入，说明模型无跨请求内部状态污染，不是实际恢复。

真正串行要求：

- 首窗正确；
- 第 2 窗注入错误；
- 后续至少运行 3 窗；
- 下一窗由上一窗实际结果构造；
- 不允许 GT reset；
- 保存 text/time cursor、commit 和 lineage。

分别测试固定窗口只传播文本状态、动态窗口传播文本和时间状态，以及 slot+串行混合。

## 12. 困难区隔离

用户提出，即使 realign 也无法解决的困难区不能污染后面。建议状态：committed、provisional、unsafe、unresolved、unseen。

困难区有限复查后若仍不可信：

- 标记 unresolved；
- 不用其错误时间推进；
- 使用非连续 sparse slots 查询后续歌词；
- 建立新的右侧锚点；
- 后续继续；
- 困难区留在左右锚点之间单独处理。

这可能是 slot 相比单一 cursor 最重要的系统价值。

## 13. 子区间判别器

用户冻结：判别器至少输出查询范围内部可信与不可信子区间，不只做整请求二分类。

在 validation 冻结 95% 和 99% 两个高召回 operating point；test 同时计算错误 unit recall、错误区间 75% 覆盖 recall、错误区间 100% 全覆盖 recall。正确误判只按 retained correct unit 计算。错误捕捉更重要，可以接受一定误判，但必须报告代价和停滞。

第一版动作保持简单：

```text
trusted → 允许提交
unsafe → 换预定义视图复查一次
再次 unsafe → unresolved，继续后续
```

主要指标是 unsafe unit/interval recall、长错误段完全漏检、正确误判、提交延迟、额外请求和停滞率；AUROC/F1 仅辅助。

## 14. Test demo 自动化和多语言切分

用户指出人工看 demo 成本过高，必须自动利用全部 35 首 demo。强伪标签/一致性包括：

- 前置静音整体平移；
- tail dosage 共同 prefix；
- full vs sparse；
- 相邻窗口重叠；
- 不同 slot mask。

仅渲染潜在漏检、潜在误报、最长异常、阈值附近和随机对照。

用户补充历史问题：英文窗口曾把单词从中间切开，日文不确定是否也有。正式 smoke 必须：

- 英文只在合法行/标点/单词边界切分，覆盖撇号和连字符；
- 审查日文 processor unit、小假名、促音、长音符、汉字+假名和混写；
- 不在最小 alignment unit 内切断；
- alignment/window/render units 可追踪。

## 15. 长数据与外部数据

用户否定 45 秒作为长数据，要求至少 90 秒，并有一定数量 180 秒数据。180 秒指形成和评价的数据时间线，不是把模型窗口改成 180 秒；主流程继续使用此前较稳的 fixed 60s 请求。自然静音可保留，但禁止靠人工静音把短音频凑成长数据。

agent 可按规则构造 M4Singer 同歌长时间线，也可尝试公开同步歌词、字级 Enhanced LRC，或转换用户本地合法拥有的 QRC/YRC/音乐软件歌词文件。必须记录来源、许可、版本匹配、时间粒度和单位映射；网络探索不能阻塞本地主线。

## 16. 12 小时预算、缓存和避免笛卡尔积

用户最终要求：formal 最好控制在 10 小时内，12 小时可以接受但为硬上限；使用缓存节省时间，并特别提醒避免笛卡尔积。

冻结策略：

- 实验按问题隔离 cohort，每次只改变一个主要因素；
- 先筛主效应，仅对已有证据提示的交互增加少量成对条件；
- 不做长度×slot×mutation×声学×串行×模型全组合；
- 用冻结 seed 将歌曲分配到互补 cohort；
- 只共享完整 request identity 相同的 matched legal baseline；
- 缓存长音频派生、processor 输入、可复用音频编码、attempt 底层 evidence、H/R/O 特征和评价；
- 判别器全部消融复用同一 evidence，不重新推理；
- pilot 估算成本，预计 formal 超过 10 小时先缩减；任何情况下不得超过 12 小时。

缩减顺序：删除无信息条件、百分比极端压力档和随机重复，减少同歌变体但保留 source-song 分层，删 90 秒对照并保留 ≥180 秒时间线；不得删除非连续 slot、missing/replace gap 评价、真实串行、demo 自动分析和跨域判别器，也不得退回短音频。

## 17. 分工与后续归档

agent 负责代码、数据构建、本地线索修正、缓存、运行和机器可读结果。所有自动文档仅为 draft。

用户明确要求：所有正式文档标注在结果回传后由 ChatGPT 修正。届时需审查实现、指标和原始 evidence，记录 negative results，更新正式报告与下一阶段决定。

本 patch 只归档本会话讨论、冻结实验设计和 agent 实施合同，不包含下一阶段代码实现或实际实验结果。


## 18. Patch review 后的用户修订（2026-08-04 晚）

用户逐项确认并补充：

1. 长时间线文本扰动必须同时保留绝对 unit 和百分比口径；
2. missing 不能只按 output unit 评价，需建立 omission gap；replace 需同时评价错误替换输出、被替代 GT 缺失和周围正确 unit；
3. 判别器同时计算 unit recall、错误区间 75% 覆盖 recall 和 100% 全覆盖 recall；正确误判按 unit 统计；
4. 不以置信区间作为主要门槛，但实验必须有一定 source-song、unsafe unit 和 error interval 规模，并报告分母；
5. 当前主要目标是诊断 raw、official、hidden，不急于冻结生产 commit；必要可视化应自动筛选，避免依赖人工；
6. baseline 只有完整 request identity 相同才能共享，不同 slot mask、上下文和 crop 必须有 matched legal baseline；
7. S6 必须分成单机制消融和端到端系统配置比较；
8. slot density 需要固定公共 queried units 并轮换 stride phase，避免不同密度选择不同难度 unit；
9. 180 秒是数据时间线时长，主窗口继续采用此前表现较好的 fixed 60s；不得靠人工静音凑 180 秒；
10. formal 目标 10 小时，硬上限 12 小时；
11. seam 影响已有证据倾向较小，只做少量直接拼接 vs seam 插入 0.5 秒静音的对照，插入静音总时长和对照规模均受限，不能成为凑长度手段；
12. 判别器增加 M4 synthetic-long→MIR natural-song、leave-one-mutation/acoustic-family-out 等跨域评价；
13. hidden 特征必须先冻结 token/output-row/layer/dtype/数值等价和 train-only feature fitting 契约；
14. 弱人声校准包作为第一批工作尽早生成，与其它代码并行；
15. 人工 review 结果与标签已经存在，所有写成“未填写”的文档均需纠正，并在下一阶段定位和审计原始 artifact。
