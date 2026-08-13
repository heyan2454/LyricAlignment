# OpenCode implementation review — 抗辩意见（Rebutal）

对 `07_OPENCODE_IMPLEMENTATION_REVIEW.md` 的逐条核验。原则：以**当前工作区代码事实**为准
（`scripts/unit_realign/run_unit_realign.py` 最后修改 2026-08-13 12:42，review 文档生成 13:46，
两者基于同一工作区），只评功能正确性/口径/可追溯性。

## 结论一览

| 编号 | review 主张 | 判定 | 备注 |
| --- | --- | --- | --- |
| P0-1 | 无 execute/evaluate/report 入口、两套 pipeline 无 adapter | **部分成立** | "无入口"表述过时；"无端到端接线"成立 |
| P0-2 | confirmation pool 可抽重复/非法 case | **完全成立** | 证据充分，无抗辩 |
| P0-3 | classification 忽略 context/extra harm | **部分成立** | v2 正式路径已合规；违规的是 post-hoc 脚本 |
| P1-4 | FINAL_REPORT 旧 schema + empty crash | **完全成立** | 第 69–70 行格式 bug 真实存在 |
| P1-5 | 500/300 gate 非冻结门槛 | **完全成立** | 且修正本 session 07 文档的错误引用 |

---

## P0-1 — v2 controller 与执行/评价/报告尚未接线

### 抗辩：表述过时，但核心问题成立

review 称 v2 controller "只实现 `population/screen/expand/p1-pool/p1-refill`"。**当前代码事实不符**：

- `scripts/unit_realign/run_unit_realign.py:84-85`：command choices 已含 `execute/evaluate/report`；
- `execute`（140–165 行）：对 request 做 `validate_request()` 校验，写 `01_requests/REQUEST_STATUS.jsonl`
  与 identity-keyed `07_runtime/RUN_STATE.json`（completed/failed/null/not_constructible）；
- `evaluate`（166–193 行）：调 `pair_unit_outcomes()` + `aggregate_region_outcome()` +
  `aggregate_candidate_outcome()`，写 `03_unit_outcomes/UNIT_OUTCOMES.jsonl`、`REGION_OUTCOMES.jsonl`、
  `05_analysis/CANDIDATE_OUTCOMES.json`；
- `report`（194–209 行）：读 `03_unit_outcomes/REGION_OUTCOMES.jsonl` + `CANDIDATE_OUTCOMES.json`
  生成 `reports/FINAL_REPORT.md`。

但 **review 的核心主张成立**，三处接线缺陷真实存在：

1. `execute` **不执行 GPU forward**：文件 docstring 明示 "Model forwards remain owned by
   `scripts/research_v7/run_behavior_suite.py`"，execute 只做校验与记账，不消费 `02_forwards`。
2. `evaluate` 期望 `--evidence-dir` 下存在平铺 `{rid}.baseline.jsonl` / `{rid}.candidate.jsonl`
   （177–178 行），而当前真实 run 的 forward evidence 是
   `02_behavior/forward/evidence/*.json`（research_v7 `run_behavior_suite` 产出，含
   `attempt/decoder_outputs`）。**v2 evaluate 与真实 evidence 格式不兼容**，无法端到端消费。
3. `evaluate_formal.py:121-124` 确实硬编码读 `02_behavior/REQUESTS.jsonl`、
   `02_behavior/CASES.jsonl`、`02_behavior/forward/RUN_MANIFEST.json` —— 与 review 所述一致。

### 整改口径（接受，但需写明边界）

- 接受 review 第 2–4 点：`execute` 需真正接 research_v7 real-executor（或提供 adapter），
  `evaluate`/`report` 需消费 v2 目录布局，empty/exhausted 也必须出报告。
- 但对 "无 execute/evaluate/report 入口"的表述予以纠正：**骨架已存在**，缺口是
  evidence 格式 adapter 与 real-executor 接线，而非命令缺失。
- 补充 review 未列的一个事实：`p1-pool/p1-refill` 产出 `01_requests/P1_SELECTED_REGIONS.jsonl`
  （region 级），而 `execute` 读 `01_requests/REQUESTS.jsonl`（request 级）——两者之间还缺
  region→request 的 v2 builder 转换，这条才真正导致 p1-pool 结果进不了 formal evidence。

---

## P0-2 — detector-only confirmation pool 可抽到重复/非法 case

