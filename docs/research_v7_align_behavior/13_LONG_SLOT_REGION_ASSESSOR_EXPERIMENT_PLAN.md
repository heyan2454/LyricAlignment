# Research v7 补充冻结计划：长时间线 Slot/串行混合行为与子区间判别器

日期：2026-08-04
状态：待 agent 实现与运行；正式结论需在结果回传后由 ChatGPT 复核和修正文档。

## 1. 本轮目标与基本口径

本轮不再将 slot 与串行视为互斥路线。二者控制不同层面：

- **串行/窗口策略**决定多次 60 秒请求如何逐步覆盖长歌曲，以及是否传播文本 cursor、时间 cursor 和提交状态；
- **slot 策略**决定一次请求中哪些歌词单元需要输出时间，哪些歌词只作为上下文。

正式研究对象是二者的组合：

```text
≥90 秒、以 ≥180 秒为主体的真实或规则构造时间线
+ 当前冻结的 fixed 60s acoustic request
+ 足够的歌词上下文
+ 当前区/复查区的 sparse 或非连续 slots
+ 逐 unit/逐 gap 子区间判别器
+ 有限重试与 unresolved 机制
```

**180 秒是形成和评价数据时间线的时长，不是模型单次窗口长度。** 本轮默认沿用此前观察较稳的 fixed 60s production baseline，不将主请求直接改成 180 秒，也不扫描 180 秒模型输入长度。

本轮需要完成：

1. 修复旧行为实验的评价口径、历史文档错误和未真正完成的串行实验；
2. 以 90 秒以上、尤其 180 秒以上时间线为主体，系统研究 slot 的工作方式；
3. 同时补充绝对 unit 与百分比文本扰动；
4. 从 hidden、raw、official 及其交互中寻找逐 unit 和逐 gap 的错误信号；
5. 建立初步子区间判别器，并分别诊断 raw-target 与 official-target；
6. 将判别器放入真实多窗流程，验证是否能阻断 end-early、错误 head 和困难区的传播；
7. 正式实验运行目标控制在 **10 小时以内**，硬上限 **12 小时**。

## 2. 判别器输出与冻结评价目标

判别器输入一个或多个歌词查询范围，输出范围内部的可信与不可信连续子区间，而不是对整条请求给一次二分类。对于 missing，还需要输出相邻保留 unit 之间的可疑 gap。

```json
{
  "queried_intervals": [[40, 100], [130, 150]],
  "trusted_intervals": [[40, 67], [82, 100], [130, 141]],
  "unsafe_intervals": [[67, 82], [141, 150]],
  "unsafe_gaps": [{"left_unit": 73, "right_unit": 78}]
}
```

在 validation 上冻结 `high_recall_95` 和 `high_recall_99` 两个 operating point。test 同时报告三种错误捕捉标准：

1. **unit recall**：错误 output unit 被判 unsafe 的比例；missing 另报告 deleted-GT-unit weighted gap recall；
2. **interval recall@75%**：一个真实错误区间至少 75% 的 canonical units 被预测 unsafe；
3. **interval recall@100%**：一个真实错误区间全部 canonical units 被预测 unsafe。

正确结果的代价只按 **retained correct unit** 统计 false-positive rate，不用 request 或 interval 数量替代。错误捕捉优先，可以接受一定正确误判；原 20%/10% 正确 unit 误判率继续作为参考目标，而不是以牺牲错误捕捉为代价的绝对硬门槛。

同时报告：

- missing gap event recall；
- replace wrong-output recall 与 replaced-GT omission recall；
- 长度不少于 3 units 的错误区间完全漏检率；
- unsafe 预测的平均扩张长度；
- 额外请求、提交延迟、unresolved 和停滞率。

AUROC、AUPRC、F1 只作辅助，不替代上述 operating-point 结果。

## 3. 长时间线与 60 秒窗口

### 3.1 长度口径

| 时间线长度 | 用途 |
|---|---|
| <30 秒 | 单元测试和快速代码 smoke |
| 30–90 秒 | 历史兼容或长度对照，不作为主结果 |
| 90–180 秒 | 正式最低档 |
| ≥180 秒 | 正式主体，支持至少 3 个 60 秒请求 |
| 完整歌曲 | 真实多窗串行、后部定位和困难区隔离 |

正式主统计不得用 4–12 秒短片段替代长时间线结论。

### 3.2 请求窗口冻结

