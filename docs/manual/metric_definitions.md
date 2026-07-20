# Metric Definitions

## 1. Token 对齐输入

每个 GT 与预测 token 至少包含：

```text
item_id
token_index
token_text
normalized_token
start_seconds
end_seconds
```

中文使用 character token；英文使用 word token。GT 与模型 token 不一致时，先进行显式序列映射，并单独报告 unmapped / missing / extra。

## 2. 边界误差

```text
start_signed_error = pred_start - gt_start
start_abs_error = abs(start_signed_error)
end_signed_error = pred_end - gt_end
end_abs_error = abs(end_signed_error)
```

分别统计 mean、median、p90，signed 和 absolute 不混算。

## 3. 容忍率

候选容忍度：

```text
50 ms / 100 ms / 200 ms / 500 ms
```

分别报告 onset、offset 和 joint within-tolerance。正式容忍度需在读取高质量 GT 与相关论文后冻结。

## 4. 序列与有效性

- token coverage；
- missing token count / rate；
- extra token count / rate；
- token mapping failure；
- monotonic violation；
- negative duration；
- near-zero duration；
- 前半段与后半段误差差异；
- token index 对 signed error 的漂移斜率。

## 5. 聚合口径

同时报告：

- pooled micro：所有 token 合并；
- per-song macro：先按歌曲统计再平均；
- 样本数、歌曲数、GT token 数、预测 token 数。

长歌不得在不说明的情况下通过 pooled 结果获得过高权重。

## 6. 辅助 transcription 指标

若开展 audio-to-text：

- 中文：CER；
- 英文：WER；
- deletion / insertion / substitution；
- 与 forced alignment 结果分表报告。

不使用 token-level CER。