### 判定：完全成立，无抗辩

- `materialize_no_gt_confirmation_pool.py` 的 `choose()`（16–37 行）：只按 `song_id` 分组 + per-song
  cap + seed shuffle，**无** (song, canonical ID) 去重、**无**同 song time overlap 排除、
  **无** `baseline_available=false` 过滤 —— 与 review 完全一致。
- case 构造（79–89 行）把整窗 `old_units` 写入 —— 与 review 一致。
- 06 文档 read-only audit 证实：40 windows、8,694 rows、1,091 个 invalid baseline —— 与 review 一致。

### 整改口径（接受，不加限定）

接受 review 全部 4 点：唯一 primary sampler 或严格复用 `balanced_replenishment()` 的
(song, canonical ID) 与 strict-time-overlap 规则；仅 `baseline_available=true` 入 eligible；
case 必须显式写 `active_target_unit_ids/fixed_context_unit_ids/outside_unit_ids` 与 local context
boundary；补 overlap/同 target 跨 window/invalid interval 回归测试。

---

## P0-3 — OpenCode classification 忽略 context/extra harm

### 抗辩：v2 正式路径已合规，违规的是 post-hoc 旧 run 脚本

review 称 "`aggregate_classification.py` 先取 target rows，fixed-context missing/drift 与 extra
prediction 不会进入 region/candidate harmful、mixed、catastrophic 判定"。

- 对 `aggregate_classification.py` 本身：**属实**。`aggregate()`（90–116 行）确实
  `target_rows = [r for r in rows if r.get("role") == "target"] or rows`，只用 target 行分类；
  它也是独立 policy，未调 `unit_outcome`。
- 但 review 要求的修复对象在 **v2 路径已经完成**：`run_unit_realign.py evaluate`（189 行）调用
  `unit_outcome.aggregate_region_outcome()`，而该函数（`unit_outcome.py:159-181`）的 relevant
  集合含 `target/context/extra`（161 行），`harmed` 含 `degraded_finite/covered_to_missing/extra/invalid`
  （169 行），catastrophic 检查覆盖 target covered-to-missing 与 >1s（165–167 行）——符合 04 Batch4
  契约（beneficial/harmful/catastrophic_harmful/mixed）。
- 因而问题收窄为：`aggregate_classification.py` 是 **旧 run（02_behavior evidence）专用的 post-hoc
  补算脚本**，它没走 v2 聚合，造成"两套 classification policy"的口径分叉。

### 整改口径（部分接受）

- 接受：旧 run 补算不得持有独立 policy，应复用 `unit_outcome` 聚合；或在旧 run 侧先经
  `run_unit_realign.py evaluate` 生成 `REGION_OUTCOMES.jsonl` 再聚合。
- 澄清：新建 run 走 v2 `evaluate` 即合规，无需重复整改；本项应加回归：target improved + context
  degraded ⇒ mixed、target improved + extra ⇒ mixed/harmful、target covered-to-missing ⇒
  catastrophic_harmful（review 第 3 点）。

---

## P1-4 — FINAL_REPORT 仍引用旧 schema，empty metrics 会崩溃

### 判定：完全成立

- `report_final.py` 确实读 `02_behavior/SAMPLE_ACCOUNTING.json`（106 行）与
  `06_evaluator_only/EVALUATOR_ONLY_SUMMARY.json`（129 行）——非 v2 布局，与 review 一致。
- **crash bug 属实**：`_num(None)` 返回字符串 `"n/a"`（26–27 行），而第 69–70 行
  `f"- hit_rate {t}ms: {_num(h.get('old')):.4f} ... (delta {_num(h.get('delta_pp')):+.2f}pp)"`
  对返回的字符串做数值格式化 → 无 paired row（denom=0，old/new/delta_pp 均 None）时抛
  `ValueError`。
- 现状未触发是因为三个 run 均有 paired rows；**empty/all-null run 必崩**。

### 整改口径（接受）

接受 review 第 1、2、4 点：改读 v2 布局 + null-safe formatter + empty/exhausted 输出
`NOT_EVALUATED/EXHAUSTED` 报告 + 对应回归测试。第 3 点（family×stratum 分母、target/context 分开、
region/candidate/song-cluster 汇总）属增强项，记为 MINOR 不阻塞。

---

## P1-5 — 未冻结 round-2 gate 不得替代 P1 acceptance

