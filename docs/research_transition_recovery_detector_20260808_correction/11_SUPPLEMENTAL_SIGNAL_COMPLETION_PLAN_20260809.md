# LyricAlignment 补充实验：Transition / Recovery 纠正与 Detector 全信号补完

**日期：2026-08-09**  
**性质：correction + small diagnostic + signal completion**  
**执行要求：新 session 目录执行，不覆盖 2026-08-08 已有结果。**

建议新运行根：

```text
runs/research_transition_recovery_detector_20260809_signal_completion/
```

---

## 0. 本轮要解决的问题

当前 2026-08-08 结果已经提供了若干有价值的阶段性结论，但仍有两类问题没有闭环。

### 0.1 已有结果需要纠正

1. Transition serial reaggregate 丢失 row-level 信息，造成 `wrong_committed_250ms=0` 等不可能结果。
2. Markdown report 错读 `product_candidate` / `mechanism_candidate` 字段，错误显示 `None`。
3. `INTERVAL_METRICS.json` 缺少正式、可复现的生成入口。
4. closed-loop 中出现 `36/36 retry, 0 retry-derived writeback`，但没有拆解失败到底来自：
   - retry 本身没有改善；
   - retry 改善但 detector 不接受；
   - retry 改善且 detector 接受，但 route/writeback policy 阻止写回。

### 0.2 Detector 信号长期没有完整实现

本轮必须一次性补完：

- `R`：raw / local posterior geometry；
- `O`：official / repair；
- `RO`：raw↔official interaction；
- `V`：cross-window / cross-view consistency；
- `P`：posterior competing coherent path / occurrence ambiguity；
- `S`：per-unit sequence trajectory / change-point；
- `H`：hidden-state sequence；
- `PR`：propagation-risk target / detector。

**重要纠正：H / P / PR 等信号均为当前模型/实验框架支持的能力，过去缺失属于实现未完成，而不是 API 不支持。**

因此本轮：

> `blocked_api`、`not_executed`、`coverage=0` 不能作为 H/P/PR 的正常完成状态。

如实现出现 bug，应修复并继续。只有硬件/模型 forward 本身实际失败且有完整错误日志时才可记录 failure，但仍不得跳过其余信号后提前结束 session。

---

# 1. 总体目标与完成定义

本轮不是重新扩大 formal 数据规模，而是在现有冻结数据、缓存和小规模重新 forward 上完成以下闭环：

1. 修正 Transition aggregation / report。
2. 正式重建 interval-level detector metrics。
3. 对现有 closed-loop retry 做 failure decomposition。
4. 在同一冻结样本上比较 raw / official timing。
5. 完成 H/R/O/RO/V/P/S 的 evidence、coverage、feature、最小消融。
6. 完成 PR propagation-risk 标签与最小 detector。
7. 用同一 source-song split、同一标签、同一 learner 公平比较信号。
8. 生成新的 compact report 与 evidence pack。

只有以下条件全部满足，才可写：

```json
{
  "supplement_completed": true,
  "signal_completion": true
}
```

否则必须写 `false` 并明确缺项。

---

# 2. 不允许改变的冻结口径

## 2.1 Correctness 标签

保持当前 v2 主口径：

- `Safe`：边界误差 `<=100 ms`；
- `Grey`：`100–250 ms`；
- `Unsafe`：`>250 ms` 或明确错位/缺失/严重非法；
- Grey 不进入 Safe/Unsafe 二分类训练，评测时单列。

同时报告：

- 100 ms；
- 250 ms；
- 500 ms；
- 1000 ms。

GT 只用于 label / evaluation / diagnostic，**不得进入 detector feature**。

## 2.2 Split

所有同一 source song 的：

- window；
- mutation；
- overlap view；
- hidden/posterior evidence；
- propagation episode；

必须属于同一 split。

禁止 unit/window 随机拆分。

## 2.3 Learner

本轮主要目的为比较信号，不研究更多 classifier。

固定一个当前已经使用且可复现的 tabular learner 作为主 learner。若现有实现为 MLP，则继续使用冻结 MLP；同时允许 Logistic 作为 cheap sanity baseline。

