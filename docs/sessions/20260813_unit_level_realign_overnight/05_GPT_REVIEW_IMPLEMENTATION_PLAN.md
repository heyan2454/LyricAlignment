# GPT review 落地实施方案：balanced P1 unit/region realign

## 目标与验收门槛

在不改变冻结的 production baseline、detector、decoder 和 window policy 的前提下，完成可恢复的
P1-A，并在需要时进入 P1-B：

- 主 cohort 为 `S1/S2/S3/S4`，每类目标 **25 个 valid case**（合法 baseline + 合法 target region +
  至少一个真实、非 null GPU intervention）；
- 每个 case 独立记录 R-U、R-A、R-B、R-S 的 selected/constructible/executed/null/failed/valid 状态；
- 所有 GT outcome 只在 evaluator namespace 出现；no-GT feature / deployable gate input 无 GT 字段；
- report 必须同时给 target unit、context unit、region、candidate、song 五个层级；
- `writeback_gate=NOT_FROZEN`，只有全新的 no-GT holdout 实验通过预先冻结门槛后才可另行讨论。

补充冻结口径：25 是 case-level 的 any-family valid 目标；每个 family × stratum 另报 selected、
constructible、effective-executed、valid 数及 paired-constructible 比较子集，不能把不同 family 的
不同 case 集当作可比较策略结果。所有 primary inference 以 song cluster 为单位。

这里的“25”是 effective case 数，不是 pool 数、request plan 数，也不是包含 null 的 case 数。每类少于
25 时控制器必须继续 replenishment，直至可审计穷尽；不能静默降低目标。

## 实施批次与文件

### Batch 1 — 冻结 v2 contracts 与 manifest identity

修改 `src/lyricalign/unit_realign/request_families.py`：

1. 引入 `UNIT_REQUEST_SCHEMA = "unit_realign_request_v2"` 和 `build_request_identity()`；identity 的
   SHA-256 输入为 family/version、document-global canonical IDs、active/fixed role、audio/text span、
   baseline digest、audio SHA、model/checkpoint/decoder identity 与 mapping schema。
2. 将 `build_family_request()` 拆为 `build_r_u`、`build_r_a`、`build_r_b`、`build_r_s`；输出共同字段：
   `active_target_unit_ids`、`fixed_context_unit_ids`、`outside_unit_ids`、`local_to_canonical`、
   `baseline_audio_range_sec`、`candidate_audio_range_sec`、`baseline_text_ids`、`candidate_text_ids`、
   `writeback_unit_ids`、`request_identity`。
3. 添加 `classify_intervention(request, baseline_request)`：比较不含 `family`、schema、request ID 与运行
   元数据的 canonical intervention payload digest；输出
   `effective_intervention`、`null_intervention`、`null_reason`。R-NULL 不进入 executor。
4. R-B 必须使用最近的左右 ACCEPT anchor；任一 anchor 缺失仅产生 `not_constructible/missing_*_anchor`，
   不影响同 case 的其它 family。R-S 必须有 active/fixed 完全分割，且 fixed rows 带 baseline timestamps。

修改 `src/lyricalign/realign_gate/case_selection.py`：保留 `_localize_target_ids()` 作为旧 adapter，
但停止给新 P1 生产 request；仅修正其 manifest 中遗留的 `target_unit_ids` 字段为
`active_target_unit_ids`，并确保旧字段是兼容 alias，绝不再指代整个 window。

新增 `src/lyricalign/unit_realign/intervention_check.py`：对每个 request 做 identity、global/local
bijection、audio span、target locality、anchor、active/fixed partition 和 GT firewall 校验。失败写
`01_requests/REQUEST_STATUS.jsonl`，不得发 GPU。

### Batch 2 — 生成 balanced P1 population 与补样控制器

改造 `src/lyricalign/unit_realign/region_sampling.py`：

1. `build_region_population()` 输出所有 1--8 unit contiguous unsafe spans、ACCEPT control spans、song/
   language/window/overlap interval、anchor candidates 和 baseline availability；不读 GT。
2. 新增 evaluator-side `assign_gt_stratum(population, baseline_gt)`，只写入
   `03_unit_outcomes/STRATIFIED_POOL.jsonl`：
   - correct：全部 active target `max_boundary_error<=200ms`；
   - bad：至少一 target `>1000ms` 或预冻结 region catastrophic 条件；
   - grey：其余 `200--1000ms`；只进入 boundary cohort，不进入 S1--S4；
   - state：ACCEPT => S1/S4，UNCERTAIN/REJECT => S2/S3；GT/baseline missing、非法 interval、重复 baseline
     预测一律 `ineligible_*`，不静默归类；`1000ms` 本身属于 grey；catastrophic predicate 必须在 resolved
     config 中逐字段冻结。
