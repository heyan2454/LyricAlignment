# Codex 审核后的 OpenCode 二次补修实施方案（2026-08-12）

## 0. 任务边界与结论

**权威输入：** `25_QUICK_CORRECTION_REVIEW_FOLLOWUP_20260812.md`；它补正
Document 24 的 quick-correction 实施结果，不取代 Documents 14--20 的 real-GT
下一轮主线。

**本轮允许：** 文档与审计修正、已有 unit-level artifact 的纯 CPU 重算、可恢复性交付
补全、快速单元测试、重新打包。

**本轮禁止：** GPU/model forward、detector 训练、任何正式阈值搜索、B-freeze→A-test、
semantic formal、closed-loop recovery、数据集/manifest 重建、detector 或 planner 核心算法改写。

交付根固定为 `/home/hyan/LyricAlignment_20260812_quick_correction/`。在该目录原有
内容上增量更新，但不得删除旧交付物；以新的 `FINAL_REPO_STATE.json`、changelog 和 tarball
明确其最终状态。

### 已复核事实

1. `/tmp/opencode/window_gate.py:77` 将 `hit100` 取自
   `metrics.tolerance_hit_rates_ms["100"]`。这是每 unit 的 start **与** end 都在
   100 ms 内的正式 real-GT reaggregate 指标；window bad 定义 `hit100 < 0.7` 应保留。
2. `/tmp/opencode/eval_rule_subwindow.py` 与 `/tmp/opencode/eval_subwindow.py` 都从
   `LONG_TIMELINE_MANIFEST.canonical_units` 取 `start_sec`，计算
   `abs(raw_start - gt_start) <= 1.0`，却把结果叫作 `hit100`。这是
   `synthetic_uniform_timeline` 上的 `start_hit_1s`。
3. 现有 `quick_correction_audit.py` 对裸 token `hit100` 做全局默认归类，且
   `KNOWN_OVERRIDES` 未覆盖这两个 subwindow 脚本。这会把 window-gate artifact 错归类，
   也漏掉两份 synthetic-GT correctness 使用；必须改为**来源/证据优先**的分类。
4. `gt_provenance.py` 和 `test_gt_provenance.py` 目前存在于工作树但为未跟踪文件；仅
   `git diff` 不会把它们带进补丁包。因此交付必须显式收录新增文件内容/补丁。

## 1. 统一执行约定

