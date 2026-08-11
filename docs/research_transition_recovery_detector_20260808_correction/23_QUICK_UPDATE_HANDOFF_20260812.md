# LyricAlignment 当前工作快速更新交接说明
**日期：2026-08-12**  
**用途：先交由 Codex 审核，再由 OpenCode 进行快速、低风险更新**  
**目标：不启动新的大规模 GPU 实验，优先修正文档口径、补充 provenance、统一 metric schema，并基于现有结果做少量可复现计算。**

---

# 0. 总体要求

本轮不是新实验阶段，而是一次 **结果口径纠正 + 归档清理 + 低风险代码修复 + 现有数据重算**。

要求：

1. 先由 Codex 审核本说明中的结论与修改范围。
2. Codex 审核通过后，再让 OpenCode 执行。
3. OpenCode 不得自行扩大任务范围。
4. 不启动新的 formal GPU 实验。
5. 不重新训练 detector。
6. 不重写 recovery 主算法。
7. 不重新生成数据集或大规模 manifest。
8. 所有新增/修改内容必须记录 provenance、输入来源与计算口径。
9. **最终更新资料必须打包并放在 `/home/hyan`。**

建议最终目录：

```text
/home/hyan/LyricAlignment_20260812_quick_correction/
```

并在 `/home/hyan` 下额外生成一个压缩包，例如：

```text
/home/hyan/LyricAlignment_20260812_quick_correction.tar.gz
```

或：

```text
/home/hyan/LyricAlignment_20260812_quick_correction.zip
```

---

# 1. 当前需要优先纠正的结论

## 1.1 Detector：`light_merge` 修复后的结果应成为当前主要诊断结果

此前 Detector Phase 4.2 的 A-heldout 结果中：

- Raw protected recall ≈ 0.904
- Official protected recall ≈ 0.914

后续发现 `light_merge` 的 post-processing 存在保护语义错误：

> 孤立的 REJECT 岛可能因为左右都是 ACCEPT 而被重新翻成 ACCEPT。

该行为违反 detector 的保护优先契约。

修复后的语义应为：

> 只允许填补 ACCEPT 岛；REJECT 不能因为 smoothing 被翻回 ACCEPT。

在使用 **同一冻结阈值**、同一 A-heldout 数据重新评估后，得到：

### Raw

- protected recall = **0.9567**
- reject recall = **0.9474**
- safe accept = **0.8320**
- unsafe accept = **14 / 323**
- unsafe interval protected@75 ≈ **0.872**
- longest continuous leaked unsafe = **1 unit**

### Official

- protected recall = **0.9628**
- reject recall = **0.9312**
- safe accept = **0.7303**
- unsafe accept = **13 / 349**
- unsafe interval protected@75 ≈ **0.879**
- longest continuous leaked unsafe = **1 unit**

这些数字应作为当前 detector 的主要 bug-fixed 结果。

但是必须明确标注：

```text
evaluation_type = retrospective_after_light_merge_fix
threshold_source = pre_fix_frozen_threshold
```

**不能表述成一次新的 clean formal freeze → untouched test。**

原因：

- 阈值来自修复前的冻结过程；
- A 已经在后续自由探索中被反复查看；
- 因而当前结果是非常有价值的 retrospective bug-fixed evidence，但不是最终 formal test。

---

## 1.2 Detector family-LOO 修复后结果也应更新

修复后：

### Raw

- baseline excluded:
  - protected recall ≈ **0.9624**
  - safe accept ≈ **0.8421**
- missing excluded:
  - protected recall ≈ **0.9489**
  - safe accept ≈ **0.8270**

### Official

- baseline excluded:
  - protected recall ≈ **0.9706**
  - safe accept ≈ **0.7478**
- missing excluded:
  - protected recall ≈ **0.9517**
  - safe accept ≈ **0.7180**

注意 Raw missing-excluded 的 protected recall ≈0.9489，略低于 0.95，因此不能概括成“所有 family-LOO 条件均稳定达到 R95”。

