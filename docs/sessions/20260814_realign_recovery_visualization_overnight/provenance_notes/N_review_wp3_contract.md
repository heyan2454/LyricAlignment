# N — WP3 代码正确性/契约 review（commit 3d19152，E1 multi-realign dynamics）

Session：`20260814_realign_recovery_visualization_overnight`
审查对象：`src/lyricalign/unit_realign/multi_iteration.py` + `scripts/unit_realign/run_multi_realign.py`
对照：M note（`M_wp3_multi_realign.md`）、02 E1 §126-146、04 §7、07 plan §9（WP3）
审查人：WP3 代码正确性/契约 review 子 agent
只评 P0/P1；MINOR 记 backlog。

## 结论概要

- **无 P0**。
- **P1 × 3**：① per-unit 轨迹 schema 缺失 07 plan/02 E1 冻结的多项 required 字段（first_hit、per-unit 动力学指标）；② 自带单测 `test_chain_not_constructible_on_bad_baseline_source` 恒红（且暴露 executor=None 语义与 M note 不符）；③ 链上 not_constructible 停止步在 REQUESTS/RUN_STATE/计数中丢失。
- M note 声明的 3 个 residual 评级：``best_error_ms`` 为 **P1**（见下），``wall_time_ms=0`` 与 ``smoke 假执行器`` 均为 **MINOR**。

---

## P1 问题

### [P1-1] per-unit 轨迹 schema 缺失冻结的 required 指标（07 plan §9 / 02 E1 §128-138 / 04 §7）

**问题**：`extract_trajectory`（multi_iteration.py:448-601）产出的 per-unit 行只有
`initial_error_ms / error_ms / best_error_ms / delta_to_baseline_ms` 四项；
缺失 07 plan `multi_realign_dynamics_v1`（docs/07 §9 行 97-100）与 02 E1 §128-138 "逐 unit" 定义的多项字段：
- `first_hit_ms_iteration{100,200,500,1000}`：**未产出，也未在代码 / FINAL 中导出**（仅能从 per-unit 的
  error_ms 序列下游反推，属"可导出"而非"在产出"）。
- `monotonic_improvement_ratio / improve_then_regress / fixed_point_iteration /
  oscillation_divergence`：02 E1 §130-138 明确按 **逐 unit** 口径列出，但实现仅在
  **per-region 聚合布尔** 上给出（`extract_trajectory` 内 per_unit 行不含任一）；per-unit 视图彻底丢失。
- per-region 的 "any catastrophic regression"（02 E1 §145）未实现。

**证据**：实跑 smoke（合成 5-unit region, target=auto:1, iter 1,2,3,5）TRAJECTORY 16 行 =
15 per-unit（仅 4 个数值字段）+ 1 region（布尔聚合）；per-unit 行 `{"row_kind","schema_version",
"song_id","region_id","request_identity","iteration","canonical_unit_id","initial_error_ms","error_ms",
"best_error_ms","delta_to_baseline_ms"}`，无 first_hit/per-unit 动力学。

**影响/建议**：E1 screening 的用途是区分"一次恢复 / 逐步恢复 / 停在错误定态 / 越修越坏"四类 region。
当前输出只有数值时间 + region 级布尔，无法在逐 unit 级别报 first_hit 迭代数与 per-unit 动力学，
与 07 plan 冻结的 `multi_realign_dynamics_v1` schema 契约不一致，会削弱/无法支撑逐 unit 结论口径。
**建议**：把 region 级布尔聚合保留的基础上，在 extract_trajectory 里补 per-unit 的
`first_hit_ms_iteration{100,200,500,1000}`、`monotonic_improvement_ratio`、`fixed_point_iteration`、
`oscillation_or_divergence`（按 unit error 系列组内计算）；fixed_point_iteration 应明确为"达到定态的最小迭代数"而非"末两步近 0"的布尔；补 region 的 `catastrophic_regression`。

---

### [P1-2] `tests/unit_realign/test_multi_iteration.py::test_chain_not_constructible_on_bad_baseline_source` 恒红；且 `executor=None` 行为与 M note §2 不符

**问题**：(a) 该测试断言 `steps[0]["iteration"] == 1`（test 行 77），但 `build_chain(..., executor=None)`
实际返回**单个 iter0 step**（iteration=0，status=`failed`，reason=`no_executor`）——断言恒不成立；
(b) 暴露语义缺口：M note §2 说 "`executor=None` 时仅造出 iter0，**后继步**标 not_constructible"，
docstring（multi_iteration.py:129）也说 "later steps are marked not_constructible"；
但实现中 `_execute` 对 iter0 执行即返回 `no_executor` → iter0 自身被判 failed（constructible=False），
链随即 break，真正的 iteration≥1 的 `previous_step_not_constructible` step **从未产生**。

