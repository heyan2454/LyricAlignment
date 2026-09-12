# 是信号弱还是标签粗？量化感知 AUC 诊断（第 31 轮，2026-09-12）

> 数字由 `runs/20260912_label_noise_ceiling/LABEL_NOISE.json` 生成；只读既有面板，零前向。
> 动机：第 30 轮用 M4Singer 复现触发器失败（熵 AUC 0.662 vs GTSinger 0.845）。但两个语料的标签与**质量层**都不同，单个 AUC 无法区分原因。

## 0. 三条结论

### (1) M4Singer **不是可比的复现语料**（对第 30 轮的更正）

- M4 面板（研究用 detector_v2 拼接时间线）中位误差 **525.0ms**，误差>100ms 流行率 **96.4%**；GTSinger 中位 **40.0ms**、流行率 **19.6%**。
- 也就是说 M4 上**几乎所有单元都错**（96.4%），判别任务退化成「在普遍错的里面排先后」；因此第 30 轮对 `gap_over_core` 的否证**证据强度要下调**：结论仍是「除 GTSinger 外无正证据 ⇒ 不上线」，但不能再表述为『已被独立语料证伪』。

### (2) 100ms 阈值本身被 80ms 格点污染（影响全项目 headline 口径）

- 落在阈值 ±1 个量化格（±80ms）内的单元：GTSinger **22,458 个（73.4%）**、M4 547（12.9%）。
- 剔除这些「标签可能被量化翻转」的单元后，同一个分数的 AUC：GTSinger 0.7993 → **0.8662**（Δ +0.0669）；M4 0.6619 → 0.7003（Δ +0.0384）。
- 为什么 GTSinger 比例这么高：其**中位误差 40.0ms 远小于量化格 80ms**，于是大量单元挤在 100ms 判定线附近。⇒ **任何以 100ms 为界的判别力评估都会系统性低估真实判别力**；detector_v2 的 SAFE ≤100ms 带正落在这个区间内（第 20 轮已给出 50ms 侧的同类警告）。

### (3) 判别力随容差单调上升 ⇒ 触发器擅长抓「粗错」，不擅长抓边缘错

| 容差 | GTSinger 流行率 | GTSinger AUC | M4 流行率 | M4 AUC |
|---|---:|---:|---:|---:|
| 80ms | 24.6% | 0.7763 | 97.9% | 0.6914 |
| 100ms | 19.6% | 0.7993 | 96.4% | 0.6619 |
| 120ms | 16.8% | 0.8218 | 94.0% | 0.6572 |
| 160ms | 14.2% | 0.8353 | 89.6% | 0.6681 |
| 200ms | 12.8% | 0.8435 | 84.5% | 0.683 |
| 250ms | 10.9% | 0.8525 | 78.8% | 0.6876 |

## 1. 分层（同一分数、同一目标，只看标签最可信的子集）

| 语料 / 切片 | 单元 | 流行率 | 中位误差 | AUC(熵) |
|---|---:|---:|---:|---:|
| M4 · all | 4,241 | 96.4% | 525.0ms | 0.6619 |
| M4 · baseline_legal_only | 515 | 97.1% | 438.2ms | 0.6273 |
| M4 · train_split | 2,827 | 95.8% | 479.1ms | 0.6763 |
| M4 · validation_split | 767 | 97.3% | 565.7ms | 0.6392 |
| M4 · unambiguous_neighbours | 278 | 97.8% | 418.4ms | 0.7586 |
| M4 · long_note | 138 | 100.0% | 1308.4ms | None |
| GTSinger · all | 30,600 | 19.6% | 40.0ms | 0.7993 |
| GTSinger · production_view | 2,550 | 12.0% | 40.0ms | 0.7888 |
| GTSinger · long_note | 1,440 | 43.1% | 80.0ms | 0.7132 |

- M4 上**邻居无歧义**（下一单元起点距本单元终点 ≥240ms）子集 AUC 升到 0.7586（vs 全体 0.6619）⇒ 与 (2) 同向：边界越含糊，标签噪声吃掉的判别力越多；
- 但 M4 `baseline_legal_only`（未被拼接/伪造的原始时间线）AUC 只有 0.6273 ⇒ 标签质量分层解释不了全部差距，**语料差异（录音条件/曲风/单元长度）仍在**，不能声称熵的跨语料一致性已被证明。

## 2. 对既有产物的动作

- 索引 B37（触发器复现失败）加 ♻️ 限定：**不是被独立语料证伪，而是该语料不可比**；
- 清单新增一条：**报判别力/AUC 时必须同时报标签流行率、量化歧义比例与容差敏感性**；
- 第 29 轮预算表口径不变（其结论建立在 GTSinger 自身口径上），但引用时应注明「100ms 阈值下的 AUC 是保守值」。

## 3. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_label_noise_ceiling.py
PYTHONPATH=src python scripts/evaluation/report_label_noise_ceiling.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_label_noise_ceiling.py
```