- 主 acoustic request 使用现有 **fixed 60s production baseline**；
- overlap、步长和尾窗处理沿用当前已验证实现，本阶段不再把窗口长度加入实验因素；
- 180 秒及完整歌曲通过多个 60 秒请求覆盖；
- full-song audio 单次输入若保留，只能作为小型诊断 control，不进入主系统平均结果；
- 不需要把“模型能否一次处理 180 秒输入”设为本轮 gate。

### 3.3 Formal 数据规模

优先目标：

- 至少 20 首独立 source song 可形成 ≥180 秒时间线，理想 30 首以上；
- 至少 8 首完整歌曲支持 4 个以上连续 60 秒请求；
- 每个核心主效应条件覆盖至少 12 首独立 source song；
- assessor 的 test split 应包含多个独立 source song，并明确报告每类 unsafe units、gap events 和 error intervals 的实际分母；
- early/middle/late 三种时间线位置均有覆盖。

本轮不要求用置信区间作为启动门槛，但不能只给百分比而隐藏样本数；95%/99% 的解释强度必须随实际分母说明。

如果本地数据无法满足，agent 应在 preflight 中报告实际可用规模，并按以下顺序降级：

1. 减少次要交互和极端严重度；
2. 减少重复随机种子；
3. 减少 90 秒对照，优先保留 ≥180 秒主体；
4. 减少每首歌的变体数量，优先保留 source-song 多样性；
5. 不得通过大量短片段或重复 slot view 填充正式 attempt 数。

### 3.4 M4Singer 长时间线构造

agent 可依据本地元数据灵活构造，但必须遵守：

- 只拼接同一 source song、同一录音版本、同一歌手的片段；
- 顺序必须由原元数据确定，不按文件名任意猜测；
- 歌词与音频同步拼接；
- 禁止循环复制短片段凑长度；
- 禁止通过强塞人工静音把短样本凑成 180 秒；自然存在的静音正常保留；
- 保存每个 seam 的来源、原时间、新时间和位置；
- 同一 source song 的所有派生时间线和窗口属于同一数据 split。

已有实验倾向于 seam 影响较小，因此不做大规模 seam 扫描。只建立一个小型对照：

- 主版本直接按规则拼接；
- 对照版本在 seam 插入 0.5 秒静音并同步平移后续 GT；
- seam-silence 对照不超过 synthetic-long attempts 的 10%；
- 全部插入静音占最终时间线时长也必须低于 10%；
- 原始有效内容本身必须接近目标长度，不能依靠这 0.5 秒静音达到长度门槛；
- 分别报告 seam 邻近与远离 seam 的结果。

### 3.5 外部长数据探索

网络数据只作为补充，不能阻塞本地主线。可尝试许可清楚的完整歌曲同步歌词、Enhanced LRC，或用户本地合法拥有的 QRC/YRC/音乐软件导出歌词。每个外部项目必须记录来源、许可、音频/歌词版本、语言、时间粒度、单位映射和版本匹配审计。

若只有 onset，可用下一个 onset 派生 offset，但必须标记，主指标只评价 onset，不与真实 offset GT 混合。

## 4. 避免笛卡尔积的设计

禁止把以下所有因素做全组合：

```text
时间线长度 × 时间线位置 × slot 拓扑 × slot 密度 × 文本上下文
× extra/missing/replace × 严重度 × 扰动位置 × 声学退化
× 串行方式 × 判别器特征组合
```

### 4.1 问题隔离 cohort

每个实验只回答一个主要问题，其他因素固定：

- 时间线实验：只改变时间线长度和目标位置，request 始终为 60 秒；
- slot 拓扑实验：固定长时间线、同一 60 秒 crop、正确文本和 queried units，只改变 slot 结构；
- slot 上下文实验：固定 slot 区和 acoustic crop，只改变历史/future 文本预算；
- 文本扰动实验：固定主 slot 方式，分别运行绝对 unit 与百分比 cohort；
- 声学困难实验：歌词完全正确，只改变弱人声/静音等声学条件；
- 串行传播实验：固定 60 秒窗口计划和已选定 slot 方式，只改变传播状态或 commit 规则；
- 判别器消融：复用同一底层 evidence，不重新推理。

### 4.2 主效应后再做少量交互

smoke/pilot 先筛选单因素。只有已有观察提示交互后，formal 才增加少量成对条件，例如：

