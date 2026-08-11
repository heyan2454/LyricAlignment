# 当前实验现象与结论（Realign Session 起点）

- 日期：2026-08-12
- 作用：给下一轮 Agent 一个经过纠正的结果起点；避免重新引用已被 synthetic-GT 或 metric bug 污染的旧结论。

## 1. 当前最稳定的总体认识

当前系统不是“所有窗口都普遍低质量”。更符合证据的描述是：

> 多数正常、对应关系明确的窗口可以工作；少数特定歌曲/窗口会发生非常严重的整体错位，而且这些严重错误会集中出现并可能通过串行状态继续传播。

当前已经观察到的重要困难条件包括：

- 重复元音、衬词（如连续“啊”）；
- 重复歌词、相似副歌/occurrence；
- 长窗口内 text/audio pairing 歧义；
- 前窗已经错误导致后续 cursor/request 偏移；
- 某些静音/边界条件。

Realign 主线应优先处理 catastrophic misalignment，而不是把普通几十到几百毫秒的小误差全部当 recovery 对象。

---

## 2. Raw detector 当前成果

`light_merge` 修复前，REJECT 岛可能被平滑规则翻回 ACCEPT。修复后，A retrospective evaluation 的主要结果约为：

### Raw

- protected recall ≈ **0.9567**；
- reject recall ≈ **0.9474**；
- safe accept ≈ **0.8320**；
- unsafe accept = **14 / 323**；
- longest continuous leaked unsafe = **1 unit**。

### Official

- protected recall ≈ **0.9628**；
- reject recall ≈ **0.9312**；
- safe accept ≈ **0.7303**；
- unsafe accept = **13 / 349**；
- longest continuous leaked unsafe = **1 unit**。

正确解释：

- Raw/Official 都能保护绝大多数严重错误；
- Raw 的保护率略低一点，但 safe accept 明显更高，平衡更适合作为本轮闭环主线；
- 这些是 **retrospective_after_light_merge_fix**，不是新的 untouched formal test；
- threshold 来源于修复前冻结流程，A 后续也已被探索使用，因此不得包装成全新 formal generalization。

本轮决定：**Raw 为主；Official 仅低成本 shadow/reference，不扩矩阵。**

---

## 3. Raw 严重错误通常会暴露自身异常

困难区域已经观察到：

- timestamp pile-up；
- 多 unit 得到同一/近似时间；
- 时间倒序与大跨度跳跃；
- entropy 上升；
- top-1/top-2 margin 下降；
- Raw 时间序列结构异常。

已有探索示例中，重复困难簇的平均 entropy 约 6.09，普通单独 unit 约 3.45；困难簇 margin 约 0.008，普通区域约 0.240。

这些数字不是新的正式产品指标，但支持一个重要机制判断：

> catastrophic alignment failure 往往不是“模型悄悄地错但内部完全正常”，而是 Raw 输出本身也出现明显异常，因此 no-GT detector/quality gate 有可利用信号。

---

## 4. 错误高度集中，而非均匀分布

A Raw unsafe 中，已有统计包括：

- 《绒花》：199；
- 《月满西楼》：52；
- 《孤勇者》：36；
- 《春天里》：32；
- 《老男孩2》：4；
- A Raw total unsafe = 323。

A+B 合并后，Raw unsafe 的很大比例集中在少数歌曲；当前 quick-correction2 的展示仍有“song×family top-k 未完全聚合到 song”小问题，本 session 记录为延期修复，不影响“错误集中”这一方向性观察。

研究意义：

> 下一轮应大量采集自然 bad windows / error episodes，并按 failure family 与 song 分层，而不是只看 pooled unit average。

---

## 5. Window-level detector 有很强的排序能力

后续 metric 审计确认：window-gate 中使用的 `hit100` 来自正式 real-GT reaggregate：

```text
abs(start_error) <= 100 ms
AND
abs(end_error) <= 100 ms
```

不是 start-only 1 s。

探索中 `frac(p_bad > T_accept)` 的 bad/good window AUROC 约 **0.9831**。

曾探索 threshold 0.45：15/15 bad 被抓到，75 个 good 中 9 个误报；但该阈值是看过 A 后探索得到，必须继续标记：

```text
exploratory_test_tuned_threshold = true
formal_threshold = false
```

这支持 detector 作为 realign trigger/ranking signal，但不允许把 0.45 直接写入生产配置。

---

## 6. 短窗 / 重新配对能缓解 collapse，但旧 semantic accuracy 不能作为 real-GT 结论

自由探索中已经看到：

> 把长窗中重复元音/困难区域拆短，timestamp pile-up、窗口起点吸附、乱序等现象明显缓解。

这说明 window length / request pairing 很可能是 catastrophic failure 的重要因果因素之一。

但旧 `eval_rule_subwindow.py` / `eval_subwindow.py`：

- correctness reference 使用 `LONG_TIMELINE_MANIFEST.canonical_units` 的 synthetic-uniform timing；
- legacy `hit100` 实际是 start-only <=1 s，应叫 `start_hit_1s`。

因此当前只能保留：

> **短窗可缓解 collapse 的机制证据。**

不能保留：

> “automatic semantic planner 已经在 real GT 上把准确率提高到 0.53/0.57”。

下一轮 Realign 将用真正 real GT 重新回答“短窗能修多少”。

---

## 7. 旧 recovery 14–16% 不是 real-GT 能力上限

旧 Phase 4.3 报告过：

- O0 ≈13.94%；
- O1 ≈15.86%；
- O2 ≈15.86%。

后续审计确认 `run_oracle_recovery.py` 的 correctness GT 来自 synthetic-uniform timeline，且部分 oracle 路线直接用 GT 决定 head/query/range。

因此这些数字只能标记为：

```text
historical synthetic-GT oracle diagnostic
```

不能继续写：

> real-GT oracle recovery 上限约 16%。

当前真实状态是：

> **我们还不知道模型在“正确 audio/text request 下”的真实 repairability，也不知道 no-GT closed-loop 能修多少。**

这正是下一轮要回答的问题。

---

## 8. Enhanced detector feature 的旧 negative result 暂不关闭方向

R+repair / R+crossview / R+neigh / R+all 等旧负结果发生在 `light_merge` bug 存在时，当前状态应为：

```text
unresolved_after_bugfix
```

但用户已经决定下一阶段主要研究 realign，因此本 session **不主动重新展开 detector feature search**。只有当 realign quality gate 明确成为瓶颈，且现有 Raw detector 无法满足关键闭环要求时，才允许在自由探索中有针对性复查。

---

## 9. 本轮起点结论

下一阶段最稳的研究故事是：

> 严重歌词对齐错误主要集中于少数困难窗口；Raw 输出通常会暴露明显异常，因此无 GT 检测已经具备较强保护能力。现在最大的未知不再是“能不能发现错误”，而是“发现以后能不能重新构造更正确的 audio/text request，把错误真正修回来，并且在无 GT 条件下判断新结果是否值得写回”。
