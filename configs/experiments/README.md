# Experiment Configs

保存后续正式实验矩阵和阶段入口。

当前资产准备阶段不运行本目录中的 character-alignment、metric 或 LoRA 实验配置。当前 raw inference smoke 由 `configs/assets/smoke_samples.local.yaml` 驱动，只验证输出结构。

已有配置均为后续设计，不表示数据、metric 或训练接口已经就绪。

## Inline realign multilingual completion (2026-07-28)

Canonical design snapshots:

```text
inline_realign_multilingual_smoke_20260728.yaml
inline_realign_multilingual_formal_20260728.yaml
```

The formal config deliberately uses `demo_total_cap: null`: current Test Demo
counts are runtime metadata, not a permanent contract. The executable source of
truth remains `scripts/demo/run_inline_realign_{smoke,formal}.sh` and
`build_inline_realign_manifest.py`.