- leading silence × extra-head 10%；
- end-early × 判别器 commit；
- 非连续 slot × 中间困难区；
- replace 困难区 × 后续 sparse slot 重新入轨。

不增加三因素以上全组合。

### 4.3 固定代表条件

默认代表设置：

- 主时间线长度：≥180 秒；
- 主 acoustic request：fixed 60s；
- 主目标位置：middle，另保留少量 early/late；
- 主 slot 区长度：32 units；
- 主历史文本：从当前可信 cursor 到当前区，必要时保留更早文本作上下文；
- 主 future lookahead：16 units，无 slots；
- 稀疏真实错误：1/2/4/8 units；
- 百分比核心档：10%/25%/50%；
- 百分比极端档只在小型压力子集运行。

### 4.4 分层抽样而非全量复制

每首歌不承载所有条件。用冻结 seed 将歌曲分配到互补 cohort，保证：

- 每个核心条件有足够 source-song 覆盖；
- 同一歌曲不会生成大量高度相关变体；
- 同一底层 request 的不同 view 可成对分析，但不能当作独立歌曲扩充样本；
- M4 synthetic-long、MIR natural-song 和 demo 分开汇报。

## 5. 阶段 A：修复评价、映射和历史事实

### A1. Raw/Official 分开

每个 queried unit 保存并评分：

- raw onset/offset/duration；
- official onset/offset/duration；
- raw 顺序、重复、逆序；
- raw→official 位移；
- official repair 标志、连续 repair 长度和局部 repair 比例；
- posterior top-k、entropy、margin 和边缘概率。

当前阶段是诊断研究，不冻结最终生产 commit 路线。raw-target 与 official-target 必须分别建立标签、训练和评价；必要的可视化由自动异常排序选择，不能依赖大规模人工观看。

### A2. Mutation canonical mapping

显式保存 canonical GT axis、输入 axis、输出 row 和 gap candidate 之间的映射：

- before mutation；
- inside mutation；
- after mutation；
- inserted input unit；
- removed GT unit；
- replacement input unit；
- replaced original GT unit；
- retained correct unit。

replace 不再通过字符偶然相同决定评分。100% replace 单列为无正确 anchor 行为。

### A3. Missing 与 replace 的评价方式

#### Missing

被删除的 GT unit 没有 output row，不能伪装成普通 output-unit 标签。必须同时建立：

1. **retained output-unit 评价**：评价 deletion 前后仍存在的正确 unit 是否被带偏；
2. **virtual gap 评价**：在每对相邻 retained units 之间建立 gap candidate。若 canonical GT 中间存在一个或多个 removed units，该 gap 为 positive；
3. **missing event recall**：最大连续 removed run 是否被对应 gap 检出；
4. **deleted-GT-unit weighted recall**：一个 positive gap 被检出时，其覆盖的 removed GT units 计为被捕捉，并明确这是 omission detection，不代表模型恢复了每个缺失 unit 的精确时间。

virtual gap 的输入特征只能来自左右 unit 的 hidden/raw/official/posterior、时间跳变和跨视图差异，不得使用 mutation mask、缺失数量或 GT 身份。

#### Replace

replace 同时包含两个方向：

1. replacement input units 是不存在于 GT 的 wrong-output units，按 identity error 评价；
2. 被替代的 original GT units 在输入中缺失，按 omission gap 评价；
3. replacement 前后的 retained correct units 单独评价是否被污染；
4. 组合报告 wrong-output recall、replaced-GT omission recall、combined replace-region recall@75%/100%。

### A4. Slot 映射

- slot indices 强制严格递增；
- 保存输入 timestamp token 位置；
- 保存输出 row 到原 input unit 和 canonical GT unit 的映射；
- 连续与非连续 slots 均有单元测试；
- 同一 queried unit 在不同 slot mask 下可追踪；
- gap candidate 的左右边界映射可追踪。

### A5. 真正串行 lineage

保存：

- parent request；
- 上一窗 trusted/provisional/unsafe/unresolved；
- 文本 cursor 来源；
- 60 秒 acoustic crop 来源；
- slot mask 与 review slots；
- 本窗是否使用任何 oracle reset。

正式串行不得每窗用 GT 重置。

### A6. 历史文档事实修正

当前文档统一修正为：

