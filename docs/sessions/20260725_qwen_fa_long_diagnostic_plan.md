# Qwen FA 长音频诊断分层计划

日期：2026-07-25

## 当前目标

当前阶段不直接追求更好的长音频结果，而是用最少的新增推理和训练，区分以下机制：

1. 微调训练缺少晚时间戳类别监督；
2. raw timestamp 已经错误，或官方单调修复扩大了错误；
3. 完整上下文导致局部对齐路径变化；
4. join、padding 或 mask 造成尾部输入异常；
5. 重复歌词导致第二次出现跳回第一次出现。

## A. 需要立即获得、会改变当前判断的结果

以下内容由 `scripts/training/run_qwen_fa_immediate_diagnostics.sh` 一次完成。

### A1. GT timestamp 类别覆盖

不加载模型，统计：

- M4Singer train/test；
- synthetic b180；
- MIR-1K OOD；
- 0–30、30–60、60–90、90–120、120–150、150–180、180–240、240–300 秒分桶；
- 最大 GT timestamp 和占用类别数。

用途：确认正式训练是否实际上没有覆盖 120 秒以后的正标签。

### A2. b180 全量 raw/fixed、seam 和 mask 联合审计

R0、R1、R2 各只做一轮 b180 前向，同时输出：

- raw timestamp argmax；
- top-2 类别、概率、margin、entropy；
- 官方 fixed timestamp；
- raw 与 fixed 的 boundary error；
- repair rate 和 repair amplification；
- 字符到最近 join 的距离；
- processor 输入 tensor 的 shape、dtype、nonzero fraction；
- mask 的有效元素数量。

用途：区分模型错误、后处理放大、seam 相关性和明显的尾部 mask/truncation 异常。

### A3. 时间平移等变性

选 M4Singer test 中确定性的最短样本，在前面添加静音：

```text
0, 30, 60, 120, 180, 240 秒
```

同一音频、歌词和 GT 整体平移。报告扣除 offset 后相对 0 秒版本的 raw/fixed 差异。

用途：直接判断绝对 timestamp 位置是否导致微调模型失去校准。

限制：前置静音不等价于真实长歌曲；它是只改变绝对时间位置的机制实验。

### A4. dominant outlier 的 full/crop 一致性

使用已确认的 Tenor-6《寻人启事》异常序列：

```text
full
90–120 秒
110–150 秒
120–140 秒
140–151 秒
```

crop 根据 GT 选择对应歌词，仅用于 oracle diagnostic。局部预测加回 crop offset 后与 full prediction 比较。

用途：区分局部声学困难与 full-context/path collapse。

### A5. MIR-1K 自然长音频分桶

对已有 MIR-1K OOD 输入收集同样的 raw/fixed、mask 和绝对时间分桶结果。

用途：检查问题是否也出现在自然连续的 OOD 长音频，而不仅是 M4Singer synthetic join。

## B. 快速结果，但不阻塞当前判断

在 A 完成并阅读后再决定是否执行。

### B1. 相邻完全重复

构造：

```text
A + silence + A
歌词：A + A
silence ~ Uniform(0, 8 s)
```

优先固定若干离散点，例如 0、0.5、1、2、4、8 秒，便于复现。统计第二个 A 跳回第一个 A 的比例，以及两个重复位置在 top-2 中的排序。

### B2. 输入 batch/padding 等价性

同一长样本分别：

- 单独推理；
- 与短样本同 batch；
- 与更长样本同 batch。

正常 eval 模式下，同一样本的 raw logits 应基本一致。若不一致，优先检查 attention mask 和 padding。

### B3. 三种 join 小样本对照

只做：

- hard join；
- 插入静音；
- crossfade。

先使用少量固定 source composition。只有 A2 显示 seam 距离与错误相关时才提高优先级。

### B4. 扩展 E/F 样本数

若单一样本的 shift 或 crop 结果显示明确趋势，再扩展到：

- 3–5 个短样本的时间平移；
- b180 中前 3 个 R2-R1 退化样本的 crop；
- 不同歌曲和歌手。

## C. 长训练验证

必须先修复 epoch 尾部 gradient accumulation，再启动新的正式训练语义。

### C1. 前置静音 timestamp-shift 训练

这是机制验证，不需要先考虑短音频性能。对每个原始短训练样本：

1. 采样最终输入总长度 `T ~ Uniform(150, 300)` 秒；
2. 前置静音长度为 `max(0, T - original_duration)`；
3. 歌声片段位于输入尾部；
4. GT timestamp 整体平移；
5. 记录最终时长、offset 和 timestamp-class histogram。

只训练一个主要验证配置，不做多组长训练。与原 R2 进行：

- 相同基础模型与 LoRA 注入；
- 相同 optimizer steps；
- 相同学习率和 seed；
- 修复后的相同 gradient accumulation 语义。

主要判断：晚时间位置的 shift test、b180 outlier 和 MIR-1K 后段是否恢复。短音频下降可以记录，但不作为本机制实验的否决条件。

### C2. 是否需要真实长上下文训练

仅当以下情况出现时再做：

- shift training 修复时间平移，但 full/crop 仍明显不一致；或
- 自然 MIR-1K 长音频仍存在 full-context 特有失败。

这时才构造真实/拼接 150–300 秒歌词上下文训练，避免过早引入重复、join、字符数和上下文复杂度等多个变量。

## 立即运行入口

```bash
cd /home/hyan/LyricAlignment
conda activate lyricalign-qwen
bash scripts/training/run_qwen_fa_immediate_diagnostics.sh
```

可先缩小 MIR-1K，验证入口：

```bash
MIR_MAX_ITEMS=8 LONG_MAX_ITEMS=3 \
OUT_ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_diagnostics_smoke \
bash scripts/training/run_qwen_fa_immediate_diagnostics.sh
```

完整结果：

```text
/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_immediate_diagnostics/
  timestamp_coverage.json
  raw/
  r1/
  r2/
  final_summary.json
  pipeline.complete
```

每个模型目录包含：

```text
existing_b180/
shift/
crop_outlier/
existing_mir1k/
```

每项包含：

```text
diagnostic_rows.jsonl
item_summary.jsonl
input_audit.jsonl
identity.json
```

## 解释边界

- crop 使用 GT 选择歌词窗口，只能用于机制诊断；
- shift 静音实验主要验证绝对 timestamp 和长输入位置，不代表真实长歌效果；
- synthetic b180 不是独立 benchmark；
- 不使用这些诊断结果选择当前历史 checkpoint；
- 后续长训练必须从修复梯度累积语义后的新运行开始。
