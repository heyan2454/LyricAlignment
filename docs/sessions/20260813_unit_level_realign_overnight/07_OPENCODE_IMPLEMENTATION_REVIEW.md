# OpenCode implementation review — required v2 integration fixes

## Review disposition

OpenCode 已补充旧 pipeline 工具，但其现状不能作为当前 unit-level P1 formal 的执行实现。以下 P0/P1
必须修复并完成对应测试后，才可以启动 formal GPU。本清单只关注功能正确性、实验口径和可追溯性，
不要求防篡改或信任链。

## Fix status (2026-08-13 验收)

| 编号 | 状态 | 验收证据 |
| --- | --- | --- |
| P0-1 | **已修复** | `run_unit_realign.py execute/evaluate/report` 接线，v2 布局 + real-executor adapter；`tests/unit_realign` 新增 integration 覆盖 |
| P0-2 | **已修复** | materializer 复用 (song, canonical ID)/strict-overlap/baseline_available 排除；真实 shadow 补算见 `CASE_POOL_V2.jsonl`（60 case，audit `ineligible_invalid_baseline_interval=1091`） |
| P0-3 | **已修复** | `aggregate_classification.py` 删除独立 policy，delegate 到 `unit_outcome.aggregate_region_outcome/aggregate_candidate_outcome`；两个旧 run 已补算 `CLASSIFICATION_AGGREGATE_V2.json` |
| P1-4 | **已修复** | `report_final.py` 只读 v2 布局 + null-safe formatter + empty/exhausted 回归 |
| P1-5 | **已修复** | `audit_round2_gates.py` 输出 `exploratory_only=true`；formal run 已重跑 `ROUND2_GATE_AUDIT_V2.json` |

验收：`PYTHONPATH=src python -m pytest -q tests/unit_realign tests/realign_gate` → **149 passed**；
`python -m compileall -q src scripts` 与 `git diff --check` 通过。实验补算详情见本 session
`09_OPENCODE_FIX_ACCEPTANCE.md`。

## P0-1 — v2 controller 与执行/评价/报告尚未接线

v2 controller 产出 `00_population/`、`01_requests/`、`02_forwards/`、`03_unit_outcomes/` 等目录，
但只实现 `population/screen/expand/p1-pool/p1-refill`，没有把 P1 region 转成 v2 request、GPU forward、
evaluator 或 report 的入口。

相反，OpenCode 的 `evaluate_formal.py` 硬编码读取旧路径 `02_behavior/REQUESTS.jsonl`、
`02_behavior/CASES.jsonl`、`02_behavior/forward/RUN_MANIFEST.json`。所以 `p1-pool/p1-refill` 的结果
无法端到端进入 formal evidence 和 evaluator。

### Required fix

1. 实现 `run_unit_realign.py execute/evaluate/report`，或提供唯一等价入口；不得保留两套没有 adapter
   的 formal pipeline。
2. `execute` 只消费经 `validate_request()` 判为 ready 的 v2 request，写 `02_forwards/FORWARDS.jsonl`、
   `FAILURES.jsonl`、`REQUEST_STATUS.jsonl` 和 identity-keyed `RUN_STATE.json`。
3. `evaluate` 从 v2 request、forward evidence、evaluator-side GT 和 `STRATIFIED_POOL` 生成
   `03_unit_outcomes/UNIT_OUTCOMES.jsonl`、`REGION_OUTCOMES.jsonl`、`CANDIDATE_OUTCOMES.jsonl`。
4. `report` 只消费 v2 artifacts，生成 `05_analysis/*` 与 `FINAL_REPORT.md`；empty/exhausted run 也必须
   正常产出报告。
5. 新增 synthetic CPU integration test：one ready、one R-NULL、one failed request。

## P0-2 — detector-only confirmation pool 可抽到重复/非法 case

