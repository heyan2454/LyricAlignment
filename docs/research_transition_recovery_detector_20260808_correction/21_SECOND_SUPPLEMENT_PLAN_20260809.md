# LyricAlignment 当前实验路线：第二次补充实验计划

**日期：2026-08-09**  
**阶段性质：second supplement / final correction pass**  
**目标：在不扩大主实验树的前提下，修正第一次 signal-completion 补充实验中发现的实现与评测问题，使 Transition / Detector / P / Interval / Recovery 的当前阶段结果能够真正冻结。**

---

# 0. 使用方式与角色分工

本文件首先交给 **Codex**。

Codex 的任务不是直接运行实验，而是：

1. review 当前仓库、第一次补充实验产物和 external evidence；
2. 核实本计划中指出的问题是否与实际代码一致；
3. 标记任何计划中的错误假设；
4. 给出具体实现方案、影响文件、数据流、缓存复用方式和验收测试；
5. 尽可能避免新增 GPU forward；
6. 明确哪些结果可由已有 evidence 重新聚合得到，哪些必须重新推理。

随后将 Codex 核实后的实现方案交给 **OpenCode**：

1. 建立新的 session / OUT_ROOT；
2. 完成代码修正；
3. 跑单元测试与 smoke；
4. 运行必要的补充实验；
5. 自动汇总结果；
6. 生成完整 evidence pack 和最终报告；
7. 不得在某一分支得到 negative result 后提前停止其余独立任务。

---

# 1. 本轮为什么必须做

第一次 signal-completion 补充已经取得进展：

- Transition aggregation 的旧错误大部分得到修复；
- H 已经真正从模型 hidden state 中提取，不再只是 placeholder；
- PR pipeline 已经实际执行；
- recovery decomposition 已经观察到少量真实改善和 writeback；
- R 仍显示为当前较强的无 GT correctness signal；
- V 可能对 R 提供少量增益。

但 review 发现若干问题会直接影响当前结论是否可信。

## 1.1 Detector committed-view 对齐错误

同一 T2 model-selection：

```text
authoritative Transition:
Safe / Grey / Unsafe = 549 / 804 / 2021

Detector v3:
Safe / Grey / Unsafe = 509 / 722 / 2143
```

总 unit 数均为 3374，但标签分布不一致。

初步代码审查显示：

- 系统先知道一个 canonical unit 实际在哪个 request 被 committed；
- 随后 R/O 等 row lookup 却可能使用 `canonical_id -> last observed row`；
- overlap 后续 view 会覆盖真正 committed observation；
- H/P 仍可能按 committed request 取；
- 因而不同 signal family 可能并非对应同一次 observation。

这会影响当前：

- H
- R
- O
- RO
- V
- P
- S
- R+V
- sequence model

等 detector v3 指标。

**本问题必须首先修复。**

---

## 1.2 P 并未真正完成 coherent competing path

第一次补充报告将 P 写为“完成且 negative”，但底层 evidence 显示：

- model-selection 36 requests；
- 仅约 4 个 request 为 `status=ok`；
- 其余多数为 `insufficient_paths`；
- 已成功的少数 request 中：
  - second path diversity 为 false；
  - differing-slot fraction 为 0；
  - alternate run 为 0；
  - local ambiguity 为 0。

而最终 P detector 实际消费的主要是：

- local top2 gap；
- path_ok。

这并没有真正回答：

> 是否存在第二条**不同但连续、单调、自洽**的时间路径，以及这种路径不确定性是否预示 alignment failure。

因此 P 当前不能作为 negative result 冻结。

---

## 1.3 Interval metrics 有实现错误

当前 interval evaluator 存在至少两个问题：

### Grey 被计入 Unsafe

冻结标签定义为：

```text
0 Safe
1 Grey
2 Unsafe
```

但旧实现把 `(1, 2)` 同时计入 unsafe denominator。

因此当前：

