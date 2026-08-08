# Transition–Recovery–Detector 纠偏后的实现计划

日期：2026-08-08  
依据：`transition_recovery_detector_correction_patch_20260808.zip` 及当前仓库审计  
用途：交给执行 agent 实现和运行；本文件本身不改变旧实验结果。

## 1. 审计结论

这次 review 的主要判断在当前代码和旧 evidence 中均可复现，因此按 P0 处理：

| 项 | 当前实现/证据 | 结论 |
|---|---|---|
| Transition density | `runner.py::TransitionRunner.run_song()` 计算 `n_units / duration`；`build_query_ids()` 再用它做 `seconds / density`；`FakeAlignerBackend` 也把同名值当 seconds/unit | 单位倒置确实存在。`newboy` 首窗实际 36 units，443/231.5=1.9136 units/s，67.27s 正确预算约 128.7 units。2026-08-07 T1/T2/T3 formal 无效 |
| propagation continuation | `collect_propagation.py` 从 `state_after` 构造 corruption 后再次调用 `run_song()`；`run_song()` 使用 `enumerate(windows)` 从 0 开始 | 确实重放已执行窗口；必须从 `k+1` 继续 |
| detector denominator | `thresholds.py::working_point_metrics()` 看到 `UNCERTAIN` 直接 `continue`，safe/unsafe total 只累计 ACCEPT/REJECT | SA60/SA80/R95 旧值确实不可用；UNCERTAIN 必须留在 safe/unsafe 总分母 |
| detector completion | `detector_features.py` 只有 8 个基础特征；旧工作点文件存在，但没有 V/P/S/H/PR 完整分支和完成矩阵 | Phase 6 未完成；旧 detector 行来自无效 T2，必须重建 |
| Oracle | `run_oracle_recovery.py` 使用 GT 错误时间和 GT 邻近歌词范围构造 retry | 有诊断价值，但不是 recovery upper bound；缺正确 head、occurrence、state reset 和写回后续串行 |
| closed loop | `run_closed_loop.py` 直接用 GT 行定位段、GT 时间构造 audio/query；没有真正执行 `RoutePlan -> execute -> writeback -> next state` | 旧 L/W 结论不能作为产品闭环结论 |
| 320ms | `transitions.py` 的 stability tolerance 与多个旧 metrics 使用 `0.32` | 只能保留 legacy compatibility 列；正式标签使用 100/250/500/1000ms 及 Safe/Grey/Unsafe 语义 |

保留的冻结约束：full-slot 主线、10s + 60s + 10s 窗口、silence-aware planner、skip silent、raw 主视图、official 同一 forward 的 secondary/reference、无大笛卡尔积、GPU hard cap 12h。

## 2. 目标架构和版本标识

新增 session root，例如：

```text
runs/research_transition_recovery_detector_20260808_corrected/
```

不能覆盖 `reports/research_transition_recovery_detector_20260807/` 或其 cache。所有 corrected artifact 写入新 root，并在 `00_meta/SESSION_META.json` 记录：

```json
{
  "schema_version": "transition_recovery_detector_session_v2",
  "correction_plan_version": "20260808_correction_v1",
  "query_estimator_version": "units_per_sec_v2",
  "label_schema_version": "safe100_grey100_250_unsafe250_structural_v1",
  "source_split_version": "...",
  "model_identity": {},
  "audio_preprocessing_identity": {},
  "decoder_evidence_version": "raw_official_shared_forward_v2",
  "gt_schema_version": "canonical_source_segment_mapping_v2"
}
```

### 2.1 Density contract

新增 `src/lyricalign/research_transition_recovery_detector/query_estimator.py`，提供一个带版本的纯函数/数据类：

- canonical 名称只允许 `units_per_sec`；
- `sec_per_unit = effective_audio_sec / n_units` 只能作为明确的 reciprocal 字段；
- `expected_units(audio_span_sec) = audio_span_sec * units_per_sec`；
- query 起止 id、margin、estimator version 一并返回；
- 禁止继续使用 `unit_density_sec` 这一同时表示两种物理量的名字；旧配置命中该字段时 fail closed 或显式迁移，不得静默解释。

`runner.py::build_query_ids()`、`TransitionRunner._request_for()`、`TransitionRunner.run_song()`、`FakeAlignerBackend`、`collect_propagation.py`、`run_transition_formal.py` 全部改用该 contract。H0 是修复后的现有 density 算法，不是旧代码的兼容别名。

## 3. 按依赖顺序执行的实现阶段

### P0：语义修复、合同、CPU 测试

