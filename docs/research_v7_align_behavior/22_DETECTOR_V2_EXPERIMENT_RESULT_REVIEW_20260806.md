# Detector V2 当前实验结果复审（2026-08-06）

状态：**当前结果不满足 Detector V2 实验设计，不能标记为 `detector_v2_completed=true`。**

建议状态：

```json
{
  "detector_v2_completed": false,
  "partial_exploratory": true
}
```

本文件供后续实现 agent 直接整改。复审范围限于：标签与坐标语义、训练/验证切分、模型与阈值、指标解释、跨域/压力实验和串行闭环是否符合 `18/19/20` 的冻结设计，以及相关代码是否正确实现这些设计。本复审不讨论 artifact/manifest 的防篡改、签名、SHA 信任边界或有写权限者修改文件等问题。

## 1. 总结判断

当前真实 forward 和离线训练/评价流程已经运行，raw/official 双目标、三态指标和若干 family 结果也已经生成；但最上游的 M4 correctness 标签存在两个阻断性实现错误：

1. 分段局部 GT 时间没有转换为拼接整歌的全局时间；
2. sparse view 中未查询的 canonical units 被当成“输出缺失”并标为 unsafe。

这两个问题会直接污染 M4 训练标签、validation 阈值、M4 heldout、family-LOO、stress 与 serial 所使用的 detector。现有 detector 随后又退化为近乎全拒绝：它确实保护了 unsafe units，但几乎不接受 safe units，因而没有证明产品可用性。

当前最合理的科研表述是：

> O-only standardized Logistic 在当前标签和冻结阈值下呈现近乎 reject-all 的行为；由于 M4 标签坐标与 sparse 标签口径错误，不能据此判断 Detector V2 的真实检测能力或跨域泛化能力。

## 2. P0：M4 GT 坐标映射错误

### 2.1 当前实现

`scripts/research_v7/label_detector_v2_run.py::build_song_gt()` 对每个 GT row 执行：

```python
s = timestamp_class_ids[2 * i] * timestamp_segment_sec
e = timestamp_class_ids[2 * i + 1] * timestamp_segment_sec
```

然后把各 row 的字符和时间直接追加到 song-level 数组。这里没有加入：

- 当前 source segment 在拼接整歌中的起点；
- 前序 segment 的累计 duration；
- segment 之间的 artificial seam silence。

M4 原始标签中的 `timestamp_class_ids` 是单个 source segment 内的局部坐标。与此同时，`src/lyricalign/research_v7/timeline.py::build_timeline()` 使用累计 `cursor` 构造整歌 canonical unit 全局坐标，请求和模型输出也使用该整歌坐标。因此第二个 source segment 以后的 GT 与 prediction 不在同一坐标系。

此外，`align_units_to_gt()` 每次请求都从整首歌 GT 字符序列的开头做单向贪心字符匹配。它没有利用已有的 `source_segment_id`、`source_unit_index` 或请求窗口范围，无法可靠处理：

- 从歌曲中段开始的第二/第三个 60 s 窗口；
- 重复副歌和重复字符；
- 某个字符匹配失败后同一请求内的后续字符；
- 同一歌词文本在多个 occurrence 中出现的情况。

### 2.2 对结果的影响

`run1/LABEL_SUMMARY.json` 当前记录：

- `n_units = 107412`；
- `n_safe = 4280`；
- `n_unsafe = 98224`；
- `unsafe_rate = 0.91446`；
- `safe_rate = 0.039847`。

这个极端分布不能先解释为模型能力差或数据很难；它首先是错误坐标和错误匹配造成的标签异常。所有依赖这些 M4 标签的模型、阈值和评价均须在修复后重算。

### 2.3 必须采用的实现

不得再通过整歌字符贪心搜索建立 GT。应在 timeline 构造时保留并消费确定性映射：

```text
canonical_unit_id
  -> source_segment_id
  -> source_unit_index
  -> local GT (start, end)
  -> segment_global_start + local GT
  -> global GT (start, end)
```

其中 `segment_global_start` 必须与真实拼接音频完全一致，并包含前序 segment duration 和 seam silence。

如果某个 canonical unit 没有唯一的 source segment/unit 映射，应标为 `gt_unavailable` 或 `ambiguous`，不得退回到整歌字符搜索猜测 occurrence。

### 2.4 关闭条件

至少新增以下失败回归测试：

