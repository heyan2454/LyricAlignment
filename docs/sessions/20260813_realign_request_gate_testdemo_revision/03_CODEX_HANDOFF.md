# Codex Handoff：请先拟定具体实现方案，再交给 OpenCode/agent

## 1. 任务边界

请将本 session 合并到当前仓库后，先 review 当前 `realign_gate` 实现与最近 run artifact，再给出**具体实现方案**。本次不要直接扩大 formal run，也不要照抄上一轮 `04_OPENCODE_IMPLEMENTATION_PLAN.md`；需要针对本次 review 新发现的问题修订实现。

实现方案完成后，用户会把方案交给 OpenCode/agent 执行。

## 2. 必须吸收的 review 事实

1. P0 production population 基本正确：13 songs / 40 windows / 4093 units / ACCEPT 85.07%。旧 15.5% 是 E5 proposal contamination。
2. 97.5% whole-window unsafe 是 `any reject -> unsafe` 聚合结果，后续不要把优化该数字作为重点；realign trigger 应转向 interval/unit region。
3. 当前 S2=2 是 whole-window strata 设计造成的假性样本不足。已有数据中存在大量 `GT<=200ms + detector UNCERTAIN/REJECT` units/regions。
4. 当前 R-B 是 23/23 null/no-op：无左右 anchor、request 与 baseline 相同、GT delta 全 0。必须真实重构 R-B。
5. `n_big` 不能被冻结为 gate；当前漂亮 AUROC 被 no-op R-B / pseudo-replication 影响。
6. GT `delta_error_ms` 禁止进入 no-GT gate feature 或 recommendation。
7. Test Demo 当前只有 dynamic discovery 有效，model behavior 是 mock；下一轮必须真实运行。
8. “样本不足/无法构造”必须触发主动补样本与重构，而不是直接继续或停止。

## 3. Codex 实现方案必须明确回答

### 3.1 Region-level sampling 怎么实现

请定位现有 detector unit/interval 数据结构与 canonical GT binding，说明：

- 如何从 production baseline 生成 contiguous unsafe regions；
- 如何生成匹配的 ACCEPT control regions；
- 如何得到 S1/S2/S3/S4/grey；
- 具体 manifest schema；
- 如何保证 song/case/cid identity 不污染；
- 如何自适应补样本直到达到 S2/S3 最小目标或穷尽数据。

### 3.2 三种 request family 怎么真正构造

至少给出：

- R-U unit-local；
- R-A unsafe-interval narrow；
- genuine R-B safe-anchor bounded。

必须写清：

- text units 如何选择；
- audio range 如何选择；
- safe anchors 如何搜索；
- anchor search radius 与 fallback；
- 什么条件算 `effective_intervention=true`；
- R-B anchor null 时怎样重抽/扩搜，禁止 fallback 成 baseline；
- 如何把 no-op 单独标为 R-NULL；
- request identity/cache key 如何保证公平且可恢复。

### 3.3 R-A/R-B 公平比较怎么实现

同一 case 必须共享 original / target ids / model / decoder，并有 R-A/R-B 双 candidate。缺任一正式 variant 时该 case 不能进入 R-A vs R-B 主比较。

实现方案要说明：

- pairing key；
- effective intervention assertion；
- variant completeness gate；
- GT metrics；
- context collateral damage。

### 3.4 Gate feature 怎么重构

请彻底移除任何依赖 GT delta 的 recommendation 逻辑。

candidate-level no-GT feature 至少规划：

- locality / outside-target change；
- safe-context / anchor corruption；
- detector before/after target-vs-context delta；
- entropy/margin 等 confidence delta；
- R-U/R-A/R-B consensus；
- structural anomaly；
- coverage/missing/extra；
- n_big baseline；
- ambiguous-case second-pass stability。

说明每个 feature 的输入来源、聚合级别、缺失处理和是否需要额外 GPU。

分析的独立样本必须是 candidate，不是 unit row；song holdout。

如果预定义信号弱，请设计一个受控的 free exploration 环节，使 agent 能继续寻找 no-GT signal，但必须有 leakage/shortcut 检查和预算上限。

### 3.5 Test Demo 真跑怎么实现

请定位当前动态 Demo discovery、parser、真实 model inference 与 detector adapter。

必须：

- formal run 禁止 mock；
- 全量动态发现 Demo 做真实 detector summary；
- 小规模跨语言 region 做真实 R-U/R-B（必要时 R-A）；
- 输出 per-language/per-item summary；
- 输出 top suspicious/stable/counterexample cases；
- 如现有 visualization 可复用，给出自动渲染 top case 的方案。

不要给 Test Demo 加 GT accuracy。

### 3.6 样本不足自动修正

实现方案必须有具体算法，而不是一句“若不足则扩样本”。

至少定义：

- 最小 S2/S3 region 数；
- 初始 song cap；
- 扩展顺序；
- anchor 重搜顺序；
- 同歌追加顺序；
- 全量 exhaustion audit；
- 达不到目标时的 fail/degraded 条件。

Agent 应当有权限在这些规则内主动选择补样本策略，不需要每次询问用户。

## 4. 测试要求

Codex 方案必须列出新增/修改测试，至少覆盖：

- unsafe region extraction；
- S2 不依赖 whole-window 全正确；
- 200--1000ms grey 不静默丢失；
- genuine R-B 两 anchor 非空；
- R-B forward identity 与 baseline 不同；
- no-op 被标 R-NULL 而不是 R-B；
- 每 case R-A/R-B completeness；
- per-candidate feature isolation；
- no GT leakage；
- candidate-level analysis 不 pseudo-replicate；
- adaptive resampling / exhaustion；
- formal Test Demo mock fail-fast；
- dynamic multi-language Test Demo discovery；
- resume/cache/failure recovery。

## 5. 执行顺序建议

Codex 应将 OpenCode 实现与实验拆为以下 gated stages：

1. P0 metric supplement（CPU/offline）
2. P1 region population + adaptive sampler（CPU）
3. request construction smoke：至少验证 R-U/R-A/genuine R-B 都是 active intervention
4. 小 GPU smoke：2--4 regions × request families
5. 正式小规模 GT realign collect
6. candidate-level gate analysis + counterexample exploration
7. real Test Demo detector all + realign subset
8. final report

前一阶段 correctness 未通过，不允许后面用 degraded data 生成正式 recommendation。

## 6. 报告语义要求

最终实现方案和 agent 报告必须区分：

- detector output rate vs GT accuracy；
- unit/interval vs whole-window；
- active realign vs no-op control；
- target repair vs context harm；
- no-GT feature vs GT outcome；
- independent candidate count vs unit row count；
- Test Demo mechanism behavior vs GT correctness。

禁止再出现：

- `delta_error_ms AUROC=1 -> ACCEPT_WRITEBACK`；
- null R-B 被算作成功 intervention；
- mock Test Demo 被写为真实结果；
- `S2 only 2` 后直接继续；
- whole-window 97.5% 被当成 detector 主性能。

## 7. 交付给用户

Codex 完成 review 后，请输出一份可以直接交给 OpenCode 的具体实现方案，包含：

- 要改的文件/函数；
- 新增文件；
- manifest/schema；
- 关键伪代码或接口；
- tests；
- smoke 命令；
- formal 命令；
- resume/cache；
- GPU 预算；
- 每阶段 expected artifacts；
- fail-fast 条件；
- 完成判据。

不要在实现方案阶段重新做大实验。
