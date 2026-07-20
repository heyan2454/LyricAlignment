# Model Usage Notes

## 当前候选

- Qwen3 Forced Aligner：raw alignment baseline，后续评估 LoRA/PEFT 可训练性；
- Qwen3 ASR / Whisper 等：仅在开展 audio-to-text 辅助实验时使用。

## 使用前核验

- 官方 model id 和 revision；
- 参数量、dtype 和设备；
- 输入采样率、最大时长、切片与 overlap；
- 中文 character timestamp schema；
- 英文 word-level 当前处于 deferred 状态，不进入本轮实现；
- 是否提供训练代码、loss 和可插入 LoRA 的模块；
- 长音频、重复歌词和中英混排行为；
- license 和数据使用限制。

## 结果记录

- raw model 与 adapter 分开记录；
- 不能只记录展示名称，必须记录 revision/hash；
- 使用量化、flash attention、gradient checkpointing 或 CPU offload 时必须进入配置快照；
- 未经 smoke 测量，不提前宣称具体显存、吞吐或训练规模。