3. 新增 `balanced_replenishment()`：按 stratum 缺口 round-robin 选歌，优先没有入选歌曲；禁止主 cohort
   的 `(song_id, target canonical ID)` 或同 song time overlap 重复；time overlap 为严格相交、不同 song
   不冲突；默认每歌 4、仅在第一次 exhaust 后统一扩展到 8。每轮输出
   `eligible → baseline-valid → constructible-any-family → executed-effective → valid` 的逐步计数和原因。
4. 所有天然 case 标 `origin=natural`；受控扰动只能写入独立 `origin=injected` cohort，永不并入主
   S1--S4 指标。自然池穷尽后才允许生成 injected pool。

修改 `scripts/unit_realign/run_unit_realign.py`：添加 `p1-pool`、`p1-refill`、`execute`、`evaluate`、
`report` 子命令。`RUN_STATE.json` 以 request identity 为 completed key，分别维护 completed/failed/
null/not_constructible；写入采用临时文件+rename。`--resume` 只能跳过匹配 identity 的 completed forward，
failed request 可由 `--retry-failed` 单独重试。

### Batch 3 — 执行接口与 cache/resume

修改 `scripts/research_v7/run_behavior_suite.py`、`src/lyricalign/research_v7/requests.py`、
`src/lyricalign/research_v7/attempt.py` 和 `src/lyricalign/research_v7/real_executor.py`：

1. 接受 request v2 的 global/local map 与 active/fixed slots，forward evidence 回写同一
   `request_identity` 和 `canonical_unit_id`，不可只按 new output index 关联。
2. cache key 纳入 v2 identity；identity 还必须含 code revision/dirty digest、text adapter/tokenizer、audio
   preprocess、decoder 完整 options 与 determinism seed；任一改变强制新 forward。
3. R-S 解码后立即执行 `validate_fixed_slots()`：当前 active-only decoder 只能校验 active coverage/geometry
   与其相对 frozen baseline 的 crossing/non-monotonic，不得伪称观察到 fixed decoder drift；随后 remerge
   baseline fixed rows。未来 decoder 输出全部 slots 时才校验其 fixed drift。任一可观测 invariant 失败写
   `SAFE_SLOT_INVARIANT_VIOLATION` 并标 invalid，绝不报告 sparse success。
4. 每 request 落 `FORWARDS.jsonl`（start/end/wall time/cache hit）、`FAILURES.jsonl`（分类、retry count）、
   `REQUEST_STATUS.jsonl` 和原子 `RUN_STATE.json`。

### Batch 4 — v2 evaluator：责任范围、missing 与 candidate classification

扩展 `src/lyricalign/unit_realign/unit_outcome.py`：

1. `pair_unit_outcomes()` 只为 active target、fixed context、candidate extra 三类输出行；outside unit
   不进入 intervention efficacy denominator。每行含 onset/offset/max-boundary before/after、100/200/500/
   1000ms buckets、`covered_to_missing`、`missing_to_covered`、`extra_prediction`、`invalid_unpairable`。
2. 新增 `classify_unit_outcome()`：improved finite、degraded finite、unchanged finite、covered-to-missing、
   missing-to-covered、extra、invalid；`covered-to-missing` 必为 catastrophic harm，不能依赖 delta。
3. 新增 `aggregate_region_outcome()` 与 `aggregate_candidate_outcome()`：
   - beneficial：有实质 improvement 且无 degraded/missing catastrophe；
   - neutral：无实质 improve/harm；
   - harmful：存在 harm、无 compensation；
   - catastrophic_harmful：任一 target covered-to-missing 或 catastrophic threshold；
   - mixed：同时有实质 improve 和 harm，不能被平均为 beneficial。
   阈值（200ms / 1s）写入 resolved config，且 report 输出阈值。
4. 汇总必须分 active target 与 fixed context：target coverage/missing、improve/harm/catastrophic/neutral、
   MAE/median、四个 tolerance、large improve/harm。candidate 推断与 gate 泛化以 song cluster 为单位，
   不以 unit row pseudo-replicate。

新增 `src/lyricalign/unit_realign/reporting.py`，由新 `report` 子命令生成：`UNIT_OUTCOMES.jsonl`、
`REGION_OUTCOMES.jsonl`、`CANDIDATE_OUTCOMES.jsonl`、`QUADRANT_REPORT.json`、`STRATEGY_REPORT.json`、
`NULL_INTERVENTION_REPORT.json`、`MISSING_COVERAGE_REPORT.json`、`REJECT_SAFE_REPORT.json`、`FINAL_REPORT.md`。

### Batch 5 — no-GT gate 数据集与 Test Demo

修改 `src/lyricalign/unit_realign/unit_gate_features.py`：