不得为了某个信号单独调不同模型/超参。

## 2.4 计算预算

本轮为小规模补充：

- 优先复用现有 forward cache；
- H/P 需要新增 evidence 时，只在冻结 detector train / model-selection / threshold-validation 所需样本上重新 forward；
- 不重新跑完整 M4 formal；
- 不扩大 Transition 矩阵；
- 不做 classifier 笛卡尔积；
- 不搜索大量 threshold；
- 总预算仍不得超过 12h，预期应明显低于该上限。

---

# 3. 实验 A：Transition aggregation 与报告纠正

## A1. 修复 serial row-level aggregation

修复 `reaggregate_transition.py` 或对应聚合函数，使 serial 结果保留逐 unit / row-level correctness。

必须重新计算：

- target units；
- committed units；
- committed coverage；
- correct committed / all target；
- wrong committed / all target；
- 100/250/500/1000 ms correctness；
- final cursor coverage；
- 每首歌曲相同指标。

必须加入 invariant：

```text
committed = correct_committed + wrong_committed + grey_committed
```

并检查：

```text
T1/T2 committed coverage ≈100% 时，
wrong_committed_250ms 不可能在 unsafe units >0 的情况下为 0。
```

## A2. 修复 candidate report 字段

统一：

- `product_candidate`
- `mechanism_candidate`

JSON 与 Markdown 只能从同一 authoritative artifact 读取，不允许两个 report 自己重新选择。

## A3. song-level paired comparison

对 T1 / T2 / full-song 生成：

- 每首 100/250/500/1000 ms；
- T2−T1；
- serial−full-song；
- win/tie/loss song count；
- song-level mean / median；
- 按 source song bootstrap 的 95% CI。

重点回答：

> T2 是否真的优于 T1，还是只是 pooled nominal best？

### 预期解释

若 T2−T1 CI 大量跨 0：

> 正式结论应为 T1/T2 当前不可区分，T2 仅为 nominal product candidate。

不得把约 0.5 pp 的 pooled 差异写成明确机制优势。

---

# 4. 实验 B：raw vs official timing 的同数据对照

当前 Transition 主评测更接近 raw timing，而 Test Demo 的观感可能更接近 official decoder 后时间轴。

在**完全相同 request / unit / split**上，对：

- raw；
- official；

分别重新计算：

- <=100 ms；
- <=250 ms；
- <=500 ms；
- <=1000 ms；
- MAE / median absolute error；
- invalid / zero-duration / inversion（如适用）。

同时给：

- pooled unit；
- per-song；
- raw vs official paired delta。

不得重新改变窗口、query、slot、Transition，只改变被评估的 timing view。

### 目的

解释：

> 为什么 250 ms correct coverage 约 40%，但很多 Demo 仍有“基本可正常跟随”的观感？

### 可能结果

1. **official 明显优于 raw**  
   说明 Demo 与主指标差异部分来自 decoder/评估对象不同。

2. **official 与 raw 接近，但 500 ms / 1 s 大幅更高**  
   说明主要是 250 ms 本身严格，而非 decoder 差异。

两种结果都必须如实报告。

---

# 5. 实验 C：正式重建 interval-level detector evaluation

不得继续直接消费来源不清的旧 `INTERVAL_METRICS.json`。

新增正式生成入口，例如：

```text
scripts/research_transition_recovery_detector/evaluate_interval_metrics_v2.py
```

输入必须显式记录：

- prediction artifact；
- threshold artifact；
- target（raw / official）；
- source-song split；
- Safe/Grey/Unsafe 定义；
- intervalization rule hash。

输出：

```text
06_detector/INTERVAL_METRICS_REPRODUCIBLE.json
```

## C1. 三个既定错误捕捉口径

同时报告：

1. interval 内错误 unit **100% 被捕捉**；
2. interval 内错误 unit **>=75% 被捕捉**；
3. unit-level unsafe recall。

其中必须分别报告：

- REJECT-only；
- REJECT + UNCERTAIN protected；

不能混淆。

