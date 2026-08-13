# 下一轮实验设计：Local Realign Requests + Realign Gate Signals + Real Test Demo

## 1. 核心研究问题

本轮只回答三个问题：

1. **什么样的局部 realign request 真正有修复价值，同时尽量不破坏原本正确内容？**
2. **在没有 GT 的线上条件下，realign 前后哪些行为信号能够判断 candidate 是 improve / neutral / harm？**
3. **上述 detector / realign 行为在真实 Test Demo 上是否也呈现类似结构？**

本轮不做 stateful closed-loop writeback，不做大规模模型训练，不做笛卡尔积。

---

# P0 — Detector baseline 补完：只补有意义的 GT-conditioned / interval 指标

## 原因

当前 P0 已证明 production unit output ratio 约 85% ACCEPT，且旧 15.5% 是人口错误。97.5% whole-window unsafe 主要来自 `any reject` 聚合，研究价值有限。

但当前 85% 仍只是 output ratio，不是 detector accuracy。

## 目的

补齐 detector 在 production population 上真正的 GT 行为，并生成后续 realign region sampling 的唯一 source-of-truth。

## 设计

复用现有 13-song / 40-window baseline evidence，不重新 GPU 推理，除非发现 evidence 缺失。

在 canonical GT 上计算：

- GT <=100/200/500ms 与 >1s；
- detector ACCEPT / UNCERTAIN / REJECT；
- correct→ACCEPT、correct→UNCERTAIN/REJECT；
- bad→UNCERTAIN/REJECT、bad→ACCEPT；
- protected recall / false reject / false accept；
- interval-level recall、precision、coverage、unsafe length distribution；
- per-song 分布。

whole-window `any reject` 只作为附属统计，不进入主要决策。

## 预期结果

可能结果 A：unit/interval detector 仍有较高正确内容放行率，同时能覆盖多数 catastrophic region。

可说明：detector 可以继续作为 local realign proposal trigger，但不能整窗触发。

可能结果 B：大量 GT-correct region 被高置信 REJECT。

可说明：后续必须把 S2 作为主要 safety stress，detector 本身还需要继续研究。

---

# P1 — 重建 interval / unit-region case population

## 原因

whole-window strata 把大量真实 hard negatives 排除，造成 S2=2 的假性样本不足。

## 目的

得到足够、跨歌、与 detector 实际接口一致的局部 realign case。

## Region 构造

从 production baseline detector output 自动生成：

- 每个连续 UNCERTAIN/REJECT span 作为 seed；
- 可按 unit index 合并相距极近的 seed；
- target region 推荐 1--8 units；极长 span 可切成多个局部 region；
- 保存 target units、左右 ACCEPT anchor candidates、原 window context、音频时间范围；
- 不允许跨歌/case canonical id 污染。

增加正确 control region：从 ACCEPT 连续区按匹配长度/位置采样，与 unsafe region 做长度和歌曲分层匹配。

## GT strata

- S1: correct ACCEPT control region；
- S2: correct UNCERTAIN/REJECT region；
- S3: bad UNCERTAIN/REJECT region；
- S4: bad ACCEPT region；
- SG: 200--1000ms moderate/grey GT，仅探索，不混入主二元 safety/recovery 指标。

## 样本规模

本轮控制昂贵 realign 总规模，不追求几百个 region：

- 目标主 pool：约 48--72 个 regions；
- hard cap：80；
- 优先保证 S2 >=20、S3 >=20；
- S1 约 10--16；
- S4 按自然数量；
- 尽量覆盖 >=8 首歌；单歌设置合理 cap，不能由 1--2 首歌主导。

如果 S2/S3 未达到目标，不允许直接停止：执行 `EXHAUSTION / RESAMPLING` 流程，自动扩大 eligible region，直到达到目标或穷尽全部数据并给出证据。

## 预期结果

若 S2 可以轻易达到 >=20：说明此前“hard negative 不足”完全是 strata 实现问题。

若穷尽全部 region 后仍不足：才可说明 production 数据中此类错误确实稀少，并报告真实上限。

---

# P2 — Realign Request Family 实验

## 原因

当前 R-B 是 no-op；当前 request 仍偏 window/粗 region。用户希望研究更接近 unit 级的 realign 请求。

## 原则

