# 上一轮 Realign/Recovery 实验结论与审计修正

- 日期：2026-08-12
- 来源：当前 repo/session 文档 + `realign_recovery_evidence_20260812_20260811T202813Z.zip` + 自由探索 FE-01～FE-17。
- 目标：给下一轮一个不会继续传播旧 metric/语义误读的研究起点。

---

## 0. 上一轮关键量化结果快照

以下数字用于保留 evidence 语境；解释必须服从后文的 metric/语义修正。

### 0.1 Real-GT oracle（cohort A+B 合并离线汇总）

| Request | Units | residual <=1s | <=5s | <=10s |
|---|---:|---:|---:|---:|
| O0 exact/local | 202 | 59.9% | 82.7% | 88.1% |
| O1 +2s context | 202 | 45.5% | 85.6% | 88.6% |
| O2 +5s context | 203 | 20.7% | 58.6% | 88.7% |
| O3 +10s context | 209 | 7.7% | 12.0% | 53.1% |

这些数字只说明 catastrophic residual 的变化趋势，不能称为产品可用 repair rate。尤其 `<=1s` 仍太粗；下一轮必须补 100/200/500ms。

Cohort 差异明显：例如 O0 `<=1s` 在 A 约 41.1%，B 约 89.7%，说明 repairability 强烈依赖 song/failure family，不能只报 pooled 数字。

当前 5+5 主要 real-GT song cohort 为：

- A：孤勇者、春天里、月满西楼、绒花、老男孩2；
- B：全世界失眠、已是两条路上的人、我爱你中国、真实、阴天快乐。

这正是下一轮需要扩大 source-song pool、但控制 realign case 总量的原因。

### 0.2 Natural 30-window R-B 对比

- Original：3086 units，coverage≈98.83%，covered-unit MAE≈0.5765s，>=1s units=117；
- R-B：coverage≈98.15%，covered-unit MAE≈0.6201s，>=1s units=140；
- 约 2/30 明显改善、15/30 明显恶化、13/30 近中性；
- total absolute error 相对 original 增加约 134.6s。

因此当前 R-B 不能被描述为“已有正收益，只差 gate”。

### 0.3 E7 quality/ranking

上一轮主要汇总约为：

- pairwise quality AUROC≈0.578；
- catastrophic subset AUROC≈0.683；
- pairwise accuracy≈0.712；
- Q2 top-1≈43.3%，top-2≈76.7%；
- episode-level TPR=0；
- unit-level TPR≈43.5%，FPR≈4.1%。

说明存在一定 quality signal，但不足以支持当前自动 writeback。

### 0.4 Shadow C3 / natural writeback real-GT spot check

C3 的 action-derived `7/111` 不能解释为真实 closed-loop repair。对其中 natural writeback 做 real-GT 回看时出现：

- 月满西楼:w0：近似中性；
- 绒花:w2：约 +25.36s，严重恶化；
- 老男孩2:w1：约 -0.61s，小改善。

另有 synthetic writeback 涉及 text semantic drift。因此“0 harmful writeback”不成立。

### 0.5 完成度边界

上一轮已完成 oracle/proposal/quality/shadow decision 与较丰富 free exploration；但：

- E2 计划中的系统 audio/text tolerance grid 未完整执行；
- E10 retry/shrink 未形成正式结果；
- E9 不是实际 stateful closed-loop writeback。

## 1. 当前可以成立的结论

### 1.1 旧“real-GT recovery ceiling ≈14–16%”必须废弃

旧 Phase 4.3 的 14–16% 使用 synthetic-uniform correctness GT，不能视为真实 repairability 上限。

新一轮 real-GT oracle 说明：当 audio/text request 更正确、更局部时，aligner 对 catastrophic misalignment 确实存在明显重新对齐能力；因此“模型完全修不动”不是当前最合理解释。

但新 oracle 目前主要汇报 `<=1/2/5/10s` residual threshold，不能据此说已经恢复到产品可用精度。

### 1.2 Realign 当前主要瓶颈更像 request/proposal、quality judgement 与安全 writeback

证据包括：

- exact/narrow oracle 明显优于过宽 context；
- natural R-B proposal 没有整体改善；
- perturbation episode 中存在 text semantic drift；
- after-score 变好并不保证真实 GT 变好；
- large-scale unit changes 往往伴随 harm。

因此下一阶段不应只问“realign 能不能跑”，而应问：

1. 是否对正确的 audio/text region 做 realign；
2. candidate 是否优于 original；
3. 是否只改变该改变的局部；
4. 是否值得 writeback。

### 1.3 当前 R-B 不能作为已验证有效的 recovery baseline

在上一轮 natural 30 windows 上的离线 GT 比较中：

- Original coverage ≈98.83%，covered-unit MAE ≈0.5765s；
- R-B coverage ≈98.15%，covered-unit MAE ≈0.6201s；
- 30 windows 中约 2 明显改善、15 明显恶化、13 近似中性；
- total absolute error 相对 original 增加。

这支持“R-B 当前 proposal 构造不足”，而不是“R-B 已经有效，只差 gate”。

### 1.4 `n_big` 是值得继续验证的 seed signal，但还不是正式 gate

自由探索定义：

```text
n_big = count(|Δp_bad| > 0.05)
```

在上一轮小样本 natural window 中，它与真实 seconds harm/improvement 呈很强的单调关系；`n_big <= 2` 的简单规则能够挡住若干大幅恶化，同时保留少数真实改善。

但：

- 样本只有约 30 natural windows；
- feature 是看过当前样本后探索得到；
- 不能把 exploratory Spearman/threshold 当 untouched generalization。

下一轮必须在更多 song、song-held-out 方式下验证。

---

## 2. 必须纠正的 metric/语义口径

### 2.1 `residual <=1s/5s` 不是“对齐可用”