---

## 1.3 旧的 detector enhanced-feature negative result 不能继续视为冻结结论

此前有：

- R+repair
- R+crossview
- R+neigh
- R+all

曾得到类似 `0 / 5 feasible`，并据此倾向认为增强特征没有意义。

但这些结果是在 `light_merge` bug 存在时完成。修复 post-processing 后，基础 R 路线本身已经明显改善。

因此当前正确状态应改为：

```text
status = unresolved_after_bugfix
```

而不是：

```text
status = disproved
```

本轮不要求重新训练或完整重跑这些增强特征方案，但要把其 negative result 从“冻结结论”恢复为“待修复后复评”。

---

# 2. Recovery：必须纠正 synthetic-GT 结论

## 2.1 当前 Phase 4.3 oracle recovery 不能称为 real-GT upper bound

已有文档中报告过：

- O0 recovery ≈ **13.94%**
- O1 recovery ≈ **15.86%**
- O2 recovery ≈ **15.86%**

并进一步写成类似：

> oracle recovery 上界约 15.9%。

这个结论必须撤回/降级。

需要 Codex 核查：

```text
run_oracle_recovery.py
```

重点检查 GT 来源是否为：

```text
LONG_TIMELINE_MANIFEST
canonical_units
```

如果仍直接使用其中的 `start_sec/end_sec` 作为 correctness GT，则该 GT 属于此前已经明确需要废弃的：

```text
synthetic_uniform_timeline
```

而不是 accepted real-GT projection。

如果核查成立，则应把 13.94% / 15.86% / 15.86% 统一重新标注为：

```text
historical synthetic-GT oracle diagnostic
```

不能写：

```text
real-GT oracle recovery upper bound
```

也不能据此声称：

```text
模型重试能力本质上最多只能修复约 16%
```

---

## 2.2 O0/O1/O2 的 GT 使用契约也需要审计

需要确认：

- O1 是否直接通过 GT 选择正确 head；
- O2 是否通过 GT 提供 exact-pair query；
- O0 是否通过 GT 时间范围选择 retry/query。

如果是，则这些路线也不符合后续更严格的 no-GT recovery 契约：

> GT 只能用于识别实验中的错误和最终评分，不能直接参与 retry/query/writeback 选择。

因此 Phase 4.3 只能保留为 diagnostic oracle mechanism exploration。

---

# 3. Semantic / short-window exploration：指标与结论需要纠正

## 3.1 当前 `hit100` 命名存在 metric schema 混淆

正式 real-GT reaggregate 中的 `"100"` / `hit100` 口径应核查为：

```text
abs(start_error) <= 100 ms
AND
abs(end_error) <= 100 ms
```

但自由探索中的：

```text
eval_rule_subwindow.py
eval_subwindow.py
```

若实际计算是：

```python
abs(raw_start - gt_start) <= 1.0
```

则其真正含义是：

```text
start-only hit within 1 second
```

而不是 100 ms。

因此所有这类字段应改名为：

```text
start_hit_1s
```

如需保持旧 artifact 兼容，可暂时同时输出：

```text
start_hit_1s
legacy_hit100
```

但必须明确：

```text
legacy_hit100 = deprecated
```

禁止继续把 0.53 / 0.57 与正式 100 ms correctness 混在一起。

---

## 3.2 semantic-window 当前 accuracy 结果不能称为 real-GT

需要 Codex 核查：

```text
eval_rule_subwindow.py
eval_subwindow.py
```

以及 semantic window planner 的输入 GT / timeline 来源。

若仍然从：

```text
LONG_TIMELINE_MANIFEST.canonical_units.start_sec/end_sec
```

读取时间，则其 correctness reference 仍是 synthetic-uniform timing。

如果 automatic semantic planner 的子窗边界也由该 synthetic unit timing 推导，则存在：

```text
synthetic timing 定义 text/audio 配对
→ 模型推理
→ 同一 synthetic timing 再用于评分
```