在仓库根执行：

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
export PYTHONPATH=src
DELIVERY=/home/hyan/LyricAlignment_20260812_quick_correction
```

开始时记录 `git rev-parse HEAD`、`git status --short`、环境、及 delivery 已有文件的
SHA-256。不得修改、重置或暂存现有无关 dirty changes。所有新生成的 JSON/CSV/MD 均写：
输入绝对路径与 SHA-256、命令、UTC、git HEAD、`result_status`。

如果某个来源仅位于 `/tmp/opencode`，它是审计证据而非仓库实现：在 audit 中记录绝对路径及
SHA-256；只有被确认应纳入仓库的代码，才复制/实现为受测试的仓库文件。不得把 `/tmp` 文件
的存在误称为 repository provenance。

## 2. WP-F1（P0）：按来源修正 Metric Schema Audit

### 问题与根因

`hit100` 名字本身不携带语义；当前 token-first 规则把
`/tmp/opencode/window_gate_report.json` 误判为 start-only 1s。

### 实现

修改 `scripts/research_transition_recovery_detector/quick_correction_audit.py`：

- 增加路径/脚本级 known override，优先级高于 token heuristic：
  - `window_gate.py` 及它的 `window_gate_report.json`：
    `both_boundaries_100ms`；证据为 `tolerance_hit_rates_ms["100"]`；action=`keep`。
  - `eval_rule_subwindow.py`、`eval_subwindow.py`：`start_only_1s`；证据为
    `canonical_units.start_sec` 与 `<=1.0` 比较；canonical=`start_hit_1s`；
    action=`rename`。
- 对同名字段但无来源或无足够上下文者继续输出 `unknown` 与 `flagged=true`，不得由
  `hit100` 名称自行推断。
- audit 表必须新增/保证以下列：`File / Artifact`、`Field`、`Actual definition`、
  `Correct interpretation`、`Action`、`evidence`、`method`。
- 只对确认是 subwindow 的实现改输出字段为 `start_hit_1s`。若仍需旧读取器，输出
  `legacy_hit100` 和 `legacy_hit100_deprecated=true`；不得输出无 provenance 的新
  `hit100`。window-gate 代码/历史 artifact 仍保留 `hit100`，不要重命名。

### 验收

新增/扩展测试必须验证同一个 token 在三个 source hint 下得到不同的正确结果，尤其
`window_gate_report.json` 必须是 `both_boundaries_100ms`，不是 `start_only_1s`。随后重新
生成 `$DELIVERY/METRIC_SCHEMA_AUDIT.md` 及 JSON companion。

## 3. WP-F2（P0）：修正 Synthetic-GT Usage Audit

### 实现

在同一审计器的 `KNOWN_OVERRIDES` 加入：

| 文件 | GT source | synthetic | correctness | real-GT valid |
|---|---|---|---|---|
| `run_oracle_recovery.py` | manifest `canonical_units.start_sec/end_sec` | true | true（且 routing） | false |
| `eval_rule_subwindow.py` | manifest `canonical_units.start_sec` | true | true | false |
| `eval_subwindow.py` | manifest `canonical_units.start_sec` | true | true | false |

每项应为 `synthetic_kind=synthetic_uniform_timeline`、
`conclusion_affected=true`，并在 notes 指明 O0/O1/O2 的 GT routing 或 subwindow 的
start-only 评分。保留 heuristic 扫描作未知候选发现，但 known override 是已人工核实
事实，不能被 heuristic 覆盖。

扫描范围至少覆盖 transition/recovery scripts、relevant `/tmp/opencode` evidence scripts、
manifest builder 和 semantic planner。对 planner 仅使用时间做 geometry、未评分时保持
`used_for_correctness=false`，不要扩大污染结论。

### 验收

重生 `$DELIVERY/SYNTHETIC_GT_USAGE_AUDIT.md/.json`，表含：File、GT source、
synthetic/real、Used for correctness、Valid for real-GT correctness、Conclusion affected、
method/evidence。测试三 known override 以及一个无评分 planner 反例。

## 4. WP-F3（P1）：交付包可独立恢复

### 实现

确认并保留：

```text
src/lyricalign/research_transition_recovery_detector/gt_provenance.py
tests/research_transition_recovery_detector/test_gt_provenance.py
```

所有调用它的仓库脚本必须能在 `PYTHONPATH=src` 下 import；输出 JSON 含
`gt_kind`、`valid_for_realgt_correctness=false`、`result_status`，O0/O1/O2 另含
`gt_used_for_routing=true` 与 mode；stderr 出现 warning。

将这两个文件的完整副本放入
`$DELIVERY/patches/recoverable_files/`，并生成：

- `patches/working_tree.patch`：包含已跟踪修改；
- `patches/untracked_files.patch`：对每个新增文件使用
  `git diff --no-index -- /dev/null <file>` 生成并正确处理该命令的 exit code 1；
- `updated_docs/changed-files.txt`：所有本轮修改、新增、交付副本；
- `IMPLEMENTATION_CHANGELOG.md`：逐项说明恢复入口及 SHA-256。

不可用裸 `git diff --binary` 代替 untracked patch。

### 验收

执行 `pytest -q tests/research_transition_recovery_detector/test_gt_provenance.py`，并在
tarball 展开到临时目录后检查两个 recoverable 文件、两个 patch 和 changed-files list 均存在。

## 5. WP-F4（P1）：真正的 per-song failure concentration

### 实现

替换 `audit_wp4_light_merge_before_after.py` 中按 route 汇总的
`song_failure_concentration()`；该两行 request summary 不能再使用该名称。

从已有 unit-level `LABELS.jsonl` 或等价 real-GT label artifact **流式**读取，并先验证每行
含 song identity、target/raw-official identity（或能无歧义派生）、family、label。对每个
`(cohort, target, song_id, family)` 统计：

```text
n_labeled, n_safe, n_grey, n_unsafe,
unsafe_fraction, share_of_target_all_unsafe, cumulative_unsafe_share
```

各 target 内按 `share_of_target_all_unsafe DESC, song_id, family` 排序；在 Markdown 输出 top-1,
top-2, top-3, top-5 cumulative share。若标签 artifact 没有 target，请拒绝把单一路线标签复制成
Raw/Official 两份，改输出 `not_available_target_identity` 及原因。

若可从 identity-equivalent decision artifact 安全地 join，另列 per-song
`unsafe_accept`、`unsafe_protected`、`protected_recall`、`safe_accept`；无法完全 join 时只报告
GT failure concentration，并写出 `detector_decision_status=not_available`。绝不能将 route 级两行
摘要冒充 per-song/target 输出。

### 验收

使用两首歌、两个 target、Safe/Grey/Unsafe fixture 测试分母、排序和 cumulative 计算；验证 CSV
至少存在上述列。重新生成 `$DELIVERY/results/song_failure_concentration.{csv,md}`，并在 provenance
列出 exact label artifact SHA。

## 6. WP-F5（P2）：Archive Reference Audit 与最终状态

### 实现

收紧 archive path extractor：只接受 markdown link target、反引号路径、或包含 `/` 且有可接受
文件扩展名/已知前缀（`docs/`、`runs/`、`results/`、`configs/`、`scripts/`、`src/`）的 token。
显式过滤数值、比例、`a/b` 数学表达式、变量名、duration/density 等自然语言片段。每个候选保留
source、line、原 token、normalised path、classification；不可解析 token 不计入 missing 分母。

重点人工复核 `AI_SESSION_ENTRY.md`、README、SESSION、PHASE 和 Documents 14--20。真实不存在的
路径保持 `referenced but not present in current archive`，不伪造恢复。

保留既有 `00_meta/REPO_STATE.json`，在其 metadata 说明
`snapshot_phase=pre_execution`。所有代码/文档/交付变更结束后再产生
`00_meta/FINAL_REPO_STATE.json`，其中有 repo path、HEAD、`git status --short`、dirty files、
changed files、UTC、`snapshot_phase=post_execution`。Changelog 中解释两个 snapshot 的时点差异。

### 验收

在 fixture 中确认 `n_units / duration`、`0.901/0.857`、`gt=0/1` 不会成为 path 候选，而真实
`docs/...md` 与 `runs/...json` 会被检查。重新生成 archive report/JSON；报告在摘要中说明真实
候选和过滤 token 的数量。

## 7. 文档、测试、打包顺序

执行顺序：F1 与 F2 → F3/F4/F5 → 重生 audits/reports → focused docs → tests → final state → package。

所有结论文档继续使用下列口径：

- Detector 的 0.956656/0.962751 仅为
  `retrospective_after_light_merge_fix`，阈值来自 `pre_fix_frozen_threshold`；
- O0/O1/O2 是 `historical_synthetic_gt_oracle_diagnostic`；
- semantic/subwindow 是 synthetic start-only mechanism evidence；
- window-gate 的 bad 定义为 real-GT 双边界 100 ms，但 AUROC≈0.9831 和 0.45 仍是
  exploratory/test-tuned，`formal_threshold=false`；
- enhanced feature negative result 保持 `unresolved_after_bugfix`。

最少执行：

```bash
python -m pytest -q \
  tests/research_transition_recovery_detector/test_gt_provenance.py \
  tests/research_transition_recovery_detector/test_metric_schema_audit.py \
  tests/research_transition_recovery_detector/test_quick_correction_audit.py \
  tests/research_transition_recovery_detector/test_light_merge_before_after.py \
  tests/research_v7/test_detector_v2_intervals.py \
  tests/research_v7/test_semantic_window_planning.py \
  tests/research_v7/test_semantic_window_planning_wiring.py \
  tests/research_v7/test_window_boundary_clamp.py
python -m compileall -q src scripts
git diff --check
```

将 commands/environment/pass/fail/skipped/runtime 写到 `$DELIVERY/tests/test_summary.md`。
最后创建 `/home/hyan/LyricAlignment_20260812_quick_correction.tar.gz`，排除模型、音频、cache 和
大 prediction；通过 `tar -tzf` 和 required-file list 验证。任一 P0 audit 仍有错误、补丁不能恢复
新增文件、或 concentration 缺 target identity 时，交付状态必须为 `not_frozen_followup_incomplete`，
而不是完成。