## C2. 正确区域代价

报告：

- safe accept；
- safe reject；
- safe uncertain；
- safe interval 被切碎比例；
- predicted accept/reject/uncertain interval 数；
- 平均/中位 interval 长度；
- longest unsafe ACCEPT run。

## C3. 工作点

正式生成：

- SA60；
- SA80；
- R95；
- SA60+R95 joint feasibility。

严格定义：

- `SA60/80`：Safe accept 约束；
- `R95`：Unsafe **REJECT-only** recall >=95%；
- UNCERTAIN 不算 REJECT。

旧报告中实际表示 non-accept 的字段不得继续叫 `unsafe_reject_rate`。

---

# 6. 实验 D：Detector 全信号 evidence 补完

本节是本轮硬性重点。

---

## D0. Evidence 一次 forward 复用原则

H / R / P 等来自同一模型 forward 的信号必须**一次 forward 同时保存**，禁止为了每个 ablation 重跑模型。

对于每个成功 request，至少保存：

```text
rows
raw timing
official timing
full timestamp-slot logits 或可无损/明确精度地重建所需 posterior 的压缩表示
hidden states（指定层、仅 timestamp slot）
request identity
view/window identity
canonical mapping
decoder/processor/model identity
schema version
```

cache key 必须包含 evidence schema / hidden config / posterior config。

---

## D1. R：Raw / local posterior geometry

保留并统一当前已有信号：

- raw start/end；
- duration；
- gap / overlap；
- zero-duration / compression；
- entropy；
- top1 probability；
- top1-top2 margin；
- top-k span / variance；
- local timing velocity / acceleration；
- 一阶/二阶局部差分。

要求：重新生成 coverage audit，确认 R 与所有成功 forward unit 对齐。

---

## D2. O：Official / repair

至少包含：

- official start/end/duration；
- official gap/overlap/compression；
- raw→official start shift；
- raw→official end shift；
- repair magnitude；
- local repair run length；
- local repaired-unit ratio；
- official timing 一阶/二阶变化。

---

## D3. RO：Raw–Official interaction

RO 不是简单把 R 与 O 拼起来后改名。

必须显式加入交互特征：

- raw confidence 高但 official shift 大；
- raw entropy 高但 official 几何变平滑；
- raw/official onset disagreement；
- raw/official offset disagreement；
- duration change；
- repair direction consistency；
- 连续 repair cluster；
- raw/official local ordering disagreement。

单独生成 `RO_SIGNAL_ATLAS.json`。

---

## D4. V：Cross-window / cross-view consistency

只在同一 canonical unit 的 matched overlapping views 上计算。

至少：

- raw onset displacement；
- raw offset displacement；
- official onset/offset displacement；
- top1 class change；
- posterior JS/L2 或等价距离；
- top-k overlap；
- occurrence/time-mode jump；
- context/window 改变后的连续 displacement run。

分母必须是：

```text
eligible canonical units covered by >=2 valid views
```

不得用全数据分母稀释 coverage。

### V 验收

对于 eligible units：

- coverage 目标 >=95%；
- 若不足，必须列出缺失原因与 exact denominator；
- 不允许再次只写“cross-view planned”。

---

## D5. P：Posterior competing coherent path

**本信号已由当前 forward logits 支持，本轮必须实际实现。**

当前 serial inference 已能拿到 timestamp-slot logits 并计算完整 softmax；过去只保存 top-k 导致后续无法完成 P，不再接受这种截断。

### P 的固定定义

对一个 request 的 timestamp boundary posterior，寻找：

1. best coherent monotonic path；
2. second-best coherent monotonic path。

只实现一种冻结算法，不做算法网格。

推荐采用 k-best dynamic programming / beam DP，并遵守与时间边界一致的单调约束。

保存每个 request / unit neighborhood 的：

- best path score；
- second path score；
- normalized score gap；
- 两条 path 的时间距离；
- fraction of differing boundary slots；
- longest contiguous alternative run；
- second path continuity；
- alternate path 是否形成近似一致的整体平移；
- local path ambiguity；
- repeated-occurrence-like mode separation。

