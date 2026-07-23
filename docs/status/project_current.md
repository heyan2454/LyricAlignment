# Project Current

**Snapshot date:** 2026-07-23  
**Stage:** Qwen Forced Aligner LoRA first-round full R2 finalization

## 当前定位

```text
known Mandarin lyrics + vocal-only singing audio
-> character-level timestamp weak supervision
-> raw / projector-only / audio-LoRA comparison
-> full R2 training
-> validation-only checkpoint selection
-> sealed M4Singer test
-> MIR-1K vocal-only OOD
```

## 数据身份

### M4Singer

| Item | Value |
|---|---|
| accepted train/val/test candidates | 20,298 |
| excluded review records | 598 |
| interpretation | `rule_validated weak supervision` |
| canonical manifest SHA-256 | `22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a` |
| character annotation SHA-256 | `ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d` |

split 单位为 song；test 在配置和 checkpoint 冻结后使用。

### MIR-1K vocal-only OOD

| Item | Value |
|---|---|
| songs / characters | 17 / 2,035 |
| role | `test` / `ood_test_only` |
| audio | user-confirmed zero-based channel index 1 extraction |
| output root | `/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood` |
| manifest SHA-256 | `bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f` |
| characters SHA-256 | `78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9` |

MIR-1K 不参与训练、early stopping、checkpoint 选择或超参数选择。

## 模型与配置

- model ID：`Qwen/Qwen3-ForcedAligner-0.6B-hf`；
- revision：`c07281df297b9905d24a508279258cccf987a064`；
- R1：projector full train；
- R2：projector full train + audio tower top-half attention LoRA；
- R3：projector full train + audio tower all-attention LoRA；
- 正式配置冻结 language model 和 timestamp classifier；
- full R2 config：`configs/training/qwen_fa_lora_full_r2_v1.yaml`。

## Pilot validation

| 配置 | Step | Song-macro boundary MAE |
|---|---:|---:|
| R0 raw | 0 | 169.925 ms |
| R1 projector-only | 100 | 90.823 ms |
| R1 projector-only | 200 | 65.699 ms |
| R2 top-half LoRA | 100 | **55.247 ms** |
| R3 all-layer LoRA | 100 | 61.078 ms |

R2 相对等 step R1 降低 35.576 ms（39.2%）。R3 在当前统一 pilot 预算下没有带来增益。

## Full R2

- train items：17,748；
- optimizer steps：1,110；
- training wall：5,620.47 s；
- final validation：46.634 ms song-macro boundary MAE；
- invalid rate：0.802%；
- joint within 80 ms：88.924%；
- mean IoU：84.248%。

周期 validation 的程序最佳为 step 1000（46.734 ms）。最终 step 1110 为 46.634 ms，但没有进入每 250 step 的 selector。自动后处理被报告为使用 validation-best，因此当前 finalization 入口默认 step 1000。

## Sealed M4Singer test

已有：

```text
/home/hyan/Data/lyricalign/runs/20260723_qwen_fa_r2_full_m4singer_sealed_test/metrics.json
```

结果：

- song-macro boundary MAE：79.590 ms；
- onset/offset MAE：41.854/51.249 ms；
- joint within 80 ms：89.755%；
- mean IoU：84.579%；
- invalid rate：0.959%。

限制：metrics 文件没有 checkpoint 路径/hash；不重复运行 sealed test，也不利用 test 在 step 1000/1110 间反选。

## MIR-1K OOD 状态

已有 `20260723_qwen_fa_r2_mir1k_ood`，但它生成于 full R2 完成前，是 pilot OOD。最终缺失：

```text
/home/hyan/Data/lyricalign/runs/20260723_qwen_fa_r2_full_mir1k_ood
```

## 当前结论

- projector-only 对领域适配有效；
- audio tower top-half LoRA 提供明确的额外收益；
- all-layer LoRA 在本轮预算下没有超过 top-half；
- full R2 在 validation 和 sealed test 上继续改善；
- 结论为单 seed 可行性证据，尚缺 final full-R2 MIR-1K OOD 与跨 seed 稳定性。

## 当前唯一执行入口

```bash
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```
