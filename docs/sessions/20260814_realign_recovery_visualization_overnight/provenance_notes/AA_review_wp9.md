# AA — WP9 Review: recovery-atlas + serial stress (commit 37e88d9)

审查对象：`src/lyricalign/unit_realign/recovery_atlas.py` + `run_recovery_atlas.py` +
`run_serial_stress.py`。只读代码 + 最小 CPU smoke（不跑 GPU）。对照 WP9 契约
`Z_wp9_atlas_serial.md` 与 `02` §393-418 / §449-457。

验收结果：`pytest -q tests/unit_realign` 109 passed；E6 atlas smoke（含/不含 GT）、
E7 serial smoke 均跑通，serial 三判据与契约逐项吻合。发现 **1 个 P1 分类/数据口径 bug、
1 个 P1 recrop 机制 schema 契约缺口**、若干 P2；无 P0。详见下。

---

## 实测（本机 conda lyricalign-qwen，CPYTHON，纯 CPU）

- 测试：`PYTHONPATH=src:.readline_stub python -m pytest -q tests/unit_realign` → **109 passed**。
- E6 atlas smoke（构造 4 区域 + 忠实 multi_iteration/split schema 的 evidence，配 `--gt`）：
  `once-realign:1 (REG_A)`、`split-only:1 (REG_B)`、`still-unrecoverable:2 (REG_C + REG_NOGT)`，
  与 Z note 预期一致。
- E6 GT firewall（不传 `--gt`，region 无 gt_units）：4 区域均 `baseline_present_gt=false`、
  `baseline_error_bucket_ms=None`、`atlas_class=still-unrecoverable`、`n_gt_present=0`。**通过**。
- E7 serial smoke（`--smoke` 内建 bundle）：
  - `smoke_unmitigated`  `windows_to_recover=5 bad=5 area=1250 extra=0`  ✓（契约 5/5/1250/0）
  - `smoke_reset_recovers` `windows_to_recover=2 bad=2 area=860 extra=2` ✓（契约 2/2/860/2）
  - `smoke_false_recovery` `windows_to_recover=2 false=[1]` ✓（契约 2/[1]）
  均逐项吻合。

GT 泄漏核查（项 6）：serial `summary.gt_used=False`，无 GT 字段，无泄漏。atlas 的
`baseline_error_bucket_ms/baseline_max_detector_error_ms/baseline_present_gt` 是 evaluator-side
（GT present 才填）的契约内输出，`best_*_error_ms` 为机制自身恢复误差（非 GT-derived），
无 GT label 泄漏进证据字段本身。

纯 CPU / 不 forward（项 5）：两个 runner 均为只读 evidence/outcome 的「汇总 + 内建 CPU
模拟器」路径；atlas 不含任何 `_smoke_serial`/executor 调用，serial 默认走 `_smoke_serial`
纯 CPU 占位，不发起真实 forward，无写回，`RENDER_MODE`/GPU 无关。**通过**。

---

## [P1] atlas 分类/数据口径：coarse_fine 的 `target_recovered_*` 为**比例**，被当作布尔桶误判

- 现象：`_row_recovered_buckets`（recovery_atlas.py:96-123）对任意 int/float 字段一律
  `ok = bool(v)`。coarse_fine_v1 的 region 行里的 `target_recovered_100/200/500/1000`
  （coarse_fine.py:595-598）是 **0..1 的恢复率**（`n_100/n_ok`），不是布尔。于是
  `target_recovered_100 = 0.5` → `bool(0.5)=True` → `best_coarse_100ms=True`。
- 实测：region 只有 `target_recovered_100=0.5`（半数目标单元未在 100ms 恢复）、无其它机制
  达 100ms 时，atlas 仍将其判为 `coarse-fine`（且 `best_achievable_ms=100`、
  `coarse_fine_can_rescue=true`）。→ **把未真正在 100ms 全达标的区域误判为可恢复**，
  违反「100ms 桶=可达」口径（02 §414-418；Z note:35 `best_{mech}_{b}ms` 为机制最好可达到
  的容差桶）。
- 影响面：`classify_region` 在 coarse 分支、`best_{coarse}_*ms`、`combined_can_rescue`(200ms)、
  `best_achievable_ms` 全部受污染。split 的 `recovered_strict_*`/`recovered_coarse_*` 是真
  布尔（split_variants.py:506-509）不受影响；it≈rec: `first_hit_ms_iteration_{b}`（int 或 None）
  也无此问题。**仅 coarse_fine 的 `target_recovered_*` 字段与之撞名且类型为比例。**
