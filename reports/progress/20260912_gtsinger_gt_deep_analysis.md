# GTSinger 真值深度分析（2026-09-12，goal 自由行动轮）

> 本报告全部数字由 `runs/20260912_gtsinger_gt_deep/*.json` 结构化产物生成（`scripts/evaluation/report_gtsinger_gt_deep.py`），不手抄。
> 只读复用 2026-08-16 evaluation_v1 的既有产物，未新增任何 GPU 前向。

## 0. 数据面板

- 段落：159 个 GTSinger 片段（gtsinger_ZH-Alto-1, gtsinger_ZH-Tenor-1；技法族 Glissando, Mixed_Voice_and_Falsetto, Pharyngeal；分组 Control_Group, Falsetto_Group, Glissando_Group, Mixed_Voice_Group, Paired_Speech_Group, Pharyngeal_Group）
- 逐单元证据行：57,960（面板内）/ 63,828（含 window 机制消融小集）；标注配置 3 模型 × 2 音频标签 × 2 规划模式 × 2 解码管线
- 单元总数（去重配置后每个 item 平均 154.5 行/段/run）；计数不一致被跳过的配置：0（缺文件 780）
- 口径：`both_abs_err = max(|start_err|,|end_err|)`，命中阈 100/200ms；GT 为 GTSinger word-level JSON（过滤 `<AP>`），段级配对、segment 层面等权（cluster bootstrap）。

## 1. 配置矩阵其实是"假因子"（P1 数据完整性）

每段音频 `sha256` 只有 [1] 个不同值：标注为 `mix` 与 `vocal` 的配置**喂的是同一个 wav**（GTSinger 切分只给干声）；mix≡vocal 音频的 item 占比 100%。
- 预测向量层面复算：`mix` vs `vocal` 的起止边界完全相同 100.0%（n=15,957）。
- `full` vs `windowed`：start 一致 100.00%，end 一致 98.60%，任一边界被改动的单元 1.40%（n=15,957）——短片段（单窗口）上 window 规划几乎不激活。
- 结果：标注的 12 个配置每段只剩 **3.52 个不同预测向量**（冗余因子 3.409×）。全矩阵各 run 概览：

| run | items | 标注配置/段 | 实际不同向量/段 | 冗余因子 | mix≡vocal 音频的 item 占比 |
|---|---:|---:|---:|---:|---:|
| `ablation_compress` | 3 | 12.0 | 4.0 | 3.0× | 100% |
| `ablation_rawdec` | 3 | 12.0 | 4.0 | 3.0× | 100% |
| `ablation_rawdec_all` | 18 | 12.0 | 3.833 | 3.13× | 100% |
| `ablation_skip` | 3 | 12.0 | 4.0 | 3.0× | 100% |
| `ablation_strict` | 3 | 12.0 | 4.0 | 3.0× | 100% |
| `diag_all` | 75 | 12.0 | 3.52 | 3.409× | 100% |
| `rawdec_all` | 75 | 12.0 | 3.547 | 3.383× | 100% |
| `regression_official_all` | 84 | 12.0 | 3.357 | 3.574× | 100% |
| `regression_rawdec_all` | 84 | 12.0 | 3.5 | 3.429× | 100% |

**含义**：这批 evaluation_v1 矩阵的独立观测数是 3（模型阶梯），不是 12；任何"音频输入 / 规划模式"因子比较在这批数据上都是空比较，且约 3/4 的前向计算是同一输入的重算（GPU 预算浪费）。这把 2026-08-21 的"window 机制消融 inconclusive（短片段上未激活）"从推断升级为可验证事实，并把 `compute_matrix()` 作为入口审计固化下来。

## 2. 模型阶梯与管线的真实效应（配对 + 重采样 CI）

| 因子 | 水平 | hit@100(macro) | hit@200 | MAE start | MAE end | IoU | 零时长率 |
|---|---|---:|---:|---:|---:|---:|---:|
| model | `r0` | 67.9% | 74.0% | 79ms | 153ms | 0.6389 | 4.13% |
| model | `r1` | 88.2% | 92.6% | 51ms | 45ms | 0.7988 | 2.33% |
| model | `r2` | 90.0% | 94.4% | 47ms | 41ms | 0.8119 | 2.15% |
| pipeline | `official` | 81.2% | 86.7% | 61ms | 77ms | 0.7425 | 4.44% |
| pipeline | `raw` | 82.9% | 87.3% | 57ms | 83ms | 0.7573 | 1.29% |

