# W review — WP7 E5 no-GT selector/safety

- 审查对象（commit 202bcba）：`src/lyricalign/unit_realign/no_gt_selector.py`、
  `scripts/unit_realign/run_no_gt_selector.py`、`src/lyricalign/unit_realign/unit_gate_features.py`（diff）
- 审查类型：代码正确性/契约 + 数据一致性/跨模块接线
- 审查人/时：本 agent（STEP BUDGET=6，2026-08-14）
- 方法：只读源码 + `--smoke`（纯 CPU，forward=0）复现 + 最小 CPU 单点验证；未跑 GPU。

---

## 结论概览

- **P0：无**
- **P1：4 项**（均为接线/契约/回归缺口，含一条 no-GT proxy 实为「无真实生产者」的关键接线断点）
- MINOR：若干，见文末 backlog

smoke 复现（`/home/hyan/Data/lyricalign/runs/wp7_no_gt_selector_smoke_review_20260814`）与 V_note 完全一致：
recovery-first `selected=208 / safe_cov=0.682 / reject=0.102`；safety-first `selected=0 / unsupported=208`
（proxy 缺失 fail-closed）；`evaluated_once=True`；`detector_p_bad`(proxy) 缺失。
`tests/unit_realign` 95 passed。compileall / `git diff --check` 通过。

---

## [P1] 1. `NO_GT_PROXY="detector_p_bad"`（裸键）无真实生产者 —— 接线断点

**问题 → 证据 → 建议**

- 问题：selector 的 no-GT 主代理读裸键 `detector_p_bad`，但真实特征矩阵生产者从不产出该键。
  `freeze_simple_selector` 的 p_bad 阈值校准（`_signal_mean(rows,"detector_p_bad")`）与
  `_apply_selector` 的 safety-first 依赖同样落空 → 真实数据上 proxy 恒 None：
  `audit.proxy_available=False`、p_bad 阈值不校准（回落到默认 0.5）、safety-first 全量 `unsupported`。
- 证据：
  - `unit_gate_features.build_unit_features`（行 70–84）只写 `detector_p_bad_before`/`detector_p_bad_after`/`signed_detector_delta`，**不写裸 `detector_p_bad`**（实测 `'detector_p_bad' in row` == `False`，row keys 见下方）。
  - 全仓 grep：裸 `detector_p_bad` 仅出现在 allowlist 声明、selector 自身读取、`build_selector_features` 里 `c.get("detector_p_bad")`（而 `by_cid` 单元格从不 set 该键，故恒 None）。
  - `no_gt_selector.SIGNAL_NAMES` 注释（行 50）写明意图为「`detector_p_bad_before/after -> max`」，但该推导**未实现**。
  - V_note「proxy 来自 FrozenScorer 矩阵可跑」的 `feat_smoke` 用的是**手工构造的 60 行矩阵**（裸 `detector_p_bad` n=60），非 `extract_unit_gate_features.py` 真实产物。
- 建议：在 `build_unit_features`（或 `extract_unit_gate_features.py` 汇总层）补一个裸 `detector_p_bad`
  = `max(detector_p_bad_before, detector_p_bad_after)`（与 SIGNAL_NAMES 注释一致），并入 allowlist 已存在；
  或 selector 改读 `detector_p_bad_after`（并同步 audio_views）。变更后需重新跑 feat 路径证明 proxy true。

---

## [P1] 2. freeze 校准 percentile 标签：文档/注释为「85 百分位」，实际算 90 百分位

**问题 → 证据 → 建议**

- 问题：`freeze_simple_selector` 声称按 85 百分位收紧 p_bad 阈值，但代码取的是 p90 索引，
  同名变量 `p85` 实际指向 `stats["detector_p_bad"]["p90"]`，导致下发的阈值与报告口径不一致。
