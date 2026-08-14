# T_note — WP6 E4 coarse->fine（R-U proposal → re-crop → sparse/fixed refinement）＋第四路补进四路可视化

会话：`20260814_realign_recovery_visualization_overnight`。实现人/时：WP6 实现子任务（STEP BUDGET=10）。
目标（02 E4 §272-326 冻结 / 07 §9 WP6 / 05 §G5）：实现第四路
`R-U coarse proposal → re-crop → bounded sparse/fixed refinement`（family = `R-CF`），
产出 `coarse_fine_v1` 全部 7 项指标，并把它补进 `render_current_4way.py` 的四路可视化。

核心契约（02 E4 §272-326）：Stage A 对 target 执行 R-U → coarse proposal（**不写回 baseline**）；
Stage B 以 proposal 为中心 re-crop，保留可信 context/fixed slots，只允许 target/必要邻域 active，
用 sparse/fixed refinement；proposal 与固定 context 不合法几何 → **fail-closed not_constructible**。
第四路**不得**拿 R-A/R-B、重复 R-U 或旧 pseudo-local 冒名（family 隔离验证见 §4）。

## 1. 交付物

| 文件 | 角色 |
|---|---|
| `src/lyricalign/unit_realign/coarse_fine.py` | R-CF 组合：stage-A R-U proposal、stage-B re-crop sparse/fixed refinement、constructible 门、evaluation、几何安全 smoke executor |
| `src/lyricalign/unit_realign/request_families.py` | `allowed` 增加 `R-CF`；新增 `build_r_cf` 别名（最小改动，不动算法） |
| `scripts/unit_realign/run_coarse_fine.py` | E4 运行器（smoke / real + resume），输出 01/02_coarse_fine/06/forward-evidence/FINAL_COARSE_FINE |
| `scripts/realign_recovery/visualization/render_current_4way.py` | **未改动**；`--fourth-family R-CF` 直接消费 WP6 evidence（family 索引） |
| `docs/sessions/.../provenance_notes/T_wp6_coarse_fine.md` | 本备注 |

## 2. `coarse_fine.py` 契约

### 2.1 第四路 family 与身份

- `FOURTH_FAMILY = "R-CF"`，schema `COARSE_FINE_SCHEMA = "coarse_fine_v1"`。
- 组合的两阶段通过 `build_request_identity` 的 **chain_context 全量 content-address** 绑定身份：
  - Stage A（coarse）：`parent_request_identity=None, iteration=0, recrop_view_id="base", split_slot_id="R-CF"`；
  - Stage B（refine）：`parent_request_identity` = Stage A identity、`iteration=1`、
    `recrop_view_id="recenter_proposal"`、`split_slot_id="R-CF"`。
  - 因 `chain_context` 折进 digest，**两阶段 `request_identity` 必互异**（验收确认，见 §4），
    且 chained 请求（有 parent）缺四个 family 维度之一会 fail-closed。
- 几何上 Stage A 复用 `build_family_request(family="R-U")`，再用 `_rekey_request` 把 family/chain 重标为 `R-CF`
  并重算 `request_identity`；Stage B `_build_refinement_stage` 手动构造 sparse/fixed v2 请求（re-crop 子集 + `timestamp_slot_indices`/`fixed_slot_rows`/`slot_constraint_schema="realign_sparse_fixed_v1"`）。
- `baseline_digest` 由 region 冻结 units 计算（`_baseline_digest`），与 E1/E2 基线口径一致，no-GT recovery 参考。

### 2.2 Stage B re-crop

- `_recrop_context_ids`：以 coarse proposal 各 target 均值 start 为**中心**，保留 target +
  按距离选取最邻近 `context_neighbors`（默认 2）个 context unit，裁剪到 region；`active_neighbors` 默认 0 → 仅 target active。
- 固定 context 以 `fixed_slot_rows`（`local_index/canonical_unit_id/fixed_global_start_sec/end_sec`）给出，build 时先做单调性检查，非单调 → not_constructible。

### 2.3 `constructible`（fail-closed）