目标文件：

- `src/.../query_estimator.py`
- `src/.../runner.py`
- `src/.../contracts.py`
- `src/.../identity.py`
- `src/.../transitions.py`
- `src/.../thresholds.py`
- `src/.../transition_metrics.py`
- `scripts/.../collect_propagation.py`
- `tests/research_transition_recovery_detector/test_runner_resume.py`
- `tests/research_transition_recovery_detector/test_detector_thresholds.py`
- 新增 `test_query_estimator.py`、`test_propagation_resume.py`、`test_metric_denominators.py`

必须实现：

1. `WindowRequest` 增加 `query_estimator_version`、明确的 query audit identity；`parent_state_hash` 由真实 `state_hash(state_before)` 填写，不能再是空字符串。
2. `TransitionRunner.run_song()` 支持 `start_window_index`/等价 API。若 `starting_state.window_index == k+1`，默认只执行 windows[k+1:]；request id 使用绝对 window index。恢复时同时恢复前序 observations，否则 T3/query head 不能声称等价。
3. resume state、request、observations 的 identity 进入 trajectory/forward cache key；每个 item 原子写出，失败只隔离该 item。
4. `working_point_metrics()` 对所有 `gt=0/1` 记录计入 safe/unsafe denominator；分别输出 safe/unsafe 的 ACCEPT、REJECT、UNCERTAIN 三态率，并断言各组三态率和为 1。`gt=None`、GT ambiguity 另行排除并计数。
5. transition metrics 改为连续 start/end error 分布和 100/250/500/1000ms；320ms 仅 `legacy_320ms`。
6. `state_after_clean_window(k)`、`window_index_before_intervention=k`、`continue_from_window_index=k+1`、`intervention`、provenance 写入 episode；no-op 和无效干预标为 `no_effect_attempt`，不进入有效 recovery 分母。

最低测试：

- 240s/480 units、60s span 得到 2 units/s 与约 120 units；reciprocal 结果相同；span 加倍预算单调加倍；unit count 改变方向正确。
- `newboy` fixture 不得再得到约 36 units。
- clean uninterrupted run 与从 window k 的 clean resume 在后续 request identity、state transition、query ids 完全一致。
- intervention 只改变声明字段；no-op 没有下游差异；k+1 之前不得出现新 forward。
- `UNCERTAIN` fixture 下 safe/unsafe 三态率分别和为 1，R95 为 `unsafe REJECT / all unsafe`。
- L/W fixture 的 retry request region、commit/writeback 区域不同。

### P1：Query audit 与 corrected Transition

新增 `scripts/.../build_query_audit.py` 或等价 runner 内 audit writer。每个 request 输出到 `01_query_audit/QUERY_AUDIT.jsonl`：

```json
{
  "window_index": 0,
  "original_bounds": [0, 0, 57.27, 67.27],
  "model_bounds": [0, 0, 57.27, 67.27],
  "query_start_id": 0,
  "query_end_id_exclusive": 129,
  "n_query_units": 129,
  "units_per_sec": 1.9136069,
  "sec_per_unit": 0.5225734,
  "query_estimator_version": "units_per_sec_v2",
  "cursor_before": {},
  "cursor_after": {},
  "gt_first_relevant_id": 0,
  "head_delta_units": 0,
  "gt_active_unit_recall": 1.0,
  "extra_left_units": 0,
  "extra_right_units": 0,
  "correct_occurrence_contained": true,
  "first_sung_unit_rank": 0
}
```

GT 只能写入 audit/evaluation，不能进入 T1/T2/T3 query construction。audit 发现系统性 underfeeding/overfeeding、query 不含正确 occurrence、或 estimator version 不一致时，formal 命令退出非零。

重跑顺序：

- T2 上 pilot H0/H1；若当前架构确实存在独立的 slot/stable identity，再加 H2；否则在 manifest 中合并为 H1。
- H1 以 committed canonical cursor 决定 lyric head，density 只负责 future budget；记录 query length、active recall、left/right extra，防止把“更长 query”误判为“head 更正确”。
- 选择后仅携带一个最佳 head strategy；不做 transition × head × decoder 全组合。
- T1/T2/T3 formal 各自产出 raw 与 official 视图；两者应从一次 forward 派生。

目标文件：`run_transition_smoke.py`、`run_transition_formal.py`、`report_transition.py` 以及 `runner.py`。report 必须分开 committed correctness、committed coverage、correct committed/all target、final cursor coverage、query head delta、first catastrophic window、occurrence jump、natural recovery 和 raw/official disagreement。