P 的目的不是重复 entropy：

> entropy 回答单个 boundary 是否犹豫；P 回答是否存在另一条**连续、整体自洽**的时间路径。

### P 验收

对所有成功 forward：

```text
n_P_rows == n_R_rows
```

或仅允许由明确 sequence-length 条件造成、且记录 denominator 的极少缺失。

不得出现 `P coverage = 0`。

---

## D6. S：Per-unit sequence trajectory

输入为连续 canonical units 的时序信号，不使用未来 GT。

至少包括：

- entropy trend；
- margin trend；
- timing velocity；
- timing acceleration；
- compression run；
- overlap/gap run；
- raw→official repair cluster；
- posterior mode switch；
- local change-point；
- abrupt occurrence/time jump；
- sequence rolling statistics。

S 应输出 per-unit feature，不是“整窗有一个 bad 就广播到全部 unit”。

---

## D7. H：Hidden-state sequence

**H 已知为模型支持能力，本轮必须实际接入，不得再把全零 placeholder 当实现。**

### H1. 提取

固定只保存两个层，避免数据过大：

- last layer：`-1`；
- earlier/high-level layer：建议 `-4`。

仅保存 timestamp token positions，不保存所有文本 token 的完整 hidden。

对每个 canonical unit：

- start boundary hidden；
- end boundary hidden；
- layer id；
- hidden dimension；
- canonical mapping；
- schema/hash。

建议落盘 float16；统计计算使用 float32。

### H2. 数值等价 audit

同一 deterministic request：

- hidden off；
- hidden on；

比较：

- logits；
- raw timing；
- official timing；
- row count；
- canonical mapping。

要求 alignment 输出保持等价；记录 max absolute logit difference。

### H3. H 特征

至少：

- start norm；
- end norm；
- start-end cosine；
- start-end L2；
- adjacent hidden cosine；
- adjacent hidden L2；
- layer-to-layer cosine/L2；
- first difference；
- second difference；
- local change-point score。

另保留一个 **direct hidden linear probe**：

- 输入可为 start/end concat 或固定压缩；
- 训练 split 内做标准化 / PCA（如需要）；
- 不允许用 test fit PCA。

### H 验收

对于所有成功 forward：

```text
hidden_available_rate ~= 100%
```

且：

```text
n_H_rows == n_R_rows
```

除了真实 forward failure 外，不允许 `blocked_api`。

---

## D8. Signal coverage audit

新增：

```text
06_detector/SIGNAL_COVERAGE_AUDIT.json
```

至少包含：

| Signal | Denominator | Covered | Coverage | Missing reason |
|---|---:|---:|---:|---|
| R | successful unit rows | | | |
| O | successful unit rows | | | |
| RO | successful unit rows | | | |
| H | successful unit rows | | | |
| P | successful unit rows | | | |
| S | eligible sequential rows | | | |
| V | eligible multi-view rows | | | |
| PR | valid propagation episodes | | | |

**不能只证明 schema 存在，必须证明实际 evidence 非零且被 feature extractor 消费。**

---

# 7. 实验 E：最小信号消融

避免笛卡尔积，但必须能够回答每类新信号是否有独立价值。

---

## E1. 单信号/基础组

同一 split / learner / threshold protocol 上至少跑：

1. `H`
2. `R`
3. `O`
4. `RO`
5. `V`
6. `P`
7. `S`

目的：判断每类信号单独是否有 discriminative information。

---

## E2. 固定组合

继续保留原计划最重要的组合：

1. `H+R`
2. `H+O`
3. `R+O`
4. `H+R+O`
5. `H+R+O+selected(V/P/S)`

`selected(V/P/S)` 的选择只能在 validation 完成：

- 先比较 V/P/S 单信号和对 R 的增量；
- 选一个最有价值的，避免组合搜索。

额外允许一个：

```text
R + selected(V/P/S)
```

用于回答新时序信号相对当前最强 R 的真实增量。

---

## E3. 一个 sequence model

只实现一个轻量模型：

