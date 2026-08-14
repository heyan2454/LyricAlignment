# P — WP4 E2 fine-grained split screening（协议与 smoke）

日期：2026-08-14（本 session）
对应：07 计划 §9 WP4 / 02 E2 §168-222；schema `split_realign_v1`（07 §104-116）。

## 实现文件
- `src/lyricalign/unit_realign/split_variants.py`
  - `PARTITION_SCHEMAS = ("one_unit","two_unit","adaptive","anchor_gap")`
  - `partition_region(region, partition) -> list[subtarget]`：纯函数，返回连续 canonical-id 子目标段，并在 `partition_identity` 记录 partition 决策（`adaptive_boundary@a~b` / `anchor_boundary@...` / `gap_boundary@...`）。
  - `build_split_requests(..., partition, direction, family, identity_context)`：每组子目标一个 v2 request（复用 `build_family_request`）。**每个子请求的身份都带 `split_slot_id`（= `{partition}:{direction}:idx{idx}`）+ `direction` + `partition`**，经 `chain_context` 内容寻址进 `request_identity`，保证不同分片身份互异（WP1 P1-2）。串行（L2R/R2L）子请求还带 `parent_request_identity/iteration/split_slot_id`（fail-closed 四 key）。
  - `class_target_order(region, subtargets, direction)`：L2R 递增 / R2L 递减 / independent 原序（独立合并）。
  - `merge_split_results(results)`：按 canonical 序合并各分片候选，产出 `merge_ok`/`merge_collision`/`merge_overlap`/`non_monotonic`/`collision_units`。
  - `evaluate_split(...)`：产出 `split_realign_v1` 行（每 unit 行 + 每 region 聚合行），**全部 8 项指标**（见下）。
- `scripts/unit_realign/run_split_realign.py`
  - `--regions/--partition one_unit|two_unit|adaptive|anchor_gap（兼容 1unit/2unit 等别名）--direction L2R|R2L|independent/--family R-U/--out-root/--smoke/--real(--model-dir --checkpoint-path)/--limit/--resume`。
  - 输出：`01_requests/REQUESTS.jsonl`、`02_split/SPLIT_OUTCOMES.jsonl`（schema `split_realign_v1`）、`06_runtime/RUN_STATE.json`（按 request_identity resume）、`FINAL_SPLIT.json`。
  - 执行：smoke = `make_smoke_executor()`（确定性 CPU）；real = 冻结 Qwen `real_executor`。串行方向下后一子目标以**前一 forward 真实候选作为 baseline**（真 multi-realign chaining）。

## 指标口径（`split_realign_v1`，02 E2 §205-214 全部 8 项 + extra_forward_cost）
- 恢复参考 = **冻结 detector 基线（shadow-only，无 GT）**：`err_ms = candidate_start - baseline_start`（×1000）。
- 每 unit：`recovered_strict_100/200`、`recovered_coarse_500/1000`。
- 每 region 聚合：`strict_100/200_recovery`、`coarse_500/1000_recovery`、`context_preservation`（fixed-context 位移≤1ms 全保）、`split_boundary_harm`（位于 split 边界的 unit 被位移>1ms）+ `split_boundary_harm_units`、`merge_collision`、`merge_overlap`、`non_monotonic`（合并时间线违反单调）、`recovered_unit_fraction`（strict-200 命中 fraction）、`region_all_hit`（100% strict-200）、`region_ge75_hit`（≥75%）、`extra_forward_cost = forward_count − 1`。
- `actual_writeback = 0`（shadow-only 永真）。

## Identity 契约（WP1 / 07 §5）
- `build_request_identity` 已支持 `split_slot_id`（request_families.py §51-88）。本模块把 `split_slot_id`/`direction`/`partition`/`sub_target_index` 全部并入 `identity_context`→`chain_context`，同一 region 同子目标在 L2R 与 R2L 下身份不同（smoke 验证 sha256 不同），不同分片互异。
- smoke 下补全 8 个必需 identity key（`audio_sha256/model/checkpoint/decoder/code/text_adapter` + 本模块补 `baseline_digest`），否则 `request_identity=None`（f-fail 关断）。
- **>3-unit 子目标**：`R-U` 上限 3 连续 unit，超长回退 `R-A`（context 保留、无长度上限），有效 family 记入 `effective_families` 与 `split_shard.effective_family`。