- E5 当前 artifact 缺真正 fixed baseline，paired 结果不可验证；
- P1 是 same-audio incremental prefix/stateful prefix workflow，修正后与 P0 基本持平，不是“显著变差”；
- recovery 0.0 秒只说明当前调用式实现无跨请求隐状态污染，不是真实错误恢复；
- M4 短片段、M4 synthetic-long、MIR natural-song 和 demo 必须分开；
- 人工 review 结果与标签已经存在；此前“未填写”的表述错误。下一阶段必须定位原始人工 artifact，审计实际填写数量、schema、reviewer 和可用字段，再纳入正式统计，不能仅凭 packet 数推定标签数。

## 6. 阶段 B：Slot 工作方式研究

slot 与串行可组合。所有主实验在 ≥180 秒时间线上用 60 秒 acoustic request 运行。

### S0. 长时间线位置基线

固定合法文本和 60 秒 crop，比较：

1. crop 内全部目标歌词有 slots；
2. 当前连续区有 slots，其余歌词只作上下文；
3. 当前区有 slots，只有有限历史文本；
4. 只有当前短文本。

目标分别位于长时间线 early/middle/late。查询区以 32 units 为主，少量 8/16/64 units 作容量对照。

回答：

- sparse slot 对 GT 的 raw/official 精度；
- 在歌曲后部和连续多窗后能否保持定位；
- 历史文本和 future lookahead 是否必要；
- 孤立短文本为何失败。

### S1. Slot 拓扑

固定同一长时间线、同一 60 秒 crop、正确文本和相同 queried units，分别运行：

- 单个连续区间；
- 两个不连续区间；
- 三个短区间；
- 当前生成区 + 仍位于 crop 内的历史复查区；
- 困难区两侧；
- 联合查询与分别查询。

主评价是同一 unit 的成对 GT 误差和跨视图 hidden/raw/official/posterior 一致性；分别查询的额外请求成本必须单列。

### S2. Slot 密度与公平比较

固定 32-unit 目标区，比较：

- 100%；
- stride 2；
- stride 4；
- stride 8；
- 仅首尾与公共锚点。

为避免不同密度评价了不同难度的 unit：

- 预先冻结一组所有密度都包含的 **common anchor units**；
- stride 2/4/8 使用多个起始 phase 轮换，不固定只取某一种位置；
- 主精度比较只评价所有 mask 共同 queried 的 common units；
- 次要结果再报告各条件全部 queried units 的绝对表现；
- 仅首尾锚点只能说明锚点定位和成本，不能代表整个 32-unit 区间的完整对齐质量。

pilot 后只保留有信息的 2–3 个密度进入 formal。

### S3. 上下文预算

固定当前 slot 区和 acoustic crop，分别研究：

- 历史文本：无、最近 16、完整可用历史；
- future 文本：无、16 units、较长 future。

先分别研究历史和 future 主效应，仅在 pilot 显示交互时增加少量组合。

### S4. Slot mask 不变性

同一 unit 在以下视图中重复查询：

- full slots；
- 连续 sparse；
- 非连续 sparse；
- 联合与单独查询；
- 两种 future dosage；
- 相邻 60 秒窗口重叠区。

保存 raw/official 时间差、posterior 分布差和 hidden 距离。这既是行为研究，也是无 GT 判别信号。

### S5. Slot 外部文本错误

queried interval 保持正确，只在查询前、两个查询区之间或查询后加入代表性的 extra、missing、replace。分别运行：

- 稀疏真实错误：1/2/4/8 units；
- 比例错误核心档：10%/25%/50%；
- 极端比例只在小型 stress subset 运行。

回答 slot 是否能隔离局部正确区，或是否受远处错误文本污染。

### S6. 机制消融与系统配置分开

#### S6-M：机制消融

使用相同 60 秒 acoustic crops、相同歌词、相同 queried units 和尽量相同请求计划，分别只改变一个机制：

- 当前 slots vs 当前 + 历史 review slots；
- 固定 acoustic window 下，不传播 vs 传播 text cursor；
- 固定 text schedule 下，不传播 vs 传播 time cursor；
- unsafe 后强行提交 vs 有限复查后 unresolved；
- 同一 queried units 的联合查询 vs 分别查询。

这部分用于回答组件作用。

#### S6-S：端到端系统配置

系统配置同时改变多个机制，只作为整体路线比较，不称为严格消融：

