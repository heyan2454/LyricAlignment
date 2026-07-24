# Qwen FA approximately-150-second outlier audit

**Date:** 2026-07-24  
**Evidence:** preserved `references.filtered.jsonl` and `predictions.jsonl`; no new model inference  
**Scope:** paired R1 versus R2 diagnostic on the nominal `bucket_180`, whose actual mean duration is approximately 152.5 seconds

## Result

The previously observed R2 regression is confirmed, but it is not uniform across the complete sequence set.

| Model | Song-macro penalized MAE | Pooled penalized MAE |
|---|---:|---:|
| R1 | 51.831 ms | 50.329 ms |
| R2 | 102.825 ms | 115.085 ms |

The dominant outlier is a Tenor-6 rendition of `寻人启事`:

- characters: 224;
- R1 item-level penalized MAE: 69.484 ms;
- R2 item-level penalized MAE: 806.768 ms;
- R2 minus R1: 737.284 ms;
- R2 unusable-character rate: 3.57%.

Removing only this item changes R2 pooled penalized MAE from **115.085 ms** to **64.534 ms**. R1 without the same item is **48.929 ms**. Therefore:

1. one severe sequence collapse explains most of the aggregate regression;
2. a smaller residual R2 disadvantage remains after removing the outlier;
3. the issue is not simply a global increase in invalid predictions.

## Error position

### Absolute-time bins

| Time | R1 MAE | R2 MAE |
|---|---:|---:|
| 000-030 s | 32.312 ms | 29.388 ms |
| 030-060 s | 38.280 ms | 33.593 ms |
| 060-090 s | 34.708 ms | 35.688 ms |
| 090-120 s | 44.838 ms | 70.506 ms |
| 120-150 s | 102.358 ms | 399.241 ms |
| 150-180 s | 32.667 ms | 136.918 ms |

### Normalized quarters

| Relative position | R1 MAE | R2 MAE |
|---|---:|---:|
| Q1 | 32.057 ms | 29.004 ms |
| Q2 | 39.290 ms | 35.376 ms |
| Q3 | 42.161 ms | 48.500 ms |
| Q4 | 87.279 ms | 342.213 ms |

The R2 failure is concentrated in the final quarter, especially around the 120–140 second region of the dominant outlier. The model becomes several seconds early for a contiguous character span and later partially recovers. This is consistent with a local alignment-path collapse or skip rather than uniform timestamp quantization error.

## Interpretation limits

- The set contains 11 synthetic sequences but only 6 songs.
- Sequence composition differs from shorter buckets.
- The analysis does not identify whether the collapse originates in attention length, repeated lyrics, absolute timestamp classes, or the synthetic concatenation structure.
- This does not establish monotonic degradation with duration.

## Next targeted check

Before increasing LoRA scope or training duration, run a controlled windowed evaluation of the dominant item:

```text
0–90 s
90–120 s
120–140 s
140 s–end
```

Compare full-context inference against overlapping-window inference with the same checkpoint. This directly tests whether the failure depends on accumulated context length or on local audio/lyric ambiguity.