避免笛卡尔积。默认只保留 3 个机制明确的 request family，每个 case 至多 3 个 active candidates。

每个 candidate 必须通过 `EFFECTIVE_INTERVENTION_CHECK`：至少一项 forward-affecting 输入相对 original 发生有效变化；否则只能标为 null control，不进入 R-A/R-B/R-U 正式比较。

## R-U：unit-local / minimal request（新增主线）

目标：尽量只重新解释 detector 指向的 1--N 个 unit。

建议构造：

- text：target units + 左右各 1--2 个可信 anchor units；
- audio：围绕 target 当前预测时间或 anchor-bound interval，加固定小 margin；
- 若 target timestamp 本身极不可信，优先由两侧 safe anchors 定义 audio bounds；
- 不允许把整首/整窗 text 全部送入。

记录 request span 相对于 baseline 的 text/audio 缩减比例。

## R-A：unsafe-interval narrow request

以完整 detector unsafe interval 为 target，比 R-U 稍宽：

- text：unsafe span + 少量相邻 safe units；
- audio：unsafe interval 当前时间范围 + 小 context，或由最近有效 anchors 夹定；
- 必须实际小于 production full-window request。

## R-B：genuine safe-anchor bounded request

必须真实寻找左右 ACCEPT anchors：

- left_anchor 和 right_anchor 都不能为空；
- anchors 必须位于同一 source production window/局部 context；
- text/audio request 由两侧 anchors 真正限制；
- request forward identity 必须区别于 original；
- 如果当前 seed 无法构造两个 anchor，不能退化成 full-window/no-op R-B；应扩大 anchor search radius，在预设上限仍失败后从 case pool 补抽另一个可构造 region。

可额外保存 no-op re-run 作为 determinism control，但必须命名为 `R-NULL`，不能计入 R-B。

## 公平性

同一 case 的 R-U/R-A/R-B：

- 同 model/checkpoint/decoder；
- 同 source baseline；
- 同 target units；
- 只改变 request construction；
- 使用同一 cache identity 规则；
- candidate 评估始终相对于同一个 original。

## GT 评估

主指标必须是 100/200/500ms 和 >1s：

- target-unit paired error before/after；
- improve/harm >=200ms；
- correct<=200ms -> >500ms / >1s；
- coverage / missing / extra；
- context/safe-unit collateral damage；
- candidate-level sum/median/max delta；
- target improvement 与 outside-target harm 分开。

不再用 <=1s / <=5s 作为“repair success”。

## 预期结果与可解释结论

A. R-U harm 最低、recovery 仍存在：支持更细粒度 realign 作为主生产 request。

B. R-B 在有真实 anchors 时显著稳定：支持 anchor-bounded recovery，但此前 null R-B 结论作废。

C. R-A/R-U/R-B 都高度不稳定：说明问题不只在 request 构造，gate/aligner behavior 仍是主瓶颈。

D. 某 family 只对 catastrophic S3 有益、对 S2 危险：支持 detector-state/GT-like-risk 条件下的分层 retry，而不是通用 writeback。

---

# P3 — Realign Gate Signal Exploration

## 原因

`n_big` 更像改动幅度，不足以判断改动方向。当前还没有可靠 no-GT writeback gate。

## 数据与分析单位

独立样本严格是 `(song_id, region_case_id, request_family)` candidate，不允许把同 candidate 的 feature 复制到 unit rows 后当独立样本计算 AUROC。

GT outcome 只存在独立 label 表；no-GT feature 表禁止包含任何 GT/error-derived 字段。

song-level dev/holdout split；样本较小时同时报告 bootstrap CI / candidate count，不用单个 AUROC 包装确定性。

## 第一组：改动局部性 / collateral damage

优先研究：

- changed target unit count / ratio；
- changed safe-context unit count；
- `sum_abs_timestamp_change_inside_target`；
- `sum_abs_timestamp_change_outside_target`；
- `outside / inside change ratio`；
- 最大 safe-anchor displacement；
- request 外 unit 是否被改变；
- target-locality score。

假设：好 realign 应主要改变 detector 指向区域，且保护稳定 context。

## 第二组：before/after detector evidence 的“方向”而非单纯幅度

