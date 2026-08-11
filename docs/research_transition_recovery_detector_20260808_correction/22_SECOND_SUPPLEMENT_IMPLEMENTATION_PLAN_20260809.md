# LyricAlignment 第二次补充：核实结论与 OpenCode 实施方案

**审计日期：2026-08-09**  
**实施根目录：** `runs/research_transition_recovery_detector_20260809_second_supplement/`  
**基线只读：** `runs/research_transition_recovery_detector_20260808_corrected/`、`runs/research_transition_recovery_detector_20260809_signal_completion/`

## 1. 审计结论

第二次补充计划的核心判断成立；但其中两项应改写为更精确的表述，不能把现有数值本身当作已复现事实。

| 问题 | 核实 | 代码/证据 | 处理 |
|---|---|---|---|
| committed-view 混用 | **成立（P0）** | `train_detector_v3.py:281-284` 用 `{canonical_id: row}` 推导 R/O/标签，后遇 overlap 会覆盖先前行；但 `row_req`（333-340）和 H/P（375-388）用 committed request。 | 修复后，现有 detector v3 指标、阈值和 interval 必须作废并重训。 |
| detector 与 authoritative 标签数不一致 | **成立（P0）** | 权威 T2 是 `549/804/2021`（3374）；计划记录 detector 为 `509/722/2143`（3374）。上述混用足以解释不一致。 | 将“最终必须完全一致”设为 blocking invariant。 |
| H slot 映射只是 `2i/2i+1` 假设 | **成立（P0）** | `train_detector_v3.py:113-180` 全部以 `2*i`/`2*i+1` 切 hidden；没有保存 decoder 的 slot map。 | 不可把现有 H negative 冻结；需从 decoder 输出同源映射。 |
| P 尚未证明 coherent distinct second path | **成立（P0）** | `posterior_paths.py` 是有限 beam（宽度 24）后再要求至少半数 slot 不同；它把“无该幅度 alternate”编码成 `ok/diverse=false`，而非 unit-level second coherent path。`train_detector_v3.py` 仍主要消费 local top-2 gap 与 `p_path_ok`。注意：当前 `_beam_paths()` 已以 class tuple 去重，故“second path 与 best 完全相同会被接受”这一子判断**不成立**；问题是 50% diversity 门槛和不充分的单位特征，而非 exact duplicate。 | 重写为 exact/可证明 k-best monotonic DP，并给每 slot/unit 的 best-vs-second 差异。 |
| “32/36 为 insufficient_paths” | **未能从保留 evidence 独立复核** | 当前 evidence pack 不含 posterior `.npy` 或 `evidence_posterior_*.jsonl`；仓库无该文件。 | 新运行先输出 request-level P audit，再报告根因；不要将 `32/36` 当作已验证输入。 |
| Grey 被算为 Unsafe | **成立（P0）** | `evaluate_interval_metrics_v2.py:64` 使用 `l in (1,2)`；标签注释已定义 1=Grey、2=Unsafe。 | 所有 interval 数值无效，严格只用 `label==2`。 |
| interval 可跨歌 | **成立（P0）** | evaluator 以 `enumerate(p_bad)` 构造 id（60），`build_intervals()` 仅按连续 id 合并；没有 song key。 | 用 `(song_id, canonical_id)` 分组。 |
| O/RO end 字段缺失 | **成立（P1，原因已定位）** | decoder 已生成 official start/end（`align_qwen_fa_serial_demo.py:386-421`），但 `runner.py:385-409` 仅写出 official start，丢弃 official end。 | 扩大 runner evidence schema；旧 records 不能离线补 official end。 |
| recovery artifact/report/source provenance 不一致 | **成立（P0）** | artifact 实为 3 accept writeback + 2 block；报告仍写“全部 5 被 block”。更重要的是仓库的 `run_recovery_decomposition.py:96-116` 明言未保存 retry rows、只能生成占位分解，故无法产生当前 artifact。 | 不能信任当前 decomposition 为可复现来源；重新记录真实 before/retry/writeback/next-state 链。 |
| CNN vs MLP 不公平 | **成立（P1）** | 现有 sequence report 只声明 CNN input，未保存/复用 MLP 的 train-only scaler；源码应显式共享同一 scaler。 | 最小公平复跑一次 MLP vs CNN1D。 |
| PR 以 pooled in-sample 0.608 为主结果、proxy 非冻结 detector | **成立（P1）** | `PR_EVALUATION.json` 标明 correctness proxy 为 feature mean；报告输出 pooled AUC。 | 只用 OOF/LOSO 和修复后冻结 correctness score。 |

