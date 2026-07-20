# Dataset Module

数据集转换、字符边界 schema、统一音频格式和长音频构造在数据清洗阶段实现。

当前可用入口：

```bash
python scripts/datasets/prepare_m4singer.py \
  --m4singer-root /external/m4singer \
  --out-dir /external/lyric_alignment/derived/m4singer_v1
```

该入口只读 `meta.json` 和 WAV，生成外部 JSONL manifest、字符到音素的候选索引映射及摘要。只有音素组数与规范化歌词字符数一致时才保留索引映射，且仍标为 `review_required`；不生成字符时间戳、不分配 split、不构造长音频。

本阶段不实现 dataset adapter。未来必须区分：

- `native_short`：数据集原生短片段；
- `synthetic_concat`：同曲相邻片段按顺序拼接的虚拟长样本；
- `natural_long`：真实连续长歌声。

三类数据不能在报告中混为同一口径。