- **Window-sparse**：fixed 60s 多窗 + 当前 sparse slots + future 无 slots；
- **Window-review**：fixed 60s 多窗 + 当前区 + crop 内历史复查区；
- **Serial-text**：fixed 60s 窗口计划，仅传播文本 commit；
- **Serial-dynamic**：下一 crop 和文本起点由上一窗可信结果共同决定；
- **Hybrid-relocalize**：平时 60 秒串行，失败时用更大范围或相邻请求的 sparse slots 重新定位后续区。

先用合法输入比较精度、请求数和耗时，再只对最有价值的 2–3 个系统运行错误传播实验。

## 7. 阶段 C：文本与声学困难行为

### C1. 绝对 unit 与百分比扰动同时保留

#### 稀疏真实错误

1/2/4/8 units：

- extra：重复已提交文本、相邻短语、同歌过去/未来文本、跨歌同语言文本；
- missing：单字、短语、句首、分散漏字；
- replace：同歌其他位置、跨歌真实文本、同音/近音、小连续块。

#### 百分比曲线

每条记录同时保存 requested ratio、actual ratio 和绝对 unit 数。

核心正式档：

- extra：+10%/+25%/+50%；
- missing：10%/25%/50%；
- replace：10%/25%/50%。

小型压力子集：

- extra：+100%/+200%；
- missing：75%/90%；
- replace：75%/100%。

比例档不与所有位置、slot 密度和声学条件做全组合。主曲线固定代表位置，并用少量 head/middle/tail 分层检查位置效应。

### C2. Replace 作为困难区代理

replace 只作为“文字与声音不对应”的人工困难区，不预设其与弱人声机制一致。比较 replace、正确歌词+弱人声、混响、dropout 和自然高误差区，并进行有限迁移：replace 训练→弱人声测试、弱人声训练→replace 测试、联合训练和 leave-one-family-out。

### C3. 前置静音与弱人声

纯伴奏只保留极端负对照，正式主条件为纯人声输入的合理退化。

弱人声校准是第一批工作：

- Phase 0 立即生成小型 calibration packet；
- 与 evaluator、slot mapping、cache 和 hidden 代码并行推进；
- 尽早交给用户试听，冻结“轻度合理”和“明显但合理”两档；
- 人工选择不阻塞其它代码和非声学实验；
- 未完成校准前可以生成 provisional 结果，但不能混入正式声学结论。

正式主要测试：

- 绝对静音、低幅噪声、自然无唱前奏；
- 正常人声、冻结的轻度弱人声、明显弱人声、混响、分离残留。

不做全组合。先测试正确 head；仅对发现明显风险的条件增加 extra-head 10% 或 missing-head 10% 交互。

#### C3 操作化定义（2026-08-04 定稿）

本子实验的"弱人声"指：**静音/间隙区实际非静音的分离残留污染**——
模拟 Demucs 把 mix 中静音区/和声段错误分离产生的"不干净"，而非单纯音量衰减：

- **目标机制**：理想 Demucs 把静音区分为纯静音；真实不足会把静音区分成「混入微弱的乐曲声（错吸非人声曲段）」，
  并在遇到和音/伴唱时留下「伴唱残留/混叠」。于是 vocals 里的"静音段"实际带弱曲+伴唱残响。
- **构造**：普通人声段保持原样（**不削弱 voice**）；只在静音/间隙区注入
  「微弱伴奏泄漏 + 伴唱残留」，形成"静音区实际非静音"的弱人声输入。
- **对照**：normal（静音区为纯静音） vs weak（静音区带分离残留） → 只改变静音区污染与否。
- **观测**：检验非静音的静音区是否引起对齐错误（should-be-silent 间隙被误对齐/插入 token、
  边界侵入下一窗、重复/漏字、cursor 漂移）。正确歌词、其他声学不变（§4.1 声学困难——只改弱人声/静音条件）。

## 8. 阶段 D：真实串行、end-early 和困难区隔离

### D1. End-early

在第 2 个 60 秒窗口提前结束音频 0.5/1/2/4/8 秒，歌词仍含原 tail。比较：

- 全部提交；
- 固定安全尾区；
- oracle 区间判断；
- 初步判别器判断。

后续至少继续 3 窗，不得 GT 重置。观察错误提交、下一窗 head、重复/漏字、cursor 漂移和恢复。

### D2. 困难区隔离

困难区有限复查后仍不可信时：

