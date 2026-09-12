# 把学到的放行率搬到 33 首真实歌：无真值下的结构审计（第 39 轮，2026-09-12）

> 数字由 `runs/20260912_gate_batch_application/GATE_BATCH_APPLICATION.json` 生成。**本批没有真值**：绝对熵阈值不跨域（第 27 轮：GTSinger 上合理的阈值在产品批会 flag 68.7%），所以这里按 GTSinger 学到的**放行率**做批内分位匹配；被放行集合只审计**结构安全**，不构成任何精度声明。零新前向、零 GPU。

## 0. 结论

- 整批 13,735 单元里零长/负长占 **16.28%**、结构非法合计 **16.72%**（第 12 轮同一口径）。
- **R1（只用边界熵，放行 76.30%）**：被放行集合零长 **5.10%** vs 被拦集合 **52.26%**（lift +47.1pp）；即 **76% 的零长单元被集中到 23.7% 的复核队列里**。
- **R3（加间隙残余，放行 85.01%）**：捕获率降到 **54%**（复核队列仅 15.0%），且被放行集合零长升到 8.74%。
- **无真值的独立警告**：R3 相对 R1 新增放行的 **1,490** 个单元中，**35.7% 是零长单元**（整批平均 16.3%，即 **2.2×**）⇒ 间隙残余在 GTSinger 上的增益**没有迁移到产品批**，与第 30/31 轮跨语料复现失败完全一致；**结构代理在无真值条件下独立否证了 R3 上线**。
- **单一全局阈值 = 按语言分配复核预算**：R1 下普通话放行 **94.1%**、粤语 72.5%、英语 66.1%、日语 27.1% ⇒ 若不希望「日语几乎全部进复核」，需按语言分别标定阈值。

## 1. 两个策略的结构审计

| 指标 | 整批 | R1 放行 | R1 拦下 | R3 放行 | R3 拦下 |
|---|---:|---:|---:|---:|---:|
| `flag_zero_or_negative` | 16.28% | 5.10% | 52.26% | 8.74% | 59.06% |
| `flag_overshoot` | 0.37% | 0.11% | 1.20% | 0.24% | 1.12% |
| `flag_overlaps_next` | 0.10% | 0.05% | 0.28% | 0.06% | 0.34% |
| `flag_start_regression` | 0.07% | 0.02% | 0.22% | 0.05% | 0.15% |
| `is_illegal` | 16.72% | 5.26% | 53.64% | 9.03% | 60.37% |

两档一致部分：both_accept 10,186、R3 新增放行 1,490、R3 撤回 294、Jaccard 0.851；间隙特征在本批覆盖 12.7%（R3 新增放行单元里间隙特征覆盖 15.3%）⇒ R3 大部分时候并没有间隙信息可用，其排序变化主要来自那 12.7% 有值的单元。

## 2. 复核队列集中在哪些歌

| 策略 | 放行率最低的歌（前 5） |
|---|---|
| `r1_entropy` | I See Fire（English，放行 3%）、初音未来的消失（Japanese，放行 7%）、p.h（Japanese，放行 16%）、冬之花（Japanese，放行 23%）、皱鳃鲨（Japanese，放行 23%） |
| `r3_entropy_inversion_gap` | I See Fire（English，放行 22%）、初音未来的消失（Japanese，放行 27%）、皱鳃鲨（Japanese，放行 40%）、p.h（Japanese，放行 49%）、冬之花（Japanese，放行 53%） |

- 这与第 27 轮的重解码队列**同源同序**（I See Fire、初音未来的消失、p.h、冬之花、皱鳃鲨），两个独立构造的清单互相印证 ⇒ 排序稳定；
- 但同样**只是建议复核顺序**，不是「这些歌一定错」。

## 3. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_gate_application_to_batch.py
PYTHONPATH=src python scripts/evaluation/report_gate_batch_application.py
```