因此目前只能保留以下机制性结论：

> 将长窗口中的重复元音/衬词困难区域拆短并重新配对后，原先明显的 timestamp pile-up、乱序、窗口起点吸附等 collapse 行为显著缓解。

不能写：

> automatic semantic planner 已经在 real GT 上证明准确率从 X 提升到 Y。

---

# 4. 当前可保留的机制观察

## 4.1 Raw posterior 对 catastrophic failure 有明显异常信号

已观察到某些灾难窗口中：

- 多字符 timestamp pile-up；
- raw timestamp 大量相同；
- raw 输出顺序反转；
- start diff 可出现大幅负值；
- entropy 明显升高；
- margin 明显降低。

已有记录示例：

- clustered mean entropy ≈ **6.09**
- solo mean entropy ≈ **3.45**
- clustered margin ≈ **0.008**
- solo margin ≈ **0.240**

这支持：

> catastrophic alignment failures 并非完全隐藏在 raw posterior 中，Raw-only detector 能利用模型自身异常信号进行保护。

---

## 4.2 错误高度集中于少数歌曲/窗口

A Raw unsafe 中，已有观察：

- `绒花`：199
- `月满西楼`：52
- A Raw total unsafe：323

两首合计约占 77.7%。

B 中：

- `我爱你中国`：115 unsafe
- B Raw total unsafe：187

当前合理研究叙述是：

> 问题不是所有窗口均匀低质量，而是少数特定歌词结构/长窗配对条件触发 catastrophic collapse。

本轮可以让 OpenCode 基于现有结果自动生成完整 per-song concentration 表。

---

# 5. 本轮建议 OpenCode 完成的简单计算

以下计算全部要求：

- 只读取已有结果；
- 不重新跑 GPU 推理；
- 不重新训练；
- 不改变模型；
- 保存输入 artifact 路径和 schema；
- 每个输出标注生成时间和代码版本。

## 5.1 Corrected detector summary

生成：

```text
results/corrected_detector_summary.json
results/corrected_detector_summary.md
```

至少包含 Raw / Official：

- protected recall
- reject recall
- safe accept
- unsafe accept count / denominator
- unsafe interval protected@75
- longest continuous unsafe leak
- family-LOO
  - baseline excluded
  - missing excluded

同时记录：

```text
evaluation_type = retrospective_after_light_merge_fix
threshold_source = pre_fix_frozen_threshold
dataset/cohort = A-heldout
postprocess_fix = light_merge_reject_preservation
new_training = false
new_threshold_search = false
```

---

## 5.2 Before/after `light_merge` 对照

自动生成：

```text
results/light_merge_before_after.md
```

至少包含：

| Metric | Raw Before | Raw After | Official Before | Official After |
|---|---:|---:|---:|---:|
| protected recall | 0.904 | 0.9567 | 0.914 | 0.9628 |
| safe accept | 0.900 | 0.8320 | 0.839 | 0.7303 |
| unsafe accept | 31/323 | 14/323 | 30/349 | 13/349 |

如果原始 JSON 中精确数字与此略有差异，以原始 artifact 为准，并在文档中注明来源。

---

## 5.3 Per-song failure concentration

生成：

```text
results/song_failure_concentration.csv
results/song_failure_concentration.md
```

Raw / Official 分开，字段建议：

```text
cohort
route
song_id
num_labeled_units
num_safe_units
num_unsafe_units
unsafe_fraction
share_of_all_unsafe
```

按 `share_of_all_unsafe` 降序排序，同时生成 top-1 / top-2 / top-3 / top-5 cumulative share。

---

## 5.4 Window-level detector gate 的探索性重算

基于已有 90 requests 输出：

```text
results/window_gate_score_summary.json
results/window_gate_threshold_sweep.csv
results/window_gate_exploratory.md
```

包括：

- AUROC
- AUPRC
- 每个 score 的分布
- bad/good window 数
- per-song bad/good 数
- threshold sweep

threshold sweep 字段：

