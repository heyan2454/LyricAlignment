# O — WP3 E1 multi-realign dynamics：数据一致性/跨模块接线 review

- 审查对象：commit `3d19152`（WP3 E1 multi-realign dynamics runner）
- **重要**：审查时工作区存在 N-review 之后的**未提交改动**（`multi_iteration.py` +75/-45、
  `run_multi_realign.py` +21），已部分修复旧 P1（best_error 游标、first_hit_ms_iteration、catastrophic_regression、
  per-unit monotonic/improve-then-regress、not_constructible stub）。**本报告按"当前工作区 on-disk 实际可运行代码"取证**，
  同时标注每项相对 commit `3d19152` 的现状。未提交改动本身尚未被任何审查/测试验收，属待收尾状态。
- 审查范围：`src/lyricalign/unit_realign/multi_iteration.py`、`scripts/unit_realign/run_multi_realign.py`、
  `src/lyricalign/unit_realign/request_families.py`（接线）+ 07 plan §3.2 / 02 E1 §126-146
- 审查类型：数据一致性 / 跨模块接线（只关注 P0/P1，MINOR 进 backlog）
- 限制：pytest 在本 conda 环境 + landlock 沙箱下**对任意平凡测试也段错误（exit 139）**，故无法在沙箱内以 pytest 验证绿（见 [环境限制]）。WP3 逻辑改用等效 standalone 运行脚本 + 手动复现核心指标判定来取证。
- 实跑：`run_multi_realign.py --smoke --iterations 1,2,3,5 --targets auto:1`（输出 /tmp/wp3smoke、/tmp/wp3new、/tmp/wp3p、/tmp/wp3p2 等）与多处判定逻辑复现。

---

## P0

### [P0-1] `oscillation_or_divergence` 判定在绝对值序列上算方向翻转 → 纯单调改善被误报"振荡"，真实振荡被漏报
- **问题（对当前 on-disk 代码仍成立）**：`extract_trajectory` 先对 `error_ms` 取 `abs()` 构造序列（未提交改动里为
  `abs_series = [abs(float(r["error_ms"])) ...]`），再用相邻差的符号判定"方向是否翻转"（`signs.append(1 if d>0 else -1)`、
  `if any(s==p ...)`）。取绝对值把 `error_ms` 的**带符号方向**丢掉，而后面的"方向翻转"判定却在绝对误差上做，结果：
  - 纯**单调改善**（绝对误差递减，如 [5,3,1]）相邻差都是负号 → `any(prev==s)` 触发 → **改善被误判为振荡/发散**；
  - 真实 **振荡**（[5,1,5]：|-4|、|+4| 符号确实翻转）→ 因两段符号不同 → `any(prev==s)` 不触发 → **真振荡漏报**；
  - 发散序列 [1,3,5] 恰好命中（同一号连续），但属"碰巧"而非"算对方向"。
- **证据**：手动复现 + 对当前 on-disk 代码直接调 `extract_trajectory`：
  ```
  improving [5,3,1]  -> osc_or_div=True   (错：本应 False)
  oscillate [5,1,5]  -> osc_or_div=False  (错：本应 True)
  diverge   [1,3,5]  -> osc_or_div=True   (对，但逻辑上并不可区分)
  纯单调改善 [50,30,10,5]（当前代码, extract_trajectory 真实调用）-> oscillation_or_divergence=True (错)
  ```
  另用 smoke 实跑（/tmp/wp3smoke、/tmp/wp3new），纯发散序列（error 100→500 单调增）也报
  `oscillation_or_divergence=true`——与"方向翻转"注释不符。
- **为什么是 P0**：`oscillation_or_divergence` 是 02 E1 定义的核心 dynamics 分类之一（07 §3.2 `oscillation_divergence`），
  本 bug 使"是否振荡/发散"这个主结论指标在真实数据上不可用，会直接污染 E1 主结论（结果 A 的"monotonic 继续改善"
  与结果 C 的"振荡/发散"无法正确区分）。修复需在**带符号**的 `error_ms`（而非 `abs`）上算相邻差符号来判定方向翻转。