### 判定：完全成立，且修正本 session 自己的错误引用

- 500/300 门槛**只存在于** `audit_round2_gates.py:17-18`（`GATE_ELIGIBLE=500`、`GATE_SELECTED=300`），
  **不是** 05 或 06 冻结文档中的门槛。05 的 P1 门槛是 S1–S4 各 25 valid case；
  06 文档（34 行）只有 resolved P0 与 read-only audit，无 500/300。
- **承认本 session 错误**：`07_RUN_ARTIFACT_LAYOUT_DEVIATION.md:83` 写 "round-2 gate 门槛（06 契约）：
  formal eligible 40/500、selected 25/300" —— 把 audit 脚本自造阈值误引为 06 契约，需修正为
  "audit 脚本自定 exploratory 阈值，非冻结门槛"。
- `report_final.py` 把 `ROUND2_GATE_AUDIT.json` 列为"数据侧 P1 审计产物"（196 行）——用途标注
  不严谨，与 review 一致。

### 整改口径（接受）

接受：`audit_round2_gates.py` 输出标 `exploratory_only=true`，不得被 FINAL_REPORT 的
formal pass/fail 或 writeback 讨论消费；P1 completion 只按 v2 resolved config 的
strata/family denominator（S1–S4 各 25 valid）判定。

---

## 需要的整改与遗留

### 必改（P0/P1，接受 review）— 已于 2026-08-13 全部完成并验收

1. P0-1：`execute` 接 research_v7 real-executor 或 adapter；`evaluate`/`report` 消费 v2 布局；
   region→request 转换补上；empty/exhausted 出报告。**已修复**（见 `09_OPENCODE_FIX_ACCEPTANCE.md` §1）。
2. P0-2：confirmation pool sampler 复用 `balanced_replenishment()` 的排除规则 + baseline 过滤 +
   显式 role/context 字段 + 回归测试。**已修复**，且真实 shadow 补算确认
   `ineligible_invalid_baseline_interval=1091`（`CASE_POOL_V2.jsonl`，60 case）。
3. P0-3：旧 run 补算复用 `unit_outcome` 聚合；补 3 条 context/extra 分类回归。**已修复**，两个旧 run
   已补算 `CLASSIFICATION_AGGREGATE_V2.json`（v2 schema，catastrophic_harmful 51/76 不变）。
4. P1-4：`report_final.py` 改 v2 布局 + null-safe formatter + empty 回归。**已修复**。
5. P1-5：`audit_round2_gates.py` 标 `exploratory_only=true`；修正 `07_RUN_ARTIFACT_LAYOUT_DEVIATION.md`
   的 "06 契约"错误引用。**已修复**，formal run 已重跑 `ROUND2_GATE_AUDIT_V2.json`（exploratory_only=true）。

### 无争议 / 已具备

- P0-2 的 8,694/1,091 数据、P1-4 的 crash 行号、evaluate_formal 硬编码路径：均与代码一致，无抗辩。
- v2 `evaluate` 已调用 `unit_outcome` 聚合（P0-3 的修复方向在 v2 路径已落地）。

### 需在后续 run 验证

- 真实 v2 布局 run（`00_population/01_requests/02_forwards/03_unit_outcomes/04_no_gt_features/
  05_analysis/06_test_demo/07_runtime`）能否经新 `execute/evaluate/report` 端到端跑通并出报告。

---

## 第二轮 review（Update 部分：P0-A/B/C、P1-D）抗辩

> 前提：本轮抗辩针对 07 文档 review update 追加的 4 项。核心判断依据是"是否影响
> **本次 session 已交付的实验结论**（三 run 补算 V2 分类、ROUND2_GATE_AUDIT_V2、R-B 归因）"。

### 事实核验（已实测）

1. **三 run 的 UNIT_OUTCOMES 全部由旧 `evaluate_formal.py` 经 `pair_unit_outcomes()` 生成**
   （schema=`unit_realign_outcome_v2`，含 `role` 字段），**不是**新 `run_unit_realign.py evaluate` 生成。
   - formal `UNIT_OUTCOMES.jsonl` 718 行、confirmation 1500 行、heldout 5012 行，全部为
     `target`/`context` 两种 role。
2. **三 run 实测 `extra=0`、`invalid_unpairable=0`**：已核验 formal/confirmation/heldout 的
   UNIT_OUTCOMES 与 REGION_OUTCOMES，`extra` 列全零。