`materialize_no_gt_confirmation_pool.py` 的 `choose()` 仅执行 per-song cap，未排除同
`(song_id, canonical_unit_id)` target 重复、同 song 的 time overlap，亦未排除
`baseline_available=false` 的零长或倒置 baseline interval。它还将整窗 `old_units` 写出，增加 downstream
把 whole window 当 local request 的风险。

真实 frozen detector shadow 的只读 audit：40 windows、8,694 population rows，其中 1,091 个 unsafe
region baseline geometry 无效；这些必须标为 `ineligible_invalid_baseline_interval`，不得进入 primary cohort。

### Required fix

1. 以 `balanced_replenishment()` 作为唯一 primary sampler，或严格复用其 `(song, canonical ID)` 与同-song
   strict-time-overlap 排除规则。
2. 仅 `baseline_available=true` case 可进入 eligible pool；其余保留行和 exclusion reason 于 audit。
3. case 必须明确写 `active_target_unit_ids`、`fixed_context_unit_ids`、`outside_unit_ids` 和 local context
   boundary，禁止只靠整窗 `old_units` 推断 target/context。
4. 增加 overlap、同 target 跨 window、invalid baseline interval 回归测试。

## P0-3 — OpenCode classification 忽略 context/extra harm

`aggregate_classification.py` 先取 target rows，fixed-context missing/drift 与 extra prediction 不会进入
region/candidate harmful、mixed、catastrophic 判定，违反 v2 evaluator 合同。

### Required fix

1. 删除脚本内独立 classification policy，改为调用
   `unit_outcome.aggregate_region_outcome()` 与 `aggregate_candidate_outcome()`。
2. region 输出必须有 target 与 fixed-context 分母；extra/unpairable 保留并影响 harm。
3. 回归：target improved + fixed degraded => mixed；target improved + extra/unpairable => mixed/harmful；
   target covered-to-missing => catastrophic_harmful。

## P1-4 — FINAL_REPORT 仍引用旧 schema，empty metrics 会崩溃

`report_final.py` 读取旧 `02_behavior/`、`06_evaluator_only/`，不是 v2 artifact layout。其第 69–70 行将
`_num(None)` 的字符串 `n/a` 用数值格式化；没有 paired row 时会抛异常。

### Required fix

1. 改读 v2 `00_population`、`01_requests`、`02_forwards`、`03_unit_outcomes`、`05_analysis`、`07_runtime`。
2. nullable metric 使用 null-safe formatter；empty、all-null、exhausted 必须输出 `NOT_EVALUATED/EXHAUSTED`
   report，不能 crash。
3. report 输出 family × stratum selected/constructible/executed/null/failed/valid，target/fixed context 分开
   指标，以及 region/candidate/song-cluster 汇总。
4. 增加 empty、all-null、one-valid-case regression tests。

## P1-5 — 未冻结 round-2 gate 不得替代 P1 acceptance

`audit_round2_gates.py` 的 `eligible>=500`、`selected>=300` 不是本 session 冻结的 primary P1 门槛
（S1–S4 各 25 valid case，另报 family coverage）。它只能保留为 exploratory audit，不能被 FINAL_REPORT、
formal pass/fail 或 writeback discussion 消费。

### Required fix

标记 `exploratory_only=true`；P1 completion 仅按 v2 resolved config 的 strata/family denominator 判定。

## Required verification

运行 `PYTHONPATH=src python -m pytest -q tests/unit_realign tests/realign_gate`、`python -m compileall -q src scripts`
和 `git diff --check`。额外必须覆盖 v2 controller end-to-end、confirmation overlap/invalid interval、
context/extra classification、empty report，以及 P1/exploratory gate separation。

---

## Update review — OpenCode revision after this review

### Closed / materially improved

- P0-2 的 confirmation pool 已加入 `baseline_available`/strict interval eligibility、同 song target 去重、
  同 song strict-time-overlap 排除和审计；对应 unit tests 已存在。
