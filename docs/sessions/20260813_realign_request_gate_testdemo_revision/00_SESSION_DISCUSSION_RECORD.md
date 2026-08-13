# 会话记录：Detector / Realign Gate review 后修订

日期：2026-08-13

## 1. 背景

上一轮目标是重新核实 detector 的生产行为，并研究 realign 自身行为是否能形成 no-GT writeback gate。此前发现旧 run 的 production audit 被 E5 proposal bank 污染，随后要求 P0/P1 重构：恢复唯一 production raw baseline，重新建立 GT strata，再执行 R-A/R-B 与 gate 分析。

本轮收到并 review 的 evidence：`detector_realign_gate_evidence.tar.gz`。

## 2. Review 中确认的结果

### 2.1 P0 production detector baseline 已基本修正

新的正式 baseline population：

- 13 首 real-GT song；
- 40 个唯一 production baseline windows；
- 4093 个有效 detector units；
- unit ACCEPT = 85.07%；
- UNCERTAIN = 0.54%；
- REJECT = 14.39%。

历史 frozen validation：safe accept = 86.89%，protected recall = 65.52%，n=761；retrospective 83.2% / 95.67% 未找回原始 artifact，保持 `not_reproduced_source_missing`。

旧的 15.5% ACCEPT / 84.4% REJECT 已能明确归因为 E5 多变体 proposal population contamination 加跨 variant 的保守合并，不代表 production detector 退化。

### 2.2 97.5% whole-window unsafe 不代表 detector 几乎全错

40 个真实 production windows 中 39 个至少含一个 REJECT unit，因此在 `any reject -> whole window unsafe` 契约下，window unsafe rate = 97.5%。

这与 unit-level 85% ACCEPT 并不矛盾。用户明确反馈：

> “97.5%窗口报警这个数据没有太大实际意义。”

用户认为后续应更接近 detector 原本的接口：关注 unsafe subinterval / unit region，而不是把整 60s window 是否包含任何 reject 作为主要研究指标。

### 2.3 当前 P1 hard negative 数不足是分层设计问题，不是数据真的没有

当前 window-level CASES 只有约 S1=1、S2=2、S3=22。review 发现，已有执行数据里 GT <=200ms 的正确 units 约 2197 个，其中约 522 个 detector 并非 ACCEPT（约 227 UNCERTAIN + 295 REJECT）。

所以 “GT correct + detector bad” hard negative 实际上大量存在，只是整窗必须全部 correct 的 strata 使它们无法进入 S2。

因此应改成 interval/unit-region 级 hard negative sampling，而不是接受 “S2 只有 2 个，所以样本不足”。

用户明确反馈：

> “没有足够样本之类的问题，不应该直接放过，要要求agent发挥自己的能力去修正。”

### 2.4 R-A 实际执行了；当前 R-B 是 null/no-op

表面上有 23 个 R-A + 23 个 R-B，但检查发现 23/23 R-B：

- left anchor = null；
- right anchor = null；
- audio range 与 production baseline 相同；
- text range 与 production baseline 相同；
- 2442 个 paired units 的 GT delta 全部严格为 0。

因此当前 R-B 只能当 deterministic null re-run，不能当作第二种 realign intervention，也不能用它来美化 gate negatives。

用户反馈：

> “在上面的更换realign请求的基础上，测试RARB实际效果，并且真实地运行RB。”

### 2.5 Realign request 本身需要重新研究

用户反馈：

> “我觉得可以要求它尝试多种realign的请求方式，或者是切出更接近unit级别的realign请求。”

因此下一轮不应继续固定当前整窗/粗 request。应把 realign request family 本身作为研究对象，但避免大笛卡尔积：只保留少数具有明确机制差异、且能实际改变 forward 输入的局部 request family。

### 2.6 `n_big` 不能视为 gate 已经成功

当前报告的 holdout `AUROC(n_big)=0.934` 受到两类问题影响：

1. 大量 R-B 是 `n_big=0, harm=0` 的 no-op easy negatives；
2. feature 被复制到 unit rows 后统计，独立 candidate 数远小于行数。

仅看真正 active 的 R-A，`n_big` 更像“改动幅度”而非“改动方向”：大的 n_big 同时出现在大幅改善和大幅恶化中。

用户反馈：

> “n big看起来不够好，还有什么其他信号比较好吗？没有的话继续要求尝试其他信号。”

所以 n_big 应降级成 diagnostic，agent 要继续主动探索其他 no-GT realign behavior signals；初始信号弱不能直接停止。

### 2.7 Test Demo 仍未真正进入实验

inventory 已动态发现 36 个 Test Demo 文件/条目，但当前 `04_test_demo` 是 mock adapter。mock 结果不能用于 detector 或 realign 的真实行为结论。

用户反馈：

> “好像还是没有看到test demo数据”

因此下一轮必须真实运行 Test Demo：全量真实 detector audit，及经过控制的小规模真实 realign behavior/stress sampling，并输出用户能直接看到的 per-item/per-language 结果。

## 3. 用户本轮最终要求（忠实记录）

用户原话：

> 1. 我觉得可以要求它尝试多种realign的请求方式，或者是切出更接近unit级别的realign请求。，97.5%窗口报警这个数据没有太大实际意义。
> 2. 在上面的更换realign请求的基础上，测试RARB实际效果，并且真实地运行RB。
> 3. n big看起来不够好，还有什么其他信号比较好吗？没有的话继续要求尝试其他信号。
> 4. 好像还是没有看到test demo数据
> 5. 没有足够样本之类的问题，不应该直接放过，要要求agent发挥自己的能力去修正。
>
> 给出提供给codex的patch，codex拟定实现方案后我会交给agent实现、。

## 4. 最终决定

下一轮冻结为：

- P0 不重新做无意义的 whole-window trigger 优化；保留 production unit/interval detector baseline，并补 GT-conditioned detector 指标。
- P1 改成 detector unsafe interval / contiguous unit-region 级 sampling，主动获得足够的 S2 hard negatives。
- P2 研究少数真实局部 realign request families；R-A/R-B 必须是真 intervention，增加更接近 unit 级的 R-U。
- P3 以 candidate 为独立样本继续探索 no-GT behavior gate，不把 `n_big` 当默认 gate。
- P4 Test Demo 使用真实模型跑全量 detector，并做小规模真实 realign stress。
- 任何“样本不足/无法构造”必须触发自动补样本或请求重构，不允许直接作为终点。
