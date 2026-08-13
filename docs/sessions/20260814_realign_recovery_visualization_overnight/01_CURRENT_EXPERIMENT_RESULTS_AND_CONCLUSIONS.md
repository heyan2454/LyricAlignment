# 当前实验结果与结论（2026-08-14 review 冻结版）

## 0. 结论强度说明

本文件优先引用本轮 evidence pack 中的 evaluator-only/paired 结果，不把不同 denominator 的历史摘要直接混在一起。所有 `actual_writeback` 仍为 0；无 GT 结论与 GT evaluator 结论分开。

需要特别避免两个误读：

1. **平均误差下降不等于精确修复成功**；当前 realign 很多时候只是 coarse correction；
2. **稳定/一致不等于正确**；fixed-point、multi-view consensus 只能描述 self-consistency。

---

## 1. P1 主 screening 已实现四象限均衡，但 formal 不是四象限正式验证

主 screening：

- S1 safe + ACCEPT：25 regions；
- S2 safe + REJECT：25；
- S3 bad + REJECT：25；
- S4 bad + ACCEPT：25。

这是本轮修复后的重要进展。

主 screening 最终执行/评价约 346 个 family×region candidate（R-A 100、R-B 83、R-S 66、R-U 97；另有 R-NULL/null/not-constructible accounting）。

但后续 formal 的抽样组成未保持 S1/S2/S3/S4 均衡，因此 formal 不能替代上述四象限 screening 做 strata 间正式结论。

**当前结论强度：强（对 screening 构成），有限（对 formal strata 比较）。**

---

## 2. R-S sparse/fixed 的“保护 context”结论很强，但“修 bad target”证据很弱

主 screening 的 unit transition 表中，R-S fixed context 在四个 stratum 的 evaluator-safe context 均为 100% preservation：

- S1：569/569；
- S2：206/206；
- S3：337/337；
- S4：379/379。

独立 confirmation：R-S context 可评价 132 个，132/132 max-error unchanged。

heldout expansion：可评价 691 个，691/691 unchanged。

但是主 screening 对真正 bad target：

- S3：22 target，`>200ms -> <=200ms` strong recovery = 0；
- S4：18 target，strong recovery = 0。

因此 R-S 当前可以可靠表述为：

> **强 isolation / context protection mechanism；尚未证明具有强 precise recovery。**

不能表述成“既保护又保留 recovery”的已证结论。

**当前结论强度：context protection 强；precise recovery negative result 强。**

---

## 3. R-U 是当前 target recovery 更强的 production-capable family，但仍不是可靠 writeback winner

使用当前 evidence pack 的 evaluator-only 同口径结果：

### Confirmation

- R-U：old mean max error 3435.1ms -> new 787.5ms；
- R-S：3435.1ms -> 866.7ms；
- paired `R-S - R-U`：+75.8ms，song-cluster bootstrap CI95 `[+10.9, +135.2]`。

### Heldout expansion

- R-U：2450.5ms -> 940.3ms；
- R-S：2450.5ms -> 1044.7ms；
- paired `R-S - R-U`：+112.6ms，song-cluster bootstrap CI95 `[+8.6, +188.8]`。

因此在当前 evaluator-only paired 口径下，R-U target accuracy 稳定优于 R-S。

但 R-U 会改变周围 context，而且大量 target 最终仍没有进入 100/200ms 精确区间。所以当前正确定位是：

> **R-U 更适合作为 coarse proposal / recovery candidate，而不是未经 gate 的最终 writeback。**

注：此前某些报告出现过约 724/956ms 等不同均值，属于不同 denominator/过滤口径；下一轮比较必须固定同一 evaluator schema，不再把这些数直接横比。

**当前结论强度：R-U vs R-S target paired 优势中强；自动 writeback 不成立。**

---

## 4. 模型对困难区“再跑一次”的能力有限：coarse correction 明显，fine recovery 弱

从 formal/confirmation/heldout 的总体模式可见：

- 几秒级错误经常被拉回到约 0.5–1s；
- 1s tolerance 的比例提升通常比 500ms 更明显；
- 200ms strict recovery 提升很小，某些 heldout 条件甚至几乎无改善。

因此当前最重要的行为结论是：

> **Forced aligner 对困难区存在 coarse relocation/correction 能力，但精确 fine recovery 不可靠。**

这也是下一轮必须拆分 coarse stage 与 fine stage 的原因。

**当前结论强度：中强。**

---

## 5. Oracle 仍无法修回 catastrophic：问题不只是 request heuristic

Oracle basin：

- 40 requests / 40 regions；
- 48 target units；
- GT±100ms target recovery：39.6%；
- region recovered：45%；
- catastrophic bucket：15 regions，0/15 recovered；
- recovery bucket：6/7 recovered；
- safe：5/5 recovered。

这说明：

- request 构造确实会影响 recovery；
- 但即使给接近 oracle 的定位，仍有一类困难区不存在当前机制可达的精确解；
- 不能把失败全部归因于 detector 或 request family。

**当前结论强度：强 negative result，样本量仍应扩张。**

---

## 6. Perturbation 暗示 audio observation 比少量 text context 更值得研究

9-case perturbation subset：