- target p_bad mean/max before→after；
- safe-context p_bad before→after；
- target risk improvement 与 safe-context risk degradation 的差值；
- ACCEPT/UNCERTAIN/REJECT transition matrix；
- entropy / margin / top-k span 的 target-vs-context delta；
- raw detector 与 official/shadow detector 的 before/after agreement（若现成输出低成本可得）。

假设：有效修复应减少 target ambiguity，而不是通过扰乱整个 context 获得漂亮分数。

## 第三组：多 request family consensus

同一 case 有 R-U/R-A/R-B 后可计算：

- target timestamp pairwise median difference；
- unit order agreement；
- candidate coverage agreement；
- request family consensus ratio；
- 是否多个独立局部请求收敛到近似相同位置。

假设：多个不同 request construction 收敛到相同 alignment 时可信度更高；结果随 request 剧烈变化时应拒绝写回。

## 第四组：结构稳定性

- inversion count；
- pile-up / zero-duration；
- local compression/expansion；
- local time-warp slope；
- duration ratio异常；
- large jump count；
- anchor crossing；
- missing/extra transitions。

## 第五组：self-consistency / fixed-point（只对少数 ambiguous case）

对 gate 最不确定或多个 request family 冲突的 top 8--12 candidates，允许额外做一次 second realign：

`candidate -> same/similar local request -> candidate2`

记录 A→B displacement；稳定 fixed point 可作为候选信号。

该 probe 不能全量跑。

## 第六组：继续探索要求

如果上述预定义信号都弱，agent **不能直接写“没有好信号”停止**。在不使用 GT 作为 feature 的前提下，允许继续机器上探索已有 evidence 中可合理导出的 signal，例如：

- hidden/posterior stability；
- raw/official disagreement；
- boundary sensitivity；
- request-size sensitivity；
- per-unit risk gradient；
- anchor confidence/anchor asymmetry；
- candidate pair ranking feature。

探索流程：

1. 先看分布、Spearman/AUROC/AUPRC、counterexample；
2. 找机制明确的 single signal；
3. 尝试最多 2--3 个简单组合规则；
4. 若独立 candidate 数足够，可补一个轻量 logistic/tree diagnostic，但必须 song holdout、报告参数与 overfit 风险；
5. 每发现一个“漂亮”信号，必须检查它是否只是 intervention/no-op、歌曲身份、request size 等 shortcut。

`n_big` 保留为 baseline signal，不得优先假定它有效。

## Gate 的主要目标

优先优化：

1. catastrophic harmful writeback rate；
2. harmful writeback precision/risk；
3. good-repair precision；
4. repair capture；
5. coverage。

输出 risk-coverage / harm-vs-repair capture 曲线，而不是只给单一 AUROC。

## 可支持结论

- 若存在跨歌稳定信号，且低 harmful risk 下仍保留一定 repair capture：支持进入下一轮 gate validation。
- 若只有 request-consensus/locality 在 subset 有效：支持条件式 gate，不支持全局 gate。
- 若所有 no-GT signal 都无法区分 improve/harm：应明确结论为“当前 observable evidence 不足”，并指出最可能缺少的模型内部信息，但这个结论必须建立在完成上述主动探索之后。

---

# P4 — Test Demo：真实模型、真实 detector、真实 realign

## 原因

当前虽然发现 36 个 Demo item，但 `04_test_demo` 使用 mock adapter，用户没有看到真实 Test Demo 行为。

## 目的

检验 production-style detector 与 realign behavior 在真实多语言 demo 中是否出现类似现象，并产生可直接检查的案例。

## Detector 全量

动态发现当前所有 Test Demo，当前 evidence 为约 36 个：中文 17、粤语 6、英文 6、日文 6、其他 1；运行时必须重新 discovery，不写死 36。

对所有可运行 Demo production windows 使用：

- 真实 frozen Raw detector；
- 与 P0 同 identity/threshold；
- 真实 parser/alignment evidence；
- 禁止 mock adapter。

输出：

- per-language / per-song ACCEPT/UNCERTAIN/REJECT；
- unsafe intervals 数量、长度分布；
- longest unsafe run；
- raw/official disagreement（若可低成本获得）；
- suspicious region ranking。

Test Demo 无 GT，不计算 accuracy/protected recall。

## Realign stress subset