```text
threshold
TP
FP
TN
FN
recall
false_positive_rate
precision
specificity
```

已有探索中 `frac(p_bad > T_accept)` AUROC ≈ **0.9831**，test-tuned threshold `0.45` 得到：

- bad: 15/15 captured
- good: 9/75 false rejected
- FPR ≈ 12%

这些数字可以复算，但必须标注：

```text
exploratory_test_tuned_threshold = true
formal_threshold = false
```

禁止把 0.45 自动写入正式配置。

---

# 6. 本轮建议 OpenCode 完成的低风险代码修复

## 6.1 修复 semantic metric 字段名

检查：

```text
hit100
hit_100
100ms
```

所有出现位置。

区分：

1. 真正 `start+end <=100ms`
2. `start-only <=1s`
3. 不明确

对第 2 类统一改为：

```text
start_hit_1s
```

如兼容旧 artifact：

```text
legacy_hit100
```

仅作为 deprecated alias。

要求更新：

- 代码
- JSON schema
- Markdown 文档
- README / session notes
- tests

---

## 6.2 semantic window 边界 round / clamp

此前已观察到类似：

```text
audio duration = 181.34975
round(..., 4) = 181.35
```

可能导致序列化后 `audio_end > exact_audio_duration`。

需要检查至少：

```text
PlannedWindow.to_dict()
build_long_timeline_manifest.py
```

修复原则：

```text
0 <= audio_start < audio_end <= exact_audio_duration
```

优先：

1. 使用精确 duration 做 clamp；
2. 再做 serialization；
3. serialization 后再次保证不越界。

不要改变 planner 的核心策略。

至少新增测试：

- 非整数 duration；
- 尾窗；
- 4 位 round 会向上越界；
- fixed window；
- semantic window；
- 极短合法尾窗；
- serialization round-trip。

---

## 6.3 synthetic GT provenance / warning

对任何仍然使用：

```text
LONG_TIMELINE_MANIFEST.canonical_units
```

作为 correctness GT 的脚本，增加显式 provenance。

重点检查：

```text
run_oracle_recovery.py
eval_rule_subwindow.py
eval_subwindow.py
```

至少要求运行日志/结果 JSON 中写入：

```text
gt_kind = synthetic_uniform_timeline
valid_for_realgt_correctness = false
```

并输出 warning：

```text
WARNING:
Using synthetic_uniform_timeline GT.
This result must not be interpreted as real-GT correctness/recovery.
```

本轮无需把它们全部重写成 real-GT 实验。

---

# 7. Codex 必须先完成的审计

## 7.1 `light_merge` 修复合法性

确认：

- detector score 没变化；
- model 没重新训练；
- threshold 没重新搜索；
- dataset/cohort 相同；
- metric schema 相同；
- 只有 post-processing 语义修复。

结果写入：

```text
CODEX_REVIEW.md
```

建议明确：

```text
VALID:
retrospective bug-fixed evaluation

NOT VALID AS:
new untouched formal test
```

---

## 7.2 Synthetic GT 使用范围

搜索：

```text
LONG_TIMELINE_MANIFEST
canonical_units
uniform
gt_start
gt_end
oracle
recovery
```

生成：

```text
SYNTHETIC_GT_USAGE_AUDIT.md
```

表格至少：

| File | GT source | synthetic/real | Used for correctness? | Conclusion affected? |
|---|---|---|---|---|

不要只检查已知三个脚本，应对当前 session 相关代码做一次全局搜索。

---

## 7.3 Metric schema 审计

搜索：

```text
hit100
hit_100
100ms
1.0
tolerance
start_error
end_error
```

生成：

```text
METRIC_SCHEMA_AUDIT.md
```

分类：

- start+end ≤100 ms
- start-only ≤1 s
- 其他
- 未知/需人工确认

---

## 7.4 Archive reference integrity

检查：

```text
AI_SESSION_ENTRY.md
README*
SESSION*
PHASE*
```

