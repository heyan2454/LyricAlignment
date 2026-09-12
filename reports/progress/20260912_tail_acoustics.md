# 末字尾边界的声学锚点实验（第 11 轮，2026-09-12）——**否证两条简单判据**

> 数字由 `runs/20260912_tail_acoustics/TAIL_ACOUSTICS.json` 生成。
> 纪律：阈值/规则**只在 GTSinger 上导出**，冻结后迁移到 MIR-1K（test-only）；MIR-1K 上的 ρ 族**整族报告、不做选择**。零 GPU，音频只读不复制。

## 0. 结论

- **RMS 衰减锚点在末字上几乎不触发**：GTSinger 末字 168 单元里最多只有 6 个有锚点（θ=0.5 覆盖 30.1%），MIR-1K 末字 17 单元里**只有 1 个**有锚点 ⇒ 它根本没有机会修我们已定位的失效层。
- **导出的阈值不可迁移**：GTSinger 长音上最好的 θ=0.15（+3.69pp）冻结到 MIR-1K 长音后是 **-13.37pp**（全单元 -22.08pp）。
- **人声/伴奏能量比锚点触发率很高但没有用**：覆盖 88.3%（含全部 17 个末字），而其 hit@100 只有 61.5%，同一批单元上模型是 95.8%；末字子集上锚点 29.4% vs 模型 88.2%。
- **两个 oracle 界都表明空间很小**：在"模型 vs 各锚点"之间用真值逐单元挑最优，GTSinger 全单元只 +0.75pp、末字 **+0.00pp**；MIR-1K 全单元 +1.67pp、末字 **+0.00pp**（长音 +7.14pp 但那是 test 上的事后观察，不构成可部署结论）。
- ⇒ **关闭 F3 的简单版本**：末字/长音的残余误差**不能**用相对能量阈值或人声-伴奏比值阈值这类事后声学判据修复；这些信号在带伴奏、带混响的真实录音上要么不触发、要么系统性偏晚。剩余误差需要**模型侧**改动（更长右上下文、拖长音 offset 的训练信号），这与第 5/6/7 轮"单次解码之后的环节可挽回空间都是个位数 pp"完全一致。

## 1. 导出集（GTSinger，人工真值）

| 规则 | 覆盖 | all hit@50 | all hit@100 | all MAE | 长音 hit@100 | 长音 MAE | Δ长音 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `model_end_sec` | 100.0% | 84.4% | 94.3% | 38.9ms | 89.2% | 69.1ms | +0.00pp |
| `anchor_theta15` | 21.9% | 52.9% | 61.2% | 201.7ms | 92.9% | 98.6ms | +3.69pp |
| `anchor_theta25` | 24.7% | 59.4% | 66.3% | 154.5ms | 66.7% | 122.8ms | -22.50pp |
| `anchor_theta35` | 27.2% | 60.8% | 69.5% | 128.0ms | 61.1% | 125.8ms | -28.06pp |
| `anchor_theta50` | 30.1% | 54.8% | 66.9% | 114.1ms | 36.8% | 166.9ms | -52.33pp |
| `anchor_theta8` | 18.3% | 42.3% | 50.4% | 372.9ms | 90.9% | 121.6ms | +1.74pp |
| `blend_close100` | 100.0% | 83.4% | 93.9% | 38.4ms | 87.5% | 70.8ms | -1.67pp |
| `blend_mean` | 100.0% | 79.4% | 90.0% | 48.9ms | 86.7% | 70.0ms | -2.50pp |
| `control_next_onset` | 100.0% | 32.4% | 36.1% | 851.8ms | 19.2% | 2406.7ms | -70.00pp |

## 2. 迁移集（MIR-1K，test-only，人工逐字真值）