- 证据：
  - `no_gt_selector.py` 行 330–334：注释「tighten to the **85th** percentile」+ 变量名 `p85`，
    赋值却是 `stats["detector_p_bad"]["p90"]`（`p90 = int(0.9*len)`）。
  - V_note §2 明写「按 **85** 百分位校准为 0.79」；而 `feat_smoke/FROZEN_SELECTOR.json` 里
    `detector_p_bad {'n':60,'p50':0.4303,'p90':0.7896}` → `p_bad_threshold=0.7896`，实为 **p90**。
- 建议：统一语义——要么实现真 85 百分位并改索引，要么把注释/V_note 改为 90 百分位。二选一后重跑 feat 路径，避免「报告 85、实算 90」的契约漂移。

---

## [P1] 3. 非 smoke 下 runner 仍用「同一行集」既 freeze 又 heldout，无 disjoint 保护

**问题 → 证据 → 建议**

- 问题：`run_no_gt_selector.py` 在**任一模式**（含非 smoke）都把 `heldout_features = sel_features`，
  即 heldout 用的是与 freeze 完全相同的行集；`disjoint_check()`（设计为 disjoint 守卫）从未被调用/接线。
  `_smoke_split_warning` 只是 eval 里的数据字段，不是强制 guard。这违反 02 §358-359
  （freeze 于 discovery、heldout **对 disjoint 数据**只做一次评价）——正式数字会乐观偏差、不能作 heldout 证据。
- 证据：
  - `run_no_gt_selector.py` 行 112–119：`frozen = freeze_simple_selector(sel_features,...)` 与
    `heldout_features = sel_features`，无任何按 region identity 切分逻辑；`--split` 只是改 freeze/heldout **命名**。
  - `no_gt_selector.disjoint_check()`（行 486–490）未被 `main()` 调用。
- 建议：在下发 heldout 前按 region identity 把 `sel_features` 切成 discovery/freeze 与 heldout 两个不相交集合；
  在 `main()` 里调用 `disjoint_check()`，`frozen in heldout_splits` 为 True 时 fail-fast 而不是把同集当 heldout。
  库函数 `evaluate_heldout_once` 本身正确（对传入 heldout 只求值一次、同时出两个 operating point）。
  亦需补测试锁定「heldout 行 ≠ freeze 行」。

---

## [P1] 4. WP7 无 `no_gt_selector` 的提交测试（含 `assert_no_label_leak`、双 operating point）

**问题 → 证据 → 建议**

- 问题：新增模块 `no_gt_selector`（含新的 `assert_no_label_leak` 防火墙、freeze、heldout 一次评价、
  recovery/safety 双 operating point）**零提交测试**。提交信息「GT firewall negative tests all blocked /
  369 tests pass」指的是手工验证，仓库未固化。