这里 residual 是真实时间边界误差，不是风险分数。

因此：

- `<=5s` 只适合作为 catastrophic residual 粗分类，不能称为 repair success；
- `<=1s` 对字符级歌词同步仍明显不可用，只能表示从更严重 drift 拉回；
- 下一轮 repairability / harm 主口径必须回到 start/end 100/200/500ms，并保留 >1/2/5/10s catastrophic buckets。

上一轮 oracle evaluator 暴露了 `thresholds_ms=(100,200,500)` 之类接口，但最终汇总并没有真正统计这些阈值；已有 raw evidence 应先尝试离线重算，不能为补 metric 重复 GPU 推理。

### 2.2 `repaired@1s` 不能自动等价于 before→after improvement

如果 evaluator 只判断 after residual 是否落入阈值，那么从 0.3s 恶化到 0.9s 也可能被算进 `<=1s`。

下一轮必须显式同时报告：

- before error；
- after error；
- `Δerror = after - before`；
- threshold transition（例如 <=100ms → >500ms / >1s）。

### 2.3 E8 `net_improved` 不是 seconds improvement

E8 的 `net_improved` 是离散状态/transition 计数，不是总 absolute error 秒数。

已观察到 candidate 可在 E8 离散计数上显示局部正值，同时整窗真实 GT error 增加数十秒。因此：

> E8 的 `+65/+61` 不得再写成“净改善 65/61”或等价的量化恢复收益。

如要评价 strategy recovery，必须使用统一 canonical units 上的 seconds-based before/after metric。

### 2.4 E9 当前不是实际 stateful closed loop

当前 closed-loop decision path 为 shadow policy simulation，`actual_writeback=0`。

它没有执行：

```text
window i proposal
→ write back timeline/state
→ update cursor/committed state
→ forward window i+1 with updated state
→ evaluate whether trajectory recovered
```

因此 C3 中 `repair_success`、`harmful_writeback` 等 action-derived 计数不能直接解释为真实 GT 闭环恢复率/危害率。

上一轮 natural writeback 的真实 GT 回看已经出现：小改善、近中性、严重恶化并存，因此“0 harmful writeback”不能成立。

### 2.5 E4 propagation 主要是 synthetic episode construction

E4 构造了 propagation-style episodes，但没有真正把前窗错误写入 state 后再 forward 后窗观察自然传播。

因此“81 propagated”更应理解为“81 个可构造的传播式 episode”，不能说已经观测到 81 次真实串行传播。

---

## 3. Detector 当前证据如何解释

### 3.1 上一阶段 retrospective-after-light-merge-fix

当前 session 起点文档记录：

#### Raw

- protected recall ≈ **0.9567**；
- reject recall ≈ **0.9474**；
- safe accept ≈ **0.8320**；
- unsafe accept = 14/323；
- longest continuous leaked unsafe = 1 unit。

#### Official

- protected recall ≈ **0.9628**；
- reject recall ≈ **0.9312**；
- safe accept ≈ **0.7303**；
- unsafe accept = 13/349。

正确解释：这些是 retrospective-after-fix，不是新的 untouched formal test；但说明 Raw detector 在当时分布上并不是“几乎全部拒绝”。

### 3.2 为什么上一轮 recovery natural 30 windows 会近乎全触发

上一轮 natural 30 windows 的 window-level核查约为：

- TP 15；
- FP 14；
- FN 0；
- TN 1。

这个集合来自 real-GT/recovery 困难 cohort 和后续筛选，明显存在 selection bias；不能拿它估计 production window 的 overall accept/reject prevalence。

因此下一轮 detector 首要任务不是重新训练，而是：

> **按 production-style 数据流重新统计分布，确认此前 0.83 左右 safe accept 是否能在更自然的窗口 population 中重现。**

### 3.3 threshold 不能用当前 natural 30 直接调

探索中提高 threshold 可减少这些 FP，但全局 replay 对 synthetic perturbation recall 有明显损失。

因此下一轮 detector production audit：

- 必须冻结当前 threshold/provenance；
- 先测，不调；
- 如要探索 threshold，只能作为独立 exploratory analysis，不能污染主结论。

---

## 4. 当前最重要的新增问题：正确内容被 realign 打坏

上一轮 recovery 研究主要从 bad region 出发，不足以评价产品风险。

下一轮必须重点研究：

> **GT 已经正确，但 detector 判 UNCERTAIN/REJECT，于是系统触发 realign。realign 会不会把原本正确的 alignment 改坏？**

这类 `correct + detector bad` 是 realign gate 最重要的 hard negative。

应至少报告：

- original <=100ms → after >200ms；
- original <=100/200ms → after >500ms；
- original <=100/200ms → after >1s catastrophic harm；
- safe-context 被改变的 unit 数/比例/最大位移；
- 是否出现 pile-up/inversion/compression。

---

## 5. 本轮结束时的结论强度

### 可以较强地说

1. 旧 synthetic-GT 14–16% recovery ceiling 无效。
2. aligner 在更正确局部 request 下存在真实 recovery 能力。
3. 当前 no-GT proposal 与 writeback quality judgement 仍不可靠。
4. 当前 natural R-B proposal 不能证明整体有效。
5. detector 可以用于找“值得尝试”的位置，但当前不应单独授权 writeback。
6. realign before/after behavior 中已经出现值得研究的 gate signal，尤其是 change breadth/locality 类信号。

### 仍不能说

1. no-GT closed-loop recovery 已完成；
2. 当前 C3 实际修复了 7/111 且没有 harmful writeback；
3. E8 strategy 产生了 +65 的真实净收益；
4. detector 在生产上会几乎全报；
5. `n_big<=2` 已经是可上线 gate；
6. `<=1s/5s` 就是可用 repair success。