### P2：有效 propagation corpus

只消费通过 Gate T 的 corrected Transition candidate。修改 `collect_propagation.py`：

- P-N：真实错误 commit 后自然继续 2–5 windows；
- P-M：只强制一次 model-native alternate（raw/official disagreement、posterior alternate 或 repeated occurrence），后续正常；
- P-C：small/medium/large 三档 canonical cursor/time/occurrence/boundary corruption，报告绝对 units 和相对比例；
- 每一行 `EPISODES.jsonl` 带 `source_song_id`、`transition_id`、`window_index_before_intervention`、`state_before`、`state_after_clean_window`、`continue_from_window_index`、`intervention`、`provenance`、`no_effect_attempt`。

传播输出只有在 continuation equivalence、intervention effect 和 source provenance 均通过时才设置 Gate P。旧 2026-08-07 `EPISODES.jsonl` 只作 historical evidence。

### P3：Supplementary Oracle Recovery

重构 `run_oracle_recovery.py`，或把构造逻辑抽到新的 `oracle_recovery.py`：

- O0：保留旧 GT-range rerun，名称为 `oracle_gt_range_rerun_legacy`；
- O1：GT 只设置正确 canonical lyric head/occurrence，音频仍遵守冻结 L/W retry 定义；
- O2：GT exact-pair query，首个 relevant unit、occurrence、bounded margin 明确；
- O3：若 O1/O2 仍差，只在 failure subset 做 GT-correct cursor/occurrence reset，写回后后续窗口不再用 GT reset。

L 保留正确 prefix、只 retry gap；W 回到 stable retry point、affected region 不提交。报告 immediate repaired units、interval @75/@100、outside-target regressions、prefix preservation、occurrence correction、retry cost、后续 1/2/3 windows 的 track/recover/relapse。

### P4：Detector evidence 和信号完成

主要修改：

- `scripts/demo/align_qwen_fa_serial_demo.py::infer_slice()`：保留 raw/official 同 forward；扩展 posterior export（至少可重算 entropy/margin/multimodality/coherent path；若 dense logits 可用则保存压缩/哈希版本）；尝试 `output_hidden_states=True` 或等价 hook。
- `src/lyricalign/inference/qwen_forced_aligner.py`：如该 adapter 被复用，增加可选 evidence/hidden 返回并保持默认 alignment 输出一致。
- `runner.py::_cached_forward()`：不能丢弃 backend audit；cache payload 至少含 rows、raw/official evidence、posterior config、hidden config、schema version。
- `detector_features.py`：扩展 R/O/RO/V/P/S/H/PR，并新增 per-unit/cross-window 聚合入口；不得把 GT、未来 trajectory、mutation family 写入 features。
- `train_detector_helpers.py` / `train_detector.py`：只接受 corrected corpus；固定一个 tabular learner；raw_target 与 official_target 分开；加入 `SIGNAL_COMPLETION_MATRIX.json`。
- 复用已有 `research_v7` evidence/interval contracts 时，先适配到 corrected request identity；不能直接把旧 detector rows 当新数据。

必做信号：

1. R：raw geometry、entropy/margin/top-k、局部 gap/overlap/compression、差分；
2. O：official geometry、repair shift/run/trajectory；
3. RO：明确 interaction；
4. V：相同 canonical unit 跨 overlap window 的 timing/posterior/top-k/occurrence/context consistency；
5. P：连续 coherent second path 与 repeated occurrence ambiguity；
6. S：trajectory/mode switch/change-point；
7. H：last layer + 一个 earlier/high-level layer，token→row→canonical mapping、hook on/off numerical equivalence、hidden schema/hash；只有真实实现尝试失败并保存日志才可 `blocked_api`；
8. PR：Gate P 后才构造 propagation-risk target，只用决策时 evidence 作输入。

固定 ablation rows：`H`, `R`, `O`, `H+R`, `H+O`, `R+O`, `H+R+O`, `H+R+O+selected(V/P/S)`。再比较一个 per-unit CNN1D/TCN；不能使用旧的“整段 any-unsafe 广播到每 unit”监督。每行 matrix 包含 `branch_id/status/input_artifacts/n_train_songs/n_val_songs/n_test_songs/n_units/n_intervals/metrics_artifact/failure_or_block_reason`。`executed` 和 `negative` 才算完成，`failed`/`skipped_budget` 不算完成。