1. 两个 source segments，验证第二段首字 GT 加上第一段 duration 与 seam；
2. 三个 segments，验证第三段字符与模型全局输出比较；
3. 从歌曲中段开始的 60 s 请求只绑定窗口内 canonical units；
4. 重复副歌具有两个相同文本 occurrence，映射仍由 source id/index 唯一决定；
5. segment 顺序输入被打乱时，仍按 timeline order 得到相同 GT；
6. GT、timeline、拼接音频的最后结束时间在允许误差内一致。

修复后必须重新生成 M4 labels，并首先人工抽查 early/middle/late 各若干窗口的 `(canonical id, source segment, local GT, global GT, prediction)`。

## 3. P0：sparse view 把未查询单位标成 unsafe

### 3.1 当前实现

`label_one_request()` 使用请求的完整 `canonical_ids` 构建 `request_ids`；但是 sparse view 的真实查询集合由 `timestamp_slot_indices` 决定。例如已检查的一条请求包含 118 个 canonical units，sparse 只查询并输出 59 个 units。

`detector_v2_labels.label_request_units()` 会遍历 `canonical_gt` 中的全部单位；GT 存在但 decoder row 不存在时，按 `missing_output_geometry` 标成 unsafe。因此 sparse 中有意不查询的另一半单位被错误地解释为模型漏输出。

baseline legal/test/official 的现有标签也显示该结构性差异：

| view | safe | unsafe | grey | gt_unavailable |
|---|---:|---:|---:|---:|
| full | 28 | 232 | 4 | 1165 |
| overlap | 28 | 232 | 4 | 1165 |
| sparse | 14 | 248 | 2 | 1165 |

sparse 的 safe 约减半而 unsafe 增加，不是合法的 view 公平比较。

### 3.2 正确口径

必须显式区分三个集合：

- `query_set`：本次实际请求时间戳的 canonical units；
- `output_set`：decoder 实际返回几何的 canonical units；
- `context_only_set`：文本中存在、但本次没有查询时间戳的 units。

只有 `query_set` 中缺少输出几何的单位才能按 `missing_output_geometry` 进入 unsafe。`context_only_set` 应记录为 `not_queried`，并排除在 safe/unsafe/grey 正确性分母之外。

跨 sparse/full/overlap view 比较时，只能在 matched common queried units 上计算：

- 几何差；
- 状态一致性；
- safe accept/reject/uncertain；
- 多视图带来的状态转换。

### 3.3 关闭条件

1. full 118 units、sparse 59 slots 的 fixture 中，sparse correctness 分母必须为 59；
2. 未查询的 59 units 必须是 `not_queried`，不得产生 unsafe；
3. query unit 真正缺 row 时仍须标 unsafe；
4. full/sparse matched comparison 的分母必须等于两者 query-set 交集；
5. full 与覆盖相同 units 的 overlap view 应产生相同 GT binding。

## 4. P0：当前工作点退化为近乎全部拒绝

### 4.1 当前结果

M4 song-heldout：

| target | unsafe | safe | unsafe accept | safe accept | safe reject |
|---|---:|---:|---:|---:|---:|
| raw | 4900 | 400 | 3 | 0 | 355（88.75%） |
| official | 4904 | 396 | 0 | 0 | 342（86.36%） |

M4→MIR official：

- unsafe：5349，accept 0；
- safe：71065，accept 1；
- safe accept rate：`0.000014`；
- safe reject rate：`0.958855`。

因此 `protected_recall≈1` 主要来自不接受任何东西，而不是 detector 在错误区拒绝、正确区接受。按实验计划，正常合法输入专门用于测量正确接受率与误拒/存疑代价，不能只以 unsafe false-accept 为零宣布成功。

### 4.2 指标解释修正

- `unsafe_false_accept_rate=0`：只表示没有已知 unsafe unit 被 accept；
- `protected_recall=1`：unsafe 被 reject 或 uncertain，并不表示 safe 没被误拒；
- `safe_reject_rate` 才反映明确安全单位被拒绝的比例；
- `safe_accept_rate≈0` 时，detector 不具备提交正确结果的能力。

当前报告中的“0 误拒”如果指 safe→reject，则与结果不符；如果本意是“0 unsafe accept”，必须改用准确字段名。

### 4.3 后续实验要求

重新标注后，所有工作点必须同时报告并比较：

1. always-accept baseline；
2. always-uncertain baseline；
3. always-reject baseline；
4. rule baseline；
5. 学习模型工作点。

阈值选择不能只最大化 protected recall。至少同时约束：

- unsafe false-accept；
- safe accept；
- safe reject；
- uncertain coverage；
- source-song macro 指标；
- 正确保护率—正确接受率曲线。