- **建议**：振荡判定改用**带符号**的 `error_ms` 序列（或 `sign(error_ms)` 的翻转次数），发散单独用净增长判定；
  并为振荡/发散/单调改善/单调发散各补一条**值级**断言（见 [P1-5]，现有测试未覆盖）。

---

## P1

### [P1-1] resume 部分命中（region 内同时含已完成与新增身份）会重复追加 trajectory 行
- **问题（对当前 on-disk 代码仍成立）**：`run_multi_realign.py` 里 `build_chain` 会**无条件对所有 constructible step
  重新执行 forward**（`run_chain_smoke -> build_chain(..., executor=executor)` 每个 step 都 `_execute`），resume 只在
  "写输出"时按 `rid in done_ids` 跳过（L226-228），并不跳过重算/重执行。当某 region 至少有一个新 step
  （`fresh_region=True`）时，`all_traj_rows.extend(run["trajectory"])`（L240）会把**整条链**（含已完成 step 重新算出的行）
  追加到已保留的 `pre_traj` 上，导致已完成身份的行重复。未提交改动不改此路径。文档字符串（L7-8）声称
  "same identity is never re-executed"，与实际不符。
- **证据**：先跑 `--iterations 1,2,3`（region 全 done，unit 行 12 条），再 `--resume --iterations 1,2,3,5`（iter5 新增）
  → TRAJECTORY.jsonl 变 **27 条**（=12 已完成重复 + 15 正确）；`(iter0..3, cid)` 键各出现 2 次（/tmp/wp3p、/tmp/wp3p2）。
  (b) `--real` 下重复执行的 forward 还会白耗 GPU 预算，且模型非确定时用"二次重算"候选混入已落盘轨迹。
- **建议**：resume 时按 `request_identity` 过滤本 region 的 `trajectory`/`steps`，只 append 未完成身份的步骤行为；
  或让 `build_chain` 接受 `done_identities` 参数跳过已完成 forward。并对"部分 resume 无重复"补一条回归测试。

### [P1-2] RUN_STATE 的 `failed_identities` / `not_constructible_identities` 从不落桶
- **问题（对当前 on-disk 代码仍成立）**：`_record`（run_multi_realign.py L117-127）只有 `bucket == "completed_identities"`
  才 append（L121），`failed`/`not_constructible` 只进 `planned_identities`（L123-125）。schema（L14-15 /
  `_load_state` L100-102）声明存在 `failed_identities`/`not_constructible_identities`，但这些桶永远为空。未提交改动为
  not_constructible 加了 stub（`_record(state, seed, "not_constructible")`），但 `_record` 落桶门不改 → stub 仍只进
  `planned_identities`，`not_constructible_identities` 依旧为空。
- **证据**：手动调用 `_record(state, 'id-X', status)` 对 ok/failed/not_constructible 三种 status：
  ```
  ok              -> completed=['id-ok']      failed=[] notcon=[]
  failed          -> completed=[]              failed=[] notcon=[]
  not_constructible-> completed=[]             failed=[] notcon=[]
  ```
  smoke 实跑（/tmp/wp3p2 / RUN_STATE.json）得到 `completed=5 failed=0 not_constructible=0`（ok 场景），
  非 ok 场景下桶仍不会有 failed/not_constructible 内容。
- **为什么是 P1**：resume 幂等合并依赖"已完成身份"做 skip，`failed`/`not_constructible` 未登记意味着这些身份每次
  resume 都会被重试（smoke 无碍，`--real` 会反复重 forward 失败步骤），且 state 对失败的"已登记"表述是假的。
- **建议**：`_record` 在非 completed 分支也应 append 到对应桶；或用 `_record(..., status)` 直接桶映射。

### [P1-3] `best_error_ms`（commit 状态为伪 best，工作区未提交改动已修复）
- **问题（对 commit `3d19152`）**：`extract_trajectory` per-unit 行 `"best_error_ms": round(err_ms, 4)` 直接复用当前步误差，
  未做跨迭代 min，等价于 `error_ms`。02 §132 / 07 §3.2 要求 per-unit `best error`（历史最优）。