`constructible(proposal_rows, region) -> reason|None`：
proposal target 行与 region 全部固定 context 合并为全局 timeline，用 `validate_rows`（monotonic / 负时长 / 负时间）
校验；不合法 → 返回 `not_constructible_reason`（如 `non_monotonic_candidate_timeline`），`run_coarse_fine` 据此把 Stage B 标
`constructible=False` 并停链，绝不静默把坏 proposal 喂进精修。

### 2.4 smoke executor（几何安全）

新增 `make_coarse_fine_smoke_executor()`：固定 context 行放到 `fixed_global_start_sec` 精确位置；
active target 行按 gap 均匀 packing（与左右固定 context 不重叠），使干净合成 region 不产生平凡碰撞。
CPU 确定性，绝对时间逻辑照常，便于 smoke 验证后续指标口径。

### 2.5 `evaluate_coarse_fine(steps)` → coarse_fine_v1

per-unit + per-region 行，覆盖 **02 E4 §311-319 全部 7 项**：

| 指标 | 字段（region agg） |
|---|---|
| target 100/200/500/1000ms | `target_recovered_100/200/500/1000`（shadow baseline 参考） |
| fixed context displacement | `fixed_context_displacement_ms`、`mean_fixed_context_displacement_ms`、`n_context_units_harmed` |
| catastrophic regression | `catastrophic_regression`、`catastrophic_regression_units`（>500ms 丢弃） |
| constructibility/coverage | `constructibility{stage_a,stage_b,n_stages}`、`coverage`（有 final 的 target 占比） |
| forward cost | `forward_cost`（成功 forward 数，stage A + stage B） |
| no-GT safety signals | `no_gt_safety_signals{provider,available_signals,uncertain_flags,danger_flags,safe_to_proceed_no_gt}`（无 GT 路径，占位） |
| Test Demo structural regressions | `test_demo_structural_regressions{ok, negative_duration_units, non_monotonic_pairs, overlap_pairs}` |

外加 `stage_a_request_identity / stage_b_request_identity`（供 G5 验证两阶段互异）与 `actual_writeback:0`（shadow-only）。

## 3. 运行器 `run_coarse_fine.py`

`--regions/--out-root/--family R-CF/--smoke/--real(需 model-dir+checkpoint-path)/--limit/--resume`。
输出（`<out-root>` 下）：
- `01_requests/REQUESTS.jsonl`：粗+精两阶段 v2 request（含各自 R-CF family + chain identity）；
- `02_coarse_fine/COARSE_FINE_OUTCOMES.jsonl`：schema `coarse_fine_v1`；
- `06_runtime/RUN_STATE.json`：按 request_identity（无 identity 的 not_constructible 区用 `region_id:R-CF:no_identity` marker）记录 completed/not_constructible/failed → resume 幂等；
- `forward/evidence/*.json`：R-CF forward evidence（`attempt.status=ok`、`attempt.request.canonical_ids/text_units`、
  `attempt.request.mutation_parameters.proposal_method="R-CF"`、`attempt.decoder_outputs.{official,raw}.rows`），供四路可视化 family 索引；
- `FINAL_COARSE_FINE.json`：按 region 聚合 + summary。

resume：同一 `--out-root` + `--resume` 重跑，已 completed（含 no-identity marker）的 region 跳过，不重复写 evidence / outcomes（验收§4确认）。

## 4. 验收（synthetic smoke）

合成 region pool（10 units、0.5s 间隔、target=连续 2-unit span + 一个非连续 span）跑 `--smoke`：

| 验收项 | 结果 |
|---|---|
| 粗+精两阶段 identity 互异 | ✅ stage-A/let-B `request_identity` 不同（chain_context 含 parent/recrop/iteration/split 生效）；B 的 `parent_request_identity`=A 的 identity、`iteration=1`、`recrop_view_id="recenter_proposal"` |
| COARSE_FINE_OUTCOMES 7 项字段齐全 | ✅ region agg 全 13 个 key 无缺失 |
| proposal 与 fixed 冲突 → not_constructible | ✅ `constructible(overlap_proposal)=non_monotonic_candidate_timeline`；非连续 target → stage A `invalid_unit_target_span` not_constructible |
| resume 幂等 | ✅ 重跑 `--resume`：`resume_skipped=2`、outcome 行数不变（4）、evidence 文件数不变 |
| GT firewall | ✅ coarse_fine.py 无任何 GT/`baseline_gt`/oracle 读取，recovery 参考全是 frozen shadow baseline；`actual_writeback=0` |