**证据**：直接执行该测试函数 → `TEST FAIL (assertion)`；`build_chain(region,[1],identity_context=ctx,executor=None)`
输出 1 步 `it 0 constructible False status failed reason no_executor`。
（注：本仓库在 `landlock-run` partial-enforcement sandbox 下 `pytest` 整体 SIGSEGV（exit=139，无任何收集输出），
含 `tests/research_v7/test_detector_v2_*.py` 的对照组同样段错误，判断为环境/sandbox 与 pytest 启动不兼容、
与 WP3 代码无关；该断言错误是通过 `python -c` 直接执行测试函数核实的。）

**影响/建议**：自带 WP3 单测在正常环境必红一项，阻塞 L2 验收。**建议**：
修正测试断言为 `steps[0]["iteration"] in (0, 1)` 或改为校验迭代 0 外的 `not_constructible` 语义；
同时将 build_chain 的 `executor=None` 语义对齐文档——意图是"无 executor 时仅产出可构造的 iter0，
后续步递进停止并标 not_constructible"，当前却在 iter0 上 `no_executor` 失败。若 `executor=None` 想表达
"不执行任何 forward"，建议：iter0 直接产出且 constructible（status=None 或 'executed'），后续步标
`previous_step_not_constructible`；不要把 iter0 标记 failed。

---

### [P1-3] 链上 not_constructible 停止步未记入 REQUESTS / RUN_STATE / 计数（对比 M §3 输出契约）

**问题**：M note §3 承诺 "`01_requests/REQUESTS.jsonl`：每步 v2 request（或 not_constructible 桩）"。
但当某一轮 candidate 使下一轮 R-U 窗口非法（非单调 / 负时长 / 负时间）时，`build_chain` 产出一个
`request=None` 的 step（multi_iteration.py:218/229），随后 runner（run_multi_realign.py:223）
`if request is None: continue` 直接跳过——该停止步既不落 REQUESTS、不进 RUN_STATE 的
`not_constructible_identities` 桶，也不计入 summary 的 `count["not_constructible"]`。
链在 `build_chain` 内部确实 fail-closed（不是静默空转，step 上带 `not_constructible_reason`），
因此**结果数据方向正确，但记录不完整**：M 承诺的"每步桩"与 not_constructible 统计口径被破坏。

**证据**：强制构造非单调候选（executor 使 unit1 start < unit0 end）→
`build_chain` 输出 `it=1 constructible=False reason=non_monotonic_candidate_timeline req=None`；
该 step 在 runner 中 request=None 被 `continue` 跳过。

**影响/建议**：真实 formal 长跑若因相对运动出现非单调，not_constructible 轮数与停止点会少记，
RUN_STATE 无法精确描述完成/未完成集合（resume 依赖 identity，不影响正确续跑，但影响可追溯计数）。
**建议**：对 `request=None` 的 not_constructible step 仍向 REQUESTS 写一条桩（含
`not_constructible_reason`），并在 `_record` 里按 `not_constructible_identities_seed`（如
`song:region:iter:{reason}`）登记与计数，与 M §3 契约一致。

---

## M note 三个已声明 residual 的级别裁定

### [P1] best_error_ms = 当前步（非跨轮 min）—— M residual ②
- **裁定**：P1（口径陷阱）。
- 理由：M 自己已注明"现为该 unit 当步值（非跨轮 min）"，但该字段在 shipped TRAJECTORY 中名为
  `best_error_ms` 且始终等于 `error_ms`（multi_iteration.py:509）。07 plan §9 行 97 明确要求产
  `best_err`。任何下游只要按字面读 `best_error_ms` 拿"该 unit 的最好 recovery"，都会得到错误的
  "当前步即 best" 结论，直接让 "best recovery" 结论失真——正是本 review 提示的可能 P1 情形。
- 缓解：真实跨轮 min 可从同一 unit 的（request_identity, iteration, error_ms）序列下游重算，样本不丢。
- 建议：要么在 extract 里按 (region, canonical_unit_id) 前缀聚合真跨轮 min 填 `best_error_ms`，
  要么把字段改名并与 07 plan 对齐（如 `error_ms` 保持当步、另加 `best_error_ms`=组内 min）。

### [MINOR] wall_time_ms=0（M residual ①）
- **裁定**：MINOR。无任何计时（multi_iteration.py:579 硬编码 0）；formal 需接真 per-forward 计时，
  否则 `forward_count/wall_time_ms` 无意义。M 已记 backlog，且 wall time 不影响轨迹数据结构正确性。
  backlog 项：formal 接入计时；当前 smoke 与未接线的 real 不依赖它。

