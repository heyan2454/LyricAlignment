# LyricAlignment quick correction 二次审核与补修要求
**日期：2026-08-12**  
**用途：交由 Codex 复核，并让 OpenCode 对现有 quick correction 做一次小范围补修**  
**原则：只做文档、审计、简单重算和归档修复，不启动新的 GPU 实验。**

---

# 0. 当前状态

本次 `LyricAlignment_20260812_quick_correction.tar.gz` 的主要科学结论纠正基本成功：

- Detector 的 `light_merge` bug-fixed retrospective 结果已经正确更新；
- Recovery 旧的 14–16% oracle 结果已经降级为 synthetic-GT diagnostic；
- enhanced detector feature 的 negative result 已恢复为 unresolved；
- 当前结果已基本区分 formal / retrospective / exploratory / synthetic-GT diagnostic。

但是交付中仍有几处审计错误和归档不完整问题。

**当前状态不建议直接冻结归档。**

本轮补修只需要处理下面 5 项，不需要重新跑 GPU。

---

# 1. P0：重新修正 Metric Schema Audit

## 1.1 需要纠正的关键事实

重新检查原始实现后确认：

### Window-level gate 中的 `hit100`

`window_gate.py` 中实际使用：

```python
d["metrics"]["tolerance_hit_rates_ms"]["100"]
```

并赋值为：

```python
"hit100"
```

因此这里的 `hit100` 对应正式 real-GT reaggregate 中的：

```text
abs(start_error) <= 100 ms
AND
abs(end_error) <= 100 ms
```

也就是：

```text
both_boundaries_100ms
```

**不是 start-only 1 s。**

---

### 真正错误命名的是 semantic / subwindow evaluation

重点：

```text
eval_rule_subwindow.py
eval_subwindow.py
```

其中实际计算类似：

```python
abs(raw_start - gt_start) <= 1.0
```

但字段却命名为：

```text
hit100
```

其真实含义应为：

```text
start_hit_1s
```

因此：

```text
window_gate.py:
    hit100 = both_boundaries_100ms

eval_rule_subwindow.py:
    legacy hit100 = start_hit_1s

eval_subwindow.py:
    legacy hit100 = start_hit_1s
```

---

## 1.2 当前 audit 的问题

当前 `METRIC_SCHEMA_AUDIT.md`：

- 没有正确识别 `eval_rule_subwindow.py` / `eval_subwindow.py`；
- 反而把 `/tmp/opencode/window_gate_report.json` 中的正式 100 ms `hit100`
  错归类为 `start_only_1s`。

这需要修正。

---

## 1.3 要求

重新生成：

```text
METRIC_SCHEMA_AUDIT.md
```

至少分类为：

```text
both_boundaries_100ms
start_only_1s
other
unknown
```

并明确列出：

| File / Artifact | Field | Actual definition | Correct interpretation | Action |
|---|---|---|---|---|
| window_gate.py | hit100 | start+end <=100ms | both_boundaries_100ms | keep |
| eval_rule_subwindow.py | hit100 | start <=1s | start_hit_1s | rename |
| eval_subwindow.py | hit100 | start <=1s | start_hit_1s | rename |

如果需要兼容旧 artifact，可以保留：

```text
legacy_hit100
```

但必须标：

```text
deprecated = true
```

---

## 1.4 对已有 window-gate 结论的影响

这一修正意味着：

> window-level gate AUROC ≈0.9831 的 bad-window 定义实际上基于正式双边界 100 ms real-GT metric。

因此这项探索结果不需要因为“start-only 1s”问题而降级。

仍需保留：

```text
exploratory_test_tuned_threshold = true
formal_threshold = false
```

因为 threshold=0.45 是在已查看 A 的情况下探索得到，不是正式冻结阈值。

---

# 2. P0：修正 Synthetic-GT Usage Audit

## 2.1 当前错误

当前 `SYNTHETIC_GT_USAGE_AUDIT.md` 将：

```text
eval_rule_subwindow.py
eval_subwindow.py
```

标成类似：

```text
synthetic = unknown
used_for_correctness = false
```

这是错误的。

原始逻辑明确从：

```text
LONG_TIMELINE_MANIFEST.canonical_units
```

取：

```text
start_sec
end_sec
```

作为评分 reference。

典型逻辑：

```python
songs[d["song_id"]] = {
    u["canonical_unit_id"]: u
    for u in d["canonical_units"]
}

mae = abs(raw_start - gt["start_sec"])
hit = mae <= 1.0
```

这属于：

```text
synthetic_uniform_timeline
```

并且确实被用于 correctness evaluation。

---

## 2.2 正确分类

至少应改为：

```text
synthetic = true
synthetic_kind = synthetic_uniform_timeline
used_for_correctness = true
valid_for_realgt_correctness = false
conclusion_affected = true
```

---

## 2.3 要求

重新生成：

```text
SYNTHETIC_GT_USAGE_AUDIT.md
```

