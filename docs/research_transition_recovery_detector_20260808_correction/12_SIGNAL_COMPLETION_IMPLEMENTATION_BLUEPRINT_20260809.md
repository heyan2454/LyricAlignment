# Signal Completion 实施蓝图

日期：2026-08-09  
权威设计：`11_SUPPLEMENTAL_SIGNAL_COMPLETION_PLAN_20260809.md`  
执行根：`runs/research_transition_recovery_detector_20260809_signal_completion/`  
状态：待交接实现

本文件将补充计划拆成可实现、可验收的工程工作包。`H`、`P`、`PR` 是强制阶段：必须有
真实 evidence、非零分母、实际训练/评测记录；不得以 `blocked_api`、`not_executed`、
`skipped_budget` 或 placeholder 作为完成状态。

## 1. 初始化与共享合同（先完成）

建立新 session，不读取旧 working point 或旧 final report 作为结果输入；旧 run 只可作为 forward
cache / source evidence 的只读来源。

```text
00_meta/SUPPLEMENT_META.json
00_meta/RUNTIME_BUDGET.json
00_meta/FAILURES.jsonl
00_meta/RESOLVED_CONTRACT.json
```

`RESOLVED_CONTRACT.json` 固定：

- label：Safe `<=0.100s`、Grey `(0.100,0.250]s`、Unsafe `>0.250s`；
- report tolerances：100/250/500/1000ms；320ms=legacy-only；
- source-song split 和冻结 manifest identity；
- primary learner（现有 MLP）与 optional logistic sanity baseline；
- H layers `[-4,-1]`、float16 storage/float32 compute；
- P 算法：单一 k-best monotonic beam DP；
- sequence model：单一 CNN1D（不再在 CNN/TCN 间选择）；
- session GPU budget 和每阶段 cap。

所有入口启动时加载此合同并校验 schema/version。任意 artifact 缺少合同版本、split identity、
request identity 或 label version 时 fail closed。

## 2. Work package A：Transition / timing 修正（CPU）

### 代码

- 新增 `scripts/research_transition_recovery_detector/reaggregate_transition_v3.py`；
- 新增 `scripts/research_transition_recovery_detector/compare_raw_official_timing.py`；
- 修正 `transition_metrics.cursor_time_drift()`：使用 `committed_end_exclusive - 1` 对应的 GT；
- 新增 `scripts/research_transition_recovery_detector/evaluate_interval_metrics_v2.py`。

### 聚合实现

serial 只取 `state_before.committed_end_exclusive <= canonical_id < decision.committed_end_exclusive`
的行。每行保存 `song_id/request_id/window_index/canonical_id/view/error_raw/error_official/label`，再由
row table 汇总；不得只从已汇总 accuracy 反推。

full-song 必须用音频 bytes SHA + canonical unit count + row id range 关联 cache 与 source song；匹配不唯一或
缺失即失败。输出每歌与 pooled `target/committed/correct/wrong/grey`、coverage、曲线与 errors。

paired comparison 使用同歌的 250ms correct coverage：输出 T2−T1、serial−full-song 的 win/tie/loss、mean、
median 和 source-song bootstrap 95% CI。candidate JSON 是唯一 selection source；Markdown 不得自行决策。

### 验收

- `wrong_committed_250ms`、`grey_committed`、`unsafe` 都来自 row table；
- 每歌 invariant：`committed == safe + grey + unsafe`；
- 产出 `AUTHORITATIVE_TRANSITION_SELECTION_v3.json`、`TRANSITION_PAIRED_BY_SONG.json`、
  `RAW_OFFICIAL_TIMING_COMPARISON.json`；
- 可复现 interval metrics 入口显式记录 prediction、threshold、target view、rule hash 与 split。

## 3. Work package B：一次 forward 的 evidence v3（GPU 最小补采）

### 接线位置

主要修改：