如果在目标 unsafe protection 下 safe accept 仍接近零，结论应是“当前证据/模型无法形成有用工作点”，而不是 detector 完成。

## 5. P0：serial 实验没有实现冻结的闭环设计

### 5.1 与设计不符之处

冻结计划要求：至少连续 4 个 60 s 窗口；第 2 窗注入错误；后续 3–5 窗不得 GT reset；测量错误提交、传播、恢复、unresolved 和额外请求。

当前 `SERIAL_CLOSED_LOOP.json` 实际为：

- 3 首歌；
- 总计 8 个 scoring windows，每首只有 2–3 个；
- 窗口来自不重叠切片，跨窗口 shared canonical units 结构上约为零；
- single-view 与 multi-view 均 `total_commits=0`；
- multi-view `extra_requests=0`；
- detector 的全部决策为 reject。

这种实验无法观察错误如何通过 committed cursor 进入后续窗口，也无法观察 detector 是否恢复。`error_commit_rate=0` 只是零提交的结果，不构成 serial closed-loop 能力。

### 5.2 正确实现

每条 serial trajectory 至少需要：

1. 4–5 个按真实产品 stride 产生的连续且有 canonical overlap 的 60 s 窗口；
2. 窗口 1 为正常启动；
3. 窗口 2 注入一次 cursor/time/end-early/错误 commit；
4. 窗口 3–5 的请求范围由上一窗口的真实 commit/provisional 状态生成；
5. 除 GT-oracle 对照外，禁止在每个窗口重置为 GT cursor；
6. uncertain 路线在冻结预算内真正发出额外验证 request；
7. 至少包含会正确提交的正常 trajectory，否则无法测延迟提交和恢复成本。

四条路线继续保留：all-commit、GT oracle、single-view detector、multi-view detector。

### 5.3 关闭条件

每条路线至少报告：

- 正确提交数与错误提交数；
- 首次错误提交窗口；
- 传播的 units/windows；
- delayed correct commits；
- unresolved windows；
- extra requests/forwards；
- 困难区后的 re-entry/recovery；
- 每首歌与整体分母。

只有 detector 路线既发生了非零正确提交、又真实经历了 injected error 和后续状态传播，`serial closed-loop` 才可标 complete。

## 6. P1：source-song 样本量与内部选择切分不足

### 6.1 当前规模

当前 M4 anomaly run 只处理 10 首歌：约 6 首 train、1 首 validation、3 首 test；请求数为 444/74/222。preflight 中存在 419 首歌不代表 formal detector 实际使用了 419 首。

冻结计划建议最少 18/6/6 或约 60/20/20。单首 validation 会使阈值、feature combo 和模型选择高度依赖一首歌的分布，三首 test 也不足以支持广泛的 source-song 或 family 泛化结论。

### 6.2 内部选择仍按 unit 随机切分

`scripts/research_v7/train_detector_v2.py` 对外部 `train_rows` 做 unit-level 随机 80/20 inner split，用于 H/R/O 组合选优。同一首歌的不同窗口、mutation 和 view 因此可能同时进入 inner train 与 inner validation。

虽然外部 test 仍是 song-heldout，但 feature/combo/model 的内部选择受到强相关样本影响，不符合“同一 source song 的全部窗口与视图始终属于同一 split”的设计。

### 6.3 整改要求

- pilot 至少使用 18/6/6 source songs；资源允许时采用约 60/20/20；
- outer split 与所有 inner split 都以 source song 为 group；
- validation 至少覆盖主要语速、位置、长音、重复段和 family；
- 每份结果同时报告真实 `n_source_songs` 和 unit/request 数；
- 阈值和模型选择只读取 train/validation，test 与 MIR OOD 不参与选择。

## 7. P1：模型阶梯与信号实验未完成

冻结设计要求在同一 evidence、同一 split 上比较：

1. 单信号图谱与 rule baseline；
2. standardized Logistic；
3. constrained GBDT；
4. small MLP/hidden probe；
5. 一个小型 interval sequence model。

当前 `MODEL_SELECTION.json` 只有 `standardized_logistic`，最终组合为 O。虽然代码中已有部分模型 helper，但没有形成可比较的正式实验结果；`SIGNAL_ATLAS.json` 也未生成。

H 在抽取不可用时可以按合同标为 blocked，且不阻塞 R/O 主线；但 H blocked 不等于可以省略以下仍可执行项目：

- R/O/V 单信号图谱；
- rule baseline；
- Logistic 与 constrained GBDT；
- 不依赖 H 的小型 MLP 或 sequence model；
- 模型复杂度与 safe-accept/protection 的成本收益比较。

