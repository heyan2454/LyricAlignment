# S_review — WP5（commit 622708b，E3 observation/context study）代码正确性/契约 + 数据一致性 review

执行人：review 子任务（STEP BUDGET=6）。审查对象：
`src/lyricalign/unit_realign/audio_views.py`、`scripts/unit_realign/run_audio_views.py`、
`scripts/unit_realign/closure_k1_vs_k3.py`。只读代码 + 最小 CPU（`--smoke`），未跑 GPU/渲染。
实测环境：conda `lyricalign-qwen`，`PYTHONPATH=src:.readline_stub`。

## 结论

**无 P0/P1。**

六项重点核查全部通过：no-GT 选择器无 GT 泄漏、view identity 防复用成立、fail-closed 成立、
crop 参数口径与裁剪正确、k1/k3 closure 只读复用安全、k1/k3 反 scope 遵守。以下为证据与
极少数 MINOR（进 backlog）。

---

## 重点核查逐项证据

### 1. no-GT 选择器是否真无 GT 泄漏 —— PASS

- `select_view_no_gt` 只读 `_SELECTABLE_NUMERIC_KEYS` 五个数值信号：
  `detector_p_bad`、`detector_p_bad_after`、`margin`、`entropy`、`raw_official_disagreement_ms`、
  `mean_boundary_displacement_ms`（audio_views.py L234-244），加结构标志 `candidate_missing`/
  `context_protected`（仅计入 per-view 摘要，不作为决定性排序）。逻辑全在 `_view_signal_means`/
  `_usable_signals`/`select_view_no_gt`（L247-356）。
- **未读 GT**：对 audio_views.py 全文 grep `reference_|max_boundary_error|outcome|oracle|ground_truth|label`，
  仅 docstring 注释命中（L12/L275），无实际取值路径。`mean_boundary_displacement_ms`（L224-229）
  由 candidate rows 的 `start_sec/end_sec` vs baseline rows（`_baseline_rows` 读 `region.units` 冻结
  timeline）计算，baseline 是 frozen detector 时间线而非 GT —— **no-GT 成立**。
- runner 只读 region.units（frozen）、decoder official/raw、request 几何，未见 GT。对三个输出产物做
  递归 GT 键扫描：`VIEW_OUTCOMES.jsonl`/`FINAL_VIEWS.jsonl`/`FINAL_VIEWS.json` 均 **NONE**。
- smoke 实测：`--views base,wider --limit 2`，selection 用 `mean_boundary_displacement_ms` 唯一胜出
  base（位移 0.0 vs wider 1000.0），无任何 GT 键参与。

### 2. view identity 防复用 —— PASS

- `build_view_requests` 把 `recrop_view_id`/`view_kind`/`audio_view_schema` 并入 `identity_context`，
  经 `build_family_request` 折入 `chain_context`，`build_request_identity` content-address 整个
  `chain_context`（request_families.py L73/86）。`_override_audio_range`（L140-156）同时覆盖
  `candidate_audio_range_sec`/`baseline_audio_range_sec`（进 `intervention_payload` 参与 digest）。
- 即不同 crop 在每个 digest 维度（recrop_view_id + crop range）都不同 → identity 必不同，
  不可能复用旧 forward。leaf view 无 parent，`build_request_identity` 的 chained-fail-closed
  （需四维度）不触发，符合预期。
- **实测确认**：`--smoke --views base,wider --limit 2` 4 个 request 的 `request_identity` 全部 distinct
  （4/4）；同 region base 与 wider 的 crop range 分别为 `[4.0,6.4]`/`[3.0,7.4]`、`[7.5,9.9]`/`[6.5,10.9]`，
  双保险生效。

### 3. select_view_no_gt fail-closed —— PASS

- 无可用信号 → `selected=False`、`status=no_signal`（L301-310），reason 明确 "cannot select without GT
  (fail-closed)"。
- 平局（全 tied）→ `indeterminate`（L324-332）；决定性票数平手（votes tie across views）→ `indeterminate`
  （L338-347）。唯一胜者 → `selected_no_gt`（L348-355）。
- **实测**（inline，因无该函数提交级单测，见 MINOR-1）：`no_signal`/`tie`/`unique_winner`/`votes` 四路径
  行为全部符合契约，无 "用 GT 硬选"、"静默返回随机 view"。

### 4. crop 参数口径与裁剪 —— PASS

- `AUDIO_VIEW_SCHEMAS`（L35-60）：base=target±0.5、wider=±1.5、left_enriched=左+1.0右+0.3、
  recentered=R-U proposal 中心±0.8，与 02 E3-B 一致；具体秒数按 02 "由 Codex 依据 duration 设计"，
  R_note 与实现自洽。
- `register_audio_views`（L92-137）用 `_clip`（L63-70）裁剪到 `[0,duration_sec]`，空区间抛 ValueError，
  防越界。实测：wider 超出 duration 被 clip；`_clip` 负 start clamp 0、超时长 clamp duration；空区间
  正确抛错。`recentered` 无 proposal 时回退 target-span 中心并记录 `recenter_source=target_span_center`
  （L116-117/123-135），proposal 给定则 `recenter_source=proposal_center`。