- `scripts/demo/align_qwen_fa_serial_demo.py::infer_slice`；
- `src/lyricalign/inference/qwen_forced_aligner.py`（如共用 adapter）；
- `research_transition_recovery_detector/runner.py::_cached_forward`；
- 新增 `research_transition_recovery_detector/evidence_v3.py` 与
  `scripts/research_transition_recovery_detector/collect_evidence_v3.py`。

每次成功 forward 一次性保存：rows/raw timing/official timing、完整 timestamp-slot posterior 的可重建压缩
表示、H(-4/-1) timestamp-token hidden、request/view/canonical mapping、模型/processor/decoder identity。
Cache key 加入 `evidence_schema_v3`、`posterior_config`、`hidden_config`。旧 top-k-only cache 只可用于 R/O
回填；P/H 不足时针对 detector_train/model_selection/threshold_validation requests 做最小重跑。

### H：必须真实实现

调用模型时启用 `output_hidden_states=True`（或等价模型输出 hook），在 timestamp positions gather `-4/-1`
的 start/end vectors。每条 unit evidence 至少含：layer、dimension、start/end vectors（float16）、mapping、hash。

新增 on/off audit：同一 deterministic request 比较 logits、raw/official rows、row count、mapping；记录最大
logit delta。若有实现错误，修复后继续跑；H 完成需要：

```text
hidden_available_rate >= 0.99
n_H_rows == n_R_rows（除真实 forward failure）
```

### P：必须真实实现

从完整 boundary posterior 做固定 k-best monotonic beam DP，输出 best/second path score、normalized gap、
boundary displacement、differing-slot fraction、longest alternate run、continuity、global-shift indicator、
occurrence-mode separation。P 的行与 R 同 request/canonical id 对齐：

```text
n_P_rows == n_R_rows
```

不得用 entropy/top-k margin 冒充 P，也不得只保存 top-k 后宣称 P 不可用。

### R/O/RO/V/S

- R/O：由同一 rows 计算 geometry、posterior、repair 与局部差分；
- RO：必须有明确交互列及 `RO_SIGNAL_ATLAS.json`，非简单字段拼接；
- V：以 `(song_id, canonical_id)` 聚合同一合法 overlap views，分母为 `>=2 valid views`；导出 posterior
  JS/L2、top-k overlap、raw/official displacement、mode jump；
- S：按 canonical 连续片段仅用当前及过去 evidence 计算 rolling trend、velocity/acceleration、run/change-point。

collector 完成后生成 `SIGNAL_COVERAGE_AUDIT.json`。H/P 覆盖为零或 evidence 未被 feature extractor 消费时，
Stage 2 不得通过。

## 4. Work package C：Correctness detector 与消融（CPU，依赖 B）

新增统一 dataset builder，输入 v3 evidence，输出 source-song-disjoint rows；Grey 不进入二元 train/freeze，
但保留评测统计。每个 feature row 必须持有 request/song/canonical identity，禁止 future GT/trajectory/mutation
字段进入 feature。

H features 包括 start/end norm、cosine/L2、邻接差分、跨层差分、change point；另做 direct hidden linear
probe（PCA/scaler 只在 train fit）。P、V、S 使用 B 产物，不回落到 placeholder。

固定执行矩阵：

```text
H, R, O, RO, V, P, S,
H+R, H+O, R+O, H+R+O,
R+selected(V/P/S), H+R+O+selected(V/P/S), CNN1D
```

先在 validation 比较 V/P/S 单信号与 R 增量，冻结一个 selected signal；随后跑两项固定组合。每 branch 输出
raw_target 与 official_target 的 AUROC/AUPRC、SA60/SA80/R95、三态率、interval @75/@100、song macro、runtime。
CNN1D 为 per-unit 输出，且与同输入 MLP 比较。