- CNN1D **或** TCN，二选一；
- per-unit 输出；
- 输入使用冻结的 sequence feature；
- 与同输入的 simple MLP 比较。

若 sequence model 无增益，记录 negative result，不扩 Transformer。

---

## E4. 每个 branch 的报告

至少：

- AUROC；
- AUPRC；
- SA60；
- SA80；
- R95；
- unsafe false accept；
- interval @75；
- interval @100；
- safe accept/reject/uncertain；
- source-song macro；
- runtime。

必须同时给：

- `raw_target`
- `official_target`

不得混成一个指标。

---

# 8. 实验 F：PR — Propagation-risk detector

PR 与 correctness detector 是不同任务，必须单独实现。

## F1. 输入与标签边界

输入：

> 当前 window / 当前 commit 决策时已经可获得的 H/R/O/RO/V/P/S evidence。

禁止输入：

- 后续窗口 GT；
- future recovery outcome；
- `recovery_class`；
- mutation family；
- intervention severity 标签；
- 未来 trajectory。

未来信息只能作为 PR label。

## F2. PR target

沿用冻结定义：

- `low risk`：错误 commit 后 <=1 window 自恢复，且没有明显额外错误 commit；
- `medium risk`：2–3 windows 恢复或产生有限 corrupted commits；
- `high risk`：
  - persistent；
  - amplifying；
  - occurrence jump；
  - catastrophic corruption。

主评测先做：

```text
high-risk vs non-high-risk
```

三分类作为辅助。

## F3. 当前 corpus 的必要补充

现有 corrected `EPISODES.jsonl` 已有较多 persistent / amplifying / occurrence_jump episode，但 low/medium 风险样本可能不足。

因此必须先输出：

```text
03_propagation/PR_TARGET_AUDIT.json
```

统计每类：

- source songs；
- episodes；
- natural/model-native/corruption；
- low/medium/high；
- no-effect attempts。

若 low+medium 不足，**不得写“样本不足所以 PR 不执行”**。

应在同一 9-song 小规模集上只补轻度 intervention：

- cursor ±1 / ±2 / ±4 units；
- time ±0.25 / ±0.5 / ±1.0 s；
- mild boundary/tail corruption；
- model-native raw/official/posterior alternate（若存在）。

只补到能够形成基本 source-song-disjoint negative/non-high cohort，不扩大大矩阵。

## F4. PR 模型

固定一个 cheap learner：

- Logistic 或与 correctness detector 相同的 tabular learner。

输入比较：

1. 当前 best correctness score；
2. PR model using selected H/R/O/RO/V/P/S evidence。

主要指标：

- high-risk AUROC / AUPRC；
- high-risk recall；
- high-risk false-negative；
- source-song macro；
- family leave-one-out（仅在样本足够时）；
- fixed intervention-rate 下阻断的 corrupted future units；
- correctness detector vs PR detector 对 high-risk episode 的 recall。

### 关键问题

回答：

> 当前 correctness error 较小但会持续传播的情况，PR 能否提前识别？

以及：

> 当前 correctness detector 是否把“会自然恢复的小错”和“会放大的错”混在一起？

---

# 9. 实验 G：Closed-loop recovery failure decomposition

当前观测：

```text
36/36 retry
0 retry-derived committed row
```

本轮只复查/重跑这批小规模 selected windows，不扩大 closed-loop matrix。

对每个 retry window 保存：

## G1. before

- original raw/official timing；
- 100/250/500/1000 ms correctness；
- MAE；
- detector unit states；
- detector score；
- route plan；
- state hash。

## G2. retry after

- retry raw/official timing；
- 同样 correctness；
- detector score/state；
- writeback eligible region；
- route executor result；
- next request identity/state hash。

## G3. 改善定义

连续指标全部保存；同时冻结一个诊断分类：

`improved` 若满足任一：

- 250 ms correct coverage `+ >=10 pp`；
- MAE 相对下降 `>=20%`。

`worsened` 使用对称标准；其余为 neutral。

## G4. 四类失败来源

最终每个 retry 分类：

1. `retry_improved_detector_accept`
2. `retry_improved_detector_block`
3. `retry_not_improved`
4. `retry_worsened`