- unsafe interval recall；
- 75% / 100% interval capture；
- longest unsafe accepted run；

等结果都不可信。

### song boundary 没有明确断开

如果 intervalization 只是把 dataset row index 连续化，则前一首歌尾部和后一首歌开头可能被错误组成连续 interval。

本轮必须重建。

---

## 1.4 Recovery 当前 artifact 与最终报告、源码 provenance 不一致

底层 decomposition 已出现：

```text
retry_not_improved             27
retry_worsened                  4
retry_improved_detector_accept  3
retry_improved_detector_block   2
```

即：

- 5 / 36 retry 有明显改善；
- 3 / 5 被 detector 接受；
- 2 / 5 被阻止；
- 至少部分 case 有 retry-derived writeback commits。

但旧总报告仍残留：

> 0 writeback；5 个改善全部被 detector block。

同时当前归档脚本并不能明确复现 evidence pack 中的完整 before/after decomposition。

因此需要：

- 恢复/归档真正生成 decomposition 的代码；
- 重新从原始 artifact 生成；
- 修正总报告；
- 验证 writeback 是否真实进入 serial state，而不是仅诊断字段变化。

---

# 2. 本轮总体原则

## 2.1 不扩大实验树

本轮不新增：

- 新 Transition policy；
- 大规模新数据；
- 大量 hidden layer 搜索；
- 新的 classifier 网格；
- 多种 CNN/TCN/Transformer；
- 大型 PR intervention 网格；
- 新 recovery family；
- T3 参数调优；
- 新 oracle 路线。

本轮目标是：

> **把现有实验做对，而不是继续做多。**

---

## 2.2 优先复用已有 evidence

实施前必须逐项判断：

```text
A. 只需重新 aggregate
B. 只需重新 build features / train cheap classifier
C. 需要重新 decoder
D. 需要重新 model forward
```

原则：

> 能 A/B 解决的问题，不得重新做 D。

特别是 committed-view 修复，预计绝大多数 H/R/O/V/S evidence 已存在，应首先尝试重新绑定，而不是重新跑整批 GPU inference。

---

## 2.3 所有 signal 必须绑定明确 observation identity

从本轮开始，任何 detector feature row 必须有完整 identity：

```text
source_song_id
canonical_unit_id
transition_id
request_id
window_id
view_id
committed_request_id
is_committed_observation
```

最终用于 correctness detector 的主样本必须明确：

```text
feature observation == committed observation
```

cross-view V 可以额外使用多个 observations，但：

> target unit 的 primary row 必须仍由 committed observation 定义。

---

# 3. Stage A — Codex 首先核实当前问题

Codex 在实现前必须输出一份 review / implementation plan。

至少逐项回答：

1. committed-view 覆盖 bug 是否确实存在？
2. 当前 `canonical_id -> row` 的覆盖逻辑具体在哪里？
3. label 与 R/O/H/P/V/S 各自来自哪一个 request/view？
4. 修复后 authoritative Transition label 是否应与 detector dataset 完全一致？
5. H slot mapping 当前为什么只有部分 unit coverage？
6. P 的 `insufficient_paths` 根因是什么？
7. P 当前实现是否实际上允许 second-best path 与 best path 完全相同？
8. interval evaluator 是否确实把 Grey 计入 Unsafe？
9. interval 是否可能跨 song boundary？
10. recovery evidence 当前由哪个代码版本生成？
11. 当前源码是否能够从原始 retry artifact 重建相同 decomposition？
12. PR 是否受到 correctness detector committed-view bug 的直接影响？
13. 哪些阶段必须重新跑 classifier，哪些不用重新 forward？

Codex 应给出：

```text
problem
root cause
affected artifacts
required code changes
required tests
required reruns
cache reuse plan
expected runtime class
```

---

# 4. Stage B — 修复 committed-observation binding

这是本轮第一优先级。

## B1. 数据模型

不得再仅使用：

```python
canonical_id -> row
```

作为主查找键。

至少必须支持：