intervalization 必须输出整段无 gap/overlap 的 ACCEPT、REJECT、UNCERTAIN intervals，报告 unit unsafe reject、interval @75、interval @100、longest unsafe ACCEPT run、correct-unit false reject/uncertain。独立冻结 SA60、SA80、R95，再单独报告 SA60+R95 joint feasibility；UNCERTAIN 永远不算 REJECT。

### P5：真正的 selected closed loop

修改 `run_closed_loop.py`、`route_executor.py`、`routes.py` 和 contracts：

```text
serial state + inference evidence
  -> detector three-state units
  -> build_route_plan()
  -> RouteExecutor.execute()
  -> retry rows + explicit writeback
  -> next serial state/request
```

`RouteExecutor` 必须返回 retry rows、writeback state hash、next request identity 和 cost；executor 不读分数、不重新决策。L/W 的 audio/query/prefix/writeback 行为必须在 fixture 中不同。执行阶段禁止读取 GT；GT 仅用于最终评估。若 writeback 不改变后续 request/state，Gate C 失败。

### P6：M4、MIR、Test Demo 和最终报告

- M4：source-song-disjoint train/validation/test，所有 mutation/view 跟随 source song；
- MIR-1K：M4 模型/scaler/threshold 冻结后 fixed transfer，不 retune；
- Test Demo：自动发现全部当前 item，不固定旧数量；输出每歌 windows/cursor/query head/raw-official/jumps/unresolved/retry/top suspicious regions；无 GT accuracy claim，仅 ranked abnormalities + 小随机 control；
- `report_transition.py`、`report_final.py` 改为读取 authoritative JSON/JSONL 和 gate 状态，明确 strong/moderate/exploratory/invalidated/not_executed，不能因存在某个 final artifact 判 complete。

## 4. Artifact、cache 和依赖规则

### 4.1 Gate 文件

新 session 至少拥有：

```text
00_meta/SESSION_META.json
00_meta/DATASET_SPLIT.json
00_meta/VALIDITY_GATES.json
01_query_audit/QUERY_AUDIT.jsonl
02_transition/FORMAL_<role>.json(.jsonl)
03_propagation/EPISODES.jsonl
04_oracle_recovery/ORACLE_SUMMARY.json
06_detector/SIGNAL_COMPLETION_MATRIX.json
06_detector/FROZEN_WORKING_POINTS.json
07_closed_loop/CLOSED_LOOP_SUMMARY.json
08_transfer_demo/MIR_TRANSFER_SUMMARY.json
08_transfer_demo/TEST_DEMO_SUMMARY.json
```

下游脚本启动时必须验证上游 gate、schema 和 estimator version；缺失或 invalidated upstream 直接退出，不能静默 fallback 到旧目录。

### 4.2 Cache key

在 `identity.py::forward_cache_key()` 和 trajectory key 加入：

- query estimator kind/version；
- exact canonical query start/end ids、text content/slot topology；
- absolute `start_window_index` 和 starting-state hash；
- hidden extraction schema/config；
- posterior export config；
- decoder evidence version；
- audio/model/preprocessing identity。

可复用：完全相同 identity 的 audio preprocessing、model weights、source manifest/split、独立于错误 serial query 的 full-song evidence，以及 exact request identity 的 raw/official derivation。不可复用：旧错误 query 的任何 serial forward、其 T2 propagation、detector rows/working points、closed-loop outputs。旧文件不删除，标注 `invalidated_by_query_density_bug` 并只读。

## 5. 执行命令接口

以下命令是 agent 应实现/验证的固定入口，所有 Python 命令都从仓库根目录执行：