并进一步检查：

- detector accept 但 route/writeback 未写回；
- writeback 后 next state 是否真实变化；
- improvement 是否保持到后续 1/2/3 windows。

### 本实验决定下一阶段方向

若多数为 2：

> detector / threshold / intervalization 是 recovery 主要瓶颈。

若多数为 3/4：

> retry/re-align algorithm 本身是主要瓶颈。

若存在 detector accept 但未写回：

> route executor / writeback contract 仍有实现问题。

---

# 10. 不在本轮扩大的内容

为控制规模，本轮不要：

- 扩大 Transition 到更多候选策略；
- 调 T3 stable-boundary 大量参数；
- 重跑完整 M4 formal；
- 再做旧 T0 oracle；
- 大规模 oracle recovery 搜索；
- 多种 CNN/TCN/Transformer；
- classifier / threshold 网格搜索；
- H layer 大量枚举；
- posterior competing-path 多算法比较；
- 全组合 H/R/O/V/P/S 笛卡尔积。

本轮目标是**把已有设计真正实现完整**，不是增加更多分支。

---

# 11. 执行顺序

必须按依赖顺序执行，但不能在中间成功一部分后停止。

## Stage 1 — correctness repair

1. 修 Transition row-level aggregation；
2. 修 candidate/report 字段；
3. 重建 authoritative Transition report；
4. raw vs official timing 对照；
5. 正式 interval metrics generator。

## Stage 2 — evidence implementation

1. 扩展 forward evidence schema；
2. 同 forward 导出 R/O/H/full posterior；
3. 实现 RO；
4. 实现 V；
5. 实现 P；
6. 实现 S；
7. 完成 coverage audit。

## Stage 3 — detector offline experiment

1. 单信号 H/R/O/RO/V/P/S；
2. 固定组合；
3. SA60/SA80/R95；
4. interval metrics；
5. 一个 CNN1D/TCN。

## Stage 4 — PR

1. 审计现有 propagation corpus；
2. 必要时小规模补 low/medium episodes；
3. 构造 PR target；
4. PR detector；
5. correctness vs propagation-risk comparison。

## Stage 5 — recovery diagnostic

完成现有 36 retry 的 before/after decomposition。

## Stage 6 — report

自动检查所有 required artifacts 与非零 denominator 后再生成最终报告。

---

# 12. 必须新增/修正的 artifacts

建议至少产生：

```text
00_meta/
  SUPPLEMENT_META.json
  RUNTIME_BUDGET.json
  FAILURES.jsonl

02_transition/
  AUTHORITATIVE_TRANSITION_SELECTION_v3.json
  TRANSITION_PAIRED_BY_SONG.json
  RAW_OFFICIAL_TIMING_COMPARISON.json

03_propagation/
  PR_TARGET_AUDIT.json
  PR_EPISODES.jsonl
  PR_EVALUATION.json

06_detector/
  EVIDENCE_SCHEMA_v3.json
  SIGNAL_COVERAGE_AUDIT.json
  evidence_hidden.jsonl
  evidence_posterior.jsonl
  evidence_cross_window.jsonl
  evidence_trajectory.jsonl
  SIGNAL_ATLAS_v3.json
  SIGNAL_COMPLETION_MATRIX_v3.json
  MODEL_SELECTION_v3.json
  FROZEN_WORKING_POINTS_v3.json
  INTERVAL_METRICS_REPRODUCIBLE.json
  SEQUENCE_MODEL_EVAL.json

07_closed_loop/
  RECOVERY_FAILURE_DECOMPOSITION.json
  RECOVERY_FAILURE_DECOMPOSITION.jsonl

09_reports/
  SUPPLEMENTAL_REPORT.json
  SUPPLEMENTAL_REPORT.md
  NEGATIVE_RESULTS.md
  EVIDENCE_PACK_INDEX.json
```

---

# 13. SIGNAL_COMPLETION_MATRIX_v3 完成规则

矩阵至少包含：

