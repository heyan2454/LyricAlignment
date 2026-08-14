# WP4（commit e257542，E2 fine-split screening）代码正确性/契约 Review

- review 对象：`src/lyricalign/unit_realign/split_variants.py` + `scripts/unit_realign/run_split_realign.py` + 接线 `request_families.py`/`region_sampling.py`/`source_adapter.py`
- schema：`split_realign_v1`
- review 类型：代码正确性 / 契约（并行另一路 review 查数据一致性/接线）
- 只读代码 + 最小 CPU 实测（`--smoke` 级），未跑 GPU/渲染。
- 日期：2026-08-14（session 20260814_realign_recovery_visualization_overnight）

## 结论速览

| 编号 | 级别 | 一句话 |
|---|---|---|
| WP4-1 | **P0** | 真实营地 REGION_POOL 的 unit 无 `state` 字段 → `partition_region` 四种 partition 全部返回空 → WP4 完全不可用 |
| WP4-2 | P1 | 串行链重建单请求时 `parent_request_identity` 依赖外层覆盖 `request_identity` 维持，identity 稳定性脆弱（中等） |
| — | MINOR | resume 分支 `candidate_rows=prev_candidate or []` 在 resume 首个 identity 时丢既往候选，影响 merge/指标；`iteration=idx` 与 `sub_target_index` 用 `idx` 易被误读为绝对迭代号 |

#2（partition 语义）、#3（identity）、#4（GT firewall）、#5（指标完整性）经实测与代码核对 **无 P0/P1**，见下。

---

## [P0] WP4-1：unit 级 `state` 未注入真实营地 → WP4 四种 partition 全为空

### 证据
1. 真实营地 `/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify/00_population/REGION_POOL.jsonl` 第 1 行 region：
   - region 顶层有 `detector_state=UNSAFE`、`target_unit_ids=[0]`；`units` = 111 个 element。
   - **111 个 unit 均无 `state` 字段**：keys 仅 `{canonical_unit_id, end_sec, reference_end_sec, reference_start_sec, start_sec, text}`。实测 `[x for x in region['units'] if 'state' in x]` 长度 = 0。
2. `split_variants.unsafe_groups`（L90）依赖 `unit_state(u)`（L69-70）＝ `u.get("state") or ""` 过滤 REJECT/UNCERTAIN。
3. 实测（本 review 用真实 REGION_POOL 第 1 行直接调用）：
   - `unsafe_groups(region)` → `[]`
   - `partition_region(region, part)` for `{one_unit, two_unit, adaptive, anchor_gap}` → 全部 `n_subtargets=0`。
4. 根因：unit 级状态在**适配层被显式丢弃**，不止是"未接线"：
   - `region_sampling.build_region_population`（L24-70）只产出 `target_unit_ids` + `detector_state`（从 detector_shadow 的 unit `state` 派生），**从不写 region 的 `units` 列表**。
   - `source_adapter.enrich`（L82-89）补齐 `row["units"]` 时只保留 `canonical_unit_id/start_sec/end_sec/text/reference_start_sec/reference_end_sec`，**舍去 `state`**；即便 `shadow_by_window` 提供的 shadow unit 带 `state`（L101-147），也只用来更新 `start_sec/end_sec`（L146-147）并写审计，**从不回写 `state`**。
   - 因此无论哪个上游产出 REGION_POOL，unit 层都不再含 `state`，而 `split_variants` 完全以 unit 层 `state` 为困难片段筛选依据 → 契约在适配/营地产物层断裂。

### 影响
`scripts/unit_realign/run_split_realign.py` 对真实营地逐 region `partition_region` 得空 subtargets → 无 request、无 outcome、指标全空。**WP4 在真实数据上完全不可用**（非退化）。