3. **三 run 的 REQUESTS 来自旧 realign_gate pipeline**（`episode_family=realign_gate`、
   `workflow_mode=recovery_e5_proposal`，见 `07_RUN_ARTIFACT_LAYOUT_DEVIATION.md`），
   **不经过**新 `build_region_population`/`_region_to_request`/`p1-pool` 路径。

### P0-A — 真实 population 无法 materialize v2 request

**判定：对已交付三 run 结论无影响；但"新 pipeline 正式完成"不成立，必须修。**

- 抗辩成立部分：三 run 的 REQUESTS/evidence 全部走旧 realign_gate pipeline（run_behavior_suite +
  recovery_e5），**不经**新 population→request 路径，因此本 session 已交付的补算分类/gate audit/归因
  结论不受此 P0 影响。
- 抗辩不成立部分：07 的 disposition 把"新 pipeline 可作为当前 unit-level P1 formal 的执行实现"
  列为验收对象，P0-1 的验收声明（"region→request 转换补上"）只覆盖**合成全字段 region**；
  真实 shadow 的 population 缺 `units`/`identity_context`/`audio_path`，`_region_to_request()` 对
  真实数据 100% 返回 `not_constructible`。**正式 GPU 前必须修复**，否则下一轮 formal 无法执行。

### P0-B — execute 只计划 forward 却误标 completed

**判定：对已交付三 run 结论无影响；但新 execute 是下一轮 formal 执行路径，必须修。**

- 三 run 由 run_behavior_suite 直接产出，**不走**新 `execute`，故已交付结论不受影响。
- 但新 `execute` 把 `ready` 的 region 直接写 `completed_region_ids`，未等真实 forward evidence
  返回。作为下一轮 formal 的 `--resume`/`p1-refill` 会计基础，该状态机会漏跑/误判，必须修正为
  `ready → queued → completed`（completed 仅由真实 evidence 回填）。

### P0-C — evaluate 静默跳过缺 evidence + 单 candidate 聚合

**判定：对已交付三 run 结论无影响；但新 evaluate 是下一轮 formal 评价路径，必须修。**

- 三 run 的 UNIT_OUTCOMES 由旧 `evaluate_formal.py` 生成，**不经**新 `evaluate`，故已交付结论不受影响。
- 但新 `evaluate` 缺 evidence 时 `continue`（静默跳过，不写 `NOT_EVALUATED`），且把所有 region
  outcomes 混成单个 `CANDIDATE_OUTCOMES.json`，无法按 (song_id, request_identity) 分组比较。
  下一轮 formal 的评价正确性依赖它，必须修。

### P1-D — fixed context 与 extra 的 denominator 被合并

**判定：抗辩成立，实测零影响，记 MINOR 不阻塞。**

- 三 run 实测 `extra=0`，因此 `n_context = len(relevant) - len(target)` 恰好等于纯 fixed-context
  数，**已补算的 `CLASSIFICATION_AGGREGATE_V2` 无任何偏差**。
- 且旧 `evaluate_formal.py` 的 `pair_unit_outcomes()` 是 per-target 配对（无候选合并问题），
  P1-D 描述的新 `aggregate_region_outcome()` 候选合并行为在三 run 数据上从未触发。
- 建议：保持 `n_context` 语义但拆出 `n_extra` 单独记账（未来出现 extra 预测时才生效），记 MINOR backlog。

### 结论一览

| 项 | 影响已交付三 run 结论 | 影响新 pipeline 正式完成 | 处置 |
|----|----------------------|--------------------------|------|
| P0-A | 无 | 是（下轮 formal 无法执行） | **必须修** |
| P0-B | 无 | 是（resume/refill 会计错误） | **必须修** |
| P0-C | 无 | 是（下轮评价口径错误） | **必须修** |
| P1-D | 无（实测 extra=0） | 无（仅未来 extra 场景） | MINOR 不阻塞 |

**总体抗辩立场**：三 run 已交付的实验结论（V2 补算分类、ROUND2_GATE_AUDIT_V2、R-B 归因）全部
基于旧 pipeline evidence，不受 P0-A/B/C/P1-D 影响，**无需推翻**；但新 pipeline 作为下一轮 formal
执行实现的"正式完成度"确实不足，P0-A/B/C 属"未正式完成导致证明力不足"，**必须在启动 formal GPU 前
修复**。