```python
(request_id, canonical_id) -> row
```

或等价的不会被 overlap view 覆盖的数据结构。

先从 serial commit log 得到：

```text
canonical_unit_id
    -> committed_request_id
    -> exact committed row
```

然后所有 correctness feature family 均以该 row 为主。

---

## B2. 信号绑定规则

### R

来自 committed request 的 raw geometry / posterior-local feature。

### O

来自**同一个 committed request**的 official decoder output。

### RO

只比较同一个 request 内 raw 与 official。

### H

hidden 必须对应 committed request 中该 unit 的真实 timestamp slot。

### P

P 必须对应 committed request 的 posterior/path evidence。

### S

sequence trajectory 以 committed canonical unit sequence 为主构造。

### V

V 是例外：

- 可以访问同 unit 的多个合法 overlapping views；
- 但主样本 identity 仍归属于 committed unit；
- 不得用未来 GT；
- 不得把 test split 的其它 source-song 信息泄漏进 train。

---

## B3. 修复后的 invariants

对 T2 model-selection 应至少满足：

```text
n_units detector == n_units authoritative transition
Safe detector == Safe authoritative transition
Grey detector == Grey authoritative transition
Unsafe detector == Unsafe authoritative transition
```

如有不一致，必须逐 row 输出差异原因，不得继续训练 classifier。

新增：

```text
06_detector/COMMITTED_OBSERVATION_BINDING_AUDIT.json
06_detector/COMMITTED_OBSERVATION_BINDING_MISMATCH.jsonl
```

要求最终 mismatch：

```text
0
```

若确实存在科学上不可避免的 eligibility difference，必须单独给 denominator，不得静默丢 row。

---

# 5. Stage C — H mapping 修正与重新评测

H 已经真实实现，因此本轮不再探索更多层，而是修 mapping。

## C1. 核实真实 timestamp-slot mapping

禁止继续假设：

```text
unit i -> slot 2i, 2i+1
```

除非从模型输入/processor/decoder contract 证明该映射永远成立。

Codex 应追踪：

```text
text / request construction
timestamp slot construction
model output slot index
raw boundary extraction
canonical unit mapping
```

使用与 raw decoder **同源的 slot mapping** 来定位 H。

---

## C2. H coverage audit

重新报告：

```text
request-level hidden artifact coverage
unit-level eligible coverage
unit-level complete H feature coverage
```

三者不得混为一个“100%”。

目标：

> 对所有具有合法 committed timestamp slots 的 unit，H coverage 接近 100%。

任何缺失必须给 reason taxonomy。

---

## C3. Hidden on/off equivalence audit

若第一次补充没有实际 artifact，本轮必须补。

同一 deterministic request：

- hidden extraction off；
- hidden extraction on。

比较：

- logits；
- raw times；
- official times；
- canonical mapping。

保存：

```text
06_detector/HIDDEN_EQUIVALENCE_AUDIT.json
```

若 hidden-on 改变模型输出，则先修实现，不得直接继续实验。

---

## C4. H 重新评测

在 committed-view 与 H mapping 均修复后，再重新运行：

- H；
- H+R；
- H+O；
- H+R+O。

若 H 仍无增益，才可将：

> hidden-state signal negative

作为当前阶段结论。

---

# 6. Stage D — P coherent competing path 真正完成

本轮 P 的验收标准不是“程序成功生成 JSON”，而是：

> **在存在 posterior ambiguity 的 request 上，算法能够构造一条与 best path 实际不同的 second coherent monotonic path。**

---

## D1. 先核实当前失败原因

Codex 先分析：

- 为什么 32/36 request `insufficient_paths`？
- 当前 DP state 是否只保存单一路径？
- k-best path 是否被相同 prefix/state 合并？
- second path 是否允许与 first path 完全相同？
- 单调约束是否过严？
- candidate timestamp states 是否被 top-k 截断得过早？
- 是否应该基于完整 timestamp posterior 而不是 unit-local top2？

