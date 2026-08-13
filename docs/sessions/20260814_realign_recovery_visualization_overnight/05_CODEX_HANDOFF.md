# Codex Handoff：先制定实现方案，再交 OpenCode/agent 执行

你正在 `/home/hyan/LyricAlignment` 上继续 `20260813_unit_level_realign_overnight` 后的研究。不要直接开始大规模 GPU run。先阅读本 session `00`–`04`，再检查当前代码/产物，生成一份**可执行实现方案**。

## 1. 必须先核实的事实

1. Current baseline 的 exact resolved config / transition / slot / commit semantics；
2. B4 historical pre-slot runner 是否仍能真实复现，还是需要 adapter/compat runner；
3. 最新 unit-realign R-U/R-S artifacts 的 schema 与 old inline-realign visualizer 的差异；
4. 是否已有 reusable ComparisonTrack/timeline projection，可最小改动实现双路/四路；
5. 当前 shared cache identity 是否能表达 parent iteration、recrop、split；
6. context k1/k3 manifests 是否仍和当前 request schema/identity 兼容；
7. genuine R-B/anchor provenance 当前在哪些 runner 中成立；
8. raw/official/hidden/posterior/entropy/margin 哪些信号现在实际可导出，哪些只存在文档设想；
9. Test Demo 当前 33 success / 3 failure 的失败原因与可 resume 状态；
10. 预计 GPU forward 成本，如何在 10h target /12h hard cap 内安排 screening + expansion。

事实未知时写“未知/需核实”，不要用文档猜测代替代码现状。

## 2. 实现方案必须覆盖

### A. Scientific runner

- E1 multi-iteration direct/re-crop/perturb chain；
- E2 fine-grained split + limited directionality；
- E3 k1/k3 closure + audio recrop/multi-scale；
- E4 R-U proposal -> sparse/fixed refinement；
- E5 no-GT signal wire-up（只接实际可得信号）；
- E6 atlas / hard-case mining；
- E7 serial accumulated-error stress；
- resume/cache/identity/GT firewall。

### B. Visualization

- B4 vs Current 双路；
- Current baseline/R-U/R-S/combo 四路；
- collection-before-visualization；
- 3840×1080、30s page、原曲音轨、两行 KTV、真实播放线；
- zero-duration aggregation；
- cache-only rerender + scientific hash assertion；
- Side by Side smoke -> multilingual/hard-case batch。

## 3. 方案组织要求

请输出到本 session，例如：

```text
docs/sessions/20260814_realign_recovery_visualization_overnight/07_CODEX_IMPLEMENTATION_PLAN.md
```

至少包含：

- code change map（具体文件/新模块）；
- dataflow/schema；
- run roots；
- exact commands；
- tests；
- smoke gates；
- phase order；
- GPU budget projection；
- resume/failure recovery；
- known unknowns；
- 不会做的笛卡尔积；
- 交给 OpenCode 的分批 work packages。

## 4. 强制原则

- 不把上一轮“平均误差下降”直接写成 precise recovery 成功；
- 不把 consensus/fixed-point/context displacement 当 correctness；
- 不把旧 R-B adapter 当 genuine R-B；
- 不使用 GT 选择 no-GT candidate；
- 不允许可视化触发重复科学 forward；
- 不允许因为一条路线 negative 就结束整个挂机 session；
- sample 不足必须先主动扩大，而不是直接跳过；
- `actual_writeback=0`。

Codex 的任务是**先把实现方案做正确、做完整**；OpenCode/agent 负责具体实现与实验执行。
