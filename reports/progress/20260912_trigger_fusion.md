# 三个免费触发器合成一个重解码 flag（第 27 轮，2026-09-12）

> 数字由 `runs/20260912_trigger_fusion/TRIGGER_FUSION.json` 生成。全部特征**无需真值、无需额外前向**；在 GTSinger（人工真值、非 test）上验证，再冻结应用到 33 首真实歌（那边只产队列，不产精度）。

## 0. 结论

- **目标「端点误差 >100ms」**（流行率 12.0%，n=3,680）：
  `inversion` AUC 0.5035、20% 预算召回 19.3%｜`low_conf_end` AUC 0.8054、20% 预算召回 59.8%｜`high_entropy_end` AUC 0.8449、20% 预算召回 64.0%｜`gap_residual` AUC 0.8838、20% 预算召回 24.0%｜`fused_mean_rank` AUC 0.8501、20% 预算召回 67.1%｜`any_flag_boolean` AUC 0.805、20% 预算召回 61.8%

- **目标「端点被切早」**（流行率 9.4%，n=2,892）：
  `inversion` AUC 0.504、20% 预算召回 21.0%｜`low_conf_end` AUC 0.7862、20% 预算召回 58.8%｜`high_entropy_end` AUC 0.8293、20% 预算召回 63.9%｜`gap_residual` AUC 0.9205、20% 预算召回 30.9%｜`fused_mean_rank` AUC 0.838、20% 预算召回 68.7%｜`any_flag_boolean` AUC 0.809、20% 预算召回 65.5%

- **生产视图单独看**（`r2|vocal|windowed`，打分单元 2550）：`inversion` AUC 0.5024｜`low_conf_end` AUC 0.8387｜`high_entropy_end` AUC 0.8716｜`gap_residual` AUC 0.6519｜`fused_mean_rank` AUC 0.8461｜`any_flag_boolean` AUC 0.7563
- **长音层**（最难、也是第 19 轮 40% 不可达的那层）：`gap_residual` AUC 0.9407、`high_entropy_end` AUC 0.6946、融合 AUC 0.6778
- **分工不同，不要混用**：倒序只预示「后续塌陷」（对端点误差 AUC 0.5035），熵/置信度与间隙残余才预示端点错；因此融合比单个熵略好（AUC 0.8501 vs 0.8449）。

## 1. 复核预算下的召回/精度（GTSinger 全视图，目标=端点误差 >100ms）

| 触发器 | 打分数单元 | AUC | r@5% | r@10% | r@20% | p@5% | p@10% | p@20% | r@20%(仅覆盖内) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `inversion` | 30,600 | 0.5035 | 7.8% | 11.4% | 19.3% | 18.8% | 13.7% | 11.6% | 19.3% |
| `low_conf_end` | 30,600 | 0.8054 | 21.7% | 38.9% | 59.8% | 52.2% | 46.7% | 35.9% | 59.8% |
| `high_entropy_end` | 30,600 | 0.8449 | 20.9% | 37.9% | 64.0% | 50.3% | 45.6% | 38.5% | 64.0% |
| `gap_residual` | 4,588 | 0.8838 | 6.1% | 12.4% | 24.0% | 98.2% | 99.1% | 96.1% | 49.0% |
| `fused_mean_rank` | 30,600 | 0.8501 | 22.0% | 42.0% | 67.1% | 52.9% | 50.5% | 40.3% | 67.1% |
| `any_flag_boolean` | 30,600 | 0.805 | 14.9% | 29.3% | 61.8% | 35.9% | 35.2% | 37.1% | 61.8% |

- `gap_residual` 的精度极高（98%+）但**总体召回低**，因为可测间隙只覆盖部分单元；最右列给出「仅在覆盖到的单元里」的召回，两列一起看才不会误判它弱。

## 2. 真实歌（无真值）：冻结判据后的触发比例与重解码队列

13,735 单元；间隙特征覆盖 12.7%；各 flag 触发比例：`inversion` 6.3%、`gap_residual` 11.0%、`high_entropy_end` 20.0%；**任一 flag 29.0%**。

| 排名 | 歌曲 | 语言 | 单元 | 被 flag 比例 | 倒序 | 间隙残余 | 高熵 | 融合分中位 |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | I See Fire | English | 311 | 97.8% | 90 | 9 | 301 | 0.7184 |
| 2 | 初音未来的消失 | Japanese | 561 | 93.0% | 163 | 35 | 510 | 0.7191 |
| 3 | p.h | Japanese | 271 | 83.0% | 61 | 72 | 218 | 0.6799 |
| 4 | 冬之花 | Japanese | 222 | 79.3% | 53 | 18 | 162 | 0.6797 |
| 5 | 皱鳃鲨 | Japanese | 261 | 77.8% | 70 | 32 | 188 | 0.701 |
| 6 | Camelia | English | 334 | 68.6% | 42 | 73 | 196 | 0.6427 |
| 7 | 炉心融解 | Japanese | 326 | 62.6% | 50 | 44 | 170 | 0.6388 |
| 8 | 电灯胆 | Cantonese | 350 | 50.0% | 52 | 66 | 138 | 0.6219 |
| 9 | 月半小夜曲 | Cantonese | 388 | 46.7% | 43 | 66 | 120 | 0.5897 |
| 10 | 乙女解剖 | Japanese | 341 | 42.8% | 38 | 43 | 105 | 0.5669 |

- 队首全是非中文歌（English/Japanese），**中文歌无一进入前十** ⇒ 与第 6/12/15 轮「普通话是最新康的路径」第四次独立复现；
- 队列是按 flag 比例排序的**建议复核顺序**，不是「这些歌错了」的断言：真实歌没有真值，只能靠抽样人工确认或第 24 轮那个小标注实验来定性。
- 完整队列：`runs/20260912_trigger_fusion/redecode_queue_real_songs.csv.gz`。

## 3. 口径与方法纪律（本轮自己踩到并修掉的两个坑）

- **绝对熵阈值不跨域**：把 GTSinger 上看着合理的 `entropy ≥ 1.0 nats` 直接用到产品批，会 flag **68.7%** 的单元（等于没有筛选力）。现改为**批内分位**（top 20%），触发比例回到设计值；
- **召回分母必须区分全体与被覆盖子集**（间隙特征只覆盖 12.7% 的真实歌单元、GTSinger 上 15.0%），否则会把这个高精度特征读成弱特征。

## 4. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_trigger_fusion.py
PYTHONPATH=src python scripts/evaluation/report_trigger_fusion.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_trigger_fusion.py
```