完成标准不是每种模型都优于 Logistic，而是按冻结设计完成公平比较，并据 validation 结果选择最简单的有效模型。若所有模型均退化为 reject-all，应如实记录负结果。

## 8. P1：跨域、family-LOO 与 stress 的可声明边界

### 8.1 跨域

M4→MIR 的执行形式已经存在，但 detector 是在错误 M4 标签上训练并冻结的，且 MIR safe accept 近乎零。因此当前结果不能表述为“跨域 detector 泛化成功”。修复 M4 标签并重新冻结模型之前，MIR 结果只可作为当前模型的行为观测。

重跑时必须按冻结计划分别报告 baseline、crop/cursor、end-early、repeat、acoustic、replace 1/2/4/8、missing/extra，并同时给出 safe accept/reject/uncertain，不能只报告 unsafe protection。

### 8.2 family-LOO

当前 family-LOO 继承了错误标签和极端 reject 策略；个别 family 的 test 分母也很小，例如 crop-early `n_test=64`。修复后需要：

- 每个 family 报 source-song 数，而不只报 units；
- 保证 leave-out family 的测试样本来自未参与模型/阈值选择的 songs；
- 对小分母给置信区间或明确标 exploratory；
- 与 always-reject baseline 同表比较。

### 8.3 stress

replace/missing 1/2/4/8 已有运行，但 `accept_rate=0` 不能单独证明压力检测有效，因为正常 safe 样本同样几乎不被接受。extra cohort 尚未完成；按设计，missing/extra 只作迁移和反例，不能替代产品主标签的真实错位评价。

## 9. 对当前结果可以保留的部分

以下实现和实验框架可以继续使用，不需要推倒重来：

- raw-target 与 official-target 分开；
- safe/unsafe/grey/ambiguous 标签类型和 100/250 ms 主阈值接口；
- evidence 到 H/R/O/V feature 的统一接口；
- 三态 unit/interval metrics；
- product-like crop、cursor、end-early、repeat、acoustic manifests；
- M4 heldout、family-LOO、M4→MIR、stress、serial 的评价入口；
- 当前 `tests/research_v7` 的 427 项测试。

但现有测试主要证明模块接口和机械流程可运行，没有覆盖“分段局部 GT → 整歌全局 GT”和“sparse 未查询单位不入 correctness 分母”这两个关键语义，因此测试全过不能关闭上述 P0。

## 10. 推荐返工顺序

### Phase A：只修标签，不训练

1. 以 source segment/unit 映射重写 M4 global GT materialization；
2. 以真实 slot query-set 修复 sparse 标签分母；
3. 增加第 2.4、3.3 节的语义回归测试；
4. 在少量歌曲上重跑 labels，并人工抽查 early/middle/late/repeat/sparse；
5. 输出按 song/family/view/target 的 safe/unsafe/grey/unavailable 分布。

若 baseline legal 仍呈现极端 unsafe，停止后续训练，继续检查 GT 与 model geometry，不得通过改阈值掩盖标签问题。

### Phase B：重新 pilot 与冻结工作点

1. 建立至少 18/6/6 的 source-song grouped split；
2. inner selection 同样按 song group；
3. 生成 signal atlas 与 rule baseline；
4. 比较 Logistic、GBDT 和至少一个非 H 小模型；
5. 与 always-accept/uncertain/reject 三个常量基线比较；
6. 在 validation 上同时冻结 protection 与 safe-accept 约束。

### Phase C：重跑独立评价

1. M4 song-heldout；
2. family-LOO；
3. M4→MIR by family；
4. replace/missing/extra stress；
5. full/sparse/overlap matched common-unit evaluation。

所有表必须同时报告 unsafe 与 safe 两侧成本，并提供 source-song macro。

### Phase D：重做 serial closed-loop

使用有 overlap、真实 cursor lineage、4–5 连续窗口、非零正常 commit 和一次冻结错误注入的 trajectories，重跑四条路线和有限多视图验证协议。

## 11. 最终验收清单

只有以下全部满足，才重新考虑 `detector_v2_completed=true`：

