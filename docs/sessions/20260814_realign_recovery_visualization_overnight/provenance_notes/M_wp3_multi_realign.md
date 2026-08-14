# M — WP3 多轮对齐动力学筛选（multi-realign dynamics screening）

Session：`20260814_realign_recovery_visualization_overnight`
日期：2026-08-14
对应计划：07 plan §9 WP3（E1 multi-realign dynamics screening / `multi_realign_dynamics_v1`）。
实现对象：`src/lyricalign/unit_realign/multi_iteration.py` + `scripts/unit_realign/run_multi_realign.py`。
状态：代码已落地，CPU smoke 验收通过；GPU formal 命令模板待真实环境执行。

## 1. 目标与设计契约

对冻结 detector region，将**同一** R-U 风格干预**逐轮**喂入，每轮 request 的 baseline =
上一轮 candidate（shadow-only：只作为 isolated research state 喂入下一轮，**从不写回 production
baseline**，`region.units` 始终冻结）。观测逐轮 target 的时序轨迹，判断动力学行为（恢复 / 定态 /
improve-then-regress / 振荡 / 发散）。

关键语义（与 02 E1 §126-146、04 §7 一致）：
- baseline 继承：iter0 = 冻结 detector 行；iter>0 = 上一轮 candidate 行。
- 更新 baseline 后**重建请求**（`build_family_request`），`identity_context.baseline_digest` 按该步
  baseline **重算**（内容寻址分步）。
- `identity_context` 中链式四元组 `parent_request_identity / iteration / recrop_view_id /
  split_slot_id` 必须**全部 truthy**（`build_request_identity` fail-closed）。本链不用 recrop/split，
  显式用 `"none"` 哨兵（内容寻址）。
- R-U 构造本身不校验单调性；`build_chain` 在喂入上一轮 candidate 前用 `validate_rows` 显式校验，
  非法（负时长 / 负时间 / 非单调）→ 记 `not_constructible`，**不静默空转**。

## 2. API

`src/lyricalign/unit_realign/multi_iteration.py`
- `TRAJECTORY_SCHEMA_VERSION = "multi_realign_dynamics_v1"`
- `build_chain(base_region, target_unit_ids, family="R-U", iterations=(1,2,3,5),
  context_neighbors=1, audio_margin_sec=0.5, identity_context=None, executor=None)`：
  生成有序 step list；`executor=None` 时仅造出 iter0，后继步标 `not_constructible`。
- `run_chain_smoke(...)`：用 smoke executor 跑整链，返回 `{schema, steps, trajectory}`。
- `extract_trajectory(steps_results, region)`：产出 per-unit + per-region 行。
- `make_smoke_executor()`：确定性 CPU 假执行器（active target nudged +0.1s，context 冻结）。
- `validate_rows(rows)`：non_monotonic_candidate_timeline / negative_duration /
  non_negative_time_violation 校验。

`scripts/unit_realign/run_multi_realign.py`
```
--regions <REGION_POOL.jsonl> --out-root <run>
[--targets auto:firstN|comma-ids] [--iterations 1,2,3,5] [--family R-U]
[--context-neighbors 1] [--audio-margin-sec 0.5] [--limit N]
[--smoke | --real --model-dir <dir> --checkpoint-path <ckpt>]
[--resume]
```
（`--smoke` CPU 秒级；`--real` 保留为 GPU formal 入口。）

## 3. 输出产物（`--out-root` 下）

- `01_requests/REQUESTS.jsonl`：每步 v2 request（或 not_constructible 桩），内容寻址。
- `02_trajectory/TRAJECTORY.jsonl`：`multi_realign_dynamics_v1` per-unit + per-region 行。
- `02_trajectory/CHAIN_RUNS.jsonl`：raw 单步运行记录（baseline/candidate/status）。
- `06_runtime/RUN_STATE.json`：`completed/queued/planned/failed/not_constructible` identities。
- `FINAL_TRAJECTORY.json`：per-region 聚合 + 计数摘要。