### 建议（三选一，推荐先做 a）
- **(a) 适配层回写 state（恢复契约，改动最小）**：在 `source_adapter.enrich` 把 detector_shadow 的 `shadow["state"]` 写回对应 unit；同时 `run_unit_realign.py` 主入口产 REGION_POOL 前统一补齐，保证营地内的 unit 恒有 state。这样 `split_variants` 无需改动、语义一致。
- **(b) split_variants 增加 state join/fallback**：`partition_region` 当 `unsafe_groups==[]` 且 region 顶层为 `detector_state=UNSAFE` 时，用 `target_unit_ids`（结合左右 anchor_candidates）构造唯一 unsafe group（现 L233-243 的 `fallback_all` 因 `flat_targets` 为空而不会触发，属**死代码**）。此方案能立即跑，但把"无 state 冲突"静默降级为整段目标，应在 audit/outcome 显式打标 `state_missing_fallback`。
- **(c) 明确营地 schema 约束 + 入口校验**：在任何 build_split_requests 前 assert 每 unit 有 `state`，缺状态快速失败（fail-closed）而非返回空，避免空结果被误当"无困难片段"。

> 结合 WP1 identity 要求"输入变化不得复用旧 evidence"，单位 state 属决策输入，缺失时 identity 同样应能区分（chain_context 已整体 content-address，无需额外处理）。

---

## [P1] WP4-2：串行链重建单请求时父链 identity 依赖外层覆盖，链 identity 稳定性脆弱

### 证据
`run_split_realign.py` 串行链（L2R/R2L）在有一个 prior candidate 后，会为 `prev_candidate` 重建该 sub-request（L275-285）：
- 重建时传入**单元素** subtarget 列表 `[{"index": int(st["index"]), ...}]`。
- 由此 `build_split_requests` 内部的 `prev_identity` 在循环首为 `None`，导致重建 chain_ctx 中 **不含 `parent_request_identity`/`iteration`/`recrop_view_id`/`split_slot_id` 完整四 key**，其原生 `request_identity` digest 与一次性全链 build 的 digest 不同。
- 依赖 L285 `use_req["request_identity"] = rid or ...` 用**原 chain 请求的 rid** 强制覆盖才维持 identity 稳定。

### 影响
- 仅靠一处 `request_identity` 显式覆盖保持缓存/去重 identity 不变；若未来改动该行或遗漏 `rid`，串行链 identity 会静默漂移（与一次性链构建不一致），可能 recycle 错误 forward 或无法 resume。
- 非崩溃级，但属契约脆弱点。

### 建议
把"链上重建"改为基于**完整已 build 的 requests 列表 + 既有 `parent_request_identity`** 重建，不要重新走上游 `prev_identity` 计算路径（例如为重建单 request 传入其应有的 `parent_request_identity`/`iteration`，或在 `build_split_requests` 增加只重建 payload 而保留 chain_context 的重载），避免依赖覆盖维持一致性。

---

## MINOR（进 backlog）

1. **resume 首请求候选丢失**：`run_split_realign.py` L260-269 resume 分支 `executed.append({... "candidate_rows": prev_candidate or [], ...})`。若 resume 落在某 serial 链的第一个且无 `prev_candidate`，该已完成 shard 的候选记为空，`merge_split_results`/`evaluate_split` 的 recovered 指标会被低估。建议 resume 时按 `request_identity` 从已持久化 outcome/request 恢复候选，而非取 `prev_candidate or []`。
2. **`iteration` 语义易误读**：`split_variants` L329 `"iteration": idx`（idx 为 `sub_target_index`）。对串行链这是链内步序，合理；但字段名 `iteration` 与 multi-iteration 的迭代号易混淆，建议在 chain_context 注释/命名明确为 `split_step_ordinal` 以免后续接线误当绝对迭代计数。
3. `partition_region` L233-243 `fallback_all` 分支当前实际**不可达**（真实营地下 `flat_targets` 为空），且与 WP4-1 的 state 缺失场景未衔接，属死代码/误导。

---

## #2 partition 语义（无 P0/P1）

对照 02 E2 §180-188 机制区分，实测（合成带 state region，unsafe groups `[[0,1,2],[4]]`）：
- `one_unit` → `[0],[1],[2],[4]`：每 unsafe unit 单目标 ✓
- `two_unit` → `[0,1],[4]`：连续对，`_ids_to_segments(g,2)` 对 length5→[0,1],[2,3]+兜底，组内正确 ✓
- `adaptive` → `[0,1,2],[4]`：按 `SAFE_GAP_SEC=0.30` 拆 safe gap；本例无 >0.30 gap 未拆 ✓
- `anchor_gap` → `[0,1,2],[4]`：按 ACCEPT anchor（组间有 unit3=ACCEPT 作为 gap 参考）或 `LONG_GAP_SEC=0.90` 拆 ✓
- 跨 group 不混合、sub_target 恒为相邻 canonical id 连续段 ✓
- **`>3 unit` 子目标 R-A 回退**：`_effective_family` L263-269 对 `family in {R-U,R-U1,R-U3}` 且 `span_len>3` → `"R-A"`。实测 `_effective_family("R-U",5)=R-A`、`("R-U",3)=R-U` ✓，且 `effective_families` 记入 outcome ✓。