```bash
cd /home/hyan/LyricAlignment
export PYTHONPATH=.:src
SESSION=runs/research_transition_recovery_detector_20260808_corrected
MANIFEST=/path/to/LONG_TIMELINE_MANIFEST.jsonl

# P0 CPU
pytest -q tests/research_transition_recovery_detector \
  tests/research_v7/test_detector_v2_metrics.py

# fake semantic smoke（T1/T2/T3 各跑一次，验证 query audit/resume）
python scripts/research_transition_recovery_detector/run_transition_smoke.py \
  --mode fake --session-root "$SESSION" --transition T1_direct_serial
python scripts/research_transition_recovery_detector/run_transition_smoke.py \
  --mode fake --session-root "$SESSION" --transition T2_core_boundary_serial
python scripts/research_transition_recovery_detector/run_transition_smoke.py \
  --mode fake --session-root "$SESSION" --transition T3_stable_boundary_serial

# split/preflight/query audit（新 root，不能指向 20260807）
python scripts/research_transition_recovery_detector/build_dataset_split.py \
  --timeline-manifest "$MANIFEST" --out-root "$SESSION"
python scripts/research_transition_recovery_detector/preflight.py \
  --session-root "$SESSION" --out "$SESSION/00_meta/PREFLIGHT.json"
python scripts/research_transition_recovery_detector/build_query_audit.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --role model_selection --fail-on-systematic-bias

# corrected single-case pilot；先 T2 H0/H1（H2 只有在架构独立时）
python scripts/research_transition_recovery_detector/run_transition_smoke.py \
  --mode real --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --song-ids 'newboy' --transition T2_core_boundary_serial --head-strategy H0

# corrected formal；T0 只小规模 diagnostic，T1/T2/T3 是 mandatory
python scripts/research_transition_recovery_detector/run_transition_formal.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --role model_selection --transition T1_direct_serial
# 对 T2、T3 重复上面的命令；每条命令支持 --resume
python scripts/research_transition_recovery_detector/report_transition.py \
  --session-root "$SESSION" --role model_selection

# Gate T 后：propagation、O0/O1/O2，O3 仅按 failure subset
python scripts/research_transition_recovery_detector/collect_propagation.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" --role model_selection
python scripts/research_transition_recovery_detector/run_oracle_recovery.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" --role model_selection

# Gate P 后：evidence/ablation/working points；必须先完成 matrix
python scripts/research_transition_recovery_detector/train_detector.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --mode collect --role detector_train
python scripts/research_transition_recovery_detector/train_detector.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --mode train --role detector_train
python scripts/research_transition_recovery_detector/train_detector.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --mode evaluate --role model_selection
python scripts/research_transition_recovery_detector/train_detector.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" \
  --mode freeze

# Gate D 后：no-GT selected closed loop；再做 MIR / Demo / final report
python scripts/research_transition_recovery_detector/run_closed_loop.py \
  --session-root "$SESSION" --timeline-manifest "$MANIFEST" --role model_selection
python scripts/research_transition_recovery_detector/run_mir_transfer.py \
  --session-root "$SESSION"
python scripts/research_transition_recovery_detector/run_demo_analysis.py \
  --session-root "$SESSION"
python scripts/research_transition_recovery_detector/report_final.py \
  --session-root "$SESSION"
```

如果现有命令无法表达 `head-strategy`、`--resume`、target/raw-official、signal branch 或 gate validation，agent 应先扩展命令接口，再开始 GPU formal；不能通过手工改 JSON 绕过 gate。

## 6. 预算、resume 和失败处理

GPU hard cap 12h，预算 envelope：

| 阶段 | 预算 |
|---|---:|
| P0/P1 fixes、tests、audit | CPU / negligible GPU |
| corrected Transition + H pilot | 2.5–3.0h |
| valid propagation + O0/O1/O2/O3 subset | 2.0–2.5h |
| detector evidence（含 P/V/H minimum） | 2.0–2.5h |
| tabular/sequence offline training | CPU，必要时 GPU <=1h |
| selected true closed loop | 1.0–1.5h |
| MIR/Demo/final checks | 0.5–1.0h |

每个 item 使用 atomic JSON/JSONL append、event log、periodic session flush、strong request identity resume；单个 item failed 不得拖垮独立分支。接近预算时依次削减额外 hidden layers、corruption seeds/intensities、非主 decoder/context ablation、额外 model classes；不能削减 corrected T1/T2/T3、head audit、continuation fix、O1/O2、V/P/H attempt、H/R/O combination、独立 SA60/SA80/R95 和 selected closed loop。若 required branch 真的无法运行，保存精确 resume plan 并把 phase 标成 incomplete，不能写 `complete` 或把 `skipped_budget` 当 negative。

## 7. Agent 完成判据

交付前必须同时提供：

1. P0 CPU 测试和 query audit 通过；
2. Gate T/P/D/C 的状态及失败原因；
3. corrected artifacts 与旧 artifacts 的明确 provenance；
4. `SIGNAL_COMPLETION_MATRIX.json` 无 required `failed`/`skipped_budget`；H 若 blocked 必须有实现尝试、错误和 audit；
5. SA60、SA80、R95 各自完成，joint infeasible 也必须报告 Pareto gap；
6. closed-loop 证明无 GT execution、L/W distinct、writeback 改变后续 trajectory；
7. 最终报告按 continuous timing / unit / interval / route / Demo 分开 denominator，并把旧 2026-08-07 formal、propagation、working points、closed-loop 和 320ms 结论标成 `invalidated` 或 `exploratory`，不复述为新结论。