| 规则 | 覆盖 | all hit@100 | all MAE | 长音 hit@100 | 长音 MAE | Δ长音 |
|---|---:|---:|---:|---:|---:|---:|
| `model_end_sec` | 100.0% | 95.6% | 35.8ms | 85.7% | 73.5ms | +0.00pp |
| `anchor_theta15` | 30.5% | 73.6% | 193.5ms | 72.3% | 466.0ms | -13.37pp |
| `anchor_theta25` | 35.6% | 73.0% | 198.4ms | 58.3% | 394.0ms | -27.38pp |
| `anchor_theta35` | 40.3% | 68.5% | 117.9ms | 35.4% | 271.4ms | -50.29pp |
| `anchor_theta50` | 47.2% | 58.7% | 123.2ms | 26.9% | 404.7ms | -58.79pp |
| `anchor_theta8` | 25.3% | 65.8% | 305.4ms | 93.3% | 38.6ms | +7.62pp |
| `blend_close100` | 100.0% | 95.0% | 35.7ms | 85.7% | 74.0ms | +0.00pp |
| `blend_mean` | 100.0% | 89.8% | 47.0ms | 76.8% | 86.8ms | -8.92pp |
| `control_next_onset` | 100.0% | 54.1% | 2231.1ms | 38.4% | 4019.4ms | -47.32pp |

末字子集（每集 17 / 168 单元，样本很小，只作方向性观察）：

| 集合 | 规则 | n | hit@100 | MAE |
|---|---|---:|---:|---:|
| GTSinger | `model_end_sec` | 168 | 94.6% | 33.4ms |
| GTSinger | `anchor_theta50` | 6 | 50.0% | 138.0ms |
| GTSinger | `anchor_theta35` | 5 | 60.0% | 105.3ms |
| GTSinger | `anchor_theta25` | 5 | 60.0% | 81.3ms |
| GTSinger | `anchor_theta15` | 3 | 100.0% | 32.8ms |
| GTSinger | `anchor_theta8` | 1 | 100.0% | 47.5ms |
| GTSinger | `blend_close100` | 168 | 94.0% | 34.4ms |
| GTSinger | `blend_mean` | 168 | 94.0% | 34.3ms |
| MIR-1K | `model_end_sec` | 17 | 88.2% | 122.1ms |
| MIR-1K | `anchor_theta50` | 1 | 100.0% | 84.5ms |
| MIR-1K | `anchor_theta35` | 1 | 100.0% | 54.5ms |
| MIR-1K | `anchor_theta25` | 1 | 100.0% | 44.5ms |
| MIR-1K | `anchor_theta15` | 1 | 100.0% | 24.5ms |
| MIR-1K | `anchor_theta8` | 1 | 100.0% | 14.5ms |
| MIR-1K | `blend_close100` | 17 | 88.2% | 124.5ms |
| MIR-1K | `blend_mean` | 17 | 88.2% | 122.5ms |

## 3. 人声/伴奏比值锚点（利用 MIR-1K 原始双声道；ρ 整族报告，不选点）

模型基线：全单元 hit@100 95.4%、末字 88.2%（n=17）、长音 84.8%（n=112）

| ρ | 覆盖 | 锚点 hit@100 | 模型(同单元) | 锚点 MAE | 末字锚点 hit@100 | 末字模型 | 长音锚点 | 长音模型 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.9 | 99.4% | 6.2% | 95.7% | 261.1ms | 0.0% | 88.2% | 0.0% | 85.6% |
| 0.7 | 99.4% | 19.9% | 95.7% | 231.8ms | 0.0% | 88.2% | 0.0% | 85.6% |
| 0.5 | 99.3% | 40.5% | 95.7% | 179.6ms | 11.8% | 88.2% | 3.6% | 85.6% |
| 0.3 | 96.4% | 57.5% | 95.7% | 140.6ms | 11.8% | 88.2% | 10.8% | 85.6% |
| 0.15 | 88.3% | 61.5% | 95.8% | 130.2ms | 29.4% | 88.2% | 39.2% | 85.0% |

- no rho is selected here: this data is test-only, so the whole family is reported and any single-rho claim would be tuning on test。
- 读法：ρ 越大锚点越早触发、越差；ρ=0.15 最保守也仍只有 61.5% hit@100（模型 95.8%）。⇒ 比值信号**方向对但精度远远不够**，作为后处理判据不可用。

## 4. 与文献一致

- 歌声音符 offset 至今无稳健通用解（[McGill 论文：no robust solutions currently exist for annotating note onsets and offsets in recordings of the singing voice](https://escholarship.mcgill.ca/downloads/g158bn57z?locale=en)；实时/离线歌唱 onset-offset 方法学见 [ProQuest 2700544904](https://www.proquest.com/docview/2700544904)），本实验在**我们自己的数据**上量化了这一点。

## 5. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_tail_acoustics.py
PYTHONPATH=src python scripts/evaluation/report_tail_acoustics.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_tail_acoustics.py
```