配对差（段级 hit@100，正=a 更好；CI 为段聚类 bootstrap 95%）：

| 对比 | a | b | 均值差 | CI | a 更好格 | b 更好格 | 平 | 符号检验 p |
|---|---|---|---:|---|---:|---:|---:|---:|
| official · r0_vs_r1 | r0 | r1 | -19.89pp | [-21.27, -18.45] | 24 | 500 | 112 | 6.6e-117 |
| official · r1_vs_r2 | r1 | r2 | -1.86pp | [-2.55, -1.19] | 72 | 168 | 396 | 5.1e-10 |
| official · r0_vs_r2 | r0 | r2 | -21.75pp | [-23.29, -20.22] | 36 | 504 | 96 | 1.1e-106 |
| raw · r0_vs_r1 | r0 | r1 | -20.75pp | [-22.15, -19.36] | 8 | 508 | 120 | 1.1e-138 |
| raw · r1_vs_r2 | r1 | r2 | -1.64pp | [-2.29, -1.00] | 72 | 180 | 384 | 7.6e-12 |
| raw · r0_vs_r2 | r0 | r2 | -22.39pp | [-23.88, -20.89] | 12 | 508 | 116 | 4.3e-133 |
| cross · official_vs_raw | official | raw | -1.66pp | [-1.83, -1.51] | 24 | 420 | 1464 | 1.4e-94 |

- 阶梯 `r0→r1` 提升 19.9pp、`r1→r2` 仅 1.9pp：LoRA 之后的边际收益已小于 2pp，继续在同一数据上加训的收益预期要按这个尺度设定。
- 逐单元边界方向：r0 的 end 误差（153ms）远大于 start（79ms），r1/r2 两端对称，说明旧基线的主要缺陷就是尾边界，而非起边界。

## 3. 官方后处理在真值上是净负收益（机制分解）

- 官方管线改动了 5.4% 的单元边界（>0.001s）；raw 管线中 `selected==raw` 的比例 99.3%（即 raw 确实是未后处理的解码输出，二者构成干净的 A/B）。
- 被改动的单元：变差 46.9% vs 变好 24.5%；MAE(both) 由 259ms 升到 305ms（净 47ms）；hit@100 由 60.8% 跌到 27.3%；越界翻转 out/in = 548/24。
- 边界分工：end 端改动 39.2% 修好 vs 2.8% 改坏（且方向以提前为主：moves_earlier 596 vs moves_later 60）；start 端 11.0% 修好 vs **46.1% 改坏**。
- 零时长副作用：official 的零时长率是 raw 的数倍（r2：4.44% vs 1.29%）。
- 置信度无法预判"哪次改动是修复"：被触碰单元上 AUC(低置信→修复) min_margin 0.4408、min_top1 0.4442、max_entropy 0.5226（≈随机）。
- 参考配置 r2/vocal/windowed 同向：改动 5.9%，repair 23.2% vs damage 43.7%，net 65ms。

- **规则定位（无需读源码即可归因）**：被后移的 start 有 98.3% 精确等于**前一单元的 end**（912/936 个是后移，平均 187ms）；被改动的 end 有 56.1% 等于**下一单元的 start**（596/656 个提前，平均 -242ms）。即这是**重叠消解（overlap resolution）**规则：两侧各让一半，同时把零时长率从 raw 的 1.26% 抬到 4.61%。

**含义**：2026-08-16 的 `RAWDEC_FULL_RESULT.md` 已注意到 raw 解码整体更好（+1.8pp），但只归因为"2/75 段小幅回退"。逐单元分解后结论更强：后处理是**系统性**在 start 端把误差推大（连续/单调约束把前一单元的尾端强加给下一单元起点），并在 end 端做正向修剪；因此改造方向不是"整体关掉后处理"，而是**拆开两端**：保留 end 修剪，取消或条件化 start 的强制对齐（且不能用现有 posterior 置信度做门控，AUC≈0.44）。

## 4. 无真值置信信号在真值上的判别力（本项目第一次有真 GT 校准）

单信号 ROC-AUC（预测 `both_abs_err>100ms`；`oriented` 已按方向归一，within = 段内排序 AUC，排除段间难度差）：