### [MINOR] smoke 假执行器语义（M residual ③）
- **裁定**：MINOR。smoke 对 active target 每轮 +0.1s 且整窗随 offset 前移，导致 fixed-context 也漂移
  （离散 artifact，非真实声学运动）；本 smoke 仅用于可执行性验收，formal 以真实 forward 为准（M 已声明）。
  结论口径必须以 real 复测，不以 smoke 数字作科学结论。

---

## 核对通过的项（无 P0/P1）

- **GT firewall**：脚本 `run_multi_realign.py` 与 `multi_iteration.py` 无任何 GT 引用；pipeline 为
  纯结构 + executor（smoke=CPU / real=frozen forward）。无 GT path。✓
- **build_chain → iter0 baseline = 冻结 region 行**：`baseline_rows_from_units(region.units, full_ids)`，✓。
  **iter>0 baseline = 上一轮 candidate**：`baseline_rows = list(prev_candidate_rows)`，✓（实测它=1 的
  baseline 时间来自 it=1 candidate，见 test_chain_baseline_inherits_chained_candidate）。
- **baseline_digest 分步重算**：每步 `ctx["baseline_digest"] = _baseline_digest(baseline_rows)`（行 246），
  且 digest 内容含 chain_context（parent/iteration/recrop/split），identity 不碰撞（resume 实测 `resume_skipped=5`）。✓
- **chain_context 四元组全 truthy + fail-closed**：iter>0 显式 `recrop_view_id/split_slot_id = "none"` 哨兵，
  `build_request_identity` 对 chained request 检查 parent/iteration/recrop/split 全真，缺则 ValueError；
  build_chain 对 `request_identity` 缺失 fail-closed（`missing_identity_context:...` / `request_identity_unassignable`）。✓
- **shadow-only**：`actual_writeback` 始终为 0；candidate 仅作 isolated research state 喂下一轮，
  `region.units` 从不写回（本模块无写回路径，仅构造请求 + 记录行）。✓
- **validate_rows**：负时长 / 负时间 / 非单调分别 → `negative_duration / non_negative_time_violation /
  non_monotonic_candidate_timeline`，不静默空转（build_chain 在将上一轮 candidate 作新 baseline 前显式校验）。✓
  注意：正常 smoke 永不触发（天然单调），仅真实 forward / 扰动下触发——与 M §6 注一致。
- **--smoke/--real 互斥**：`if args.smoke == args.real: p.error(...)`，二选一强制；--real 要求 model-dir + checkpoint。✓
- **RESUME 按 request_identity 内容寻址**：`done_ids = set(state["completed_identities"])`，同 identity 跳过，
  幂等（实测重跑 `resume_skipped=5`，REQUESTS=5 行 / TRAJ=16 行 / completed=5 不重复追加，FINAL 不丢已写聚合）。✓
- **trajectory displacement 分离（04 §7）**：`target_displacement_ms` / `fixed_context_displacement_ms`
  per-region 分别独立（target 按 target_ids，context 按非 target），实测 500/800 分离。✓
- **target 与 fixed-context displacement 分开**：见上，✓。
- **编译/可执行性**：`python -m compileall -q src scripts` exit=0；`run_multi_realign.py --smoke ...`
  CPU 秒级整链跑通（5 ok / 16 TRAJ 行），数值与 M §4 完全一致。
- **现有 suite 说明**：`python -m pytest -q tests/unit_realign` 在 LANDLOCK 沙箱下整体 SIGSEGV（exit=139，无收集输出；
  对照组 `tests/research_v7/test_detector_v2_*.py` 同样段错误）。判定为环境/sandbox 与 pytest 启动不兼容，
  非 WP3 代码缺陷；且 WP3 自带单测已发现 P1-2 的独立断言错误（直接执行核实）。

---

## 建议处理顺序（Backlog/P0/P1 归属）

- P1-1 → 与 07 plan schema 契约对齐，补 per-unit first_hit + 动力学字段 + region catastrophic。
- P1-2 → 修正/新增 WP3 单测并修订 `executor=None` 语义与 M note §2 一致。
- P1-3 → REQUESTS/RUN_STATE/计数补齐 not_constructible 停止步桩。
- MINOR（backlog）：real 计时接入（wall_time_ms）、best_error_ms 跨轮 min（若 P1-1 一并补则消解）、
  smoke 假执行器仅作可执行性验收不作科学结论、target 默认 auto:1 需明确真实 pool 选择策略、
  `monotonic_improvement` 布尔用的 0.5 阈值在契约中未定义、region 级 ≥75% recovered 布尔闸未单列（pct 可导）。