不要完全依赖简单 heuristic scanner。

对于已知关键脚本，允许明确做人工 / known override。

至少检查：

```text
run_oracle_recovery.py
eval_rule_subwindow.py
eval_subwindow.py
```

并对当前 session 相关脚本全局搜索：

```text
LONG_TIMELINE_MANIFEST
canonical_units
start_sec
end_sec
gt_start
gt_end
oracle
recovery
correctness
```

最终表格至少：

| File | GT source | synthetic/real | Used for correctness | Valid for real-GT correctness | Conclusion affected |
|---|---|---|---|---|---|

---

# 3. P1：补齐 `gt_provenance` 相关代码和测试

## 3.1 当前问题

现有 patch 中多个脚本新增了：

```python
from lyricalign.research_transition_recovery_detector import gt_provenance
```

但是当前 quick correction 包中没有：

```text
src/lyricalign/research_transition_recovery_detector/gt_provenance.py
```

同时测试记录声称：

```text
test_gt_provenance.py
3 passed
```

但 correction 包和 patch 中也没有：

```text
tests/research_transition_recovery_detector/test_gt_provenance.py
```

因此：

> 当前 quick correction 包无法单独恢复本轮 provenance 修改。

---

## 3.2 要求

必须把以下文件真正加入交付：

```text
src/lyricalign/research_transition_recovery_detector/gt_provenance.py
tests/research_transition_recovery_detector/test_gt_provenance.py
```

同时：

- 更新 patch；
- 更新 changed-files list；
- 更新 IMPLEMENTATION_CHANGELOG；
- 更新 test summary。

要求最终 correction 包自身具备可恢复性。

不能依赖：

> “服务器当前 worktree 里碰巧已经存在这些文件”。

---

# 4. P1：重做真正的 per-song failure concentration

## 4.1 当前结果不符合要求

当前：

```text
song_failure_concentration.csv
```

实际上只有类似：

```text
baseline/long_timeline_60s
missing/long_timeline_60s
```

两行。

这不是：

```text
per-song
Raw / Official separated
failure concentration
```

因此不能作为原任务的完成结果。

---

## 4.2 应从现有 artifact 重算

优先读取已有：

```text
LABELS.jsonl
```

或者其他已有 unit-level real-GT label artifact。

至少按：

```text
target = raw / official
song_id
family
label = safe / grey / unsafe
```

统计。

建议生成：

```text
results/song_failure_concentration.csv
results/song_failure_concentration.md
```

字段至少：

```text
cohort
target
song_id
family
n_labeled
n_safe
n_grey
n_unsafe
unsafe_fraction
share_of_target_all_unsafe
cumulative_unsafe_share
```

按：

```text
target
share_of_target_all_unsafe DESC
```

排序。

---

## 4.3 额外建议

生成：

```text
top1 cumulative share
top2 cumulative share
top3 cumulative share
top5 cumulative share
```

用于回答：

> catastrophic failures 是否高度集中在少量歌曲。

---

## 4.4 如果能恢复 detector decision

如果修复后 unit-level detector decision 仍可从已有 artifact 映射回：

```text
song_id
unit_id
target
```

则进一步输出：

```text
unsafe_accept
unsafe_protected
protected_recall
safe_accept
```

按 song 分组。

如果现有 artifact 无法可靠恢复：

> 只输出 GT failure concentration。

不要用 request-level 两行 summary 冒充 per-song detector concentration。

---

# 5. P2：清理 Archive Reference Audit，并补 final repo state

## 5.1 当前 archive audit false positive 太多

当前报告类似：

```text
200 references
99 missing
```

但大量所谓 missing 实际是：

```text
n_units / duration
seconds / density
gt=0/1
0.901/0.857
```

这些明显不是文件路径。

因此当前 `99 missing` 没有实际解释价值。

---

## 5.2 要求重新过滤

重新生成：

```text
ARCHIVE_REFERENCE_CHECK.md
```

只保留真正可能是：

- 文件；
- 目录；
- result artifact；
- session doc；
- plan；
- correction note。

过滤：

- 数值；
- metric expression；
- 比例；
- inline formula；
- 普通变量名。

---

## 5.3 重点人工核查

特别检查：

```text
AI_SESSION_ENTRY.md
README*
SESSION*
PHASE*
```

以及其中指向：

```text
docs 14–20
result artifacts
session entries
correction notes
plans
```

真正缺失且无法恢复的，写：

```text
referenced but not present in current archive
```

禁止伪造。

---

## 5.4 补充 final repo state

当前：

```text
00_meta/REPO_STATE.json
```

记录：

```text
read-only audit; no files modified in worktree
```

但 `IMPLEMENTATION_CHANGELOG.md` 又记录了 worktree 修改。

这很可能只是 snapshot 时点不同。

需要补明确字段：

```text
snapshot_phase = pre_execution
```

或：