| 信号 | 用 GT | AUC(bad100) | AUC(bad200) | within(bad100) |
|---|---|---:|---:|---:|
| `oracle_iou` | 是(oracle) | 0.9447 | 0.9673 | 0.9766 |
| `oracle_dur_ratio_err` | 是(oracle) | 0.9323 | 0.9462 | 0.95 |
| `sig_entropy_max` | 否 | 0.8579 | 0.8828 | 0.861 |
| `sig_entropy_end` | 否 | 0.8167 | 0.8533 | 0.826 |
| `sig_top1_min` | 否 | 0.8053 | 0.8178 | 0.8112 |
| `sig_disagree_loo_both` | 否 | 0.7832 | 0.8159 | 0.804 |
| `sig_model_loo_both` | 否 | 0.7817 | 0.8171 | 0.8029 |
| `sig_model_sd` | 否 | 0.7695 | 0.8019 | 0.7691 |
| `sig_model_range_both` | 否 | 0.7684 | 0.8006 | 0.768 |
| `sig_dur_vs_segment_median_err` | 否 | 0.7647 | 0.8002 | 0.7744 |
| `sig_top1_end` | 否 | 0.7641 | 0.7881 | 0.7748 |
| `sig_entropy_start` | 否 | 0.7615 | 0.7716 | 0.7454 |
| `sig_model_loo_end` | 否 | 0.7232 | 0.7622 | 0.7546 |
| `sig_bmm` | 否 | 0.7218 | 0.7204 | 0.7253 |
| `sig_disagree_loo_end` | 否 | 0.7164 | 0.7556 | 0.7496 |
| `sig_margin_min` | 否 | 0.7083 | 0.7043 | 0.7169 |
| `sig_top1_start` | 否 | 0.7039 | 0.7002 | 0.6938 |
| `sig_margin_end` | 否 | 0.6992 | 0.7096 | 0.7073 |
| `sig_margin_start` | 否 | 0.6512 | 0.6387 | 0.6419 |
| `sig_model_loo_start` | 否 | 0.621 | 0.6187 | 0.6242 |
| `sig_disagree_loo_start` | 否 | 0.6073 | 0.5969 | 0.6041 |
| `sig_gap_to_next_start` | 否 | 0.5739 | 0.5776 | 0.5974 |
| `sig_zero_dur` | 否 | 0.5721 | 0.5737 | 0.5715 |
| `sig_raw_selected_shift` | 否 | 0.5513 | 0.5436 | 0.5494 |
| `sig_raw_selected_maxshift` | 否 | 0.5513 | 0.5436 | 0.5494 |
| `sig_disagree_sd` | 否 | 0.5328 | 0.5335 | 0.523 |

多变量门控（`GroupKFold` 按段分组、one-vs-rest OOF 概率；只喂无真值特征）：

| 特征集 | n | 阳性率 | OOF AUC | AP | ECE | Brier | flag5% 精度 | flag10% 精度/召回 | flag20% 精度/召回 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| posterior_only | 57,960 | 0.1754 | 0.8623 | 0.6034 | 0.0305 | 0.102 | 0.7819 | 0.6756/0.3851 | 0.5438/0.62 |
| disagreement_all_cells | 57,960 | 0.1754 | 0.7891 | 0.5337 | 0.0459 | 0.115 | 0.6439 | 0.6605/0.3765 | 0.5155/0.5877 |
| disagreement_per_model | 14,490 | 0.1754 | 0.7694 | 0.6329 | 0.0158 | 0.0964 | 0.9558 | 0.8075/0.4603 | 0.5097/0.581 |
| structural_only | 54,144 | 0.1719 | 0.7815 | 0.5393 | 0.0329 | 0.1131 | 0.7314 | 0.6343/0.3689 | 0.4953/0.5763 |
| posterior+disagreement | 14,490 | 0.1754 | 0.8914 | 0.744 | 0.0127 | 0.0803 | 0.9586 | 0.842/0.4799 | 0.6211/0.7081 |
| all_no_gt | 13,536 | 0.1719 | 0.9132 | 0.7893 | 0.01 | 0.0687 | 0.9601 | 0.8966/0.5217 | 0.6468/0.7525 |
| oracle_reference_uses_gt | 57,960 | 0.1754 | 0.9485 | 0.8116 | 0.0126 | 0.0576 | 0.9144 | 0.9462/0.5393 | 0.707/0.8061 |