- **现状**：工作区未提交改动已改为"跨迭代回填 true min"（每 unit 取全部 step 的 `min(error_ms)`），
  /tmp/wp3new 复测 cid=1 各 iter `best=100`（历史最小值）——**本项在未提交改动中已修复，待提交/补断言**。
- **建议**：提交该修复并补值级断言（见 P1-5）；注意 best 取 `min(error_ms)`（带符号）而未取 `min(|error_ms|)`，
  best 可能为负偏小，请确认口径（02 的 best error 建议用绝对误差的最优）。

### [P1-4] `multi_realign_dynamics_v1` 相对 07 plan §3.2 仍有缺字段 / 错语意（部分已被未提交改动补齐）
- **问题**（07 §3.2 L97-100 / 02 §133-146）要求：`initial_err / error@iter / best_err /
  first_hit_ms_iteration{100,200,500,1000} / monotonic_improvement_ratio / improve_then_regress / fixed_point_iter /
  oscillation_divergence / target_displacement_ms 与 fixed_context_displacement_ms 分开 / collateral_harm /
  forward_count / wall_time`。当前状态（对 on-disk 代码）：
  - **已补齐（未提交改动）**：per-unit `first_hit_ms_iteration_100/200/500/1000`、`monotonic_improvement_ratio`、
    `improve_then_regress`、`fixed_point_iteration`、region `catastrophic_regression`、`best_error_ms` 游标（见 P1-3）。
  - **仍然缺失 `collateral_harm`**（02 §139 `fixed-context displacement/collateral harm`；07 §3.2 `collateral_harm`）——
    仍只有 `target_displacement_ms` + `fixed_context_displacement_ms`，无 harm 维度；
  - **`wall_time_ms` 恒为 0.0**——未提交改动把 `wall_ms=0.0` 改为直接写 `"wall_time_ms": 0.0`，**仍未计时**；
    `run_multi_realign.py` 的 `import time` 依然未使用（02 §146 / 07 §3.2 `wall_time`）。
  - **`fixed_point_iteration` 语意仍错位**——未提交改动存 `bool(len>=2 and last[-1]<=1.0 and last[-2]<=1.0)`，
    即"末两步误差≤1ms"＝**末步已恢复到 iter0 时刻**，而非"候选在两个 step 间不再移动"的 fixed-point（02 §78
    "第一轮改善后停在**错误** fixed point"）。字段名 `_iteration` 却存布尔。
  - **`oscillation_or_divergence` 仍用 abs 序列算方向**——见 P0-1（未随补丁修复）。
- **证据**：/tmp/wp3new、/tmp/wp3p2 的 region 行实测 `wall_time_ms: 0.0`、`catastrophic_regression` 字段存在但
  displacement/harm 仍是 sum-of-abs 口径；`fixed_point_iteration` 语义如上。
- **为什么是 P1**：E1 主结论仍需 collateral harm / 真实 wall time；`fixed_point_iteration` 名实不符会被下游误用。
- **建议**：补 `collateral_harm`（fixed-context displacement 的变异程度/超阈值比率）、真实 wall_time（per step forward
  elapsed 计入 RUN_MANIFEST budget 账本）；`fixed_point_iteration` 改为迭代序号或改名（如 `fixed_point_reached`），
  并按"候选间隔稳定"而非"误差≈0"重定义。

### [P1-5] 轨迹/metrics 无"值级"回归测试；现有测试无法捕获 P0-1/P1-3/P1-4
- **问题**：`test_multi_iteration.py` 只断言 schema key 存在（`test_extract_trajectory_has_region_and_unit_rows` 检查
  displacement key）、构造/chain/validate 行为，**不校验** oscillation / fixed_point / best_error / first_hit 的具体值，
  也未覆盖 resume 重复/state 落桶场景（P1-1/P1-2）。