1. 标记 unresolved；
2. 不用其错误结束时间推进后续；
3. 使用非连续 sparse slots 或相邻 60 秒请求查询困难区后的歌词；
4. 建立新的右侧锚点；
5. 继续处理后续，困难区留待左右锚点约束下单独解决。

比较强行提交、无限 realign、有限重试后 unresolved 和 hybrid relocalize。

## 9. Hidden、Raw、Official 信号与抽取契约

### 9.1 Hidden extraction contract

agent 必须先生成 `hidden_extraction_audit.json`，明确：

- 实际模型模块、层编号、pre/post norm 位置和 hidden tensor shape；
- 每个 queried unit 的 start/end boundary 对应哪个 decoder token position、output row 和 timestamp class；
- unit index、boundary type、token position、layer id、request id 的可逆映射；
- dtype、device、是否同一次 forward 同时生成 hidden 与 logits；
- 启用 hidden extraction 前后 raw logits、top-k 和 official 输出的数值等价检查及容差；
- selected layer vectors 的保存 dtype、压缩方式和内容 hash。

不得只凭层序号猜测 token 语义。若模型接口不能稳定映射，hidden 路线停止在 audit，不得生成看似合理的特征。

formal 默认只保存最后层和最后四层所需向量/派生特征，不全面扫描所有层。标准化、PCA、Mahalanobis、kNN reference 和任何 feature selection 只能在 train split 拟合，再应用到 validation/test。

### 9.2 Hidden-only 特征

- start/end hidden 拼接、差、均值；
- norm、分量方差、最大绝对值；
- start/end cosine 和距离；
- 相邻 unit 的一阶/二阶变化、局部方差和曲率；
- 最后四层的层间 cosine、delta norm、总移动和稳定速度；
- 到正确训练分布中心的 Mahalanobis、PCA reconstruction、kNN 距离；
- 同一 unit 跨 slot mask、窗口和 dosage 的 hidden 一致性；
- hidden 异常序列的变化点和持续区间。

### 9.3 Raw-only

- entropy、margin、top-k 时间跨度和方差；
- 多峰和远距离第二峰；
- 音频边缘概率；
- raw duration、相邻时间差、零时长、重复、逆序；
- 局部字速和跨视图时间差。

### 9.4 Official-only

- official duration、gap/overlap、边缘吸附；
- repair 标志、位移、局部比例和连续 run；
- official 跨视图稳定性。

### 9.5 交互与消融

统一消融：H、R、O、H+R、H+O、R+O、H+R+O、H+R+O+跨视图。

显式交互包括：

- hidden 异常 × raw uncertainty；
- hidden 跳变 × raw 时间跳变；
- hidden 异常 × official repair；
- raw 确信但 official 大修；
- raw 不确定但 official 表面平滑；
- hidden/raw 跨视图不稳定但 official 稳定。

所有特征消融复用同一 attempt evidence，不重新运行 aligner。

## 10. 子区间判别器

### 10.1 Candidate 与标签

建立两类 candidate：

1. **unit candidate**：每个实际 output unit；
2. **gap candidate**：每对相邻 retained units 之间的潜在 omission gap。

unit 主标签：

- unsafe：对应 target 下任一边界误差 >250 ms，或歌词身份错误、插入内容不存在、无效时间、严重逆序/越界；
- trusted：对应 target 下两个边界均 ≤250 ms、歌词身份正确且时间有效。

同时报告 100 ms、500 ms；raw-target 与 official-target 分开。gap 标签按 canonical mapping 判断中间是否存在 removed/replaced-original GT units。

mutation mask、mutation family、GT error 和 deleted count 只能用于标签与分层，不能进入模型特征。

### 10.2 模型顺序

1. 单规则；
2. unit/gap 分开的标准化 logistic regression 或线性 probe；
3. 显式二阶交互；
4. 若仍明显不足，再尝试冻结规模浅层 MLP 或浅层树。

按 source song 切分，validation 冻结特征、阈值和区间合并规则，test 不再调参。

### 10.3 跨域评价

至少分别报告：

- M4 synthetic-long 同域 source-song heldout；
- M4 训练/验证后在 MIR natural-song 上的跨数据集测试；
- mutation family leave-one-out；
- replace、弱人声和自然高误差区之间的 acoustic/text family leave-one-out；
- demo 只做无 GT 自动 challenge 和人工标签复核，不用来调阈值。

M4、MIR、demo 不合并成一个准确率。

### 10.4 Operating points 与区间输出