`RECOVERY_FAILURE_DECOMPOSITION.json` 的数字也直接反驳旧报告：36 个窗口中 `27 not improved / 4 worsened / 3 improved+accept / 2 improved+block`，并且三例 `retry_writeback_commits` 非空。因此“0 writeback、5 个改善全部被 block”是错误结论。

补充：H 的 request-level artifact coverage 写成 100%，但 `MODEL_SELECTION_v3.json` 的 unit-level complete-H coverage 实为 `2780/3374=82.39%`；P 的 complete-feature coverage 为 0%，仅 289/3374 行有 request-level `ok` path 字段。因此两者均不能以“185 requests coverage 1.0”作为已完成的 unit-level结论。

## 2. 不可变原则与数据合同

新增 `src/lyricalign/research_transition_recovery_detector/detector_observations.py`，作为训练、interval、PR、recovery 共用的唯一行构建器；不再在各脚本复制 dict comprehension。

```text
ObservationKey = (source_song_id, transition_id, request_id, window_id, view_id,
                  canonical_unit_id)

CommittedSample = {
  source_song_id, canonical_unit_id, transition_id, request_id, window_id, view_id,
  committed_request_id, is_committed_observation=True,
  row, label_raw, label_official, all_legal_observations
}
```

实现 `build_committed_observation_index(records)`：

1. 对每个 record 用 `[state_before.committed_end_exclusive, decision.committed_end_exclusive)` 选 committed ids；
2. 以 `(request_id, canonical_id)` 保存 exact row，检测重复 key；
3. 以 `canonical_id -> committed_request_id` 保存一次且仅一次的 primary binding；
4. 保存全部合法 view 给 V，但 primary `row` 永远取 `(committed_request_id, canonical_id)`；
5. 返回 audit（总数、重复、缺行、non-committed overlap、每个 mismatch 原因）。

训练前硬断言：T2 model-selection 的 units 与 Safe/Grey/Unsafe 必须等于 `AUTHORITATIVE_TRANSITION_SELECTION` 的 T2 行计数；mismatch 不是空就退出。写出：

```text
06_detector/COMMITTED_OBSERVATION_BINDING_AUDIT.json
06_detector/COMMITTED_OBSERVATION_BINDING_MISMATCH.jsonl
```

## 3. 实施顺序

### A. 先修纯 CPU 数据通路（阻塞一切训练）

修改：

- `src/.../detector_observations.py`（新增）
- `scripts/.../train_detector_v3.py`
- `scripts/.../evaluate_interval_metrics_v2.py`
- `src/.../detector_intervals.py`
- `scripts/.../train_pr_detector.py`

要点：

- 删除 `rows_to_rowobjs()` 的 canonical-id 最后观测逻辑，R/O/RO/label 直接从 `CommittedSample.row`；H/P 查同一个 `committed_request_id`；S 按每首歌的 committed canonical 序列；V 只从 `all_legal_observations` 聚合。
- `meta_rows` 必须保存完整 identity，而非仅 `song_id/cid/request_id`。
- interval evaluator 输入改为 records（或带 song id 的 prediction jsonl），逐 song 排序；不允许 position index 作为 canonical id。Unsafe 只等于 `label==2`；Grey 三态单独报告。分别计算 `REJECT` 和 `REJECT+UNCERTAIN protected`，不将后者称为 reject recall。
- PR 的 feature builder 使用 committed primary row 和新冻结 correctness `p_bad`；先生成每 episode 的 out-of-fold prediction，再计算 pooled OOF、LOSO/source-song macro AUROC/AUPRC。