生成 `MODEL_SELECTION_v3.json`、`FROZEN_WORKING_POINTS_v3.json`、
`INTERVAL_METRICS_REPRODUCIBLE.json`、`SEQUENCE_MODEL_EVAL.json`、`SIGNAL_COMPLETION_MATRIX_v3.json`。
仅 `executed`/`negative` 算完成；H/P 必须 `executed` 或有效 `negative`。

## 5. Work package D：PR propagation-risk（GPU 最小补集 + CPU）

新增 `build_pr_targets.py`、`collect_pr_mild_episodes.py`、`train_pr_detector.py`。

先从 corrected episodes 建 `PR_TARGET_AUDIT.json`，按 source song 与 natural/model-native/corruption 统计
low/medium/high/no-effect。若 low+medium 不足，只补 `{cursor ±1/±2/±4, time ±.25/.5/1.0s, mild boundary}`，
直到有 source-song-disjoint non-high cohort；不得以样本不足跳过 PR。

PR 输入仅为决策时可见的 H/R/O/RO/V/P/S evidence；future recovery class、mutation family、severity 和未来
trajectory 仅能生成 label。主任务 `high vs non-high`，辅助三分类；比较 best correctness score 与 PR model，报告
AUROC/AUPRC/recall/FN/source-song macro，及固定 intervention-rate 下阻断的 future corrupted units。

PR 的完成标准是非零的 `PR_EPISODES.jsonl`、`PR_EVALUATION.json` 与 matrix 中 `PR: executed|negative`。

## 6. Work package E：Retry failure decomposition 与正确 writeback（依赖 C）

改造 `RouteExecutor.execute()` 返回 retry rows、retry request identity、retry audit 与 cost；executor 不读取 score/GT。
编排层对 retry rows 再运行冻结 detector、构造 retry writeback plan，并将 retry-derived committed rows/timestamps
并入 serial state。L 不可越 gap；W 必须依据 retry detector 重新决定 prefix。

对当前 36 个 selected retry window 生成 before/after 行级记录，分为：

```text
retry_improved_detector_accept
retry_improved_detector_block
retry_not_improved
retry_worsened
```

并额外标记 detector accept but route/writeback blocked。improved/worsened 规则固定为 250ms coverage ±10pp
或 MAE 相对变化 ±20%。输出 `RECOVERY_FAILURE_DECOMPOSITION.json(.jsonl)`，并检查后续 1/2/3 windows 保持性。

## 7. 交接与阶段 gate

| Agent 工作包 | 前置 | 交付 gate | 不通过时的动作 |
|---|---|---|---|
| A transition/timing | 无 | row invariants、cache map、paired CI 非空 | 修 aggregation/report，不重跑模型 |
| B evidence v3 | A 可并行 | H/P/R rows 非零且覆盖 audit | 修 extraction，最小重跑缺失 request |
| C detector | B | 所有 H/R/O/RO/V/P/S branch 实跑 | 修 dataset/features，禁止降级为 planned |
| D PR | B；可与 C 后半并行 | low/non-high 非零、PR 实跑 | 补轻度 episodes，禁止跳过 |
| E recovery | C frozen WP | retry-derived writeback/decomposition 非零 | 修 plan/writeback 后重跑 36 windows |
| F reports | A/C/D/E | required artifact + denominator gate | 报告 `supplement_completed=false` |

每位 agent 的交接报告必须包含：改动、测试、实际运行命令、GPU seconds、artifact paths、coverage/denominator、
失败日志和下一依赖。Agent 不得在某个 branch 得到 negative result 后结束其他独立 branch。

## 8. 最终报告 gate

`SUPPLEMENTAL_REPORT` 只能在以下条件为真时设置：

```json
{
  "supplement_completed": true,
  "signal_completion": true,
  "H_nonzero": true,
  "P_nonzero": true,
  "PR_executed": true,
  "retry_decomposition_complete": true
}
```

否则报告须列出精确缺失 artifact/denominator/错误日志，且不得用旧 20260808 conclusion 填补。
