# Z — WP9: E6 Recovery-Basin Atlas + E7 Serial Accumulated-Error Stress

SCOPE: 07 §9 WP9 (E6 atlas + E7 serial stress，P7/P8)。
代码只读已产出 E1-E4 的 forward evidence/outcome 做汇总/分析；E7 串行链用 smoke executor
（纯 CPU）造 episodes。不发起真实 forward、不写回、不使用 GT 除 evaluator-side baseline bucket 外。

## 产物

- 模块：`src/lyricalign/unit_realign/recovery_atlas.py`
  - `ATLAS_SCHEMA = "recovery_atlas_v1"`
  - `BUCKETS_MS = (100,200,500,1000)`
  - `build_atlas_rows(regions, evidence, outcomes, gt=None)` — 对已产出 E1-E4 evidence/outcome
    逐 region 汇总 recoverability 字段。
  - `classify_region(row)` — 六分类：once-realign / iterative / split-only / recrop /
    coarse-fine / still-unrecoverable。
  - `build_serial_episode(episode, executor=None, tol_ms=100)` — E7 episode 轨迹 + serial 指标。
- 脚本：
  - `scripts/unit_realign/run_recovery_atlas.py`（--regions/--evidence-root(可多次)/
    --outcomes-root(可多次)/--gt/--out-root/--smoke）
  - `scripts/unit_realign/run_serial_stress.py`（--episodes/--out-root/--smoke）

## Atlas schema（对应 02 §393-408）

每行 `recovery_atlas_v1`（按 region 一行，跨机制聚合）：

| 字段 | 来源 |
| --- | --- |
| `baseline_error_bucket_ms` / `baseline_present_gt` / `baseline_max_detector_error_ms` | evaluator-only（GT present 才填） |
| `detector_state` | `region.detector_state` |
| `region_length_sec` / `n_units` | 由 `region.units` 计算 |
| `language` / `domain` | `region.*` |
| `start_region` / `near_boundary` / `near_silence` / `repetition_flag` | `region.*` |
| `request_families` | evidence/outcome 行的 `family` 并集 |
| `split_slot_id` / `iteration` / `recrop_view_id` | evidence 行身份字段（best-effort） |
| `best_{iterative,split,recrop,coarse_fine}_{100,200,500,1000}ms` | 各机制最好能达的容差桶 |
| `best_{mech}_error_ms` | 各机制最好绝对误差 |
| `context_harm` / `forward_cost` | region-aggregate 行（collateral_harm / forward_count+extra） |
| `oracle/split/recrop/iterative/coarse_fine_can_rescue` | 该机制是否 100ms 可达 |
| `combined_can_rescue` | 任一机制 200ms 可达 |
| `best_achievable_ms` | 任一机制达到的最紧桶 |
| `atlas_class` | classify_region 输出 |

机制识别（`_mechanism_of`）容忍 schema 版本标记：`multi_realign_dynamics_v1`→iterative、
`split_realign_v1`→split、`audio_views`→recrop、`coarse_fine_v1`→coarse_fine。容差桶布尔兼容
各机制字段名（`recovered_strict_*`/`recovered_coarse_*`/`target_recovered_*`/`first_hit_ms_iteration_*`）。

## 分类规则（classify_region，02 §414-418）

按"最简机制优先、后置机制仅在更简机制不可达 100ms 时认领"：
iterative 100ms 可达→once（若 it<=1）否则 iterative；否则 split→SPLIT；否则 recrop→RECROP；
否则 coarse→COARSE；全不可达→still-unrecoverable。`baseline_present_gt=False` 的 region
直接收进 still-unrecoverable（GT firewall：不喂无 GT 的 evaluator-only 口径）。

## Serial 指标（build_serial_episode，02 §449-457）

episode 结构：`episode_id` + `windows[]`（window_id/units/target_unit_ids/
injected_cursor_error_ms/recovery_strategy/is_safe）。strategy：`reset`（本窗前后清 0）、
`converge|iterative`（误差减半）、`none`（误差持续传播）。GT 全程 0 使用。

`serial_episode_trace_v1` trace 每窗每目标 error，summary（`serial_episode_metrics_v1`）：
- `downstream_error_area_ms_win` — 各窗最坏 |error| 之和
- `windows_to_recover` — 自误差出现到最后一个超 tol 窗的窗口序号（未恢复=None）
- `cumulative_bad_windows` — 坏窗数
- `cursor_recovery_latency_window` — cursor 回到 tol 内的首个窗
- `extra_forwards` — 采用 reset/iterative 策略附加 forward
- `false_recovery_on_safe_windows` — is_safe 却仍出现 bad unit 的窗列表
- `gt_used=False`

## Smoke 输出（验收）

E6（`--gt GT.json`）：
```
class_counts {once-realign:2, split-only:1, still-unrecoverable:1}
REG_A → once-realign（iterative it=1 达 100ms，best_iterative_error_ms=50）
REG_B → split-only（仅 split 达 100ms，iterative 250ms）
REG_C → still-unrecoverable（best_achievable_ms=1000，各机制均不达 100ms）
REG_NOGT 无 GT 时 baseline_present_gt=false，n_gt_present=0（GT firewall 生效）
```
GT firewall 验收：不传 `--gt` 且 region 无 `gt_units` 时，所有 region `baseline_present_gt=false`、
`baseline_error_bucket_ms=None`、`atlas_class=still-unrecoverable` —— 无 GT 不做 evaluator 分类。

E7（`--smoke` 内置 bundle）：
```
smoke_unmitigated       windows_to_recover=5 bad_wins=5 area=1250 extra=0  （误差持续传播）
smoke_reset_recovers    windows_to_recover=2 bad_wins=2 area=860  extra=2 （reset 恢复）
smoke_false_recovery    windows_to_recover=2 false_recovery=[1]          （safe 窗误伤检出）
```
收敛：无缓解链 5 窗均坏（累计误差传播成立）；reset 链 2 窗恢复且附加 2 forward；
safe 窗被错误污染被标记为 false recovery。

## GPU formal 模板

E6/E7 本身纯 CPU（汇总已产出 evidence + smoke episode）。正式长跑复用其它 WP 已产出的
region/evidence/outcome：
```
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
# E6 formal
PYTHONPATH=src python scripts/unit_realign/run_recovery_atlas.py \
  --regions <REGION_POOL.jsonl> \
  --evidence-root <E1_run> --evidence-root <E2_run> --evidence-root <E3_run> --evidence-root <E4_run> \
  --outcomes-root <WP_outcomes> --gt <GT.json> --out-root <DATA>/<run>
# E7 formal（构造/收集真实 episodes）
PYTHONPATH=src python scripts/unit_realign/run_serial_stress.py \
  --episodes <SERIAL_EPISODES.jsonl> --out-root <DATA>/<run>
```
`<DATA>`=/home/hyan/Data/lyricalign/runs（runs 不入工作目录）。E6/E7 无真实 forward，不占 GPU。

## 遗留

- `run_serial_stress.py` 的聚合 `mean_windows_to_recover` 把 None(never-recover) 记为 1.0，
  MINOR（口径代理，可改 count_never_recovered 字段）。
- atlas 机制识别为 best-effort：机械 schema 若未来改名需同步 `_SCHEMA_MECH`。
- recrop/coarse 里含"combined"路线的 200ms `combined_can_rescue` 与 oracle 判定为逐 region
  简化口径；正式长跑如需更精准可扩展 per-mechanism stage 字段。
- build_serial_episode 的 `executor` 参数目前为占位（smoke 内置模拟器）；真实 forward 接入时可
  覆盖 `_smoke_serial`（cursor+offset push 给真实 executor）。
