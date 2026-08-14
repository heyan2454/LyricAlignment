# X_note — WP8 P6 adaptive expansion（扩量编排）

状态：**实现 + synthetic smoke 通过**（`compileall` OK，未跑 GPU forward）。
文档对应 `07_CODEX_IMPLEMENTATION_PLAN.md` §9 WP8 与 §6 G7；合同 `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md` §4（不做笛卡尔积、只扩 top1/2、扩量 forward 记账本）。

## 1. 概览

WP8 是**纯 CPU** 扩量编排批次：从 E1–E6 screening（40–60 regions）的 FINAL 聚合结果中选出 **top-K（默认 2）机制**（strict recovery + safety），再对更大 region population **分层抽样**得到 >=200 独立 regions + **song-held-out** confirmation population，产出供 WP3/4/6 runner 消费的 REQUESTS.jsonl/manifest。扩量 forward 只在预算账本中记账，**不实际跑**。

## 2. 实现文件

- `src/lyricalign/unit_realign/adaptive_expansion.py`（核心逻辑）
  - `EXPANSION_SCHEMA` / `EXPANSION_SCHEMA_VERSION = "lp_unit_realign_expansion_v1"`
  - `rank_mechanisms(screening_results, top_k=2)`：机制排序
  - `select_regions_for_expansion(population, mechanism_subset, target_n=200, per_song_cap=6, screening_region_ids, confirmation_target=40, confirmation_per_song_cap, seed)`：分层抽样 + song-held-out confirmation
  - `build_confirmation_manifest(regions, mechanism, out)`：产出 REQUESTS 行
  - 辅助：`region_recovery` / `region_safety` / `mechanism_metrics` / `_request_identity`
- `scripts/unit_realign/run_adaptive_expansion.py`（入口）
  - `--screening-results`（>=1 个 FINAL_*.json）/ `--population`（REGION_POOL.jsonl）/
    `--target-n 200` / `--top-k 2` / `--per-song-cap 6` / `--confirmation-target 40` /
    `--out-root` / `--seed 0` / `--resume` / `--mechanism-ids`（显式覆盖，跳过排序）

## 3. Ranking 逻辑（`rank_mechanisms`）

输入 `mapping[mechanism_id] -> list[region aggregate row]`。机制 id 的推断顺序：
embedded `mechanism_id` > `family` > 文件名 token 映射（`FINAL_TRAJECTORY→E1_direct_i5`、
`FINAL_SPLIT→E2_adaptive`、`FINAL_COARSE_FINE→E4_coarse_fine`）> 文件名 stem。

对每个机制的 region 行按 schema-tolerant 字段名提取指标（兼容 WP3/4/6 各 runner）：

- **Recovery**：`region_strict_100`/`strict_200`（or `best_*`/`hit_100`/`r200`/`region_recovery_*` 等别名）。
- **Safety**：`fixed_context_displacement_ms`（or `context_displacement_ms` 等）、
  `catastrophic_regression`/`catastrophic`（bool 或 `danger_flags`/`warnings` 里含 `catastrophic`）。
- **Fwd cost**：`forward_attempts`/`n_forward`/`forward_count`。

合成得分（本轮冻结，见 §7 遗留）：

```python
recovery_score = 0.6 * mean_strict_200 + 0.4 * mean_strict_100     # strict200 为主门
safety_score   = max(0, 1 - min(1, mean_ctx_ms / 1000) - 1.5 * catastrophic_ratio)
fwd_penalty    = min(0.10, mean_fwd / 160.0)
composite      = 0.55 * recovery_score + 0.35 * safety_score - fwd_penalty
```

只有 `n_regions>0` 且 `recovery_score>0`（有可观测 strict recovery）的机制可进入扩量（避免无声量机制被扩）。按 `composite_score` 降序取 top-K。每机制带 `rationale` 字符串（依据摘要）。

## 4. 扩量 select 与 manifest schema

`select_regions_for_expansion`：

1. 按 `song_id` 分组 population，剔除 `region_id ∈ screening_region_ids` 的重复 region。
2. **先预留 confirmation songs**：按每歌最多 `confirmation_per_song_cap` 累积到 `confirmation_target`，
   预留出的 songs 进 `reserve_songs`，**绝不再进 main pool** → main/confirmation song 集严格不相交。
3. main：对非预留 songs 做 per_song_cap 分层的多歌分散抽样，目标 >=`target_n`；同歌 interval 与已选
   interval 有 `overlap_interval_sec` 时间重叠则不选（避免重复证据）。
4. confirmation：只从预留 songs 抽取 `confirmation_target` 条。

Regions 统一挂在：
```python
dict(region, mechanism=mechanism_subset, confirmation=False|True)
```

