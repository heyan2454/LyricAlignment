# Next Execution Plan

**Date:** 2026-07-25  
**Goal:**先用低成本控制实验区分“绝对时间位置”和“总输入长度”，再决定是否扩大长音频诊断；同时独立完成夜苏打 demo，不把 demo 当成正式评测。

## Q1 — 120s 快速反馈

先运行：

```text
scripts/training/run_qwen_fa_120_quick_feedback.sh
```

两类控制：

1. 同一短样本前置静音，改变绝对时间位置；
2. 同一短样本尾部补静音，保持目标位置不变但增加总输入长度。

优先查看：

```text
QUICK_READOUT.md
final_summary.json
```

Decision questions:

- 恶化是否只随绝对位置出现？
- 恶化是否只随总输入长度出现？
- raw 是否稳定而 official fix 放大错误？
- 是否只有 R2 出现明显变化？

## Q2 — 有条件的 dominant-outlier 深诊断

只有 Q1 不能解释时，再对 frozen dominant outlier 运行：

```text
full sequence
prefix: 0–90 / 0–105 / 0–115 / 0–120 / 0–125 / 0–140
local guarded crop around 90–150s
```

局部 crop 必须保留 guard context，只评价 core 内完整字符，避免裁剪边缘的音频/歌词不匹配。

## Q3 — 夜苏打独立 Demo

使用：

```text
scripts/demo/run_yessoda_serial_demo.sh
```

生成：

```text
R0/R1/R2 × mix/vocal × full/windowed = 12 alignments + 12 videos
4 个 R0/R1/R2 三联视频
3 个同模型四联视频
```

Demo 仅用于听感和可视化，不用于：

- 选择 checkpoint；
- 调整 LoRA；
- 替代 M4Singer/MIR-1K 指标；
- 对 120s 机制做正式因果结论。

## Q4 — 根据快速反馈决定后续

- **shift 恶化、tailpad 稳定：**优先查 timestamp class calibration；
- **tailpad 恶化、shift 稳定：**优先查总长度、mask、attention；
- **raw 稳定、fixed 恶化：**优先查单调修复；
- **仅 synthetic long 失败：**优先查 join/构造；
- **窗口稳定且 full 失败：**再实现正式 serial window inference 并做有 GT 对比。

## Deferred

在机制没有更明确前，不启动：

- bottom-half LoRA；
- 更大 rank；
- 更长训练；
- 新数据集扩张；
- 根据 demo 主观效果修改 checkpoint。