以及所有其中引用的：

- 文档路径；
- result artifact；
- correction note；
- plan；
- session number。

已有观察：

> 当前 `AI_SESSION_ENTRY.md` 指向 correction 文档 14–20，但现有工作目录归档中并非全部自包含。

请实际核查，不要直接相信这句话。

生成：

```text
ARCHIVE_REFERENCE_CHECK.md
```

字段：

```text
reference_source
referenced_path
present
missing
recovered
recovery_source
notes
```

若缺失且无法从当前 evidence 恢复：

```text
referenced but not present in current archive
```

禁止根据上下文自行伪造。

---

# 8. 需要同步更新的文档范围

Codex 审核后，请 OpenCode 全局搜索并更新所有受影响文档。

至少包括可能存在的：

```text
PHASE43_44_CONCLUSION.md
PHASE42*
DETECTOR*
RECOVERY*
SEMANTIC*
AI_SESSION_ENTRY.md
README*
SESSION*
EXPERIMENT*
RESULT*
CONCLUSION*
```

更新原则：

### Detector

旧：

> protected recall ~90%

改为：

> bug-fixed retrospective protected recall Raw ≈95.7%, Official ≈96.3%，但以更低 safe accept 为代价。

并保留旧数字作为历史 pre-fix 结果。

### Recovery

旧：

> oracle recovery upper bound ≈15.9%

改为：

> 该结果使用 synthetic-uniform timeline GT，只能作为历史 oracle diagnostic；real-GT recovery capability 尚未得到可信估计。

### Semantic window

旧：

> semantic planner real-GT accuracy 达到/提升到 X

改为：

> 当前结果提供 window-length / pairing 对 timestamp collapse 的机制证据；现有 accuracy evaluation 仍受 synthetic timing 影响，正式 real-GT correctness 待重做。

### Enhanced detector features

旧：

> enhanced features 被证伪/无收益

改为：

> negative result 受 `light_merge` bug 污染，修复后需要重新评估；当前状态 unresolved。

---

# 9. 本轮明确不做的事情

OpenCode 必须遵守：

- 不重新跑完整 T1/T2/T3 formal GPU experiments；
- 不跑 full-song GPU reaggregation；
- 不训练 detector；
- 不重新进行 threshold search 并称为 formal；
- 不做 B-freeze → A-test 正式新实验；
- 不跑 semantic fixed-vs-semantic formal GPU experiment；
- 不跑 closed-loop recovery；
- 不重写 recovery 算法；
- 不修改 detector architecture；
- 不修改主要 mutation/data generation 策略；
- 不重新生成大规模数据集；
- 不直接声称新的 SOTA 或最终生产性能；
- 不把 test-tuned threshold 写入生产配置。

---

# 10. 最终要求放入 `/home/hyan` 的更新资料

本轮完成后，要求最终目录至少为：

```text
/home/hyan/LyricAlignment_20260812_quick_correction/
```

建议结构：

```text
LyricAlignment_20260812_quick_correction/
│
├── CODEX_REVIEW.md
├── IMPLEMENTATION_CHANGELOG.md
├── SYNTHETIC_GT_USAGE_AUDIT.md
├── METRIC_SCHEMA_AUDIT.md
├── ARCHIVE_REFERENCE_CHECK.md
│
├── results/
│   ├── corrected_detector_summary.json
│   ├── corrected_detector_summary.md
│   ├── light_merge_before_after.md
│   ├── song_failure_concentration.csv
│   ├── song_failure_concentration.md
│   ├── window_gate_score_summary.json
│   ├── window_gate_threshold_sweep.csv
│   └── window_gate_exploratory.md
│
├── updated_docs/
│   └── [所有本轮修改后的归档/结论文档副本或变更清单]
│
├── patches/
│   └── [代码 patch / git diff / changed-files list]
│
└── tests/
    ├── test_summary.md
    └── [必要的新增/修改测试记录]
```

同时要求在 `/home/hyan` 下生成最终压缩包：