- P0-3 的旧 `aggregate_classification.py` 已改为复用 v2
  `aggregate_region_outcome()`/`aggregate_candidate_outcome()`；target + fixed-context + extra 进入分类。
- P1-4 的 `report_final.py` 已改读 v2 artifact layout，并覆盖 empty/all-null/one-valid-case 的 null-safe
  report 测试。

`PYTHONPATH=src python -m pytest -q tests/unit_realign` 当前通过 43 tests。

### Remaining P0-A — 真正 P1 population 无法 materialize v2 request

`build_region_population()` 的真实 frozen detector population row 不含 `units`、`identity_context` 或
`audio_path`。而 `run_unit_realign.py::_region_to_request()` 要求这些字段，缺任一则返回
`not_constructible`。当前 CLI test 手工注入这些字段，不能证明实际
`p1-pool -> p1-refill -> execute` 能构造任何真实 request。

只读实测 frozen detector population row keys 为：

`baseline_available, detector_state, language, left_anchor_candidates, overlap_interval_sec, region_id,
right_anchor_candidates, seed_kind, song_id, target_unit_ids, window_index`

### Required fix

实现 source adapter：从冻结 timeline/window manifest 解析 local text units、baseline timestamps、
audio path/SHA 和运行 identity context，再 materialize v2 request。新增一个使用真实 manifest schema
fixture（不是手工内嵌完整 `units`）的 CPU integration test，证明 primary population 至少能到 ready/
not-constructible 的正确原因分流。

### Remaining P0-B — `execute` 只计划 forward，却错误标 completed

当前 `execute` 仅写 `02_forwards/FORWARDS.jsonl`，其中 status 为 `ready`、executor 是
`scripts/research_v7/run_behavior_suite.py` 的计划；它没有实际调用 runner 或验证 evidence。随后却将
ready identity 写进 `completed_identities`、region 写进 `completed_region_ids`。这会让 `--resume` 跳过从未
GPU forward 的 request，并让 refill 将其误作已完成。

### Required fix

冻结并实现状态机 `planned -> queued -> running -> executed|failed|invalid|null|not_constructible`。
只有真实 evidence 已写入且 attempt status=ok 才写 `executed/completed` 和 completed region；planned/queued
必须可安全重试，不能影响 replenishment 的 valid-case 缺口。

### Remaining P0-C — evaluator 静默跳过缺 evidence，并错误合并 candidate

v2 `evaluate` 缺 baseline/candidate evidence 文件时直接 `continue`，不写 failure/status、不进入分母、也不
触发 replenishment。它还把全部 region outcomes 一次性传给 `aggregate_candidate_outcome()`，只写一个
`CANDIDATE_OUTCOMES.json`，混合不同 request identity、family 甚至 song。

### Required fix

1. 缺 evidence 显式写 `not_executed/missing_evidence` status 和 failure artifact；报告/补样分母必须看见它。
2. 按 `(song_id, request_identity, family)` 分组 region outcome，写
   `03_unit_outcomes/CANDIDATE_OUTCOMES.jsonl`（每 candidate 一行）；report 按此表汇总，不得用一个全局
   candidate outcome 代替。
3. 新增 regression：mixed ready/missing-evidence population；两个 song、两个 family 的 candidate grouping。

### Remaining P1-D — fixed context 与 extra 的 denominator 仍被合并

`aggregate_region_outcome()` 将 extra 纳入 relevant，当前 `n_context` 以 `len(relevant)-len(target)` 计算，
于是 report 的 fixed-context 指标实际含 extra/unpairable prediction。extra 应影响 harm，但不应进入
fixed-context coverage/missing 分母。

### Required fix

region/candidate/report 分别输出 `n_fixed_context` 与 `n_extra`（及各自 outcome counts）；extra 仍参与 harm
policy，但不再伪装为 fixed context。增加 target + fixed + extra 的精确 denominator regression。