不得直接盲调参数。

---

## D2. 冻结 second-path 定义

只实现一种正确算法，不做算法矩阵。

建议目标：

```text
best coherent monotonic boundary path
second-best DISTINCT coherent monotonic boundary path
```

`DISTINCT` 至少要求：

```text
存在 >= 1 个 boundary slot 不同
```

并额外报告：

- differing slot fraction；
- max temporal displacement；
- median temporal displacement；
- longest contiguous alternate run。

对于 repeated-phrase / occurrence ambiguity，可进一步判断：

> alternative path 是否形成连续整体平移。

---

## D3. P evidence 必须包含

request-level：

```text
best_path_score
second_path_score
normalized_score_gap
has_distinct_second_path
differing_slot_fraction
max_time_displacement
median_time_displacement
longest_alternate_run
global_shift_like
```

unit-level：

```text
local_second_path_gap
local_boundary_disagreement
local_alternate_run_membership
local_displacement
```

---

## D4. P 验收

必须分开报告：

```text
successful posterior requests
eligible requests
requests with distinct second path
requests without distinct second path
algorithm failures
```

不能再把：

```text
JSON file exists
```

当成 P coverage。

对于 model-selection 36 requests：

- 如果真实 posterior 根本没有可区分 second path，这是允许的科学结果；
- 但必须证明算法能够在**构造/synthetic sanity case** 上找到 second path。

新增单测：

1. 唯一路径 case；
2. 两条明显路径 case；
3. repeated-occurrence-like 双峰路径 case；
4. 第二路径违反单调性 case；
5. second path 与 first path 相同必须被拒绝。

---

## D5. P detector 重新评测

只有在上述算法验收后，才重新运行：

- P；
- R+P；
- 如 P 在 validation 上优于 V，则替代 V 进入 `R + selected temporal signal`；
- 否则保留 R+V。

不得用 test 选择 V/P。

---

# 7. Stage E — O / RO 完整性修正

第一次补充中：

- `official_end_sec` 等字段全缺；
- O/RO classifier 实际只使用部分 features。

Codex 先检查：

> 当前 official decoder 是否本来就有 end/boundary 信息，只是 evidence exporter 没保存。

若已有数据支持：

- 修 exporter / aggregator；
- 补齐 official start/end/duration；
- raw↔official start/end shift；
- ordering / duration disagreement。

如果模型/decoder 的 official schema 本身只定义某类 boundary，则：

> 不得虚构 end。

应修改 O/RO 的正式定义和报告，明确这是 start-only signal。

最终报告必须写：

```text
O implemented feature set = ...
RO implemented interaction set = ...
```

不能继续用“完整 O/RO”掩盖字段缺失。

---

# 8. Stage F — Interval metrics v3

重新实现正式 evaluator。

## F1. 标签

严格：

```text
Safe   = label 0
Grey   = label 1
Unsafe = label 2
```

主 unsafe recall denominator：

```text
only label == 2
```

Grey 单独统计。

---

## F2. song boundary

intervalization key 至少是：

```text
source_song_id
canonical unit order
```

每首歌曲独立构造 interval。

禁止：

```text
dataset row 1024
dataset row 1025
```

因为 index 连续就自动属于同 interval。

---

## F3. 两种保护口径

必须同时报告：

### REJECT-only

只有 REJECT 视为捕获错误。

### protected = REJECT + UNCERTAIN

表示没有错误地自动 ACCEPT。

不得再混淆。

---

## F4. 三种主要指标

继续保留既定：

1. unsafe interval 100% units protected；
2. unsafe interval >=75% units protected；
3. unsafe unit recall。

同时报告：

- Safe ACCEPT；
- Safe UNCERTAIN；
- Safe REJECT；
- Grey 三状态；
- longest unsafe ACCEPT run；
- fragmentation；
- interval count / median length。

---

## F5. 工作点

重新评测：

- SA60；
- SA80；
- R95。