- [ ] M4 GT 已转换为 timeline 全局坐标，且不使用整歌字符贪心猜测 occurrence；
- [ ] sparse correctness 分母只包含 queried units；
- [ ] raw/official 标签均通过 multi-segment、later-window、repeat、sparse 测试；
- [ ] train/inner-val/outer-val/test 全部按 source song 分组；
- [ ] 实际样本量达到至少 18/6/6，或明确降级为 exploratory；
- [ ] signal atlas、rule baseline、Logistic、GBDT 和至少一个小模型完成公平比较；
- [ ] 工作点不等价于 always-reject，并公开 safe accept/reject/uncertain；
- [ ] M4 heldout 与 family-LOO 在修复后重新生成；
- [ ] M4→MIR 和 stress 在同一冻结模型上重新生成；
- [ ] serial 每条 trajectory 至少 4 个连续 overlap windows，发生真实状态传播；
- [ ] detector serial 路线有非零正确提交，多视图路线有实际额外请求；
- [ ] extra stress 和冻结计划要求的主要跨域 family 均有非零有效分母；
- [ ] 最终结论明确区分“保护 unsafe”与“接受 safe”。

在上述项目关闭前，现有结果只能作为管线 smoke 与负向诊断材料，不应作为 Detector V2 已完成或具备跨域产品能力的证据。

## 12. 2026-08-06 backlog 2-6 处理登记（总体 review 后）

对照 §11 清单之外的总体 review backlog，本轮已完成/登记：

1. **isotonic 校准后重冻结阈值（backlog #3）——负结果已登记**：`scripts/research_v7/refreeze_thresholds_isotonic.py`
   在修正标签 + song-grouped split 上验证：isotonic（train PAV）校准后 val 重冻结，
   safe_accept raw 0.0345→0.0 / official 0.0472→0.0（T_accept=0.0，prot95 1.0 但全 reject）。
   **结论：校准改善 ECE/Brier（sgcv 0.0197±0.0040）但不改善阈值下 safe_accept——safe/unsafe
   p 分布重叠是判别力问题（§9 safe_accept 低是 frozen 点属性），非校准问题。** 原
   FROZEN_OPERATING_POINTS.json 未被覆盖（产物 exploration/FROZEN_OPERATING_POINTS_V2.json）。
2. **F3 cross-view posterior 采集（backlog #4）——管线能力已实现，启用需 forward**：
   `detector_v2_evidence_converter.py` 新增 convert_evidence(keep_posterior, group_posteriors)
   → cross_view.posterior_distance（同 unit 多视图 mean pairwise L2，双侧均值）/
   posterior_vectors/reason（insufficient_posterior_views / topk_only_full_posterior_unavailable
   / class_space_mismatch）；features fallback 已兼容 dict 条目（双侧均值口径）。
   CLI `build_detector_v2_evidence.py --keep-posterior` 已接线；**group_posteriors 需真实
   forward 采集完整 posterior 后由调用方预解析提供，尚未接线**。启用步骤：real_executor
   截断点（L221-229）保留全量 softmax 向量 → 重 forward（1440 请求 GPU 4-8h，体积估算
   35-90GB，建议 float16/base64）→ --keep-posterior 转换 → collection 重消费。
3. **序列模型三选一（backlog #2）——决策为 sequence_level_viable（探索性）**：
   `evaluate_sequence_cnn1d.py` 新增序列级评价 seq_op + decision。真实 run2：窗口级
   broadcast 仍 degenerate（protocol 0.0），**序列级 protocol 1.0/AUC 1.0（n_seq_val=6，
   探索性小样本，仅指示性）**——序列级监督（段级预测）是可行方向，但需更大样本验证。
4. **19 §6 三交付物（backlog #5）——已补齐**：`build_detector_v2_audits.py` 产出
   PRECHECK_DETECTOR_V2.json（19/19 交付物存在、split 20/5/5 disjoint、预算 10h/12h OK）/
   HIDDEN_EXTRACTION_AUDIT.json（19131 行抽样 hidden available 0%，与 SIGNAL_ATLAS
   blocked_hidden 口径一致）/ REQUEST_IDENTITY_AUDIT.json（LABELS 1440 唯一 rid ↔
   evidence 1440 文件全对齐、quadruple 无重复；manifest 逻辑 id 层级仅登记）。
5. **stress 窗口级特征工程（backlog #6）——契约边界内实质负结论**：
   `analyze_stress_signal_gap.py` 在 18 个 stress family 上逐特征 rank-AUC/KS（只读
   H/R/O/V，family 仅分组）：**17/18 family best discriminative AUC 0.58-0.60（近随机），
   仅 repeated_section 0.664（raw_end_entropy）弱信号**——现有特征空间对窗口级文本
   扰动无实用判别力（STRESS_EVAL accept 0.87-0.93 的特征层面佐证）；mutation 感知
   特征需扩展证据契约（与 #4 posterior 管线对接，repeat 为起点）。