新增测试：

- overlap 中后 view 不能覆盖 committed row，且三态计数与权威 transition 相同；
- 两首歌曲连续 local/canonical id 不合并；Grey 不进入 unsafe 分母；REJECT-only 与 protected 数不同；
- PR 训练 fold 永不见 held-out song，correctness 输入是 frozen OOF score。

### B. 修 evidence exporter 和 H 的真实 slot mapping

修改：

- `scripts/demo/align_qwen_fa_serial_demo.py`
- `src/.../runner.py`
- `scripts/.../collect_evidence_v3.py`
- `scripts/.../train_detector_v3.py`

要求：

1. decoder 在生成 rows 时输出 `timestamp_slot_map`：每个 canonical/query unit 的 `start_slot`、`end_slot`、decoder slot count、token/processor mapping schema/hash。该 map 必须从实际 `output_meta/decoded` 建立，禁止训练器推断 `2i`。
2. `runner` evidence 保留 raw/official 的 global start/end，raw↔official start/end shifts，slot map 和 request identity；将 evidence schema 升到 v4 并纳入 cache key。
3. hidden collector 以 slot map 保存每层 vectors；H feature builder 通过 exact start/end slots gather。对没有合法 start/end slot 的 unit 输出 reason taxonomy，不能填 0 或截断。
4. 新增 deterministic one-request hidden off/on audit：比较 logits（或 posterior hash/最大绝对差）、raw times、official times、query ids、slot map；不等价即 fail closed。

输出：`HIDDEN_EQUIVALENCE_AUDIT.json`、`H_COVERAGE_AUDIT_V2.json`、`O_RO_SCHEMA_AUDIT.json`。

### C. 重写 P 为正确的 distinct k-best path

修改 `src/.../posterior_paths.py` 和 `scripts/.../aggregate_evidence_v3.py`。

- 对每 slot、每 timestamp class 保存 top-2 predecessor 的 backpointer，做全局 k-best monotonic DP；若 state space 大，使用有正确性断言的 lazy k-shortest，而不是固定宽度 beam。
- second path 定义仅要求至少一个 boundary slot 不同；`min_changed_slots` 作为显式冻结参数（默认 1），不得暗含 50% 阈值。报告较大 alternate（例如 >=50%）只是分析字段。
- 输出 request-level best/second score、normalized gap、has distinct second、different fraction、max/median temporal displacement、longest alternate run、global shift-like；并输出 unit-level `local_second_path_gap`、`local_boundary_disagreement`、`local_alternate_run_membership`、`local_displacement`。
- 清楚区分 `unique_posterior`、`no_distinct_path_under_constraints`、`invalid_input`、`algorithm_failure`；coverage 不能把 request JSON 数当作 unit coverage。

新增五类单测：unique、两条路径、repeated occurrence 双峰、non-monotonic invalid second、duplicate best 被拒。另加随机小矩阵 brute-force oracle 比较，保证 k-best 排序正确。

### D. 重建 detector、interval 与 sequence 的最小矩阵

在 binding、H、P、O/RO schema audit 都通过后，运行：

```text
H R O RO V P S
H+R H+O R+O H+R+O
R+V R+P R+S
R+selected_temporal
H+R+O+selected_temporal
```

仅以 model-selection 选择 `selected_temporal`，threshold-validation 冻结阈值，test/MIR 不参与选择。每支输出 raw 与 official targets、AUROC/AUPRC、source-song macro AUROC、coverage/eligibility、SA60/SA80/R95、corrected interval metrics、runtime。没有完整 input feature 的分支必须标 `not_eligible` 并带 reason，不得声称 full O/RO/P 已评测。

Sequence：MLP 和 CNN1D 都只在 train fit 同一个 `SimpleImputer + StandardScaler`；同 features、labels、eligibility、song split，CNN 输入用 transform 后数值。输出 scaler hash、missing policy、train/val/test ids。无额外模型网格。

### E. recovery 以真实执行链重建

修改 `scripts/.../run_closed_loop_v3.py`（及其下游 route executor）和 `run_recovery_decomposition.py`。