从真实 detector region 自动选约 12--20 个 region：

- 跨语言；
- 高 risk；
- 中等/grey risk；
- 重复歌词/静音附近/长持续音等不同结构；
- 同一首不占过多。

至少运行 R-U + genuine R-B；如成本允许再加 R-A。必须真实 GPU/真实 cache，不允许 mock。

输出每个案例：

- original / candidate timestamp table；
- no-GT gate features；
- request family consensus；
- detector before/after；
- 结构异常；
- 自动排名 top counterexamples / stable candidates。

如现有 visualization pipeline 可低成本复用，自动渲染 top 6--10 个 case 的对比图/视频索引；不要求人工全量看 Demo。

## 可说明结论

Test Demo 只能说明：

- detector/realign/gate 的 no-GT production behavior；
- 跨语言稳定性与异常模式；
- 哪些案例值得人工听看。

不能说明 GT accuracy 或 recovery rate。

---

# P5 — 样本与失败恢复硬要求

## 不允许“样本不够所以不做”

agent 必须维护 `SAMPLE_ACCOUNTING.json/md`：

- eligible songs/windows/regions；
- 每个 stratum 数；
- 每 request family 可构造数；
- 失败原因；
- GPU 成功/cache-hit/failure；
- Test Demo 各语言数。

若任一关键样本低于最低目标：

1. 自动扫描剩余 eligible regions；
2. 调整 region 粒度而非改变 GT 标签；
3. 扩大同歌 region 数但保持 cap；
4. 对 genuine R-B 扩大 anchor search radius 到预定义最大值；
5. 重抽 case；
6. 复用 cache，补跑缺失 candidate；
7. 最后才允许 `EXHAUSTED`，并列出所有过滤原因。

不得因为第一次 manifest 只有 2 个 S2 或 R-B anchor null 就继续后续 gate 并把缺口当事实。

## 失败恢复

所有 stage 必须：

- `--resume`；
- request/candidate content-addressed cache；
- failure jsonl；
- partial result 不覆盖正式 result；
- effective intervention fail-fast；
- mock adapter formal fail-fast；
- candidate key uniqueness assertion。

---

# P6 — 资源预算与停止规则

这是小规模机制实验，不做 12h 大 formal。

建议：

- P0/P1 CPU/cache 优先；
- GT realign regions 48--72，hard cap 80；
- 每 region 默认 3 request families，若 GPU 预算偏高可在 smoke 后淘汰明显无效的一种，但必须先保证 genuine R-A/R-B 对照；
- Test Demo realign 12--20 regions；
- fixed-point probe 8--12 candidates；
- 优先 cache；
- GPU soft budget 4--6h，hard stop 8h。

到达预算时优先保留：

1. S2/S3 genuine R-A/R-B；
2. R-U；
3. Test Demo real detector + 小量 realign；
4. fixed-point probe 最后缩减。

不能为了数量做 proposal 笛卡尔积。

---

# P7 — 最终报告必须回答的问题

## Detector

- production unit/interval detector 的 GT-conditioned 表现是什么？
- correct region 的 false reject 有多少？
- bad/catastrophic region 捕获多少？
- whole-window 97.5% 仅作为契约附属指标，不作为主要结论。

## Realign requests

- R-U / R-A / genuine R-B 各自实际构造成功多少？
- 真实 R-B 的 anchors 是否存在，forward request 是否真正变化？
- 三者在 S2 与 S3 的 improve/harm/catastrophic harm 如何？
- 哪种 request 最能保护 safe context？

## Gate

- n_big 是否仍然只有 change-magnitude 作用？
- locality、safe-context protection、detector delta、consensus、structure、self-consistency 中哪个最有用？
- 在 song holdout 上最低 harmful risk 下能保留多少 repair？
- 如果没有好 gate，agent 实际探索过哪些信号、为什么失败？

## Test Demo

- 实际发现多少文件/歌曲？
- 是否全部使用真实 detector？
- 实际 realign 了多少 region，覆盖哪些语言？
- 哪些 no-GT 行为与 GT 数据一致/冲突？
- 输出可检查的 top cases。

## 样本完整性

- 是否达到 S2/S3 最小样本？
- 若没有，是否确实穷尽数据？
- 不允许用“初始采样不足”代替上述回答。
