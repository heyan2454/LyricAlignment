# Inference Module

`qwen_forced_aligner.py` 封装官方 Transformers-native Qwen Forced Aligner：

```text
audio path + known lyrics
-> ffmpeg decode to mono 16 kHz float32
-> official processor/model inference
-> timestamps + phase-level timing
```

当前封装记录：

- requested/resolved model revision；
- processor/model load time；
- audio decode、input prepare、forward 和 alignment decode 时间；
- CUDA forward 前后同步后的 wall time。

它不实现 GT、metric、阈值、歌词转换、数据集清洗或训练。