在 validation 上冻结 `high_recall_95` 和 `high_recall_99`。test 同时报告 unit recall、interval recall@75%、interval recall@100% 和 correct-unit FPR。

逐 unit/gap score 二分后，只比较：

- 无平滑；
- 填补 1-unit 小孔、左右最多扩张 1 unit 的轻度平滑。

不得使用大范围形态学扩张人为抬高 recall。

## 11. Test Demo 自动利用、多语言和人工标签

### 11.1 自动证据

当前全部 demo 自动运行，但不称为 GT accuracy。生成：

- full vs sparse 一致性；
- 不同 tail dosage 的共同区间一致性；
- 前置静音平移一致性；
- 相邻 60 秒窗口重叠一致性；
- 连续与非连续 slot mask 一致性；
- 判别器潜在漏检/误报排序。

默认只渲染最异常、阈值附近和少量随机正常对照，总量不超过 20–30 个。

### 11.2 已有人工结果与标签

人工 review 结果与标签已经存在。agent 在 Phase 0 必须：

- 定位实际 human-review artifact；
- 报告实际填写记录数、空记录数、reviewer、schema 和 decode-key 对应关系；
- 将人工结果与 140 demo attempts、66 C10 cases 的 packet identity 对齐；
- 不能继续把 packet 模板数量写成“尚无人工结果”，也不能在未审计前假定所有 packet 都已填写；
- 人工标签只用于 heldout 复核或预先冻结的人工评价，不泄漏到自动 challenge 阈值选择。

### 11.3 英文切分

- 不在单词内部切分；
- 优先行、标点、单词边界；
- 覆盖撇号词、连字符词、非 ASCII 拉丁字符；
- alignment unit、window unit 和 render unit 映射可追踪。

### 11.4 日文切分

审查现有日文 demo：

- processor unit 与窗口 unit 是否一致；
- 小假名、促音、长音符、汉字+假名、标点和拉丁混写；
- 不在 processor 的最小对齐 unit 内截断；
- 无稳定词界时优先行或标点边界。

英文和日文边界测试必须进入 smoke gate。

## 12. Baseline、缓存与正式运行预算

### 12.1 公平 baseline

“baseline 只跑一次”只适用于 **完整 request identity 相同** 的情况。每个 mutation 或 slot 条件必须引用 matched legal baseline，身份至少相同于：

```text
audio crop/transform
normalized legal text context
alignment units
slot indices and topology
request mode
window position
processor/model/decoder version
```

因此：

- full-slot mutation 对应 full-slot legal baseline；
- sparse mutation 对应相同 sparse mask 的 legal baseline；
- 非连续 slot mutation 对应相同非连续 mask 的 legal baseline；
- 不同 acoustic crop、文本上下文或 request mode 不得共享一个不匹配 baseline。

完全相同 identity 的 baseline 才可通过缓存复用。

### 12.2 缓存分层与 key

优先复用：

1. 音频派生缓存；
2. processor 输入缓存；
3. 经等价性验证后可复用的音频编码缓存；
4. attempt 底层 hidden/raw/posterior/official/repair evidence；
5. H/R/O 和跨视图特征缓存；
6. 不同 GT 阈值、模型和 operating point 的评价缓存。

缓存键至少包含：

```text
code commit/source-tree hash
model/checkpoint hash
processor/dependency environment version
audio content hash + crop/transform spec
normalized text hash
alignment units hash
slot indices/topology
request mode and window identity
mutation spec hash and seed
hidden extraction schema/layers
decoder and global-time conversion version
GT/canonical mapping schema version
```

不得仅按输出目录或文件名复用。音频 encoder cache 只有在确认该表示与文本/slot 无关且缓存前后输出等价后才能启用。

### 12.3 正式运行预算

- **formal target：≤10 小时**；
- **formal hard stop：≤12 小时**；
- 代码开发、用户试听校准不计入 formal；
- preflight、smoke、pilot 单独记录耗时，不得被混写为 formal；
- 预计 formal 超过 10 小时时先缩减，只有保留核心实验仍无法压到 10 小时时才允许接近 12 小时；
- 超过 12 小时必须终止未开始的低优先级 cohort，而不是静默继续。

formal 建议预算：

