# Qwen ForcedAligner 技术报告对项目的影响

## 1. 模型任务定义

Qwen3-ForcedAligner 将音频表示与带 timestamp slots 的 transcript 输入 Qwen3 Transformer，在每个 slot 预测离散时间类别。公开实现对每个 slot 都产生时间，没有公开 no-match/abstain 类。

项目含义：文本不在音频中时，模型仍可能输出单调、看似合法的时间。Aligner 不能同时作为 correspondence verifier。

## 2. 因果上下文

slot 使用此前音频和此前文本/slot 的因果上下文。尾部追加文字原则上不改变前部 raw logits，但：

- 多余文字自身仍被迫分配时间；
- official 在完整序列上做 LIS/修复，可能重新引入全局耦合；
- strict serial cursor 可能把尾部吞字传播到下一 request。

因此必须分开保存 raw core delta、official core delta 和串行文本消费。

## 3. Dynamic slot insertion

报告中的“任意单位”更接近：保留 transcript 上下文，只在选定单位后插 slots，而不是长音频只给孤立短文本。

这直接支持 sparse-slot E4：

- 同一长音频；
- 第 n 次保留歌词前缀；
- 只为当前 chunk 插 slots；
- 不重复输出历史时间。

实现主要是 processor 和 mapping 扩展，不需修改模型主体。

## 4. 官方长音频实验的边界

官方 60/300 秒实验拼接了彼此对应的 speech 和完整 transcript。它没有验证：

- 长音频中短文本自动定位；
- 歌词部分/完全不对应；
- 重复副歌；
- 串行 cursor 错误；
- no-match 拒绝。

所以本项目的 production correspondence 研究不是重复官方实验。

## 5. Official decoder

公开 decoder 主要是 hard argmax + 最长非递减子序列 + 吸附/线性插值。应保存 repair trace，并研究 posterior-aware constrained decoding。

## 6. ASR 模块

官方 ASR 与 ForcedAligner 是独立 checkpoint，不能默认只加载一个小 head 即复用。近期可顺序加载/offload，或使用小型 CTC/音素模型；共享 backbone 属于长期多任务训练。

## 7. 部署

在任务结构冻结前不急于蒸馏。优先：

- INT8/INT4；
- 同一长音频的 audio embedding cache；
- 小型 coarse localizer；
- 避免重复 AuT 编码；
- 研究版和端侧版分离。

## 8. 新证据

优先收集：

- posterior 多峰、熵和远距离第二峰；
- slot-mask stability；
- official repair burden；
- sparse/full/short text 多视图一致性；
- hidden states pilot。
