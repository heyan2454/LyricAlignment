# 当前实验 review：可保留结论、失效结论与修正要求

## 1. 当前可信结论

### 1.1 P0 production population 修正成功

可正式保留：

- `population_kind=production_raw_baseline`；
- 13 songs / 40 unique production windows；
- 4093 detector units；
- ACCEPT 0.8507 / UNCERTAIN 0.0054 / REJECT 0.1439；
- 历史 frozen val safe accept 0.8689，与当前 production output ratio 接近；
- 旧 0.155 accept / 0.844 reject 是 E5 proposal-bank contamination + cross-variant conservative merge 的实现错误，不是 detector regression。

但必须注意：0.8507 是当前 production detector **状态比例**，不是 GT accuracy。当前 P0 仍需补算 GT-conditioned：correct→accept/reject、bad→accept/reject、protected recall、false-reject 等。

### 1.2 whole-window 97.5% unsafe 仅是聚合规则结果

`any REJECT unit -> whole window unsafe` 使 39/40 windows 被标 unsafe。该数字不应再作为 detector production quality 的主要 KPI，也不应直接作为整窗 realign trigger。

后续 detector→realign 接口应以：

- unsafe interval；
- contiguous reject/uncertain unit region；
- region 周围 safe anchors；

为主要实体。

### 1.3 Realign 有能力，但 active intervention 的结果高度不稳定

仅看 active R-A，已经同时观察到：

- catastrophic drift 上的大幅改善；
- 大量 neutral；
- 一部分明显 harm。

因此继续研究 realign request 与 gate 是合理的；平均 net improvement 不可代替 harm/recovery 分布。

## 2. 当前不能保留的结论

### 2.1 当前 R-B 不是有效 intervention

23/23 R-B 均没有真实 anchors，forward-affecting audio/text request 与 baseline 相同，paired GT delta 全 0。

因此：

- 当前 R-A vs R-B 比较无效；
- 当前 R-B 只能标记为 `null_control/noop`；
- 后续正式 R-B 必须 assert non-null anchors、request span 实际发生变化，并通过 forward-identity difference 验证。

### 2.2 `n_big AUROC=0.934` 不能支持 gate

R-B no-op easy negatives 和 unit-row pseudo-replication 会显著抬高结果。active R-A 上 n_big 同时随改善和恶化变大，说明它更可能是 change magnitude / instability feature，而不是 improve-vs-harm direction feature。

因此：

- 不冻结 `n_big<=k` writeback rule；
- `n_big` 只保留为一项 feature；
- gate 分析必须按独立 `(song, case, variant)` candidate 聚合和 song holdout。

### 2.3 `AUROC(delta_error_ms)=1.0 -> ACCEPT_WRITEBACK` 必须永久移除

`delta_error_ms` 来自 GT，并直接定义 harm/improve label。它只能作为 outcome，不得作为 no-GT gate feature、weakness 判断或 recommendation criterion。

正式 report 不得基于任何 GT-derived feature 产生 `ACCEPT_WRITEBACK`。

### 2.4 Test Demo 当前只有 discovery 有效

当前真实可保留：动态发现 36 个 Demo item。

当前不能保留：mock detector/realign behavior 的任何质量结论。

下一轮必须 real model + frozen detector + real realign。

## 3. P1 分层的关键修正

当前整窗级定义造成 S2=2，但这不是数据不足。已有执行样本中存在数百个 `GT<=200ms` 且 detector=UNCERTAIN/REJECT 的正确 units。

因此下一轮 strata 实体必须从“whole 60s window”改为“detector interval / contiguous unit region”。

建议 region GT 状态：

- `correct_region`：目标 region 内 target units 均/绝大多数 <=200ms，并显式报告 max/quantile；
- `bad_region`：至少一个 target unit >1s 或 region-level catastrophic/error score 达到预定义条件；
- 200--1000ms 的中间区域不再静默丢弃，可标 `moderate/grey_gt`，用于探索但不混入主 S1--S4。

主要 strata：

- S1: GT correct region + detector ACCEPT/control；
- S2: GT correct region + detector UNCERTAIN/REJECT（hard negative，重点）；
- S3: GT bad region + detector UNCERTAIN/REJECT；
- S4: GT bad region + detector ACCEPT（false negative）。

## 4. 对样本不足的处理原则

以下均不得直接以 `insufficient` 收尾：

- S2 太少；
- genuine R-B 可构造 case 太少；
- 某 request family 只有少数 active intervention；
- Test Demo 某语言/异常类型没有样本；
- holdout candidate 数太少。

必须依次尝试：

1. 从 whole-window 改到 interval/unit-region sampling；
2. 扫描全部 13 real-GT songs 和全部 constructible windows/regions；
3. 放宽“每歌最多一个 region”但保持每歌 cap，优先增加 song diversity；
4. 在不改变 GT/生产语义的前提下扩大同歌不同 window/region；
5. 对 R-B 重新搜索左右 ACCEPT anchors，允许按 unit index 或局部时间邻域搜索，但必须保持 anchor 真实存在；
6. 利用已有 baseline/cache，只补昂贵 candidate forward；
7. 若仍不足，输出 `EXHAUSTION_AUDIT`：总 eligible、各过滤步骤剩余、每个不可构造原因和穷尽证明。

只有第 7 步完成后才允许报告真实不可满足。
