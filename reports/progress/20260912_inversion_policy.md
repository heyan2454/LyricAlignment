# 倒序处理策略决策简报（第 18 轮，2026-09-12）——**没有局部策略是净赢**

> 数字由 `runs/20260912_inversion_policy/{INVERSION_POLICY,STRUCTURAL_CONSEQUENCE}.json` 生成。
> **shadow-only**：只在既有面板上逐单元施加策略并度量，未改任何生产行为、未回写。

## 0. 一句话结论

- 倒序单元**救不回来**：人工真值上最好的局部策略（交换端点）hit@100 也只有 10.5%（现状 0.0%），MAE(end) 465.2ms；弱真值 M4 上所有策略都是 0.0%。
- 交换端点**在结构上是净亏**：真实歌上非法率 16.72% → 19.64%（重叠 0.10%→6.19%、回退 0.07%→3.28%），因为倒序幅度中位 2.48s、p90 65.52s，交换后区间会**吞掉邻居**。
- **可行组合**：把倒序当作**重解码触发器**（代价：真实歌 6.33% 单元、M4 1.161%、GTSinger 0.229%）+ 全局联合求解保结构（swap 后再求解：非法率 0.01%）。

## 1. 有真值处：策略对**正确率**的影响（只施加在倒序单元上）

### GTSinger `pipeline=raw`（人工词级真值，33,228 单元，倒序 76 个）

| 策略 | hit@100 | MAE(start) | MAE(end) | 偏置(end) | 零长率 |
|---|---:|---:|---:|---:|---:|
| `P1_swap_endpoints` | 10.5% | 683.6ms | 465.2ms | -366.2ms | 0.0% |
| `P3_min_duration_floor` | 10.5% | 683.6ms | 618.3ms | -598.3ms | 0.0% |
| `P2_midpoint` | 5.3% | 647.8ms | 545.2ms | -507.3ms | 100.0% |
| `P0_shipped_clamp_to_zero` | 0.0% | 613.6ms | 465.2ms | -366.2ms | 100.0% |
| `P4_floor_from_previous_end` | 0.0% | 1239.4ms | 1172.5ms | 392.7ms | 0.0% |

### M4 长时序（弱真值·签名重建，134,538 单元，倒序 1,562 个，1.161%）

| 策略 | hit@100 | MAE(end) | 偏置(end) |
|---|---:|---:|---:|
| `P4_floor_from_previous_end` | 1.09% | 4329ms | 619ms |
| `P0_shipped_clamp_to_zero` | 0.00% | 4055ms | 1263ms |
| `P1_swap_endpoints` | 0.00% | 4055ms | 1263ms |
| `P2_midpoint` | 0.00% | 4440ms | -311ms |
| `P3_min_duration_floor` | 0.00% | 5143ms | -1836ms |

- M4 按 split 的倒序数：{"test": 258, "train": 1056, "validation": 248}（train 占多数，但**验证/测试 split 同样有** ⇒ 这不是可以靠重训偶然消失的噪声）。
- 注意 `P4_floor_from_previous_end`（用上一单元尾端定起点）在两个面板上都是**最差**（GTSinger MAE(end) 1172ms、偏置转正）⇒ 不要用「邻居顺延」猜测倒序单元的位置。

## 2. 无真值处：策略对**结构合法性**的影响（33 首真实歌）

13,735 单元 / 倒序 870（6.33%），倒序幅度中位 2.48s、p90 65.52s

| 策略 | 零长/负长 | 重叠下一单元 | 起点回退 | 超长 | **非法合计** |
|---|---:|---:|---:|---:|---:|
| `P0_shipped` | 16.28% | 0.10% | 0.07% | 0.37% | **16.72%** |
| `P1_swap` | 11.95% | 6.19% | 3.28% | 3.25% | **19.64%** |
| `P3_min_floor` | 11.95% | 5.23% | 3.28% | 0.31% | **19.02%** |
| `P1_swap_then_joint_solve` | 0.00% | 0.00% | 0.00% | 0.01% | **0.01%** |

- 现状（钳成零长）非法率 16.72%；交换端点 **19.64%（更差）**；最小时长下限 19.02%（也更差）；交换 + 全局联合求解 **0.01%**。
- 读法：局部策略只是把一种非法形态换成另一种；**结构合法性必须由全局约束保证**，而**正确性**要靠重解码（这两件事不要指望同一个手段完成）。

## 3. 给你的三个决定点（我已测好代价，未替你改行为）

1. **是否把 raw 起止倒序升级为重解码触发条件**？收益：这些单元现在 100% 错（人工真值面板），且后来塌陷率 lift 8–10×（第 15 轮）；代价：触发比例真实歌 6.33%、M4 1.161%、GTSinger 0.229%。
2. **是否放弃「交换端点」这一看似自然的修补**？数据说放弃：结构更差、正确率仍≈0。
3. **交付 gate 是否采用第 17 轮的伴生列口径**（`hit@tol_excluding_degenerate` + `degenerate_share`）？如果不采用，跨系统比较会持续把退化率差异误读成精度差异。

## 4. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_inversion_policy_brief.py
PYTHONPATH=src python scripts/evaluation/report_inversion_policy.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_inversion_policy.py
```

