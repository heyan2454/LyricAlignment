# Evaluation v1：无训练阶段计划

## 目标

在不更新模型权重的前提下，用固定旧模型回答：当前各 Lyric Align 推理机制分别解决什么问题、在哪些输入上有效、会引入什么副作用，以及哪些组合可以删除。

## 暴露层级

| Tier | 比例 | 允许行为 | 解释 |
|---|---:|---|---|
| `diagnostic_visible` | 20% | 看音频、逐条结果、可视化和 failure ID；允许据此改机制 | 工作/诊断集，不训练权重 |
| `regression_selection` | 50% | 批量运行、比较汇总、选择配置；应限制逐条人工窥视 | selection/validation，不称 final test |
| `sealed_final` | 30% | 仅里程碑运行；平时 runner 默认拒绝 | 唯一承担最终无偏结论的集合 |

## 切分约束

- 按歌曲或歌曲根分组，禁止片段级随机泄漏；
- 相同歌手、相同歌曲的 Control/Technique/Paired Speech 尽量同组；
- PJS 同编号 song/speech/原标签/人工标签必须同组；
- MIR-MLPop 必须保留官方 Train/Test 边界；
- deterministic assignment 必须记录算法、seed、源 revision 和 manifest SHA-256；
- split 前先确定分层字段，不能看完模型结果后重新分配；
- sealed 原始文件可以存在，但常规 runner 必须要求显式 `--allow-sealed`，并把每次开启写入 run record。

## 当前建议数量

| Dataset | Diagnostic | Regression | Sealed | 备注 |
|---|---:|---:|---:|---|
| MIR-MLPop cmn（20） | 4 | 10 | 6 | 前 14 只取官方 Train 可用项；6 个官方 Test 可用项全部 sealed |
| Jamendo English（20） | 4 | 10 | 6 | 按歌曲及 hard-case tags 分层；operational 前先统一做人声派生 |
| PJS（100 song IDs） | 20 | 50 | 30 | song/speech/所有标签绑定 |
| GTSinger（5 song roots） | 1 | 2 | 2 | 不按 231 fragments 随机切；逐歌曲报告 |
| MIR-MLPop yue（3） | 1 | 1 | 1 | 仅 exploratory probe，不给强总体结论 |

上述分配尚未实际生成。AMLL 和 iKala 不进入此评分表。

## 机制研究结构

不要枚举全部模式组合。建立 behavior registry，将机制归入：

1. 输入与文本规范化；
2. 窗口、上下文与候选生成；
3. anchor/slot/候选选择与冲突消解；
4. silence、短句、漏字、漂移和 recovery；
5. 单调性、最小时长、边界平滑等后处理。

每个行为至少记录：

- `behavior_id` 和完整配置；
- 目标 failure class；
- 触发条件与所需信号；
- 理论上为什么可能有效；
- 可能伤害的样本；
- diagnostic/regression 证据；
- 延迟与复杂度成本；
- 保留、限制触发、降级 fallback 或删除的决定。

## 实验阶梯

### Stage 0：冻结 baseline

- 固定旧模型 revision；
- 固定代码 commit/config hash；
- 固定 vocal source 和 input manifest；
- 记录当前默认模式及运行时间。

### Stage 1：单因素消融

- 每次相对 baseline 只改变一个机制；
- 先跑 diagnostic；
- 没有明确目标故障收益、出现严重回退或只增加复杂度的行为直接淘汰。

### Stage 2：有限交互

- 只对 Stage 1 胜出机制做少量两两交互；
- 不做完整笛卡尔积；
- 检查收益是互补、重复还是相互破坏。

### Stage 3：regression selection

- 在 50% selection 上比较固定候选；
- 关注 macro-by-dataset 与 catastrophic regressions，而不是只看 pooled mean；
- 形成一个默认配置和极少量按 failure class 触发的 fallback。

### Stage 4：sealed milestone

- 只对已经冻结的里程碑配置运行；
- 不根据 sealed 逐条结果立即调参；若据此改动，必须发布新版本并建立新的最终评测边界。

## 指标与报告

- onset/offset absolute error：median、P90；
- within 100/200/500 ms；
- catastrophic failure rate（例如整行或连续区间超过 1 秒）；
- 漏字、重复、跨行、长间奏、短词、拖音、重叠人声等 failure buckets；
- 每数据集和每语言单独报告；
- word/character/phoneme 粒度不直接混成一个总分；
- inference time、forward 数、fallback 触发率和失败恢复成本；
- paired improvement/regression count，并保留可审计的 config/input/output identity。

## 最近的可执行顺序

1. 生成但不运行 `evaluation_v1` grouped split manifest；
2. 人工审阅分层与泄漏报告，冻结 manifest hash；
3. 为 raw mixture 建立统一 vocal derivation 和 provenance；
4. 冻结旧模型 B0 baseline；
5. 只在 diagnostic 运行首轮基线和 error taxonomy；
6. 开始机制单因素消融；
7. 通过 diagnostic 后再进入 regression；
8. sealed 保持关闭，直到明确里程碑。

## 当前状态

本文件是本轮讨论形成的下一步设计，不是已执行实验。没有生成 split，没有运行新 baseline，没有打开 sealed，也没有训练新模型。
