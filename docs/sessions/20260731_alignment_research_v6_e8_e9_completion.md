# 2026-07-31 Alignment Research v6 E8/E9 二次实现完成

## 背景

对 correctness-fixed 包进行实现级 review 后发现：E5 的风险门控未贯通 planner；E8 downstream 实际是静态 splice，指标必然为零；E9 只是对 baseline 历史 attempts 排名；极端候选可能使汇总崩溃；E4 完整 96-unit 口径和参数冻结不完整。

用户决定：E8、E9 正式实现；resume/cache 强身份暂不处理；pilot 即使效力降低也应尽量生成最终结果；其余问题全部修复。

## 最终实现

- E5 planner 改用 `safe_boundary_decision_score`，并将冻结 `dynamic_safe_score` 贯通 Detector 列表、规划与 formal 指标。
- E8 将局部候选写入 committed prefix，从 target 所在 baseline window 重跑同窗尾部和全部下游窗口；保存 candidate-specific continuation trace 和 downstream causal metrics。
- E9 实现模型支持的跨窗 beam。每条路径保存 rows/cursor/input/previous state；nominal、backtrack、wider-text 分支逐窗前向；无推进淘汰；不使用 GT 剪枝；全失败显式 fallback。
- E9 剪枝加入当前进度缺口，并按 feature 数计算累计平均风险，避免低风险但停滞路径获胜。
- E4 只纳入完整 96-unit group。
- metrics 对全无效候选返回 null，不再崩溃。
- freeze 改为 best-effort 三档效力，部分失败或小样本不硬阻断 formal；分别冻结 risk/repairable/safe-boundary 阈值和 decoder，并记录 warning。
- Resume/cache 按用户决定保持现状；语义变化后必须使用新 OUT_ROOT。

## 验证

```text
research_v6 targeted tests: 23 passed
all collectable tests excluding 3 missing-pypinyin modules: 261 passed
compileall: passed
research shell bash -n: passed
```

真实 GPU smoke 尚未执行，不声称 E8/E9 的真实效果或耗时。

## Negative results / 纠正

上一版文档中“E8 downstream checks”和“E9 actual beam coverage”的表述过强：前者没有重推下游，后者没有跨窗保留模型状态。本轮已更正代码、schema 和文档，不沿用旧结论。

## 下一步

1. 服务器安装完整依赖；
2. 使用新 OUT_ROOT 运行单 Demo smoke；
3. 检查 E8 continuation trace、downstream delta、E9 survivor/path/fallback；
4. pilot 即使部分失败也会 best-effort freeze；
5. formal 继续运行，并在报告中依据 freeze effectiveness 降低结论强度。