- **证据**：L81-93 仅 `assert kinds.get("region")==1`、`"target_displacement_ms" in reg` 等结构断言。
- **建议**：为单调改善/单调发散/真振荡/真 fixed-point 构造 deterministic smoke 序列并断言各 flag（尤其 P0-1）；为 1/2/3→
  1/2/3/5 部分 resume 补"无重复"断言；为 `_record` 三种 status 落桶补单测。

---

## MINOR（进 backlog，不阻塞）

- **identity 哨兵 `recrop_view_id="none"` / `split_slot_id="none"` 与未来 E2/E3 的防撞**：哨兵已进入 `chain_context`
  （content-addressed），"无 recrop/split"链与任何真实 recrop/split 链的身份必然不同，当前**不会**跨模式误复用
  （5 个 iteration 身份互异，实测）。仅当未来 E2/E3 出现字面量就叫 `"none"` 的 view/slot id 才会撞——建议约定
  哨兵命名（如 `"none"`→`"@none"`）或用不冲突前缀，属防御性 MINOR。
- `_initial_target_error_ms`（multi_iteration.py L443-445）为未接线死代码，恒返 0.0，无调用点 → 可删或实现。
- region 级 displacement 聚合口径未文档化：是对**末个 constructible step** 的所有 unit `|末候选-t0|` **求和**，非 per-unit
  或 max；target / fixed 分开是满足的，但"sum-of-abs"语义应写清（02 §7 只要求分开）。
- 轨迹 `first_hit` / oscillation 判定阈值为硬编码 magic number（1.0ms、2.0ms），建议集中为 schema 常量并在 docs 冻结。

---

## 环境限制（影响"pytest 需全绿"验收）
本沙箱（landlock）内，`python -m pytest` 即使对**/tmp 下 `assert 1==1` 的平凡测试**也稳定段错误（exit 139，5/5）：
```
run1..4 exit=139 (Segmentation fault, core dumped)
```
而与仓库无关——`python -c "import lyricalign.unit_realign.request_families"`、构建 request、跑
`run_multi_realign.py --smoke` 均正常（exit 0）。因此**无法在本环境用 pytest 验证 `tests/unit_realign` 全绿**；
pytest 段错误是沙箱/环境层面的问题，非测试代码错误。建议在无 landlock 沙箱的正常终端重跑
`PYTHONPATH=src python -m pytest -q tests/unit_realign` 确认绿（代码层面未见测试断言过强导致的崩溃迹象），
并单独重跑断言增强后的 `test_multi_iteration.py` 以覆盖 P0-1/P1-1/P1-2。

## 结论
有 P0/P1（对 commit `3d19152` 与当前工作区 on-disk 代码均成立）。
**P0**：`oscillation_or_divergence` 方向判定在 `abs` 误差序列上算符号（未随补丁修复），纯单调改善/真实振荡均判定失真，
直接污染 E1 dynamics 主结论。
**P1（仍开放）**：resume 部分命中重复追加 trajectory 行（P1-1）、RUN_STATE failed/not_constructible 桶永不落（P1-2）、
schema 仍缺 `collateral_harm` / 真实 `wall_time` 且 `fixed_point_iteration` 名实不符（P1-4）、metrics 无值级回归测试（P1-5）。
**P1（部分/已由未提交改动修复）**：`best_error_ms` 与 `first_hit_ms_iteration{100..1000}`、`catastrophic_regression`、
per-unit monotonic/improve-then-regress 已在工作区未提交改动中补齐（需提交 + 补断言），见 P1-3/P1-4。
GT firewall：`multi_iteration.py` / `run_multi_realign.py` **干净**（无 GT/ground_truth/label/oracle 消费，
仅一处 unused placeholder docstring），符合 shadow-only。
identity 接线：`chain_context` 内容寻址正确，5 迭代身份互异，迭代间不会因哨兵误判同一请求；哨兵跨 E2/E3 撞仅为防御性 MINOR。
pytest 绿：本沙箱内 pytest 自身段错误（exit 139，含 /tmp 平凡测试），无法在本沙箱验收，需在正常终端重跑确认。