无 P0/P1。

## #3 identity（无 P0/P1）

实测（合成 region，`base_ctx` 含完整 identity 必需 key）：
- `build_split_requests(..., partition="two_unit")` 对 `direction ∈ {L2R, R2L, independent}`：每方向 shard 的 `request_identity` 全部唯一（`len(set(ids))==len(ids)` 各自真）。✓
- 机制：`split_variants` L318-324 把 `split_slot_id`（`f"{partition}:{direction}:idx{idx}"`）+ `direction` + `partition` 写入 `identity_context` → `chain_context`（L337）；`build_request_identity` L73-86 **content-address 整个 `chain_context`**，故不同 partition/direction/shard 的 digest 互异，满足 WP1（不同分片/方向 identity 互异）。✓
- **fail-closed 四 key**：`build_request_identity` L64-68 当 `parent_request_identity` 存在时要求 `iteration/recrop_view_id/split_slot_id` 全有，缺则 `raise ValueError`（显式失败非静默复用）。`split_variants` L325-333 串行方向确实注入全部四 key（`parent_request_identity=prev_identity`、`iteration=idx`、`recrop_view_id='none'`、`split_slot_id`）。✓
- 注意：WP4-2（P1）正是上述四 key 在**链上重建路径**下不稳定的脆弱点，identity 最终一致。

## #4 GT firewall（无 P0/P1）

- `split_variants.py` 及其被调 `request_families.py`/`multi_iteration.py` 无 GT 消费；`reference_*` 字段由 `source_adapter` 设成 detector baseline（L87-88，baseline `start_sec/end_sec` 的别名），非真实 GT。
- `intervention_check.FORBIDDEN_REQUEST_KEYS = {gt, ground_truth, label, old_error, ...}` 阻塞 GT/oracle 进入 request。
- aggregate 恒 `"actual_writeback": 0`（shadow-only）。
- 无 GT 路径突破代码。

## #5 指标完整性（`split_realign_v1`，02 E2 §205-214，无 P0/P1）

`evaluate_split` 提供全部 8 项 + extra_forward_cost（按 §205-214 及需求核对）：
- recovered_strict：`recovered_strict_100` / `recovered_strict_200` ✓
- recovered_coarse：`recovered_coarse_500` / `recovered_coarse_1000` ✓
- context_preservation：region 级 `context_preservation` + `n_context_units_harmed` ✓
- split_boundary_harm：`split_boundary_harm`（unit 行 `on_split_boundary`/`split_boundary_harm`）✓
- merge_collision / merge_overlap：region `merge_collision` / `merge_overlap`（来自 `merge_split_results`）✓
- non_monotonic：region `non_monotonic` ✓
- recovered_unit_fraction：`recovered_unit_fraction`（=n_200/n_total）✓
- region_all_hit / ge75_hit：`region_all_hit` / `region_ge75_hit` ✓
- extra_forward_cost：`extra_forward_cost = max(0, forward_count-1)` + `forward_count` ✓
- 另有 per-unit 行（含 `error_ms`）与 region aggregate 行（含 `strict_*_recovery`、`effective_families`、`n_constructible_sub_targets`）。✓

无 P0/P1。

---

## 实测命令摘要（可复现）
- state 缺失 & 空 partition：
  `python -c` 读 REGION_POOL.jsonl L1，`partition_region(region, part)` 各 partition → `[]`，`unsafe_groups`→`[]`。
- partition/identity/回退（合成 region）：`build_split_requests`/`_effective_family`/`partition_region` 断言如上。
- 平台提示（无碍）：landlock partial enforcement + locale 告警仅 stderr，不影响结果。
