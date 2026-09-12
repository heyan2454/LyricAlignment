# 长时序跨窗口选择：无真值能吃到多少 headroom（2026-09-12 第 8 轮）

> 数字由 `runs/20260912_m4_longform_weakgt/{CROSS_WINDOW_SELECTION,SIGNED_GT_STATS}.json` 生成。
> 纯 CPU：全部复用已落盘的逐次尝试证据，零新增前向。

## 0. 先修好尺子：重建**有符号**逐字真值并验证

面板里 `label_*_err_sec` 是**无符号**绝对误差，`raw − err` 反推真值带 ± 号歧义；面板自带的 `gt_*` 列又落在第 3 轮证明的伪造均匀轴上。本轮按 labeler 的公式重建：段局部 `timestamp_class_ids × 0.08s` + `segment_offsets.global_start_sec`。

- 验证：重建后 `|raw − gt|` 与冻结误差偏差 **max 0.0s**（start/end 命中率 100.0%/100.0%，相关系数 1.0）；official 阶段同样 0.0s。⇒ 重建与项目 labeler 用的是同一份参考，逐字不差。
- 交叉对照：与 `raw` 距离在 100ms 内的比例，面板 `gt_*`（伪造轴）只有 15.9%，重建参考为 89.1%；中位距离 327.5ms vs 33.0ms⇒ 第 3 轮的伪造轴结论现在有了定量版本。
- 跨尝试自洽：同一单元多次尝试推出的重建真值极差中位 0.0s、≤5ms 占比 100.0%（5,493 个多尝试单元）⇒ 之前看到的「24% 单元跨尝试分歧 >100ms」是 ± 号假象，不是模型不稳。
- 参考性质（必须随结论一起说）：`rule_validated (model-derived, not human GT)`，量化步长 0.08s ⇒ 任何一致性指标都有 ±40ms 底噪；这不是人工 GT。

面板：127,923 次尝试 / 13,743 个唯一单元；每单元尝试次数中位 1、p90 24、最多 24；5,493 个单元被 ≥2 个窗口覆盖。

## 1. 结论：窗口选择本身值 2.1pp；无真值选择器能再拿 0.6pp

| 方法 | 说明 | hit@100 | hit@250 | MAE | Δ vs 跨窗中位 | 吃掉 oracle 差距 |
|---|---|---:|---:|---:|---:|---:|
| `A_first_attempt` | 任意单一窗口（现状：谁覆盖就用谁） | 84.81% | 94.03% | 271.5ms | -2.14pp | -64.3% |
| `median_of_attempts` | 跨窗误差中位（参考线） | 86.95% | 96.54% | 117.9ms | +0.00pp | 0.0% |
| `consensus_median_boundaries` | 跨窗边界取中位（共识输出） | 86.97% | 96.57% | 116.7ms | +0.02pp | 0.6% |
| `C_closest_to_consensus` | 离其余尝试的中位最近 | 86.97% | 96.57% | 118.0ms | +0.02pp | 0.6% |
| `D_max_support` | 与其余尝试 50ms 内一致度最高 | 87.55% | 96.62% | 118.0ms | +0.60pp | 18.0% |
| `E_min_entropy` | 边界熵最低 | 87.04% | 96.24% | 135.1ms | +0.09pp | 2.7% |
| `F_max_margin` | 边界 margin 最大 | 87.11% | 95.93% | 150.8ms | +0.16pp | 4.8% |
| `G_most_central_in_request` | 该单元在其请求窗口内最居中 | 85.80% | 95.31% | 209.8ms | -1.15pp | -34.5% |
| `H_gated_then_confident` | 先要求与共识 ≤100ms，再取熵最低 | 87.34% | 96.60% | 112.7ms | +0.39pp | 11.7% |
| `unit_best_of_attempts_oracle` | 用真值挑最好的一次尝试（上界） | 90.28% | 97.47% | 87.8ms | +0.00pp | — |

- **单窗代价**：随便取一个覆盖该单元的窗口，hit@100 只有 84.81%（MAE 271.5ms），比跨窗中位低 **2.14pp**，最差尝试更是 64.8%（MAE 1.851s）⇒ 长时序的真实风险来自**窗口选择**，不是解码器平均质量。
- **可部署最优：`D_max_support`**（与其余尝试 50ms 内一致度最高）hit@100 87.55%（+0.60pp），吃掉 oracle 差距的 18%；`H_gated_then_confident` MAE 最低（112.7ms）。
- **熵/margin 几乎不能选窗**：87.04% / 87.11%（+0.09/+0.16pp）⇒ 第 1/3/5 轮的「置信信号」在这里只能抓 gross 错误，不足以在多个合格尝试中挑出最好的。
- **反直觉负结果：`G_most_central_in_request` 比中位差 1.15pp**（85.80%）⇒ 「把单元放在窗口中央就更可靠」在长时序上**不成立**，这直接削弱了「靠重新裁窗把困难单元居中」这类 realign 设计的理论依据。
- 共识输出（取中位边界）与「最接近共识的那一次」几乎等价（86.97% vs 86.97%）⇒ 中位本身就是某个尝试，工程上可以直接输出中位而无需回选尝试。

## 2. 与前几轮的关系（为什么这次不同）

- 第 5 轮：同一音频同一歌词的**不同 checkpoint** 之间，共识只值 +0.34pp（oracle 4.57pp，吃 7.4%）。本轮：同一单元的**不同音频切片**之间，oracle 3.33pp，可部署支持度选择器拿到 18%。⇒ **视图多样性才是关键变量**：多视图值得做，但必须是不同裁窗，不是同裁窗换模型。
- 第 1/3 轮的聚簇/接缝结论在本轮得到加强而非削弱：困难不在「接缝附近的单元」，而在「同一个单元被不同窗口给出不同答案」，且这个差异可以被一致性度量预测。

## 3. 边界

- 只有 5,493/13,743 个单元有多窗口尝试（每单元中位 1 次），所以选择器的收益只作用于这部分；对单尝试单元无任何改善。
- 参考是 rule_validated 弱标签、0.08s 量化 ⇒ hit@100 有 ±40ms 底噪，选择器之间 0.1-0.2pp 的差异不足以定序（只有 +0.6pp 与 −1.15pp 是显著的）。
- 真实歌曲（无人工/弱 GT）上无法验证，只能验证「一致性度量本身」是否可用；MIR-1K 仍是 test-only，本轮未使用。

## 4. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
# 1) 重建并验证有符号真值  2) 跑跨窗选择实验  3) 生成本报告
PYTHONPATH=src python scripts/evaluation/rebuild_longform_signed_gt.py
PYTHONPATH=src python scripts/evaluation/run_cross_window_selection.py
PYTHONPATH=src python scripts/evaluation/report_cross_window_selection.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_cross_window_selection.py
```