### per-unit schema（`multi_realign_dynamics_v1`）
```
row_kind, schema_version, song_id, region_id, request_identity,
iteration, canonical_unit_id,
initial_error_ms,      # 该步 baseline 相对 iter0 冻结 time 的 start 漂移（shadow baseline drift）
error_ms,              # 该步 candidate 相对 iter0 冻结 time 的 start 漂移
best_error_ms,         # 该步为该 unit 的 best（当前=error_ms）
delta_to_baseline_ms   # candidate vs 该步 baseline
```

### per-region schema
```
row_kind="region", ..., all_target_recovered, case_pct_recovered,
monotonic_improvement_ratio, monotonic_improvement,
improve_then_regress, fixed_point_iteration, oscillation_or_divergence,
target_displacement_ms,      # target 相对冻结 iter0 的累计位移（独立）
fixed_context_displacement_ms, # fixed-context 相对冻结 iter0 的位移（独立，04 §7）
forward_count, wall_time_ms
```

## 4. smoke 验收（本机已跑通）

最小合成 region（5 unit，单调 0.5s，target=unit1，iter 0/1/2/3/5）`--smoke`：
- 整链 5 步全部 constructible/ok（`ok=5`），每步 candidate 由 executor 产生，baseline 正确继承
  （target 的 `initial_error_ms` 随迭代 100→200→300→400→500 单调累积，证明每次从上一轮 candidate 重造窗口）。
- TRAJECTORY 16 行 = 15 per-unit + 1 per-region；per-region 聚合字段齐全
  （oscillation_or_divergence=True、target_displacement_ms=500/ fixed_context_displacement_ms=800 分离）。
- `--resume` 幂等：重跑 `resume_skipped=5`，REQUESTS/TRAJECTORY/RUN_STATE/FINAL 均不重复追加、不丢已写产物。
- GT firewall：模块/脚本无 GT 引用（纯结构 + smoke executor，无 ground-truth path）。

验证命令：
```bash
PYTHONPATH=src python scripts/unit_realign/run_multi_realign.py \
  --regions <REGION_POOL.jsonl> --out-root <run> --targets auto:1 \
  --iterations 1,2,3,5 --smoke
PYTHONPATH=src python scripts/unit_realign/run_multi_realign.py \
  --regions <REGION_POOL.jsonl> --out-root <run> --targets auto:1 \
  --iterations 1,2,3,5 --smoke --resume   # 幂等，不计入新 forward
```

## 5. GPU formal（本会话不可访问 GPU，仅交付命令模板）

真实 executor 入口保留（research_v7 RealAligner）。正式长跑需真实 region pool：
```bash
PYTHONPATH=src python scripts/unit_realign/run_multi_realign.py \
  --regions <REAL>/00_population/REGION_POOL.jsonl --out-root <REAL>/wp3/ \
  --targets auto:2 --iterations 1,2,3,5 --family R-U --real \
  --model-dir <Qwen-FA snapshot> --revision main --checkpoint-path <step-000750> \
  --limit <N> --resume
```
原则：subset 分层抽样选 region；resume 续跑；shadow-only（`actual_writeback=0`）；禁止全笛卡尔积。

## 6. 遗留问题 / 待办

- **wall_time_ms=0**：当前 smoke 未计时（CPU 秒级自然近 0）；formal 需接入真实 per-forward 计时，
  否则 `forward_count/wall_time_ms` 无意义。
- **smoke 假执行器语义**：active target 每轮 +0.1s 且窗口整体前移，导致 fixed-context 也漂移
  （离散 artifact），非真实声学运动。formal 以真实 forward 为准。
- **best_error_ms** 现为该 unit 当步值（无跨轮 min）；如需跨轮 best 需在 extract 里对 request_identity
  前缀聚合，后续可视需要补充。
- **`--targets` 默认 `auto:1`**：对真实 pool 需明确 target 选择策略（避免每 region 只打首非锚 unit）。
- **`validate_rows` 触发**：smoke 假 executor 天然单调，实际非单调触发只在真实 forward / 强扰动下出现；
  已单测 guard 逻辑正确。
- 未写 pytest（本次为 CLI 手工验收）；建议补 `tests/unit_realign/test_multi_iteration.py`（L2 层）。