```text
R
O
RO
V
P
S
H
H+R
H+O
R+O
H+R+O
R+selected(V/P/S)
H+R+O+selected(V/P/S)
sequence_model
PR
```

每行必须有：

```json
{
  "branch_id": "...",
  "status": "executed|negative|failed",
  "input_artifacts": [],
  "n_train_songs": 0,
  "n_val_songs": 0,
  "n_test_songs": 0,
  "n_units": 0,
  "n_intervals": 0,
  "coverage": null,
  "metrics_artifact": "...",
  "failure_reason": null
}
```

完成状态只允许：

- `executed`：实际运行并有有效指标；
- `negative`：实际运行但无收益。

`failed` 不算完成。

以下状态本轮禁止用于 H/P/PR：

- `blocked_api`
- `not_executed`
- `planned`
- `coverage_zero`
- `skipped_budget`

---

# 14. 最终报告必须明确回答的问题

最终 `SUPPLEMENTAL_REPORT.md` 必须逐项回答：

### Transition

1. 修正后 T1/T2/full-song 的真实 250 ms wrong-committed 是多少？
2. T2 是否在 song-level 上稳定优于 T1？
3. raw 与 official timing 差多少？
4. “40% vs Demo 观感”的差异主要来自什么？

### Detector correctness

5. R/O/RO/V/P/S/H 每个单独有多少信息？
6. H 是否产生真实增益？
7. P 的 coherent alternate path 是否能发现 entropy 看不出的 repeated-occurrence ambiguity？
8. V/P/S 哪个对当前最强 R 提供最大增量？
9. sequence model 是否优于 tabular？
10. SA60 / SA80 / R95 的 unit 与 interval 代价分别是什么？

### Propagation risk

11. 当前 propagation corpus 的 low/medium/high 分布是什么？
12. PR 是否比 correctness detector 更善于发现 persistent/amplifying/occurrence-jump？
13. PR 能否让部分会自然恢复的小错通过，同时阻断高危传播？

### Recovery

14. 0 writeback 的主要原因是 retry、detector，还是 writeback policy？
15. 是否存在“retry 已明显改善但 detector 阻止”的 case？
16. 是否存在“detector 已接受但 executor 没有真实写回”的实现问题？

---

# 15. 结果解释边界

允许出现以下 negative result：

- H 无增益；
- P 无增益；
- V/S 无增益；
- sequence model 无增益；
- PR 不优于 correctness detector；
- retry 本身几乎无法改善；
- T1/T2 不可区分。

这些都是有效科研结果。

**不允许的结果形式**是：

> “没有实现，因此无法判断。”

因为本轮的核心目的正是结束 H/P/PR 等信号反复被计划、却没有真正进入实验的问题。

---

# 16. Agent 最终停止条件

Agent 只有在以下全部满足后才可停止：

- Transition report bugs 修正；
- raw/official timing comparison 完成；
- interval metrics 可由正式脚本重建；
- H evidence 非零且通过 on/off equivalence audit；
- P evidence 非零且完成 competing coherent path；
- V/S/RO 实际进入 feature 与评测；
- H/R/O/RO/V/P/S 最小消融完成；
- sequence model 至少执行 1 个；
- PR target 审计完成，必要的 low/medium corpus 已补；
- PR detector 实际执行；
- 36 retry failure decomposition 完成；
- 所有 required artifact denominator 非零或有科学上合理的 eligibility denominator；
- compact evidence pack 可复核最终报告。

不得因为某一分支获得 negative result 而中止其余独立任务。

---

## 最终定位

本补充实验完成后，应能够把当前阶段从：

> “Transition 有初步结果；Detector 部分信号完成；H/P/PR 一直停留在计划；Recovery 只有 0 writeback 现象。”

推进到：

> “Transition 汇总口径正确；Detector 的 H/R/O/RO/V/P/S 均有真实 evidence 与公平消融；PR 被实际定义并评测；Recovery 的失败层级被拆解。”

之后再决定下一阶段到底应重点投入：

- Transition policy；
- correctness detector；
- propagation-risk detector；
- recovery algorithm；
- 或简化系统、减少 detector/recovery 复杂度。
