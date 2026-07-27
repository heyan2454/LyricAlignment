# Raw detector / guarded repair PRF 结果评审

## 输入口径

输入文件：`raw_detector_repair_metrics.json`。

- 评测字符数：1,375；
- 自然检测区间：116；
- 被 detector 覆盖的唯一字符：568；
- 独立 Q2 case 中通过 selector 的 case：3；
- meaningful change 阈值：40 ms。

错误定义为字符 onset/offset 最大绝对误差超过对应 tolerance。它是字符/单位级边界口径，
不是 frame-level 指标。

## 160 ms 主口径

- 错误字符：170/1,375，错误率 12.36%；
- detector：P=20.60%，R=68.82%，F1=31.71%；
- case-level precision：61.21%（71/116 个报警区间至少含一个真实错误）；
- 正确但被 detector 覆盖：451；
- 正确且被实际修改：0；
- 3 个被选择 case 全部改善，0 个恶化；
- 14 次 meaningful modification observation 全部发生在原本错误的字符上；
- 10 次被修正到 160 ms 内；
- intervention correction：P=71.43%，R=5.88%，F1=10.87%。

因此 detector 是宽松、高 recall 的候选生成器，guard 是非常保守的写回器。大量 false alarm
没有形成误改，当前准确率安全性较好；主要问题是最终修复 recall 极低，而不是 detector 找不到
大部分严重错误。

## Trigger 诊断（160 ms）

| Trigger | Precision | Recall | F1 | 解释 |
|---|---:|---:|---:|---|
| local/one-step short unit | 40.39% | 48.24% | 43.97% | 当前最好的单一 F1 |
| structural candidate | 47.52% | 39.41% | 43.09% | 更适合作为高优先级 realign 队列 |
| severe compression | 50.82% | 36.47% | 42.47% | 单独 precision 最高 |
| zero duration | 41.24% | 42.94% | 42.07% | 稳定结构信号 |
| boundary stacking | 41.67% | 41.18% | 41.42% | 稳定结构信号 |
| cross-window disagreement | 18.82% | 58.24% | 28.45% | recall 高但计算浪费大 |

建议将 structural / severe compression / zero duration / stacking 设为第一优先级，
cross-window disagreement 只作为第二优先级候选，必须经过更严格的 exact/+2 verifier。

## tolerance 敏感性

- 80 ms：错误率 26.69%，detector P/R/F1=35.21/54.50/42.78%；
- 160 ms：错误率 12.36%，detector P/R/F1=20.60/68.82/31.71%；
- 240 ms：错误率 8.36%，detector P/R/F1=15.32/75.65/25.48%。

随着“错误”定义变严重，当前 detector recall 上升、precision 下降。这说明 detector 确实覆盖了大部分
严重错误，但候选区间通常较宽，包含大量仍在 tolerance 内的邻接字符。

## 必须修正的计数问题

原 JSON 同时出现：

```text
selected_modified_unit_count = 11
meaningfully_modified = 14
```

原因是 Q2 case 独立评测，三个 selected case 之间存在重叠，同一字符可能被观察多次。14 不是最终
Demo 中 14 个独立修改字符。新版 experiment-suite analyzer 会同时输出：

- independent case observations；
- unique modified units；
- severity-first global non-overlap replay。

正式结论应使用 global non-overlap replay。

## 当前结论强度

可较强支持：

1. raw baseline 的错误并非完全稀少：MIR-1K development 在 160 ms 下有 12.36% 单位错误；
2. 结构 trigger 能提供中等 precision 的候选；
3. 现有安全门在当前 development 结果中没有误改正确字符；
4. 自动修复过于保守，只修正了少量错误。

尚不能支持：

1. held-out 上仍然零伤害；
2. 三个 selected case 的改善能代表整曲最终提升；
3. exact/+2 agreement 的阈值已经最佳；
4. 当前 detector 在其他分离器、歌手或高语速歌曲上可泛化。

阈值应只在 development 上冻结，之后一次性运行 held-out。统计置信区间应按 song 分组，不应把
1,375 个相关字符当作独立样本。