- 证据：
  - `git show HEAD --name-only`：WP7 仅改 3 个 src/scripts + V_note，**无 tests/** 改动。
  - `grep no_gt_selector tests/` 无结果；`tests/unit_realign/test_unit_gate_features.py` 只覆盖
    `assert_no_gt_feature_row`（含 `delta_error_ms`、`decoder_confidence` 嵌套负例），不覆盖 `assert_no_label_leak`。
  - 手工复测：V_note §4 四个负例（`verdict`/`oracle_disp`/`gt_eval`/`evaluator_row`）及嵌套
    `{'raw_rows':[{'verdict':1}]}` 均被 `assert_no_label_leak` 拦截 ✓（本审查已用最小 CPU 复现）。
- 建议：补 `tests/unit_realign/test_no_gt_selector.py`，覆盖：① `assert_no_label_leak` 正/负例
  （含 `repeat_gt_starts` 豁免、`attempt.gt_eval` 拦截）；② `assert_no_gt_feature_row` 对
  `reference_*`/`max_boundary_error`/GT delta 拒绝；③ `freeze_simple_selector`（heldout 不动、
  裸 proxy 校准）；④ `evaluate_heldout_once` 分 recovery/safety 两口径、`evaluated_once`；
  ⑤ runner 同集 freeze/heldout 的 fail-fast（配合 P1-3 修复）。

---

## 非 P0/P1 核验（通过）

- **信号白名单（13 项）**：`SIGNAL_NAMES` 全部 ∈ `ALLOWED_FEATURE_KEYS`，且均非 GT 结果
  （posterior margin/entropy、detector p_bad/state、时序几何、结构 flag）。对照 E_note §2 无漏。
- **GT firewall 双拦截**：`assert_no_gt_feature_row` 仍为**严格 allowlist**（仅 `ALLOWED_FEATURE_KEYS`
  + `decoder_confidence` 嵌套），`reference_*`/`max_boundary_error`/GT delta 键均不在 allowlist → 被拒；
  `assert_no_label_leak` 词级拦截 evaluator 命名空间，负例全 BLOCK，且能发现嵌套于 allowed-array 键内的 GT。
- **recovery/safety 两口径分开报告**：`evaluate_heldout_once` 同一次读上分别 `select_candidates`（safety_first 开关
  + require_proxy 开关），output 分 `operating_points.recovery_first / safety_first`，不因单标量冲突而停。
- **heldout 只评一次**：`evaluate_heldout_once` 只 `align_feature_matrix` 一次、两次 selection 复用同一 rows，
  `evaluated_once=True`。
- **freeze 不反向调参**：`freeze_simple_selector` 仅在传入的 freeze 集上算 percentile，不读 heldout。
- **`unit_gate_features` 改动无害**：仅向 `ALLOWED_FEATURE_KEYS` **追加** 9 个非 GT 键
  （`margin/min_margin/num_margins_above/entropy/detector_state/detector_p_bad/context_displacement_ms/
  fixed_point_spread_ms/split`），schema 保持 `unit_realign_no_gt_features_v1`，向后兼容；
  未放宽任何 GT 键，严格 allowlist 逻辑不变。
- **proxy 非 GT 误差**：`NO_GT_PROXY` 语义为 FrozenScorer 的 p_bad（no-GT），非 GT delta/误差（除非实现 P1-1，
  否则真实路径根本不产出——即不会误用 GT）。

---

## MINOR（backlog，不阻塞）

1. `LOWER_IS_SAFER` / `HIGHER_IS_SAFER` 为死常量，全模块未引用（仅文档性）。
2. `detector_p_bad_after` ∈ `LOWER_IS_SAFER` 但 ∉ `SIGNAL_NAMES`，方向映射覆盖到 selector 不发射的信号。
3. `_ARRAY_KEYS_OK`（`raw_rows/official_rows/.../attempt_rows`）遍历豁免语义安全但与 allowlist 存在冗余。
4. `disjoint_check()` 未接线（见 P1-3，修复后接上）。
5. evidence 单元命名空间未对齐（V_note §5.1）：raw 用 `global_character_index`、baseline 用 `canonical_unit_id`，
   当前 confirmation evidence 上 `mean/context_displacement_ms` 为 None（audit 已确认 missing）——真实调用建议复用
   `unit_gate_features.build_unit_features` 按 canonical 归并。
6. `raw_official_disagreement_ms`/`mean_boundary_displacement_ms` 用 `(Δs+Δe)*500`（=两边界平均位移 ms），
   命名含「mean」、规则阈值 30/80ms 语义一致，非 bug，但建议在 schema 注释里写明口径避免误解。

---

## 复现

```bash
conda activate lyricalign-qwen; cd /home/hyan/LyricAlignment
PYTHONPATH=src python -m pytest -q tests/unit_realign          # 95 passed
PYTHONPATH=src python scripts/unit_realign/run_no_gt_selector.py \
  --evidence-dir /home/hyan/Data/lyricalign/runs/unit_realign_confirmation_no_gt_20260813/02_behavior/forward/evidence \
  --out-root /home/hyan/Data/lyricalign/runs/wp7_no_gt_selector_smoke_review_20260814 \
  --split heldout --smoke --max-payloads 40
```

（P1-1 最小验证：`build_unit_features(...)` 输出 keys 无裸 `detector_p_bad`；P1-2 见 `feat_smoke/FROZEN_SELECTOR.json`；
P1-3 `run_no_gt_selector.py` 行 112–119；P1-4 `git show HEAD --name-only` 无 tests/。）