```text
/home/hyan/LyricAlignment_20260812_quick_correction.tar.gz
```

或：

```text
/home/hyan/LyricAlignment_20260812_quick_correction.zip
```

---

# 11. 必须同时更新原工作目录

除了生成独立 correction 包外：

**对经 Codex 确认应修改的文档与低风险代码，应直接更新当前 LyricAlignment 工作目录。**

独立 correction 包用于审核、交接、provenance 和以后追踪，不能只在 correction 包里修改副本而不更新工作目录。

要求记录：

```text
repo_path
git_head_before
git_head_after
changed_files
```

若当前目录未使用 git 或无法获取 commit，也必须记录：

```text
git_head = unavailable
```

禁止伪造。

---

# 12. 测试要求

本轮仅需 CPU / 快速测试。

至少覆盖：

1. `light_merge` REJECT preservation；
2. semantic metric rename；
3. legacy alias compatibility（若保留）；
4. semantic/fixed window boundary clamp；
5. non-integer audio duration；
6. tail serialization 不越界；
7. synthetic-GT provenance 字段；
8. 当前已有相关单元测试不回归。

记录：

```text
command
environment
passed
failed
skipped
runtime
```

不要求跑与本次变更无关的全部重型测试。

---

# 13. 最终状态文档建议统一写法

## Detector

> Raw/Official no-GT detector signal 已显示出较强 catastrophic-error protection 能力。`light_merge` bug 修复后的 retrospective A-heldout evaluation 中，Raw protected recall ≈95.7%，Official ≈96.3%；代价是 safe accept 降低。该结果尚不是新的 clean formal freeze→untouched-test。

## Failure structure

> Catastrophic errors 高度集中于少数歌曲/窗口。重复元音、衬词与长窗口 text/audio pairing 是已观察到的重要 failure condition。Raw posterior 在这些失败时存在明显 entropy、margin、timestamp-order 等异常信号。

## Semantic / window planning

> 短窗和重新配对能够明显缓解 timestamp collapse，支持 window length / pairing 的因果机制假设。但现有 semantic-window accuracy evaluation 使用 synthetic timeline，不可解释为正式 real-GT correctness。

## Recovery

> 当前已有的约 14–16% oracle recovery 数字使用 synthetic-uniform GT，并可能直接利用 GT 选择 retry/query，因此不能作为 real-GT/no-GT recovery upper bound。真实 recovery capability 当前仍未知。

## Transition / end-to-end

> real-GT 修正后的 T1/T2/T3/full-song 正式对比以及 detector-triggered closed-loop recovery 仍属于后续实验，不在本轮快速更新中执行。

---

# 14. 完成条件

- [ ] Codex 已审核 `light_merge` 复评口径；
- [ ] recovery synthetic-GT 使用已审计；
- [ ] metric schema 已审计；
- [ ] archive reference 已审计；
- [ ] detector bug-fixed summary 已重新生成；
- [ ] per-song failure concentration 已重新生成；
- [ ] window gate exploratory sweep 已生成；
- [ ] semantic `hit100` 命名已纠正；
- [ ] semantic boundary clamp 已修复并测试；
- [ ] synthetic GT provenance/warning 已加入；
- [ ] 受影响结论文档已统一修改；
- [ ] enhanced-feature negative result 已恢复为 unresolved；
- [ ] 变更清单与测试记录齐全；
- [ ] 当前工作目录已同步更新；
- [ ] `/home/hyan/LyricAlignment_20260812_quick_correction/` 已生成；
- [ ] `/home/hyan` 下最终压缩包已生成。

---

# 15. 本轮任务核心原则

本轮的目的不是增加更多实验，而是：

> **把“真实结论、bug-fixed retrospective evidence、synthetic-GT diagnostic、exploratory result、pending formal experiment”彻底分开。**

只有完成这个清理，下一轮实验才能在统一 GT、统一 metric schema 和清晰 provenance 下继续，避免再次把探索结果误写成正式结论。
