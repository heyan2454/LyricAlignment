# WP-C/D：实验执行工作包与资源顺序

**前置：** 08 与 09 全部验收。所有 formal command 先 `--dry-run`，随后 1--2 song/small-GPU smoke；将 runtime projection 写入 `GPU_BUDGET.json` 后才扩容。

## C1. E1/E2 Oracle：先回答模型上限

选择 real-GT 确认的 catastrophic regions，按 song、language、failure family 分层；禁止只取成功样本。O0 exact、O1 +2s、O2 +5s、O3 +10s 均只将 audio/text request 交给模型，GT timestamp 不入模型。

E2 先分别扫 audio/text 单轴容错，再根据趋势选至多 2--3 个组合。每个候选均指定 target ownership；context 输出不得被默认为可写回。若某 family exact oracle 仍低，记录 intrinsic-limit negative result，停止为其扩大 proposal/retry 矩阵。

## C2. E3/E4 Episodes：建立真实闭环分母

E3 运行冻结 baseline、只记录 detector shadow，从真实轨迹离线发现 first catastrophic commit 和 1/2/3/5-window continuation。

E4 的 P1--P5 只在源窗口注入一次；下一窗口起完全由受污染 serial state 自然生成 request。每次注入输出 `attempted`、`no_effect` 或 `effective_propagation`，后者才可进入 recovery 主分母。每 family 目标 64 effective episodes；资源不足标 `bounded_insufficient`，不得把 no-effect 作为成功。

## D1. E5/E6 Proposal 与共享 candidate bank

先实现和比较 R-A unsafe-old-range、R-B safe-anchor bounded、R-C bad-window subdivision。GT 只在 proposal 执行结束后评 coverage/missing/excess/occurrence。将 E1/E2 与 E5 的 forward 写入同一 candidate bank；典型 10--20 candidates/有效 episode，不以正常窗口做笛卡尔积。

达到 GPU 预算时，优先顺序为 E1 -> E3/E4 -> E5/E6 -> E7 -> E9 -> E10。每批更新预测耗时、实测耗时、cache hit、剩余 reserve；12h 后不再发起 forward。

## D2. E7/E8：quality 与写回必须离线配对

GT evaluator 先定义 old/new 的 `better|similar|worse` 与 oracle best；decision path 仅读 Raw signals。报告 pairwise preference、best-of-K top-1/top-2、regret、successful repair accept、harmful repair accepted、all-bad reject。

在同一 candidate outputs 上对比 full、unsafe-only、unsafe ± margin 和 detector-improved contiguous region。主风险指标为 harmful writeback episode rate；若较好候选常被错接受/拒绝，保持保守 reject，不以追求 repair recall 直接写回。

## D3. E9/E10：最终 closed loop

成对运行 C0、C0S、C1、C2、C3；C4 只处理 C3 fail/uncertain，最多 1--2 次预注册 shrink/alternate-anchor retry。realign 后至少继续 1/2/3 window，自然长歌尽可能到 song end。对每 route 报当前修复、safe damage、unsafe 累积时间/units、恢复类型、song-level outcome 和 cost。

若 C1 已得到大部分收益或 C3 harmful rate 不合格，结论应如实为 hold/restart 更安全；不得为了 C3 正结果继续调阈值。所有 threshold/ranking/writeback sweep 都基于缓存。
