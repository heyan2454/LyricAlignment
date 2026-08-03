# 阶段 A 修复报告 —— E1/E5/E6 事件与配对重算 + 条件分母审计

**计划版本：research_v7_align_behavior（阶段 A）· 日期：2026-08-03**
**输入**：v8 formal `alignment_research_v6_formal_20260731_e9_lazy_compact_v8_inputcache_e9scope_aggregatefix`（21562 item）
**性质**：纯 CPU 重算，无模型推理；结果写入 v7 目录与下方报告。

运行脚本见 `scripts/research_v7/`；完整 JSON 输出见
`runs/research_v7_align_behavior/stageA/` 与 supplementary evidence root。

---

## A1. E1 event 指标修复（按 item 分组重算）

- 方法：把 v8 formal 各 `E1_detector.json` 的 `active_event_threshold_curve`
  （阈值=active_risk_threshold 对应条目的 predicted/reference spans）按 item 分组，
  item 内合并连续 event（predicted gap=1、reference gap=0），one-to-one matching。
- 数据源（重要）：`item_summary.json` 因 v8 `--compact-artifacts` 被精简、不含 gt 字段；
  改用 manifest `active_manifest.jsonl` 构建 item→gt/dataset/source_song 索引。
- 结果（21562 item，gt=21527；demo 无 GT 剔除）：

| 指标 | 值 |
|---|---|
| micro precision / recall / F1 | 0.083 / 0.279 / **0.128** |
| item macro F1 | **0.080** |
| source-song bootstrap median (200×) | 0.080（p5–p95 见 json） |

- 结论：E1 旧 detector 的事件级能力极弱（F1≈0.08–0.13），属可信负结论；与 v6 已判定的
  "E1 unit 旧 detector 极弱"一致，且修复了此前**未按 item 分组**导致的聚合口径错误。

## A2. E5 同子集 paired 重算

- 同一 set 内 fixed baseline vs dynamic exact（−0）/−2/−4，按 item 算 MAE delta。
- 结果（807 applicable item，1614 个 variant pair；仅 gt 项算 MAE）：

| 项 | 值 |
|---|---|
| mean delta MAE | **−0.001 s**（≈无改善） |
| improve / harm / no_change | 714 / 822 / 78 |

- 结论：E5 dynamic 边界相对 fixed baseline 近乎打平（slight harm），不继续调参数 → 冻结为
  "E5 未带来稳定改善"的负结果归档。

## A3. E6 同子集 paired 重算

- 同一 silence-applicable item 上 baseline vs hard core / cap4 / cap1.5 / cap0.4。
- 结果（21527 applicable item，11988 个 variant pair）：

| 项 | 值 |
|---|---|
| mean delta MAE | **+1.05 s**（明确更差） |
| improve / harm / no_change | 923 / 3268 / 7797 |

- 结论：E6 时间压缩（silence cap）整体使边界 MAE 变差约 1s、harm>>improve → 冻结为
  "E6 时间压缩处理为负结果"，不再扫 cap。

## A4. 条件指标分母审计

- 对 E5–E9 item_summary.phases 的全部条件指标字段输出
  total/applicable/non_null/numerator/rate（见 `audit_conditional_denominators_full.json`）。
- 关键非空样本数（21562 全量）：

| phase.field | applicable | non_null |
|---|---|---|
| E5.applicable（项数） | 842 | 21562 |
| E6.applicable | 3032 | 21562 |
| E7.applicable | 796 | 21562 |
| E8.candidate_propagation_complete_count>0 | 8795 | 21562 |
| …（完整见 json） | | |

- 意义：让"条件均值"都有明确分母与非空样本数；报告不再把条件指标当作全覆盖。
- 小口径说明：`applicable` 为布尔，审计中按 True 计数（`numerator` 即 applicable_true 数）。

---

## A5. 历史状态冻结矩阵

| 阶段 | 状态 | 依据 |
|---|---|---|
| E0 | 可用（场景依赖） | formal 保留 |
| E1 unit | **强负结论**（旧 detector 极弱） | A1 微观/macro F1≈0.08–0.13 |
| E1 event | **修复后报告**（按 item 分组） | 本报告 A1 |
| E2 | 旧 detector 评价退役；扰动工具保留 | v7 用户决定 |
| E3 | 停止 | v7 用户决定（decoe only 不值得） |
| E4-old | 仅作为 oracle/localized upper bound | v7 计划 |
| E5 | **负结果归档，不再调参** | A2（Δ≈0） |
| E6 | **负结果归档，不再扫 cap** | A3（Δ+1.05s） |
| E7 | 保留有限负证据（旧 reset 不完整） | v7 计划 |
| E8 | rerun/continuation 框架保留，自动选优失败 | v7 计划 |
| E9 | 旧实验不能否定有界 request pool，暂停 | v7 计划 |

---

## 完成门槛核对（08_AGENT_HANDOFF §必须优先完成）

- [x] E1 event 修复（A1）
- [x] E5/E6 paired（A2/A3）
- [x] 条件分母（A4）
- [ ] strict serial P1 / sparse-slot S / extra-missing-replace 百分比 / cross-song no-match /
      posterior top-K / official repair trace —— 属阶段 B，另立。