| 阶段 | 目标上限 |
|---|---:|
| 长时间线合法基线、slot 主效应 | 2.5 h |
| 绝对/百分比文本扰动与 seam 小对照 | 2.0 h |
| 声学困难、真实串行、end-early | 2.5 h |
| H/R/O evidence 与 region assessor | 2.0 h |
| demo 自动 challenge、人工标签导入、汇总 | 1.0 h |

缩减顺序：

1. 删除 pilot 无信息的密度、上下文或系统配置；
2. 删除百分比极端 stress subset，保留 10/25/50 和 1/2/4/8；
3. 减少随机重复和同歌变体；
4. 减少 90 秒对照，保留 ≥180 秒时间线；
5. 保留非连续 slot、真实串行、end-early、missing/replace gap 评价、跨域 assessor 和 demo 自动分析；
6. 不得退回短音频作为主要节省方式。

pilot 必须生成每种请求的中位/p90 推理时间、cache hit/miss、预计 forward 数、formal 墙钟和 retained/dropped conditions。预计超过 10 小时时不得直接启动 formal。

## 13. 执行阶段和 Gate

### Phase 0：Preflight 与并行校准

输出：

- 长源与长度分布；
- 可构造 ≥90/≥180 秒时间线；
- 60 秒窗口计划；
- seam 0.5 秒小对照 manifest；
- slot mapping 与 density common anchors；
- hidden extraction audit；
- human-review artifact audit；
- demo 多语言切分 audit；
- cache plan 与 formal 成本预测；
- 弱人声 calibration packet。

### Phase 1：修复契约

修 raw/official evaluator、canonical mutation mapping、unit/gap candidate、slot 映射、serial lineage、多语言切分、历史文档和缓存身份。

### Phase 2：Smoke

至少包括：

- 1 个 ≥180 秒 M4 时间线上的连续 60 秒 requests；
- 1 首完整 MIR 的多窗流程；
- 1 个非连续 slot；
- 1 组 density common-anchor/phase 检查；
- 1 条真实多窗 lineage；
- 1 个 missing gap 与 1 个 replace 双向评价；
- hidden extraction 等价检查；
- 英文不切词；
- 日文 unit 边界；
- demo 自动一致性与人工标签身份对齐。

### Phase 3：Pilot

用少量长歌曲覆盖全部实验家族，冻结代表条件、formal forward 数、hidden 层、unit/gap 模型和判别器特征候选。

### Phase 4：Formal manifests

```text
01_long_timeline_60s_legal_baseline
02_slot_position_topology
03_slot_density_common_units
04_slot_context_mask_invariance
05_sparse_and_percentage_text_errors
06_seam_half_second_control
07_leading_silence_weak_vocal
08_serial_mechanism_ablation
09_serial_system_routes
10_end_early_and_difficult_region
11_region_assessor_cross_domain
12_demo_automatic_and_human_review
```

### Formal 启动硬门槛

不得 formal，如果：

- 主数据仍以 <90 秒时间线为主；
- 主 acoustic request 被误改成 180 秒，而不是冻结 60 秒；
- 人工静音被用于凑够 180 秒；
- 非连续 slot mapping 或 density common-unit 比较未测试；
- 串行仍使用 GT 重置；
- missing 没有 gap candidate，replace 没有双向评价；
- hidden 抽取改变 raw/official 输出或映射不明；
- raw/official target 混用；
- matched legal baseline identity 不完整；
- demo 未自动利用或已有人工标签未审计；
- 英文仍可切断单词；
- 日文 unit 未审计；
- 缓存身份不完整；
- 预计 formal 超过 10 小时且尚未缩减；
- 计划仍包含明显笛卡尔积。

## 14. Agent 输出与文档边界

agent 至少输出：

```text
PRECHECK.json
LONG_TIMELINE_MANIFEST.jsonl
WINDOW_PLAN.jsonl
SEAM_CONTROL_MANIFEST.jsonl
HUMAN_REVIEW_AUDIT.json
HIDDEN_EXTRACTION_AUDIT.json
RUN_MANIFEST.json
RUNTIME_BUDGET.json
CACHE_AUDIT.json
FAILURES.jsonl
AUTO_TABLES.csv
AUTO_SUMMARY.json
AUTO_FINDINGS_DRAFT.md
```

`AUTO_FINDINGS_DRAFT.md` 只是自动观察，不是最终结论。运行完成后，将工作目录或 compact evidence 包交回 ChatGPT，由 ChatGPT 审查实现公平性、核对原始结果、修正正式文档、记录 negative results，并形成下一阶段决定。