1. 主键固定为 `(song_id, region_id, request_identity, canonical_unit_id)`，并由 request active targets
   左连接 baseline/candidate outputs；candidate missing 仍须产生 feature row。
2. allowed feature 仅含 detector before/after、state transition、signed displacement、changed count、
   monotonicity/inversion、slot violation、overlap/compression、safe-context changed count、decoder confidence、
   raw/official disagreement 与 local consistency。
3. `assert_no_gt_feature_row()` 改为 allowlist 校验而非单纯 token blacklist，并递归拒绝 GT timestamp、
   old/new error、delta、label、harm/improve、oracle 字段。训练 label 只在 evaluator 后用相同主键附加。
4. 冻结 song-level train/tune/test split、特征处理、模型、tune-only threshold 与一次性 test gate；分别输出
   all、non-null、changed-only、harmful-vs-beneficial/mixed 的 song-held-out AUROC/AUPRC 和 song-clustered
   interval。`mixed` 是独立 outcome，不得暗中并入 beneficial；
   `R-O`、null、invalid、mock 一律不得进入 deployable evaluation。

修改 `src/lyricalign/realign_gate/test_demo.py` 和 `scripts/realign_gate/04_test_demo_behavior.py`：

1. 仅从真实 detector spans 构造 local requests，序列化 global ID、local index 与双向 map；whole-item
   pseudo-local 一律 `R-NULL`。
2. `REQUEST_PLAN` 与 `REALIGN_BEHAVIOR` 分目录/分 schema；mock 只能写 plan 或
   `not_executed/mock_forbidden`，禁止写 formal behavior。
3. 真正 GPU run 动态汇总 language/song/window/region/strategy/null/failure/displacement/suspicion；不写死
   中文17、其他语言6之类历史数量。

## R-U / R-A / R-B / R-S 冻结合同

| family | active target | context / request text | audio 与 writeback | non-null 条件 |
| --- | --- | --- | --- | --- |
| R-U | 一个 target 或至多 3 个连续 target | target 加配置化的 0--1 neighbor；neighbor 为 context | target boundary 加固定 margin；仅 active IDs writeback | audio/text/active payload 至少一项不同于 baseline |
| R-A | detector contiguous unsafe span（最多8） | unsafe span 加小量左右 context | span + margin；仅 unsafe active IDs writeback | local span 与 baseline identity 不同 |
| R-B | 同 R-A | R-A span，且最近左右 ACCEPT anchor 都在 text/context 中 | bilateral anchor 围成的最小 audio/text context；只写 active | 两 anchors 存在且 identity 不同 |
| R-S | 同 R-U/R-A 的 active IDs | full local context；active slots 可预测，fixed slots绑定 baseline | local span；只写 active，fixed 必回填 baseline | active/fixed complete partition + active-vs-frozen geometry invariant 通过 |

## 测试与执行顺序

先实现并运行以下 CPU tests：

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate lyricalign-qwen
PYTHONPATH=src python -m pytest -q tests/unit_realign tests/realign_gate
python -m compileall -q src scripts
git diff --check
```

必须新增的测试：local target cap；global/local bijection；fixed context 不记 target missing；真实 target
missing 记 catastrophic；missing 左连接不丢行；R-B 缺 anchor 不阻塞其它 family；R-S only-active 可变且
fixed invariant 失败；mixed classification；GT allowlist firewall；mock demo 禁止 behavior；每 stratum 独立
replenishment；resume dedupe；explicit overwrite 才能替换 completed result。

然后按以下顺序执行：

1. `p1-pool` 建自然 pool 和 baseline GT strata audit；
2. 运行每 family 至少一个 real smoke，核验 identity/non-null/fixed-slot；
3. `p1-refill --target-per-stratum 25`，循环执行与补样直至四象限都达到 25 或输出 exhaust audit；
4. P1-A 只执行 R-U/R-A/R-B/R-S，不扩 decoder/detector/window 组合；
5. `evaluate` 和 `report` 先交付四象限、strategy、missing、reject-safe 结果；
6. P1-B 再按缺口扩大 region，优先 S2、S3、S4 与 boundary cohort；
7. 最后运行真实 Test Demo local-region stress，并独立出报告。

## 不可变产物布局

`/home/hyan/Data/lyricalign/runs/<run>/` 下固定：

`00_population/`、`01_requests/`、`02_forwards/`、`03_unit_outcomes/`、`04_no_gt_features/`、
`05_analysis/`、`06_test_demo/`、`07_runtime/`。每个 artifact 含 schema、resolved config digest、run ID；
request-derived row 另含 request identity，population-derived row 另含 population identity（aggregate 不强求
不存在的 request identity）。旧 `realign_gate` evidence 只在 `deprecated_historical/` 引用，不能被
`FINAL_REPORT.md` 当作本轮 formal 指标输入。