工作点 threshold 必须基于正确 committed-view detector score。

如果 detector score 因 binding 修复改变：

> threshold 必须重新在 threshold-validation 上冻结。

不得沿用旧 threshold。

---

# 9. Stage G — Detector v4 最小重跑

修复 B–F 后，只运行必要最小矩阵。

## G1. 单信号

至少：

```text
H
R
O
RO
V
P
S
```

## G2. 组合

至少：

```text
H+R
H+O
R+O
H+R+O

R+V
R+P
R+S
```

然后只在 validation 上选：

```text
selected_temporal = best of V/P/S incremental to R
```

最终：

```text
R + selected_temporal
H + R + O + selected_temporal
```

不继续笛卡尔积。

---

## G3. 评价

每个 branch：

- AUROC；
- AUPRC；
- source-song macro AUROC；
- SA60；
- SA80；
- R95；
- interval 75%；
- interval 100%；
- Safe accept/reject/uncertain；
- feature coverage；
- runtime。

raw-target 与 official-target 分开。

---

# 10. Stage H — sequence model 公平性修正

第一次补充的 CNN1D：

- MLP 使用 StandardScaler；
- CNN1D 没有相同 normalization。

因此当前“CNN 不如 MLP”只能视为具体实现 negative，不能视为 sequence model 机制 negative。

本轮不扩大模型。

只做：

```text
same selected sequence input
same train/val/test split
same train-only normalization
MLP vs one CNN1D/TCN
```

要求：

- normalization 只 fit train；
- validation/test transform；
- missing-value policy 一致；
- 相同 label；
- 相同 eligible units。

如果公平修正后 sequence model 仍明显不如 MLP：

> 当前阶段冻结为 negative result，不再继续 sequence model。

---

# 11. Stage I — PR 只做口径修正，不扩大主实验

PR 已真正运行，但：

- pooled AUC 为同数据 fit/evaluate；
- LOSO macro AUC 更能反映泛化；
- correctness proxy 不是严格冻结 correctness detector score。

本轮不要再大规模扩 PR corpus。

只修：

## I1. held-out 评测

主报告改为：

- leave-one-song-out / source-song-disjoint；
- macro AUROC；
- macro AUPRC（若每 fold 可计算）；
- pooled out-of-fold prediction AUC。

不得把 in-sample 0.608 当主泛化指标。

## I2. correctness comparator

使用修复后的冻结 correctness detector：

```text
p_bad / unsafe score
```

作为 baseline。

不要再使用简单 feature mean 作为 correctness proxy。

比较：

```text
correctness detector
vs
PR detector
```

对 high-risk episode 的识别能力。

若 PR 仍不优：

> 正式记录为当前 propagation-risk detector negative result。

不继续调参。

---

# 12. Stage J — Recovery decomposition 正式复现

本轮不扩大 36-window 样本。

目标是：

> 让当前 evidence 的 recovery 结论从正式脚本可复现。

---

## J1. 找回真实数据链

明确每个 retry：

```text
original request
original committed rows
detector decision
retry request
retry rows
retry detector
writeback plan
actual committed rows
next serial state
```

生成脚本必须直接基于这些真实 artifacts，而不是手工/外部后处理文件。

---

## J2. 重新生成四分类

继续使用：

```text
retry_improved_detector_accept
retry_improved_detector_block
retry_not_improved
retry_worsened
```

改善判定保持第一次补充冻结标准，除非 Codex 发现实现与文档不一致；如需修正，必须同时报告旧/新定义影响。

---

## J3. 验证 writeback 是否真实进入状态

对于 3 个或任何 `detector_accept` case：

必须验证：

```text
retry_writeback_commits > 0
```

并进一步比较：

```text
state_before_retry
state_after_writeback
next_window_request
```

确认：

> writeback 不是仅 report 字段，而是实际改变下一步 serial state。

至少保存 state hash / cursor / committed-unit identity。

---

