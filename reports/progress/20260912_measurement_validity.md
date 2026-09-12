# 测量有效性：已报出的边界精度里有多少是在测钳位而不是模型（第 17 轮，2026-09-12）

> 数字由 `runs/20260912_measurement_validity/MEASUREMENT_VALIDITY.json` 生成；只重读既有面板，不改指标口径（仍用 canonical `both_abs_err = max(|start_err|,|end_err|)`），零新增前向。

## 0. 结论

- **同一处静默钳位也在评测链路里**：GTSinger `official` 面板 raw 阶段有 0.248% 起止倒序，而交付阶段倒序恒为 0、零长从 1.02% 升到 4.44%（多出 1,048 个）。
- **污染界有界但不可忽略**：GTSinger(official) hit@100 80.37% → 剔除退化单元后 83.68%，**差 +3.31pp**；MIR-1K 77.10% → 80.31% （**+3.21pp**）。⇒ 本会话前几轮的绝对数值应理解为**含退化单元的保守下界**；跨系统比较仍成立，但**差距小的比较必须补这一列**。
- **跨预测器不等量**（最重要的一条）：见 §2 表——base 无 LoRA 的预测器退化率 20.2%，剔除后 +5.38pp；而 LoRA 检查点只有 +0.23~+0.54pp。⇒ 用 hit@100 做「集成成员弱排除」（第 4/5 轮方法）时，被排除者**同时**背着退化率与边界误差两个原因；不过结论方向不变（27.7% 仍远低于阈值 45.7%，见 §2 末行）。
- **真实伴奏歌受影响最大**：raw 倒序 6.33% → 交付倒序 0%、零长 4.46% → 16.28%（钳位多出 1,623 个零长）。

## 1. 各面板的阶段形状

| 面板 | 行数 | 阶段 | 倒序率 | 零长率 | 钳位在链路中？ |
|---|---:|---|---:|---:|---|
| `gtsinger_official` | 30,600 | model_raw_slots | 0.248% | 1.02% | **是** |
| `gtsinger_official` | 30,600 | shipped_pred | 0.000% | 4.44% | **是** |
| `gtsinger_raw` | 33,228 | model_raw_slots | 0.229% | 1.03% | 否 |
| `gtsinger_raw` | 33,228 | shipped_pred | 0.114% | 1.15% | 否 |
| `mir1k` | 12,210 | shipped_pred | 0.000% | 4.05% | — |
| `mir1k` | 12,210 | human_gt | 0.000% | 0.00% | — |
| `m4_longform` | 134,538 | model_raw_slots | 1.161% | 1.00% | — |
| `real_songs_33` | 13,735 | model_raw_slots | 6.334% | 4.46% | **是** |
| `real_songs_33` | 13,735 | shipped_selected | 0.000% | 16.28% | **是** |

说明：`pipeline=raw` 的 GTSinger 面板**保留**倒序（不经压缩钳位），其 38 个倒序单元 hit@100 = 0.0%、MAE(end) 654.6ms ⇒ 倒序单元本身就是灾难单元，钳位只是把它们变成「没有时间长度的字」，并没有让它们变对。

## 2. 污染界（剔除零长单元后的同一指标）

| 面板 / 预测器 | n | hit@100 | 剔除退化后 | 差(pp) | 退化率 | MAE(end) | 剔除后 MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gtsinger_official` | 30,600 | 80.37% | 83.68% | +3.31 | 4.44% | 72.2ms | 69.7ms |
| `gtsinger_raw` | 33,228 | 82.42% | 83.13% | +0.71 | 1.15% | 75.2ms | 73.5ms |
| `mir1k` | 12,210 | 77.10% | 80.31% | +3.21 | 4.05% | 179.7ms | 143.0ms |
| MIR-1K `base_qwen_raw_v1` | 2,035 | 22.31% | 27.69% | +5.38 | 20.15% | 837.2ms | 740.9ms |
| MIR-1K `r0_raw_20260724` | 2,035 | 74.40% | 76.14% | +1.74 | 2.36% | 95.0ms | 91.4ms |
| MIR-1K `r1_full_20260724` | 2,035 | 91.15% | 91.56% | +0.41 | 0.44% | 37.6ms | 36.4ms |
| MIR-1K `r2_full_20260723` | 2,035 | 91.45% | 91.99% | +0.54 | 0.59% | 35.8ms | 34.8ms |
| MIR-1K `r2_ood_20260723` | 2,035 | 92.04% | 92.27% | +0.23 | 0.25% | 37.4ms | 37.2ms |
| MIR-1K `r2_seed_20260724` | 2,035 | 91.25% | 91.70% | +0.45 | 0.49% | 35.4ms | 34.6ms |

- **方法稳健性复核**：第 4/5 轮用「hit@100 < ½ 参考」排除弱成员。base 剔除退化后为 27.69%，参考为 91.99%，阈值 46.00% ⇒ **排除结论不变**（但当时它同时背着退化率，这个信息当时没被分开看）。

## 3. 对口径的处置建议（不改历史数字，只加伴生列）

- 在**面板级**报告里为每个 hit@tol 增设伴生列 `hit@tol_excluding_degenerate` 与 `degenerate_share`（本模块已可计算，接进 `audit_batch.py` 与后续面板即可）。
- 解释规则写死：**若两个系统的退化率之差 > 1pp，则它们的 hit@100 差距不可直接归因于边界精度**。
- 历史面板（本会话 runs/20260912_*）保持原样不重算，本报告即为它们的有效性附注。

## 4. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_measurement_validity.py
PYTHONPATH=src python scripts/evaluation/report_measurement_validity.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_measurement_validity.py
```