- basin width median ≈2s；
- 没有观察到预定义意义上的 discrete jump；
- textL -1/-2 unit 与 textR +1/+2 unit 在已测 case 中可出现 0ms 响应；
- audio-left 的变化在部分 case 可造成约 1.7–1.9s 级 timestamp 位移；
- base oracle point 自身 GT±100ms recovery 只有 50%。

因此合理但仍需扩量的假设是：

> **对困难区，重新定义 audio crop/reference frame 可能比单纯增加 1–2 个文本邻居更能改变 basin。**

不能把 9 case 直接扩大成普遍定律。

**当前结论强度：机制线索，中等偏弱，需要扩量。**

---

## 7. Fixed-point 与 multi-request consensus 是稳定性信号，不是 correctness signal

Fixed-point：

- 24/24 两轮 A→B 都 stable；
- displacement median 10ms，max 60ms；
- 0 drift >500ms。

但其中包含严重错误 case，说明模型可稳定地重复错误答案。

Multi-request consensus：

- 390 target units；
- 84.6% 达到 strong consistency；
- median multi-view span 20ms；
- consensus-strong 的 GT±100ms hit 39.7%，反而低于 weak 的 43.6%。

因此：

> **fixed-point / consensus 只能做稳定性或候选安全的辅助条件，不能单独判定候选正确。**

**当前结论强度：强 negative result。**

---

## 8. Context displacement 是 collateral-damage safety signal，不是 correctness signal

346 requests / 8855 context units 的 structure sanity：

- neutral：context mean displacement 3.0ms，98.99% <=60ms；
- harmful：252.2ms，仅 41.46% <=60ms；
- mixed：约 6007.9ms，20.21% <=60ms；
- catastrophic_harmful：虽然 target 严重错误，但 context 仍有 97.02% <=60ms。

因此 context displacement 对“是否破坏周围 context”很有用，却无法判断 target 是否正确。

冻结用法：

> **候选 context 位移小可作为 writeback 的必要安全条件之一；不能成为 correctness 的充分条件。**

---

## 9. Evidence-only p_bad proxy 失败，不能替代真正 detector 信号

当前只基于时间行结构构造的 no-GT proxy：

- signed detector delta AUC ≈0.411；
- p_bad_after AUC ≈0.512；
- cross-view span AUC ≈0.462；
- n_views AUC ≈0.434。

全部接近随机。

因此本轮失败的是“纯 timing/evidence proxy”，不是对 raw/official/entropy/margin/hidden detector 特征的否定。下一轮如做 candidate selection，必须接真实 detector/模型信号或明确标记为 unavailable。

---

## 10. R-B 与旧 artifact provenance 仍需谨慎

主 screening 的新 builder 对 genuine bilateral anchors 有明确 constructibility 检查，可用于理解机制。

但 formal/confirmation/heldout 中仍存在由旧 recovery adapter 产生的 R-B 兼容数据，其中部分 request 没有符合当前 R-B 定义的真实 bilateral anchors。此类数据不能被解释为“genuine R-B 已正式失败/成功”。

下一轮 R-B 若继续使用，必须：

- anchors 非空；
- 左右 anchor 分别位于 target 两侧；
- anchor 来源满足 nearest eligible ACCEPT/stable provenance；
- request identity 明确变化；
- 不满足时标 `not_constructible`，不能 silently fallback 成别的 family。

---

## 11. Test Demo 已跑真 local forward，但当前只能说明执行路径成立

当前 Test Demo formal：

- 33 items 成功，3 failed；
- 60 windows；
- 118 real forward（R-U 59 + R-S 59）；
- 另有 R-NULL accounting；
- 多语言覆盖 Chinese/Cantonese/English/Japanese；
- no_gt=True。

因此已经从此前 pseudo-local 迈到真实 local/sparse execution。

但 Test Demo 无 GT，当前只能支持：

> production-like detector -> local request -> real forward 路径可以执行。

不能仅凭视频或 consensus 宣称 correctness。

---

## 12. 尚未完成/需要下一轮闭合的项目

1. `context k=1 vs k=3`：只有 request manifest，没有正式 forward + GT/no-GT comparison；
2. 最新 unit-realign artifact 与旧 inline-realign visualization 尚未统一 schema；
3. B4 vs Current system-level Demo 对照尚未生成；
4. Current baseline / R-U / R-S / combo 四路视频尚未生成；
5. multi-iteration realign dynamics 尚未系统研究；
6. fine-grained split / directionality / recrop chain 尚未系统研究；
7. `R-U coarse proposal -> bounded sparse refinement` 尚不是已证方案；
8. hard-case mining / recovery-basin atlas 需要扩大独立歌曲和困难类型；
9. 真正 raw/official/hidden/posterior candidate-selection 信号尚未接入本轮 unit-realign gate。

---

## 13. 当前阶段最简洁的总判断

1. **R-S 的 isolation/context protection 成立；**
2. **R-U 更适合 target coarse recovery；**
3. **“同一个困难问题再跑一次”不是可靠 precise recovery；**
4. **模型可能稳定地收敛到错误解；**
5. **下一轮应研究如何改变 problem formulation：多次迭代、细粒度拆分、audio recrop/multi-view、coarse→fine 组合；**
6. **realign 继续 shadow-only，直到找到真正 no-GT 可选择且 GT-backed 的 recovery 机制。**