## J4. 后续持续性

对成功 writeback case，观察后续：

- 1 window；
- 2 windows；
- 3 windows（若数据存在）。

报告：

```text
improvement retained
improvement lost
new error introduced
```

这只是小样本诊断，不扩大 recovery 方法。

---

# 13. 本轮允许新增一个很小的解释性实验：Failure-shape audit

此项为可选但推荐，计算成本应接近纯离线统计。

目的不是开始新的“大 failure taxonomy”，而是帮助解释当前 Unsafe 的形状，并为下一阶段决定方向。

对 corrected T2 model-selection 的 Unsafe unit，根据 GT diagnostic 只统计以下最简单几类：

```text
local shift
local compression / inversion
large occurrence-like jump
head/startup failure
tail failure
other
```

要求：

- 规则必须先冻结；
- 仅用于 diagnostic，不进入 detector feature；
- 不使用人工逐 case 主观分类作为主结果；
- 输出每类 count / songs / typical error magnitude。

如果规则难以客观实现，本轮可以不做，不得因此阻塞主任务。

---

# 14. 本轮不做的更大研究内容

以下留到第二次补充冻结之后：

- 完整 illegal-input failure taxonomy；
- slot/sparse query 主实验；
- adaptive context；
- targeted recovery family；
- self-verification intervention；
- 更大 propagation mechanism study；
- 新论文主方法组合。

本轮必须先把当前阶段的数据与结论清干净。

---

# 15. 必须新增的测试

至少加入：

## committed binding

- 同一 canonical unit 出现在两个 overlap requests；
- 后 view 不得覆盖 committed view；
- detector label 与 authoritative transition 一致。

## H mapping

- slot 数与 unit 数不简单为 2x 的 case；
- raw decoder 能定位的 boundary，H 也必须定位到相同 slot；
- hidden on/off equivalence。

## P

- unique path；
- two distinct coherent paths；
- repeated occurrence；
- invalid non-monotonic second path；
- duplicated best path cannot count as second path。

## interval

- Grey 不计入 Unsafe；
- REJECT-only 与 protected 分开；
- 两首歌 index 相邻不能合并 interval。

## recovery

- improved+accept 产生真实 writeback；
- writeback 改变 next serial state；
- block 不得写回。

---

# 16. 推荐新目录

不要覆盖第一次 supplement。

建议：

```text
runs/research_transition_recovery_detector_20260809_second_supplement/
```

建议 artifacts：

```text
00_meta/
  IMPLEMENTATION_REVIEW.md
  RUN_META.json
  FAILURE_LOG.jsonl
  CACHE_REUSE_AUDIT.json

02_transition/
  TRANSITION_LABEL_REFERENCE.json
  RAW_OFFICIAL_TIMING_COMPARISON_V2.json

06_detector/
  COMMITTED_OBSERVATION_BINDING_AUDIT.json
  COMMITTED_OBSERVATION_BINDING_MISMATCH.jsonl
  HIDDEN_EQUIVALENCE_AUDIT.json
  H_COVERAGE_AUDIT_V2.json
  P_PATH_AUDIT_V2.json
  P_SIGNAL_ATLAS_V2.json
  O_RO_SCHEMA_AUDIT.json
  SIGNAL_COVERAGE_AUDIT_V4.json
  MODEL_SELECTION_V4.json
  FROZEN_WORKING_POINTS_V4.json
  INTERVAL_METRICS_V3.json
  SEQUENCE_MODEL_FAIR_EVAL.json

03_propagation/
  PR_HELDOUT_EVALUATION_V2.json
  PR_CORRECTNESS_COMPARISON_V2.json

07_closed_loop/
  RECOVERY_DECOMPOSITION_REPRODUCIBLE.json
  RECOVERY_DECOMPOSITION_REPRODUCIBLE.jsonl
  RECOVERY_WRITEBACK_STATE_AUDIT.json

09_reports/
  SECOND_SUPPLEMENT_REPORT.json
  SECOND_SUPPLEMENT_REPORT.md
  NEGATIVE_RESULTS.md
  EVIDENCE_PACK_INDEX.json
```

