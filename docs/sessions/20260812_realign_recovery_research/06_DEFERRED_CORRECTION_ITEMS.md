# 延期到下一轮顺手修复的小问题

这些问题来自 `LyricAlignment_20260812_quick_correction2` 审核。用户已经明确：

> “这些问题可以纪录，下一轮再修复。”

它们不阻塞 Realign 主实验，但 OpenCode 在 Phase 0 / CPU 文档阶段应顺手修复并记录，不要再开一个独立长期 correction session。

## D1. `start_mae_sec` metric audit 分类

当前 audit 曾把连续值：

```text
start_mae_sec
```

误归为：

```text
start_only_1s / start_hit_1s
```

应改为：

```text
classification = other / continuous_error
canonical_name = start_mae_sec
action = keep
```

`start_hit_1s` 才是 `start_mae_sec <= 1.0` 的 boolean 派生指标。

## D2. Failure concentration top-k 应按 song 聚合

现有明细 song×family 可以保留，但用于“错误集中在少数歌曲”的 top-k 展示应先把 family 聚合到 song。

应增加：

```text
per_song_aggregated
```

并分别按 Raw / Official（若仍保存 official shadow）给 top-1/2/3/5 cumulative unsafe share。

## D3. Codex followup final acceptance

现有 `CODEX_REVIEW.md` 主要覆盖第一轮 quick correction；应补一个 followup acceptance，记录第二轮 F1–F5 已完成、1056 tests passed，以及上述 D1/D2 的最终修复状态。

## 完成原则

- 仅 CPU / 文档 / 小计算；
- 不阻塞 E1 GPU；
- 若 E1 已排队运行，可并行做这些修复；
- 修完记录在本 session implementation log，不再循环审核 quick correction。