```text
snapshot_phase = post_execution
```

并建议再生成最终：

```text
00_meta/FINAL_REPO_STATE.json
```

至少记录：

```text
repo_path
git_head
dirty
changed_files
snapshot_phase = post_execution
```

若 git unavailable：

```text
git_head = unavailable
```

禁止伪造。

---

# 6. 本轮不允许扩大范围

本轮补修明确：

```text
DO NOT
```

- 不重新跑 GPU formal experiments；
- 不重新训练 detector；
- 不重新搜索正式 threshold；
- 不跑新的 B-freeze → A-test；
- 不跑 semantic fixed-vs-semantic formal GPU；
- 不跑 closed-loop recovery；
- 不重写 recovery 算法；
- 不重新生成大规模数据集；
- 不修改 detector architecture；
- 不修改 window planner 核心算法。

本轮只做：

```text
audit fix
documentation fix
simple recomputation
packaging completeness
CPU tests
```

---

# 7. 需要保留的当前有效结论

## Detector

当前 bug-fixed retrospective A-heldout：

### Raw

- protected recall = **0.956656**
- reject recall = **0.947368**
- safe accept = **0.831983**
- longest continuous unsafe leak = **1 unit**

### Official

- protected recall = **0.962751**
- reject recall = **0.931232**
- safe accept = **0.730263**
- longest continuous unsafe leak = **1 unit**

仍必须标：

```text
evaluation_type = retrospective_after_light_merge_fix
threshold_source = pre_fix_frozen_threshold
```

不能写成新的 untouched formal test。

---

## Recovery

旧：

```text
O0 ≈ 13.94%
O1 ≈ 15.86%
O2 ≈ 15.86%
```

应继续保持：

```text
historical synthetic-GT oracle diagnostic
```

不能作为：

```text
real-GT recovery upper bound
```

---

## Semantic / short-window

可以保留：

> 短窗和重新配对明显缓解 timestamp pile-up、乱序和 collapse，支持 window length / pairing 是重要 failure condition。

不能写：

> 已经完成正式 real-GT semantic-window accuracy 验证。

---

## Window-level gate

纠正后可明确：

> window-gate 的 bad-window definition 使用正式双边界 100 ms real-GT metric。

已有：

```text
AUROC ≈ 0.9831
```

仍然只属于 exploratory ranking evidence。

test-tuned threshold：

```text
0.45
```

不能写入正式配置。

---

# 8. 最终要求生成的补修资料

建议直接覆盖/更新现有 correction 目录：

```text
/home/hyan/LyricAlignment_20260812_quick_correction/
```

至少补齐/更新：

```text
CODEX_REVIEW.md
METRIC_SCHEMA_AUDIT.md
SYNTHETIC_GT_USAGE_AUDIT.md
ARCHIVE_REFERENCE_CHECK.md
IMPLEMENTATION_CHANGELOG.md
00_meta/FINAL_REPO_STATE.json
```

以及：

```text
results/song_failure_concentration.csv
results/song_failure_concentration.md
```

必须包含：

```text
src/lyricalign/research_transition_recovery_detector/gt_provenance.py
tests/research_transition_recovery_detector/test_gt_provenance.py
```

或至少保证它们完整存在于：

```text
patches/
```

并可独立恢复。

---

# 9. 测试要求

只跑相关 CPU / 快速测试。

至少：

1. `gt_provenance` tests；
2. semantic metric rename tests；
3. legacy alias compatibility；
4. synthetic GT warning / provenance；
5. archive audit parser tests（如有）；
6. per-song concentration 计算 smoke；
7. 现有相关 unit tests。

记录：

```text
command
environment
passed
failed
skipped
runtime
```

---

# 10. 完成条件

只有以下全部满足才算本轮补修完成：

- [ ] window-gate `hit100` 正确标为双边界 100 ms；
- [ ] semantic/subwindow `hit100` 正确改为 `start_hit_1s`；
- [ ] `eval_rule_subwindow.py` synthetic-GT 分类修正；
- [ ] `eval_subwindow.py` synthetic-GT 分类修正；
- [ ] synthetic-GT audit 重新生成；
- [ ] `gt_provenance.py` 被纳入交付；
- [ ] `test_gt_provenance.py` 被纳入交付；
- [ ] per-song Raw/Official failure concentration 已重新生成；
- [ ] archive audit false positives 已明显清理；
- [ ] final repo state 已生成；
- [ ] patch / changed-files / changelog 同步；
- [ ] CPU tests 通过；
- [ ] 更新后的 correction 包重新打包到 `/home/hyan`。

---

# 11. 当前最终判断

这次 quick correction 的核心科学结论修正方向是正确的。

当前需要补的主要不是实验，而是：

> **Metric schema 审计准确性、synthetic-GT 污染识别、per-song 简单统计，以及交接包自身可复现性。**

这些补完后，才适合把 quick correction 正式冻结成下一轮实验的基线归档。