---

# 17. 最终报告必须回答

## Transition / binding

1. detector dataset 与 authoritative Transition 的 Safe/Grey/Unsafe 是否完全一致？
2. 旧 detector v3 指标受 committed-view bug 影响多大？
3. 修正后 R 是否仍然是最强单信号？

## H

4. H 的真实 unit-level coverage 是多少？
5. hidden extraction 是否数值等价？
6. 修正 mapping 后 H 是否有独立增益？

## P

7. P 是否真的能找到不同的 coherent second path？
8. 有多少 request 存在 distinct second path？
9. P 是否对 repeated/occurrence ambiguity 有可测信息？
10. P 相对 R/V/S 是否带来增益？

## O / RO

11. O/RO 的真实可用字段是什么？
12. 完整或修正定义后是否有收益？

## Interval

13. 修正 Grey 与 song boundary 后，SA60 / SA80 / R95 的：
    - unit unsafe recall；
    - interval 75%；
    - interval 100%；
    - safe accept cost；
    分别是多少？

## Sequence

14. 公平 normalization 后 sequence model 是否仍不如 MLP？

## PR

15. out-of-fold / LOSO PR 泛化到底是多少？
16. PR 是否优于真正的 correctness detector 对 high-risk episode 的识别？

## Recovery

17. 36 retry 中多少真正改善？
18. 改善中多少被 detector 接受？
19. 接受后多少真正 writeback？
20. writeback 是否改变 next serial state？
21. recovery 当前主要瓶颈到底是：
    - retry algorithm；
    - detector；
    - executor/writeback？

---

# 18. 结果解释与停止条件

本轮允许并接受以下结论：

- H 修正后仍无增益；
- P 正确实现后仍无增益；
- O/RO 无增益；
- V 的 +0.005 左右增益消失；
- CNN/TCN 公平后仍更差；
- PR held-out 仍低于 random / correctness；
- recovery 绝大多数 retry 无改善。

这些都可以作为 **negative results** 冻结。

但以下情况不允许宣告阶段完成：

```text
committed binding mismatch > 0 且无解释
P 仍然只有 path_ok/top2-gap 而没有真实 second path
Grey 仍混入 Unsafe
interval 仍跨 song
H coverage 仍因错误 slot mapping 大量缺失
recovery decomposition 无正式可复现生成脚本
报告仍引用旧 0-writeback 结论
```

---

# 19. 第二次补充完成后的冻结目标

只有在本轮全部完成后，才建议正式冻结当前实验路线的这一阶段。

理想冻结状态：

### Transition

```text
serial > full-song
T1 ≈ T2
T2 nominal best
```

### Correctness detector

得到一份真正 observation-aligned 的：

```text
H / R / O / RO / V / P / S
```

公平比较结果。

### P

无论结果正负，都必须真正完成：

```text
distinct coherent second-path
```

实验。

### Interval

SA60 / SA80 / R95 有正确 unit + interval 口径。

### PR

有 source-song-disjoint 泛化结论，而非 in-sample 结论。

### Recovery

能够从正式源码复现：

```text
retry -> detector -> writeback -> next serial state
```

并明确当前主要失败层级。

---

# 20. 本轮之后才进入下一阶段

完成第二次补充后，不建议继续第三次“修当前实验”。

下一阶段应直接转向更大的研究问题，例如：

1. alignment failure taxonomy；
2. illegal-input robustness；
3. slot / sparse-query serial alignment；
4. context consistency / active self-verification；
5. error-type-specific targeted recovery；
6. propagation mechanism。

换言之：

> **第二次补充的使命不是提高指标，而是让当前阶段的证据链完整、口径正确、结论可冻结。**

一旦完成，就应停止继续在当前 detector patch 上打补丁，转入新的研究阶段。