四路可视化接入（family 索引，未改 renderer）：`load_evidence_index(forward/evidence)` +
`evidence_payloads_for_family(idx, request_ids, family="R-CF")` 命中 WP6 evidence
（`proposal_method="R-CF"`，rows=4），`rows_from_decoder` 投影 4 行 doc-global、`build_track_from_evidence` 建 R-CF track。
同一 request_id 用 `family="R-U"` 查回 0 → 确认第四路不冒名 R-U/R-A/R-B。smoke 若该 item 无 R-CF evidence，renderer 走既有 `[warn] ... no ok evidence; keeping 3 tracks` 保持三路，不要求必有第四路 evidence。

## 5. 运行命令

```bash
# CPU smoke（合成 region pool）
PYTHONPATH=src python scripts/unit_realign/run_coarse_fine.py \
  --regions /tmp/cf_smoke/REGION_POOL.jsonl --out-root <run>/smoke --family R-CF --smoke
# resume（幂等）
PYTHONPATH=src python scripts/unit_realign/run_coarse_fine.py \
  --regions /tmp/cf_smoke/REGION_POOL.jsonl --out-root <run>/smoke --family R-CF --smoke --resume
# 四路可视化：把含 R-CF evidence 的 forward-root + 含其 request_id 的 plan 传入
PYTHONPATH=src python scripts/realign_recovery/visualization/render_current_4way.py \
  --forward-root <run>/smoke --plan <plan.jsonl> --item <item> --audio <audio.wav> \
  --out <run>/viz --fourth-family R-CF
```

## 6. GPU formal 模板（数据目录 `/home/hyan/Data/lyricalign/runs`）

```bash
# 1) 构建真实 region pool（取既有 unit_realign smoke verify 的 REGION_POOL 即可）
#    cp /home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify/00_population/REGION_POOL.jsonl <run>/00_population/
# 2) formal 运行（真实 Qwen forward），region 由 region_id/target_unit_ids 指定或 --limit 裁剪
PYTHONPATH=src python scripts/unit_realign/run_coarse_fine.py \
  --regions <run>/00_population/REGION_POOL.jsonl --out-root <run>/output/E4_coarse_fine \
  --family R-CF --real --model-dir <snapshot> --revision main --checkpoint-path <ckpt>
# 3) 四路可视化批次（中/粤/英/日 + hard-case，见 07 §9 WP10）
PYTHONPATH=src python scripts/realign_recovery/visualization/render_comparison_batch.py \
  --forward-root <run>/output --plan <TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl> \
  --audio-root <audio> --out <run>/visualize --fourth-family R-CF
# 4) 汇总报告（coarse_fine_v1 行喂 WP6 报告）
```

## 7. 遗留 / 限制

- smoke executor 为合成几何安全实现，指标口径（恢复率、context displacement）在真实 forward 下才具科学意义；GPU formal 前先做 small-GPU smoke。
- `no_gt_safety_signals` 为无 GT 占位（`provider:"none"`，available_signals 空），需 WP7（E5）接实际 raw/official posterior/entropy/margin/p_bad 等才能出真信号（E_note §6 / 07 §9 WP7）。
- `RUN_STATE` 对无 identity 的 not_constructible region 用 `region_id:R-CF:no_identity` marker 记 done；若未来 region_id 复用需注意 marker 唯一性。
- Stage A R-U 仍受 `len(targets)<=3` 且须连续约束（继承 build_family_request R-U 语义）；超 3-unit 连续 span 会 not_constructible，需 WP8 扩量时逐 region 评估。
- `.dsh/` 为无关既有目录，未纳入本次改动。
