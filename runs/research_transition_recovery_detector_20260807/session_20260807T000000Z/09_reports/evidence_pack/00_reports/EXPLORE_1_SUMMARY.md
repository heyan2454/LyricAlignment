# Explore 1 Summary：GT 质量 / 偏移校正 / 容差敏感性

日期：2026-08-08（Phase 9 后自由探索，纯 CPU 重分析）

## 1. M4 GT 质量审计（EXPLORE_GT_AUDIT.json）

- model_selection 9 首 GT 的 mapping_status：**334 行全部 `review_required_*`（无 accepted_rule_based）**
  —— 长歌 timeline 由 m4singer_meta_v1 的 auto phoneme grouping 重建，全部是"需人工复核"的自动分组产物。
- 结论：**M4 长歌 GT 不是人工 GT**，`rule_validated` 语义在本数据上不成立；GT 边界质量未经人工确认，
  是 M4 38-55% vs MIR 100% 差异的重要贡献因素（与模型能力、长歌上下文并存，不能单因归因）。

## 2. 系统性偏移校正（EXPLORE_BIAS_CORRECTION.json）

- pooled median bias = **-0.30 s**（raw 预测系统性偏早）。
- 全局中位数校正：0.388 → **0.359（更差）**；per-song self 校正：0.359。
- 结论：**偏移校正是负收益**——偏差并非全局常数，中位数校正只平移分布，把原正确的行推错；
  校正类产品改进不可行，需逐行/逐段级信号（detector 方向）。

## 3. 容差敏感性（EXPLORE_TOLERANCE.json）

- T2 committed 行正确率随容差：0.1s→14.7%、0.2s→29.8%、0.32s→46.8%、0.5s→66.0%、0.75s→81.1%、1.0s→88.2%。
- 结论：**0.32 s 恰好卡在分布上升段中部**，正式结论（策略排序）对容差敏感；
  1.0 s 容差下模型能力显著更好（88%），产品端应评估业务可接受的容差水平。

## 产品建议（探索性）

1. M4 GT 需人工复核/重标注后再作正式基准（当前结论标注 `rule_validated` 不可靠）。
2. 容差 0.32s 偏严；若业务允许 0.5s，full-song 路线可用性显著提升。
3. 偏移校正不可行；detector 逐行信号（训练 AUC 0.84）是唯一已证实的风险识别路径，
   但其 closed-loop 收益受模型固有偏差限制（重跑无效）。