- 原始 top-1 概率**系统性欠自信**：start 均值 0.7275 对应实测命中率 0.9112（gap -0.1838，ECE 0.1838）；end 同理（0.6855 vs 0.8816，ECE 0.1962）。十分位可靠性曲线单调，说明排序信息有效、只有水平错位 → 一次重标定即可当作阈值使用（与 detector-v2 在合成扰动上得到的 isotonic ECE 0.26→0.013 同向，这次是在**真演唱真值**上复现）。
- 最强单信号是 **end 边界熵**（AUC 0.8579），优于 top-1 概率与 margin（0.80/0.71 级）；跨模型分歧（每模型一格、LOO）AUC 0.7817，段内中位时长自一致 0.7647。注意 §1 的教训：若不先去重而直接对 12 格做 LOO，分歧被自身重复格稀释（LOO(全格) 0.7832 vs 去重后 0.7817，且 AUC 表观差异掩盖了幅度偏差）。

## 5. 误差结构：错误不是独立噪声，而是"区域"

- 全面板单元坏率 17.5%；坏单元连续成段：mean run 1.665，max 11，**67.6% 的坏单元落在长度≥2 的连续段里**。
- 与 i.i.d. 零模型（几何分布）对照，长游程严重超额：

| 游程长度 | 观测 | i.i.d. 期望 | 超额倍数 |
|---:|---:|---:|---:|
| 1 | 3296 | 5036.47 | 0.7× |
| 2 | 2144 | 883.55 | 2.4× |
| 3 | 392 | 155.0 | 2.5× |
| 4 | 140 | 27.19 | 5.1× |
| 5 | 80 | 4.77 | 16.8× |
| 6 | 16 | 0.84 | 19.0× |
| 7 | 8 | 0.15 | 53.3× |
| 8 | 8 | 0.03 | 266.7× |
| 9 | 16 | 0.0 | — |
| 11 | 8 | 0.0 | — |

- **段首是双峰问题，不是"塌陷"**：GTSinger 片段第一单元的 GT start 100% 为 0.0，所以预测 start=0 属于"免费正确"；74.8%（119/159）的段首确实输出 0.0，其 hit@100 = 88.2%；剩下 40 段（25.2%）凭空插入平均 518ms 的起始留白，hit@100 只有 5.0%（即便只看 end 边界也只有 62.5%）。因此段首失败模式是**幻觉前奏**：模型在 0 与真实起唱点之间虚构了一段前奏（预测 start 平均被推迟到 518ms），而不是"直接取窗口起点"：需要的是"clip 头部允许从 0 起唱"的先验——这与 long-form 左上下文同属 `startup_vocal_onset_sec` 通道，但修正方向相反。
- **误差机械传染被否证**：预测并非强制连续（start 精确等于前一单元 end 的仅 1.1%，而 GT 本身 94.7% 连续）；start 误差与前驱 end 误差的相关系数 -0.0104，前驱尾错时本单元命中率 92.1% vs 前驱正确时 90.5%。所以 §游程聚簇不是连续性约束造成的机械传染。
- **但也不是"难单元天然扎堆"能解释的**：用可观测量（GT 时长、音节结构、音符数、位置、技法组）拟合逐单元失败概率（OOF AUC 0.7355）做伯努利模拟当零模型 B，它只预测 29.2%（95 分位 30.2%）的坏单元落在长度≥2 的游程里，实测为 67.6%：

| 游程长度 | 观测链数 | 协变量零模型 B 期望 | 超额 |
|---:|---:|---:|---:|
| 1 | 3296 | 7177.35 | 0.46× |
| 2 | 2144 | 1111.78 | 1.93× |
| 3 | 392 | 189.02 | 2.07× |
| 4 | 140 | 32.13 | 4.36× |
| 5 | 80 | 6.51 | 12.29× |
| 6 | 16 | 1.57 | 10.17× |
| 7 | 8 | 0.28 | 28.07× |
| 8 | 8 | 0.05 | 160.0× |
| 9 | 16 | 0.0 | 6400.0× |

  长度≥4 的游程超额 4–160×，9 连错观测 16 次而零模型期望 ≈0：真值误差带有超出可观测难度的**局部区域结构**，这是区域级（而非单元级）realign 迄今最直接的实证依据。
- **零声母音节**更难：单音素音节 hit@100 72.0% vs 多音素 93.3%；与段首交叉后两者独立叠加：

| 单音素音节 | 非段首 | n | hit@100 | MAE start |
|---|---|---:|---:|---:|
| 0 | False | 77 | 36.4% | 259ms |
| 0 | True | 391 | 79.0% | 96ms |
| 1 | True | 1865 | 93.2% | 34ms |
| 1 | False | 82 | 96.3% | 10ms |

- 分组难度（r2/vocal/windowed/official）：