### 5. closure_k1_vs_k3 复用安全性 —— PASS

- 纯只读：`--comparison` 读 `CONTEXT_PADDING_COMPARISON.json`，`--k1-root/--k3-root`（可选）仅
  `_sparse_structural_audit` 重派生结构计数（sparse_fixed 数、active/text 比），无 forward、
  无 re-materialize request。
- 范围守卫：`scope` 必须为 `no_gt_structural_screen_only`，否则 raise（L69-71）；`schema` 校验
  `unit_realign_context_padding_comparison_v1`（L72-73）。实测 wrong scope / wrong schema 均被拒绝。
- **不误当科学结论**：输出声明 `accuracy_claim: False`、`reads_gt_buckets: False`、
  `scope_is_no_gt_structural_screen_only: True`（L125-126），且 `structural_read` 措辞为 "restores X
  additional fixed units ... screen (status)" 的结构性陈述，不含 accuracy。`compatibility_note`
  （L104-108）明确旧 run 为 research_v7 schema、未重 forward、未接 v2 可视化。

### 6. k1/k3 反 scope（不为旧 run 补 forward / 不接 v2 可视化）—— PASS

- 07 §11 anti-scope：`k1/k3 旧 run 不接入 v2 可视化（仅 no-GT structural）`、`不在 visualization 阶段
  重复 model forward`。07 §9 WP5（L262-263）明确 k1/k3 closure 仅 no-GT structural、复用旧 run、
  不改 v2 可视化。
- 本 closure 脚本完全遵守：只读旧 comparison、不补 forward、不接 v2 可视化，CLOSURE_REFERENCE 仅为
  no-GT structural 参考。
- 附注（非缺陷）：02 E3-A 文本写 "完成 forward、unit evaluator、paired comparison"，但 07 §11/§9（本
  session 的执行合同优先）将其降为 no-forward structural；closure 与 07 一致，正确。若需与 02 措辞对账，
  已由 07 §11 anti-scope 覆盖。

---

## MINOR（进 backlog，不阻塞）

- **MINOR-1【测试缺口 / 文档高估】**：R_note L49/L104-105 声称 select_view_no_gt 已单测
  （no_signal/tie/winner/GT firewall pass），但 WP5 commit（622708b，`git show --stat`）未新增
  `tests/unit_realign/test_audio_views.py` 或等价回归测试，`tests/unit_realign` 全量（87 passed）不含
  这些路径。本轮 review 手动 inline 验证通过，但缺提交级回归保护；建议后续补 `test_audio_views.py`
  覆盖 `select_view_no_gt` 四路径，并修正 R_note 的"已单测"表述。
- **MINOR-2【数据完整性健壮性】**:`run_audio_views.py` 写 `VIEW_OUTCOMES`/`FINAL_VIEWS` 时按
  `vr.get("request_identity")` 为 truthy 才 append（L409-410）。若 real 模式 identity_context 缺失某
  必需键（如 audio_sha/checkpoint）、`_override_audio_range`/`build_family_request` 置
  `request_identity=None`，该 view 的 outcome 会**静默不进** VIEW_OUTCOMES/FINAL_VIEWS，但 forward
  已执行、RUN_STATE 会记录 identity（为 None 时也不记）。建议对 identity=None 的 ok view 显式标
  `identity_missing` 或至少写入 VIEW_OUTCOMES 供审计，避免真实数据静默缺行。
- **MINOR-3【死参数】**:`_view_result` 的 `view_out` 参数在 runner 全路径均传 None，逻辑里一直是
  "if view_out is not None: rows=[] else enrich" 的假分支，属未完成清理的残留参数。

---

## 验收命令与结果（CPU-only，已清理临时产物）

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
PYTHONPATH=src:.readline_stub python -m pytest -q tests/unit_realign        # 87 passed in 2.44s
PYTHONPATH=src:.readline_stub python scripts/unit_realign/run_audio_views.py \
  --out-root <tmp> --smoke --views base,wider --limit 2                    # n_regions 2, n_views 4, n_completed 4
PYTHONPATH=src:.readline_stub python scripts/unit_realign/run_audio_views.py \
  --out-root <tmp> --smoke --views base,wider --limit 2 --resume           # n_skipped_resume 4, n_completed 4（幂等）
```

- 身份互异：4/4 distinct `request_identity`（不同 crop 不复用）。resume 幂等通过。
- 工程卫生：`compileall` OK；`git diff --check` 干净；恢复被误删的 `.readline_stub`（`git checkout -- .readline_stub/`）。

## 下一步建议
1. 补 `test_audio_views.py`（MINOR-1）+ 修正 R_note "已单测" 表述。
2. real 模式优先验证 MINOR-2 的 identity 完整性（用真实 REGION_POOL 冻结 identity_context 后不会触发）。
3. GPU formal 按 R_note §6 模板在 data 目录另建 run root，正式期 freeze 所有 view 偏移/duration。