**EXPANSION_MANIFEST.jsonl 行 schema**（由 `build_confirmation_manifest` 产出）：
```json
{
  "schema": "lp_unit_realign_expansion_request_v1",
  "kind": "expansion",
  "mechanism_id": "...", "family": "R-U|R-U1|R-B...",
  "expansion_set": "main|confirmation",
  "region_id": "...", "song_id": "...", "window_index": null, "language": "zh",
  "target_unit_ids": [...], "baseline_available": true,
  "...": "其余 region 结构化字段透传",
  "request_identity": "sha256[:24]"
}
```
`family` 由 `MECHANISM_FAMILY`/`family_for_mechanism` 推：E2_split→R-U1/R-U2、anchor→R-B、其余→R-U。
`request_identity` = sha256(mechanism_id, family, region_id, song_id, target_unit_ids[:24])，用于账本去重/resume。

## 5. 输出布局（`--out-root`）

```
01_ranking/MECHANISM_RANKING.json       排序 + 依据 + digest
02_expansion/EXPANSION_MANIFEST.jsonl   全部扩量行（>=200 主 + confirmation 标）
02_expansion/EXPANSION_MANIFEST_<mech>.jsonl  每机制子 manifest
02_expansion/CONFIRMATION_MANIFEST.jsonl      song-held-out 确认子集
02_expansion/REQUESTS.jsonl             runner 消费的请求（region × mechanism）
06_runtime/RUN_STATE.json               resume 状态（screening_digest）
FINAL_EXPANSION.json                    计数/预算投影/审计（不覆盖式）
```

## 6. Smoke 输出（合成数据）

- 合成 screening：3 个 FINAL_*.json，各 ~12 region 行，r200 取 0.90(E4) / 0.82(E1) / 0.55(E2)。
- 合成 population：50 songs × 30 no-GT unsafe regions = 1500。
- 结果（`--target-n 200 --top-k 2`）：
  - ranking：`E4_coarse_fine(0.773) > E1_direct_i5(0.660)`，E2 split 未入 top2（符合合成 r200 排序）。
  - main=200 ✓，confirmation=40 ✓，两者 status 均 `complete`。
  - **main vs screening region 重叠 0，confirmation vs screening 重叠 0**；
    main_songs(34) 与 confirmation_songs(7) **严格不相交**（`song_sets_disjoint=true`）。
  - budget projection：main=400(=200×2mech)，conf=80(=40×2)，×6 fwd/region => **2880 forwards**（账面）。
  - resume 幂等：digest 不变时复用；digest 变化（改 screening 值）时重新计算。

## 7. GPU formal 扩量命令模板（真实 forward，WP3/4/6 runner 消费 REQUESTS.jsonl）

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment

# 1) pure CPU 编排（本 WP）
PYTHONPATH=src python scripts/unit_realign/run_adaptive_expansion.py \
  --screening-results <run>/WP3/FINAL_TRAJECTORY.json <run>/WP4/FINAL_SPLIT.json <run>/WP6/FINAL_COARSE_FINE.json \
  --population <REGION_POOL.jsonl> --target-n 200 --top-k 2 --out-root <run>/wp8_expansion

# 2) 单机制真实 forward（示例：E4_coarse_fine，实际调 WP3/4/6 runner 消费 per-mechanism manifest）
PYTHONPATH=src python scripts/unit_realign/run_coarse_fine.py --manifest <run>/wp8_expansion/02_expansion/EXPANSION_MANIFEST_E4_coarse_fine.jsonl --real --out-root <run>/wp8_run --model-dir <snapshot> --revision main --checkpoint-path <ckpt>
```

扩量 forward 结束后，真实 forward count 计入账本并回填 `FINAL_EXPANSION.json.budget_projection` 为实测
（本 WP 只写 `estimate` 投影，不覆盖原始聚合）。

## 8. 遗留 / 待 review

- **MINOR（backlog）**：`fwd_penalty` 权重（0.10 @16 fwd）与 composite 0.55/0.35 权重本轮冻结，正式扩量前可在
  review 复核口径；当前未做对标 `no_gt_selector` operating point 的 safety-first 变体。
- **MINOR**：`region_recovery` 不支持 `strict_250ms` 等非 100/200 门；添加新门需扩展字段表并重算 digest（identity 随 schema）。
- **需要确认真实 screening FINAL schema**：本实现按 schema-tolerant 别名假定 WP3/4/6 aggregate 行含
  `strict_100/200`、`fixed_context_displacement_ms`、`catastrophic_regression`。若真实运行字段名不同，
  进入 G7 前需核对并回填（mechanism id 由文件名映射已覆盖常见名）。
- **不覆盖原则**：`FINAL_EXPANSION.json` 只在无旧文件时写入；重跑需手动清掉旧输出或换 `--out-root`，避免静默覆盖原始聚合（符合 AGENTS 纪律）。