每个 retry event 必须落一条 JSONL：原请求/primary rows/score/decision、retry request/rows/score/decision、writeback plan、实际 committed ids 与 provenance、state hashes/cursor、下一请求 identity。decomposition 脚本只能消费这份 JSONL，禁止手工表或 `backend.last_rows` 临时状态。

固定 improved 规则（250 ms coverage +10pp 或 MAE -20%）后重算四类。对于每个 accept writeback，强断言 retry-derived commit >0、state hash 改变、next request 改变；随后追踪 1/2/3 window 的 retained/lost/new error。block case 不得写回。

### F. 报告与 gate

修改 `report_supplemental.py`：只读取本 session 的 authoritative artifacts；删除硬编码“0 writeback”“5/5 blocked”和 feature-mean proxy。任何以下条件失败，最终状态为 `invalidated/not_complete`：binding mismatch 非零、H on/off 不等价、P synthetic oracle 失败、interval song/label audit 失败、recovery real-chain 缺失。

## 4. 复用与重跑边界

| 项 | 可复用 | 必须重跑 |
|---|---|---|
| authoritative T2 transition 标签 | 08-08 T2 record 的 committed-row 定义与 GT | 无 GPU；从 records 重新绑定、重新聚合。 |
| R / raw label / V observations / S | 原 T2 records 的 raw rows | 无 GPU；但在新 binding 后重建 features、重训所有 classifier。 |
| official start-only O | 原 records | 无 GPU，可先做明确 start-only O。 |
| official end 与完整 RO | 不可从现有 `runner` evidence 恢复（字段被丢弃） | 必须为 exact T2 requests 重做 forward，或正式降级 O/RO 为 start-only。 |
| H | 当前 session 无 hidden jsonl/npy，且映射错误 | 必须 exact-request forward，保存 v4 evidence。 |
| P | 当前 session 无 posterior jsonl/npy | 必须 exact-request forward，保存 posterior；算法/单测本身 CPU。 |
| detector/threshold/interval/sequence/PR | 无 | CPU 重建、重训、重新冻结。 |
| recovery | 当前 artifact 无可复现 before/retry rows | 36 retry windows 必须重跑；不可从摘要反推。 |

先作 `CACHE_REUSE_AUDIT.json`：逐 request 比对 model/checkpoint/audio/preprocess/query ids/decoder/evidence schema/hash；只有所有字段相同才复用。不得复用 v3 H/P 或旧 detector scores。

## 5. 验收和执行命令

在 conda `lyricalign-qwen`、仓库根目录执行；所有结果写新 session。

```bash
export PYTHONPATH=.:src
SESSION=runs/research_transition_recovery_detector_20260809_second_supplement

pytest -q tests/research_transition_recovery_detector
python -m compileall -q src scripts
git diff --check

# 新增/扩展的 CPU commands：先生成 binding、P synthetic audit、interval fixture audit
python scripts/research_transition_recovery_detector/train_detector_v3.py \
  --session-root "$SESSION" --records-root runs/research_transition_recovery_detector_20260808_corrected \
  --timeline-manifest <MANIFEST> --mode audit-binding

# exact-request v4 evidence 仅在 cache audit 判定不可复用后执行；先单歌 smoke，再三角色。
python scripts/research_transition_recovery_detector/collect_evidence_v3.py \
  --session-root "$SESSION" --records-root runs/research_transition_recovery_detector_20260808_corrected \
  --timeline-manifest <MANIFEST> --role model_selection --song-ids newboy --smoke
```

完成 gate：

1. model-selection binding mismatch=0，且标签严格为 549/804/2021；
2. H mapping 有同源 slot map、eligible coverage/reason taxonomy、on/off 等价；
3. P passes synthetic oracle，真实 requests 有完整状态分类；
4. interval only uses Unsafe=2 and never crosses song；
5. all detector matrices/working points are regenerated from committed features；
6. recovery decomposition 可由本 session JSONL 重建，并证明每个 accept writeback 改变 serial state；
7. final evidence index 记录每个 artifact 的 command、inputs、cache decision、schema/hash、GPU seconds。