## 验收 smoke（已通过，CPU）
合成 pool（`/tmp/REGION_POOL_smoke.jsonl` 等，本机临时，不入 git）：
- 最小 region：ACCET anchor(unit0) + unstable REJECT/UNCERTAIN span（unit1-6）+ ACCEPT anchor(unit7)。
- `--partition one_unit --direction L2R --smoke`：6 个子目标各自成请求、split_slot_id 互异、request_identity 6 个唯一非空；SPLIT_OUTCOMES 各指标字段齐全；region 聚合 recovered_unit_fraction=0.5、strict_200=0.5、split_boundary_harm=[2..6]、extra_forward_cost=5。
- `--partition anchor_gap --smoke`：无中间 anchor 时整跨度 1 子目标（R-A）；引入中间 ACCEPT anchor 后正确切成 2 子目标 R-U。interleaved-anchor region 下 anchor_gap 与 adaptive 均切出 2 个子目标。
- `--partition adaptive`：安全 gap（unit 间静音>0.30s）处切分，记录 `adaptive_boundary`；region3 切成 [1,2]/[3]/[4]。
- 方向子实验：L2R/R2L 身份互异；independent merge_ok=True、recovered_fraction=1.0（独立模式下各分片从冻结基线独立评估，无串行累积位移）。
- resume 幂等：首跑 6 ok，`--resume` 重跑 6 resume_skipped、不重复写 SPLIT_OUTCOMES（仍 7 行）、RUN_STATE completed/planned 各 6。
- GT firewall：新模块与 runner 无任何 GT 消费路径（grep 确认仅注释提及 shadow/no-GT）。

## GPU formal 批命令模板（本会话 GPU 不可访问，交付模板）
```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
RUN=/home/hyan/Data/lyricalign/runs/unit_realign_wp4_split
mkdir -p "$RUN"

# 1) 构建 region pool（复用既有 REGION_POOL / emit_detector_rows 产物；每个 region 需含 units 与 detector_state）
#    REGION_POOL=...   # 既有 00_population/REGION_POOL.jsonl

# 2) 四机制 × 三方向 正式跑（shadow-only；恢复由 frozen detector 基线评估，不吞吐 GT）
for PART in one_unit two_unit adaptive anchor_gap; do
  for DIR in L2R R2L independent; do
    PYTHONPATH=src python scripts/unit_realign/run_split_realign.py \
      --regions "$REGION_POOL" --out-root "$RUN/${PART}__${DIR}" \
      --partition "$PART" --direction "$DIR" --family R-U \
      --real --model-dir <MODEL_DIR> --checkpoint-path <CKPT> \
      > "$RUN/log_${PART}__${DIR}.txt" 2>&1 &
  done
done
wait
# resume 语义：同 OUT_ROOT + --resume 重跑同一命令即可续（按 request_identity 幂等）

# 3) 汇总（每 run 的 FINAL_SPLIT.json 即 region 聚合）
```
池规模注意：`--limit` 单个小样本烟测可截断；正式前冻结 `--family R-U` / `--direction` 全部超参。

## 遗留问题 / 后续
- 指标口径的恢复引用采用 frozen detector 基线（无 GT），与 E1 `multi_realign_dynamics_v1` 的 iter0 基线口径一致；当后续接入 GT 评价时需把恢复引用切到逐字符 GT（同 calibration 口径），并保留本 shadow 口径作为基线对照。
- `context_preservation`、`split_boundary_harm` 的位移阈值（`CONTEXT_EPS_MS=1.0`）为初值；正式分析前冻结并统一到其他 WP 的 collateral_harm 口径。
- real 执行尚未在本会话验证（GPU 不可访问）；`_to_v7_request`/`_candidate_rows_from_v2` 为既有 multi_iteration 复用，formal 首跑需抽查 candidate 映射与 identity。
- `build_split_requests` 中串行链的 `iteration` 用子目标 index 作为序（非 E1 迭代号），在 identity 中与 `parent_request_identity` 并存；若 formal 需区分"同一 index 多轮"，将来扩 `iteration` 维度。
- run 数据一律外置 `/home/hyan/Data/lyricalign/runs/`（工作树只入轻量 manifest / provenance note，本 session smoke 产物在 /tmp，未入 git）。
