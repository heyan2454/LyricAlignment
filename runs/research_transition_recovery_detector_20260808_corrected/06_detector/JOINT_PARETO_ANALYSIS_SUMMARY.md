# Joint (SA60+R95) Pareto 分析结论 — model_selection

## 结论：joint 不可行是分布性质，不是阈值网格分辨率问题
- 全网格 20301 对 (t_accept, t_reject)（候选阈值 20301 个，
  来自唯一 p_bad 值 200 分位抽样 + 0/1 边界）中，同时满足 safe_accept>=0.60 且 unsafe_reject>=0.95 的点数为 **0**。
- Pareto 前沿为平滑单调曲线（200 个非支配点），两端与 FROZEN_WORKING_POINTS.json 的 joint pareto_gap 完全一致：
  max_safe_accept≈0.9988 时 unsafe_reject≈0.0012；max_unsafe_reject=1.0 时 safe_accept=0.0。
- 关键天花板（前沿点）：safe_accept>=0.60 时 unsafe_reject 最高仅 ≈0.5359
  （ta=0.4545, tr=0.4556）；
  unsafe_reject>=0.95 时 safe_accept 最高仅 ≈0.0723（ta=0.3873, tr=0.3883）。
  与目标区域 (SA>=0.6, UR>=0.95) 相距极远，任何阈值细化都无法闭合该 gap。

## 分布性质证据（p_bad 在 safe/unsafe 组几乎完全重叠）
- KS D=0.1489（p≈0，
  有统计差异但效应量极小），支持域完全重叠：safe [0.331,0.927] vs unsafe [0.332,1.000]。
- 十分位数：safe [0.3924, 0.4057, 0.4143, 0.4237, 0.4366, 0.4535, 0.4804, 0.525, 0.6122] vs unsafe [0.3992, 0.4134, 0.4267, 0.4423, 0.4629, 0.498, 0.549, 0.6173, 0.7065]，
  各分位差仅 0.01–0.09；中位差 ≈0.026（safe≈0.437 vs unsafe≈0.463）。
- 即：detector 的 p_bad 对 safe/unsafe 几乎没有区分度，任何单一 (ta,tr) 阈值对都无法同时把
  safe 放进 ACCEPT、unsafe 放进 REJECT —— 不存在联合工作点。

## 独立工作点确认（SA60/SA80/R95 必须分别独立报告）
- FROZEN_WORKING_POINTS.json 中 SA60/SA80/R95 均 feasible=true（独立约束各自可达），joint_sa60_r95 feasible=false，
  本分析复算一致。
- 独立点在抽样网格前沿上的位置：SA60 (SA=0.6036,
  UR=0.5202)；SA80 (SA=0.8050,
  UR=0.3314)；R95 (SA=0.0667,
  UR=0.9527)。
  三者距最近前沿点 <1.6%（SA60/SA80 在前沿内侧、R95 基本贴边），差异来自本分析 200 分位抽样网格
  vs 冻结时全量唯一值候选网格，不改变结论。
- **执行口径**：因 joint 不存在，SA60/SA80/R95 只能作为三个独立工作点分别报告各自指标
  （不允许合成"同时满足"的联合声明），与本分析输出一致。

## 数据
- 输入：EVAL_model_selection.json（n=3374：safe=1674, unsafe=1700）——EVAL_threshold_validation.json 不存在，按要求回退。
- 完整前沿 200 点见本文件 pareto_frontier。