- 证据：粗糙 smoke
  `/tmp/wp9_smoke/r_atlas_coarse` 输出 `coarse-fine:1`（其 `best_coarse_100ms=true`）。
  代码见 recovery_atlas.py:107-122 vs coarse_fine.py:591-599。
- 建议：`_row_recovered_buckets`/`_region_best_buckets` 需区分「布尔桶字段」与「比例字段」：
  对 `target_recovered_{b}` 仅当 `v >= 1.0 - eps`（或独立按 `n_ok==n_recovered` 全达标）才算
  达桶；或 coarse 机制改用布尔达桶位（如 `all_target_recovered_{(b)}`）再喂 atlas。修复后
  受影响 identity 需失效重跑（涉分类与 rescue 标志）。

---

## [P1] recrop（E3 audio_view_study_v1）evidence 无法填充 `best_recrop_*`，recrop 分类结构性失效

- 现象/证据：
  - `_SCHEMA_MECH` 的 recrop 标记是 `"audio_views"`（recovery_atlas.py:63），但实际 E3 schema
    是 `audio_view_study_v1`（audio_views.py:303/326/341/350）。`"audio_views" in
    "audio_view_study_v1"` 为 **False**，主标匹配不到；机制识别仅靠 fallback `"view" in lower`
    （recovery_atlas.py:89）偶然兜住，才把 E3 行归入 recrop（项 3 的静默读不到问题此处因
    fallback 未触发，但 `_SCHEMA_MECH` 主标本身是错的，随时会因 fallback 改动而失效）。
  - 更关键：`audio_views.py` 产出的 `audio_view_study_v1` 行（run_audio_views.py 的
    `VIEW_OUTCOMES.jsonl`；audio_views.py:290-354）只有
    `recrop_view_id/view_kind/request_identity/status/candidate_row_count/n_candidate_missing/
    n_context_protected/signal_means`，**没有任何 `target_recovered_*`/`recovered_*`/
    `best_error_ms`/`{b}ms`**。`_row_recovered_buckets`（recovery_atlas.py:107-122）在其上找
    不到任何桶字段 → recrop 的 `best_recrop_{100,200,500,1000}ms` 恒 False、
    `best_recrop_error_ms` 恒 None。
- 后果：`recrop_can_rescue` 恒 False、`classify_region` 的 recrop 分支不可达——真实 E1-E4
  证据集上，**任何 region 都不可能被归纳为 `recrop`**；若一个区域本「只有 recrop 能救」，会被
  错误推到 coarse/still-unrecoverable。同时 `coarse_fine` 里含 combined 路线的 200ms
  `combined_can_rescue` 依赖 recrop 桶，也会被低估。
- 契约对照：Z note:35/44/45 明确把 `target_recovered_{b}` 列为 recrop 桶字段、把 `audio_views`
  列为 recrop schema 标记；但 E3 实际不产出该字段。属「atlas 期望 schema 与实际 E3 输出
  schema 不一致」的跨模块接线缺口（项 3 的机构识别兼容要求的现实落点）。
- 建议：二选一并记录：① 在 `audio_views.py`（或 E3 runner）补产 per-target 100/200/500/1000ms
  恢复布尔桶，并同步修正 `_SCHEMA_MECH` 的 recrop 标记为 `audio_view_study`；或 ② 在 atlas
  docstring/契约中明确 recrop 为 no-GT 选择器、不产出恢复桶，recrop 分类按弃用处理（避免
  用户误以为 E3 会填 recrop 桶）。修复后重跑受影响 formal。

---

## [P2] `baseline_present_gt` 反映「全局 GT 表非空」而非「本 region 的 units 被 GT 覆盖」

- 现象：`_get_gt`（recovery_atlas.py:157-171）返回**整张 evaluator GT 表**（未按 region 过滤）；
  `_baseline_error_bucket`（recovery_atlas.py:182-184）仅判 `if not gt_by`（全局空）就置
  `present=True`。当 `--gt` 传入但某 region 的 units 一条都不在 GT 表里时，该 region 仍
  `baseline_present_gt=True`（只是 `bucket_ms=None`），`n_gt_present` 被抬高。
- 实测：REG_NOGT（unit 6，GT.json 只有 1-5）在 `--gt` 下 `baseline_present_gt=True`，
  `n_gt_present=4`（应 3）。但**不传 `--gt`** 的防火墙场景正确（`n_gt_present=0`，全
  `present=False`）——说明漏洞仅在「局部无 GT 但有全局 GT」时出现。
