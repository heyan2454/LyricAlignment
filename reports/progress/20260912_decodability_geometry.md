# 不可达真值在哪：候选之间还是跨度之外？以及偏置能不能跨域（第 21 轮，2026-09-12）

> 数字由 `20260912_decodability_ceiling/GEOMETRY.json` 生成（格点 0.08s）。只读既有面板、零前向。
> 纪律：结论依据是 GTSinger（人工真值、非 test）；MIR-1K（test-only）只用于报告**它自身偏置的方向**，不用于任何校准。

## 0. 结论：两条看似自然的省算力路径都被关掉了

- **(a) 「在两候选之间插值」不可行**：不可达时**候选跨度中位数只有 0.08s（1 格）**，所以真值几乎从不在两候选之间——全体不可达里只有 9.7% 在跨度内、长音只有 4.0%；**96.0% 的长音不可达情形落在跨度之外**（外移距离中位 0.8s）。⇒ top-1/top-2 是**相邻格点**，重排/插值不可能造出真值。
- **(b) 「全局偏置修正」不可跨域迁移**：长音端点偏置方向在两个域**相反**——录音室（GTSinger r2）中位 **-40.0ms**、偏晚比例 0.239（**截早**）；真实伴奏（MIR-1K r2_full）中位 **+32.4ms**、偏晚比例 0.741（**拖晚**）；两者 late-share 差 **0.502** ⇒ NOT transferable: the two domains err in opposite directions, so a global offset calibrated on one would hurt the other
- 末单元更极端：GTSinger 的 last_unit 不可达情形 **100% 落在跨度右侧**（真值比两个候选都晚），偏置中位 -30.0ms、偏晚比例仅 0.096 ⇒ 录音室里模型**系统性截断拖长音的尾巴**；而首单元不可达 78.5% 偏左⇒ 与硬裁片段起点一致。
- 合起来：**长音尾边界不是「选错了」，而是「候选里根本没有，而且两个域错向相反」**；能往前走的两件事仍然是（i）训练信号（第 19 轮已证可把长音不可达率 70.8%→21.7%）、（ii）产生新候选的重解码（更长右上下文；且**必须按域分别验证**，不能共用一条修正规则）。

## 1. 不可达几何（端点，±1 格容差；GTSinger 人工真值）

| 层 | 单元 | 不可达率 | 在跨度之间 | **在跨度之外** | 偏左 | 偏右 | 候选跨度中位 | 外移距离中位 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all_units | 30,600 | 6.0% | 9.7% | **90.3%** | 44.2% | 46.1% | 0.08s | 0.32s |
| long_note | 1,440 | 20.6% | 4.0% | **96.0%** | 10.8% | 85.1% | 0.08s | 0.8s |
| short_note | 14,340 | 2.9% | 7.7% | **92.3%** | 79.8% | 12.5% | 0.08s | 0.24s |
| first_unit | 2,016 | 18.4% | 11.8% | **88.2%** | 78.5% | 9.7% | 0.08s | 0.32s |
| last_unit | 2,016 | 9.9% | 0.0% | **100.0%** | 0.0% | 100.0% | 0.08s | 0.4s |

起点侧对照（首单元不可达全部偏左 ⇒ 片段被硬裁、模型无法预测到裁剪点之前）：

| 层 | 不可达率 | 在跨度之间 | 偏左 | 偏右 |
|---|---:|---:|---:|---:|
| all_units | 4.5% | 10.2% | 79.3% | 10.5% |
| long_note | 8.9% | 18.8% | 68.8% | 12.5% |
| short_note | 3.0% | 9.3% | 82.2% | 8.4% |
| first_unit | 21.2% | 0.0% | 100.0% | 0.0% |
| last_unit | 1.8% | 22.2% | 66.7% | 11.1% |

## 2. 偏置方向对照（pred − 人工真值，端点）

| 域 / 层 | 单元 | 中位 | 均值 | 偏晚比例 |
|---|---:|---:|---:|---:|
| GTSinger r2（录音室清唱） · all_units | 30,600 | -10.0ms | -30.1ms | 39.8% |
| GTSinger r2（录音室清唱） · long_note | 1,440 | -40.0ms | -273.4ms | 23.9% |
| GTSinger r2（录音室清唱） · short_note | 14,340 | -10.0ms | -4.3ms | 38.4% |
| GTSinger r2（录音室清唱） · first_unit | 2,016 | +0.0ms | -2.4ms | 45.8% |
| GTSinger r2（录音室清唱） · last_unit | 2,016 | -30.0ms | -171.2ms | 9.6% |
| MIR-1K r2_full（真实伴奏） · all_units | 2,035 | +2.6ms | +7.7ms | 51.9% |
| MIR-1K r2_full（真实伴奏） · long_note | 112 | +32.4ms | +45.2ms | 74.1% |
| MIR-1K r2_full（真实伴奏） · short_note | 1,246 | +0.0ms | +1.9ms | 48.3% |
| MIR-1K r2_full（真实伴奏） · last_unit | 17 | +20.0ms | +101.4ms | 70.6% |
| MIR-1K r2_full（真实伴奏） · first_unit | 17 | +2.9ms | +7.7ms | 52.9% |

- 机判结论：`same_direction = False`，late-share 差 0.502。
- 这条同时**回收了第 11 轮的疑问**：当时声学衰减阈值的最优 θ 在两个域之间不可迁移（导出 θ=0.15 迁移后 −13.4pp）；现在能看到根因不是阈值选错，而是**两个域的端点误差本身方向相反**。

## 3. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_decodability_geometry.py
PYTHONPATH=src python scripts/evaluation/report_decodability_geometry.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_decodability_geometry.py
```