| 组 | n | hit@100 | MAE both | 均值 GT 时长 |
|---|---:|---:|---:|---:|
| `Paired_Speech_Group` | 802 | 83.4% | 86ms | 0.231s |
| `Falsetto_Group` | 171 | 88.9% | 81ms | 0.534s |
| `Pharyngeal_Group` | 157 | 89.2% | 56ms | 0.728s |
| `Mixed_Voice_Group` | 172 | 90.7% | 97ms | 0.544s |
| `Glissando_Group` | 393 | 91.9% | 46ms | 0.489s |
| `Control_Group` | 720 | 93.9% | 51ms | 0.548s |

- 时长桶上最差的不是最短音符而是 **0.6–1.0s** 桶（hit@100 77.4%，n=252），且该桶 start 误差（111ms）显著大于 end；拖长音的起始定位是主要失分点。
- 技法标记本身不是难点：glissando/mix/falsetto/pharyngeal 单元命中率与总体持平或更高（见 `STRUCTURE.json:by_technique_flag`），难度主要来自**朗读段（Paired_Speech）**、段首与零声母。

## 6. 科学边界

- GT 为 GTSinger word-level 标注（含音素/音符/技法旗标），未做人工二次校正；`<AP>` 已按既有口径过滤。
- 片段长度 5–15s、单段基本一个窗口，故本报告的"模式/音频因子无效"结论**只适用于短片段矩阵**，不能外推到真实长歌；但至少说明既有 evaluation_v1 结果里不存在"混音 vs 分离"证据。
- 仅 2 位歌手（ZH-Tenor-1 / ZH-Alto-1）、2 首歌曲，段内相关已由段聚类 bootstrap 处理，跨歌手/跨曲泛化未测。
- "后处理净负"以 100ms 命中为尺度；若产品口径只看视觉卡拉OK跟唱（±200ms 级），其代价会小得多——两种口径都要报，不能互相替换。
- 门控模型是**诊断用**：特征与标签同源同数据、按段分组 CV，未在任何新数据上验证；不得据此宣称可用于 checkpoint 选择或真实 writeback（realign 仍 shadow-only）。

## 7. 下一步（按性价比）

1. **入口审计**：把 `compute_matrix()` 接进 evaluation 批次收尾（同 run 内若某因子的音频 sha 或预测向量重合，直接标记该因子 `not_identified` 并拒绝输出"效应"），避免再花 GPU 跑空因子。
2. **后处理拆分**：只保留 end 修剪、去掉 start 强推，在**同一 159 段真值面板**上复评（纯 CPU，产物已在 `unit_evidence.jsonl.gz`，改后处理只需重放 `alignment.selected/raw`）。
3. **段首/零声母专项**：两个独立单因素消融——(a) `startup_vocal_onset_sec` 先验（clip 头部禁止虚构前奏，或在 t<0.6s 内收紧 onset 判定）；(b) 零声母音节的左侧上下文。评价指标直接用 §5 的分层命中率（段首桶、单音素桶、段首×单音素桶），不要用总体均值：这两类合计只占 6.6% 的单元，总体均值会把它们冲淡到看不见。
4. **真·音频输入因子**：需要混音对照就必须自造 mix（GTSinger 只有干声：叠加伴奏/噪声），或在带伴奏的真实流行曲（MIR-1K/AMLL-TTML/PJS）上另建 GT 面板。
5. **门控落地**：`all_no_gt` 组合在 20% 复核预算下精度 0.65/召回 0.75，可作为 realign 触发器候选；先在既有 long-slot/serial 管线上做 shadow 记账（不改写回），并用 `sig_gap_to_next_start`/首单元位置这类结构化特征补强。

## 8. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/extract_gtsinger_unit_evidence.py \
    --preset gtsinger --out-root /home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep
PYTHONPATH=src python scripts/evaluation/analyze_gtsinger_gt_deep.py
PYTHONPATH=src python scripts/evaluation/report_gtsinger_gt_deep.py \
    --out reports/progress/20260912_gtsinger_gt_deep_analysis.md
```

- 证据面板：`/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz`（7.9 MB，sha256 `453e0e769aee5ab1…`）
- 分析产物：`EFFECTS.json` `SIGNALS.json` `STRUCTURE.json` `MATRIX_AUDIT.json` `POSTPROCESS.json` `ABLATION.json`；抽取自检：`SUMMARY.json` / `SKIPPED.json`。
- 轻量指标（canonical source 候选）：`results/by_run/20260912_gtsinger_gt_deep/metrics.json`。