- 影响：GT firewall 的语义是「该 region 无 GT 就不做 evaluator 分类」
  （Z note:79-80，atlas docstring）。当前会把这些 region 放行进 taxonomy，并在
  `baseline_error_bucket_ms=None` 与 `baseline_present_gt=True` 同时成真的不一致状态下
  参与分类。虽经 `classify_region`（recovery_atlas.py:352）以 `present=True` 放行，但由于
  桶字段本就 None，多数情形落到 unrecoverable；主要在 `n_gt_present` 统计与「可判定」语义上
  失真。
- 建议：`_get_gt` 按 region 的 `units[*].canonical_unit_id` 过滤后返回（或 `_baseline_error_bucket`
  以「该 region 有 ≥1 个 unit 命中 GT」判定 `present`）；桶仍 None 时 `present` 应为 False。
  属数据一致性修正（P2，不改变分类主路径但在 GT 覆盖率统计/防火墙上正确）。

---

## [P2] `once-realign` 判定依赖「evidence 中最后一次 iteration」而非「首个命中 iter」

- 现象：`seen_identities[(rs,"iteration")]` 在 build_atlas_rows 里被逐行覆盖，取到的是该 region
  evidence 中的**最大/最后** iteration（recovery_atlas.py:253-257）。`classify_region` 的
  once 判定用 `int(iteration)<=1`（recovery_atlas.py:357-361）。
- 证据/影响：若某 region 在 iter0/1 已达 100ms，但 evidence 因后续 iter 链（2..N）也记录了
  非 None 的 iteration，则 `seen_identities["iteration"]>=2` → 判为 `iterative` 而非 `once-realign`
  ——「once」依赖运行过的迭代次数而非达到 100ms 所需的最少迭代。该口径更贴近「试验证据里
  跑到第几步」，与 Z note:51 的「iterative 100ms 可达→once(若 it<=1)」字面一致，但对
  「actually 只需 1 步」的区域可能低判为 iterative。是否算 bug 取决于产品口径（once 应按
  first-hit-iteration 判定更稳）。
- 建议：用 `first_hit_ms_iteration_100` 的最早迭代（或该 region 所有 unit 的最小首命中 iter）
  作为 once 判定依据，而不是遍历序覆盖的末次 iteration。记 P2（口径）。

---

## MINOR / backlog

- `run_serial_stress.py:141-143` 把 `windows_to_recover=None`（永不恢复）计入
  `mean_windows_to_recover` 为 `1.0`——Z note:111 已登记。建议补 `count_never_recovered` 字段。
- `_collect_rows` 的 `_EXCLUDE_PARTS` 含 `FINAL_`，会把 `FINAL_TRAJECTORY.json`/
  `FINAL_VIEWS.json`/`FINAL_COARSE_FINE.json` 的 aggregate 一律跳过；当前因各 E-run 均有
  jsonl 行迹（`TRAJECTORY.jsonl`/`SPLIT_OUTCOMES.jsonl`/`COARSE_FINE_OUTCOMES.jsonl`/
  `VIEW_OUTCOMES.jsonl`）不受影响，但该排除粒度过宽，建议改为按文件名精确命中（如
  `FINAL_ATLAS.json`）而非前缀 `FINAL_`。
- `run_recovery_atlas.py` 的 `--smoke` 仅为 executor 标签，无内建 evidence fixture，需外部
  提供 `--regions/--evidence-root/--gt`；建议像 serial 一样实现 `--smoke` 自足 bundle 以便复现
  验收。
- atlas 缺专项单元测试（tests/unit_realign 无 `test_recovery_atlas*`；smoke 由 reviewer 手工
  构造）。建议补 `classify_region`/`_row_recovered_buckets` 的分类与占比-布尔边界回归测试
  （尤其 locked 本 review 的 [P1] 比例误判）。
- `build_serial_episode` 的 `executor` 参数是占位（Z note:116-117），smoke 为内建模拟器；真实
  forward 接入前需按 cursor+offset push 覆盖 `_smoke_serial`。已在 Z note 登记。

---

## 结论

无 P0。P1×2（[P1] coarse 比例当布尔误判、[P1] recrop evidence schema 缺口致 recrop 分类
结构性失效）；P2×2；若干 MINOR 进 backlog。测试全绿、serial 三判据与 GT 防火墙（无 --gt
路径）实测通过；GT 泄漏与纯 CPU/不 forward 均符合契约。修复 P1 后需使受影响 identity 失效
并重跑（涉 atlas 分类与 recrop/combined rescue 判定）。
