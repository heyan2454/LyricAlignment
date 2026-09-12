# 普通话自然录音真值面板（MIR-1K 人工逐字 GT × 既有预测，2026-09-12 第 4 轮）

> 数字由 `runs/20260912_mir1k_natural_panel/{PANEL_AUDIT,ANALYSIS}.json` 生成，不手抄。
> 纯 CPU：全部复用 2026-07-22/24 已落盘的预测与人工标注，零新增前向。
> 用途纪律：MIR-1K 在 `data/datasets_registry.md` 中是 **test-only**，本面板只做报告，不得用于 checkpoint 选择或机制调参。

## 0. 面板与对账

- 参考：human per-character on/off (MIR1k_partial_align.json on_offset)；2,035 字 / 17 首 （`mir1k_partial_align_characters.jsonl`，sha256 `78d7054ada0a…`）。
- 音频：真实伴奏流行歌曲提取的官方人声通道（official_vocal_channel），时长 32.2–108.4 s（中位 63.3 s）。
- 预测器 6 个，每个 2,035 行，全部与参考逐字对齐（未匹配行 0、字符不一致 0）⇒ 面板 12,210 单元行。
- **与 canonical 指标对账**（防第 3 轮那类伪造轴陷阱）：

| 预测器 | canonical 文件 | canonical mean_iou | 本面板重算 IoU | Δ | canonical onset MAE | 重算 MAE(start) | invalid 数 | 重算零/负长占比 | 判定 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `r2_full_20260723` | `20260723_qwen_fa_r2_full_mir1k_ood/metrics.corrected.json` | 0.83217 | 0.8322 | +0.00003 | 40.7ms | 36.5ms | 12 | 0.59% | **join_ok** |
| `r2_seed_20260724` | `20260724_qwen_fa_r2_full_seed20260724_mir1k_ood/metrics.corrected.json` | 0.83227 | 0.8323 | +0.00003 | 40.0ms | 36.6ms | 10 | 0.49% | **join_ok** |
| `r2_ood_20260723` | `20260723_qwen_fa_r2_mir1k_ood/metrics.json` | 0.83205 | 0.8320 | -0.00005 | 37.4ms | 35.2ms | None | 0.25% | **join_ok** |

- mean_iou is the only quantity defined identically in both implementations; MAE differences trace to the canonical song-macro / invalid-penalty conventions。

## 1. 自然普通话上的真实水平（首次单元级）

此前这批预测只留下一个标量 `loss`（0.80–1.73），没有单元级分析。

| 预测器 | 说明 | hit@100（项 bootstrap CI） | hit@200 | hit@250 | MAE start | MAE end | IoU | 有符号 start（中位） | start 晚>100ms | 零/负时长率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `base_qwen_raw_v1` | 上游 Qwen FA 原始输出（2026-07-22，本项目适配之前） | 22.7% (15.3%–30.9%) | 38.9% | 45.6% | 755.7ms | 837.2ms | 0.3094 | -3.3ms | 23.2% | 20.15% |
| `r0_raw_20260724` | R0：未适配 base（同 audio/labels 口径） | 75.0% (71.3%–78.7%) | 86.7% | 88.9% | 59.5ms | 95.0ms | 0.6989 | -35.4ms | 3.0% | 2.36% |
| `r1_full_20260724` | R1：projector 适配 | 91.3% (89.1%–93.3%) | 97.8% | 98.2% | 40.0ms | 37.6ms | 0.8194 | -20.0ms | 0.6% | 0.44% |
| `r2_full_20260723` | R2：LoRA seed3407 step-1000 | 91.8% (89.6%–93.7%) | 98.0% | 98.6% | 36.5ms | 35.8ms | 0.8322 | -17.9ms | 0.7% | 0.59% |
| `r2_seed_20260724` | R2：LoRA seed20260724 step-0750（同结构不同训练 run） | 91.6% (89.2%–93.5%) | 98.2% | 98.8% | 36.6ms | 35.4ms | 0.8323 | -18.3ms | 0.7% | 0.49% |
| `r2_ood_20260723` | R2：另一评测配置的同名 checkpoint | 92.3% (90.3%–93.9%) | 98.0% | 98.7% | 35.2ms | 37.4ms | 0.8320 | -14.6ms | 0.8% | 0.25% |

- 阶梯与 GTSinger 结论同向：r0→r1 **+16.4pp**、r1→r2 **+0.4pp**（自然录音 + 真实伴奏 + 人工逐字 GT 上复现）。
- r0 的缺陷再次落在**尾边界**：MAE end 95.0ms vs start 59.5ms；r1/r2 两端对称（36.5ms / 35.8ms）。
- 上游原始系统 `base_qwen_raw_v1` 只有 22.7% hit@100，且有 20.1% 零/负时长单元 ⇒ 项目的适配工作（含后处理与通道修正）在这批数据上的贡献是决定性的，不能拿上游分数当基线。

## 2. 关键新发现：失效层是**尾字**，不是首字

`r2_full_20260723`（自然录音、人工 GT）：

| 位置 | n | hit@100 | MAE start | 有符号 start | 有符号 end | 预测 start=0 占比 |
|---|---:|---:|---:|---:|---:|---:|
| first char | 17 | 94.1% | 43.0ms | -29.5ms | 7.7ms | 0.0% |
| early | 192 | 94.8% | 36.4ms | -21.0ms | 2.6ms | 0.0% |
| middle | 1618 | 91.1% | 36.6ms | -16.5ms | 7.9ms | 0.0% |
| late | 191 | 95.3% | 35.3ms | -20.5ms | 2.5ms | 0.0% |
| last char | 17 | 82.3% | 38.9ms | -26.2ms | 101.4ms | 0.0% |

- 首字 hit@100 94.1%（**高于**中间位置 91.1%），且 `r2_full_20260723` 的预测 start **从不**塌到 0：⇒ 第 1 轮 GTSinger 的『段首幻觉前奏』在这里完全不出现，进一步支持第 3 轮的解释——那个失效需要『音频被硬切在起唱点』作为触发条件，而不是『处于边界』本身。
- 但**最后一个字**明显更差：hit@100 82.3%（r1 76.5%、r0 41.2%），且尾边界偏移随模型翻号：`r2_full_20260723` 末字 end 平均 101.4ms（偏晚），r1 -77.4ms、r0 -468.0ms（偏早，r0 达 0.47s）。
- ⇒ 需要新增的评测分层是**每项最后一个字符**（它同时是 realign 最容易吞掉/截断的位置，旧口径只看整项均值时 hit@100 只差 9pp 的这件事被平摊掉了）。

## 2b. 末字失效的归因：长音保持的**尾边界**问题，不是截断

- 末字（n=17）：hit@100 82.3%，但 **start 侧几乎不坏**（94.1%），坏在 end（88.2%）：MAE end 122.1ms vs MAE start 38.9ms。
- **原因不是音频截断**：末字预测 end 超出音频长度的比例 0.0%、GT end 超出比例 0.0%（都是 0）。
- 真正的相关量是**时值**：末字 GT 平均时长 1.43 s，而中间位置只有 0.43 s ⇒ 每项最后一个字几乎都是拖长音，尾边界本身缺乏可判定的声学结束点。
- 偏移量级小但右偏：end 有符号中位 20.0ms、均值 101.4ms ⇒ 少数长尾错例拉高均值（不是系统性偏晚）。
- 跨预测器一致性：末字失败**只有 11.8% 是全预测器共犯**，29.4% 至少半数预测器失败，全部通过 0.0% ⇒ 末字难度里约一半是模型间随机不稳健，这既是 realign 的机会（多视角投票可能救回一部分），也是它的不确定性来源。
- 按末字时值分组：较长一半 hit@100 88.9% vs 较短一半 75.0%（n=9/8，样本太小不足以定方向，只登记不下结论）。

## 3. 长度不是因素，密度才是（自然录音上的反直觉结果）

- 项时长 13 项 >60s、3 项 >90s；hit@100 与项时长相关 **0.0025**（几乎为零）：

| 时长桶 | 项数(×预测器) | hit@100 | MAE |
|---|---:|---:|---:|
| <=45s | 2 | 88.3% | 76.2ms |
| 45-60s | 2 | 92.0% | 47.1ms |
| 60-75s | 7 | 92.5% | 52.3ms |
| 75-90s | 3 | 90.8% | 63.5ms |
| >90s | 3 | 90.7% | 53.9ms |

- 而 hit@100 与**逐项字数**相关 0.3093（字数多＝歌词更密＝更容易对齐）。⇒ 『长音频更难』在这批自然数据上不成立，难度来自唱法/密度而不是经过时间；这也解释了为什么合成长轴（第 3 轮）看不到长度退化。
- 项间离散（`r2_full_20260723`）：hit@100 min 82.9% / 中位 92.6% / max 97.1%；最差 5 项 amy_1(83%), fdps_1(83%), abjones_1(85%), geniusturtle_1(86%), Ani_1(89%)。⇒ 逐歌质量差异远大于不同 checkpoint 之间的差异。

## 4. 无真值分歧信号迁移到自然录音（并给出集成成员规则的教训）

以 `r2_full_20260723` 为目标、其余预测器的边界跨度作 no-GT 信号；成员规则：a peer enters the ensemble only if its own hit@100 is >= half the reference's，被排除的弱系统 ['base_qwen_raw_v1']。

| 预测器集合 | AUC(bad>100ms) | AUC(bad≥250ms) | 阳性率 | flag10% 精度/召回 |
|---|---:|---:|---:|---|
| strong_peers_only | 0.6282 | 0.8389 | 0.0138 | 0.0922/0.6786 |
| including_weak_systems | 0.5962 | 0.789 | 0.0138 | 0.0196/0.1429 |

- **信号强度序与第 1 轮一致**：抓 gross error（≥250ms）有效（AUC 0.84），抓 100ms 级弱（0.63–0.67）。
- **加入明显更差的系统会伤害集成**：把上游 `base_qwen_raw_v1` 放进集合后 AUC(250ms) 从 0.8389 掉到 0.789，且 flag10% 精度崩到约 0.02（跨度被坏系统主导）。⇒ 成员规则已实现为代码里的 `weak_excluded` 自动判定（hit@100 低于参考一半者不入集合）。⇒ 集成/多视角信号必须先按能力门筛选成员，不能只按『配置不同』凑数。

## 4b. 跨 checkpoint 不稳定单元普查（可直接投产的 no-GT 候选清单）

- 以 5 个强预测器的边界跨度（max−min）>20ms 定义「不稳定」：**69.5%**（1,414/2,035）单元不稳定。
- 不稳定单元的 hit@100 85.2% vs 稳定单元 95.8%；平均误差 80.4ms vs 43.3ms。
- 判别力：跨度对 **>100ms 误差 AUC 0.8407**、对 ≥250ms AUC 0.9277；以 20ms 阈值为代价可覆盖 96.3% 的 gross 错误（精度仅 3.7% ⇒ 阈值必须按预算取分位数，不能用固定 20ms）。
- 位置：首字与末字的不稳定率都是 94.1%（n=17 各），段内五等分的不稳定率 71%、68%、71%、65%、72%（几乎平坦 ⇒ 不稳健是全曲均匀分布的，不是接缝局部现象）。
- 意义：**不需要真值**就能圈出一批高错误概率单元；但 20ms 阈值太宽，工程上应改成「跨度分位数 + 复核预算」（与 §4 的 flag 曲线一致）。

## 5. 误差聚簇在自然录音上明显减弱（对第 1 轮的定量修正）

- `r2_full_20260723`：坏率 8.2%，坏单元落长度≥2 游程的占比 **41.9%**，游程分布 {'1': 101, '2': 28, '3': 4, '5': 1}（GTSinger 人是 67.6%）。
- ⇒ 『错误是区域』的强度**依赖数据来源**：录音室短片段（GTSinger）里聚簇强，真实歌曲的自然段落里聚簇弱。区域级 realign 的收益上限应按域分别标定，不能把 GTSinger 的聚簇率当通用常数。

## 5b. 多视角共识离线模拟：主线 realign 的**负结果**（省 GPU 的关键证据）

- 成员 = 5 个独立推理配置（同音频同歌词、不同 checkpoint/run），参考 `r2_full_20260723`，2,035 单元。members are five independent inference configurations of the same audio+text, not different audio crops; treat as a proxy upper bound for view-consensus selection。

| 策略 | hit@100 | Δ vs 单次 (pp) | MAE end | 重算预算 | 变好/变坏单元 | 末字 hit@100 | 不稳定 top20% hit@100 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `S0_single_reference` | 91.45% | +0.00 | 35.8ms | 0% | 0/0 | 82.3% | 85.8% |
| `S1_median_all` | 91.79% | +0.34 | 34.7ms | 100% | 94/82 | 76.5% | 86.8% |
| `S2_trimmed_mean` | 91.40% | -0.05 | 33.2ms | 100% | 299/131 | 76.5% | 83.3% |
| `S3_vote_bucket` | 91.50% | +0.05 | 34.0ms | 100% | 106/83 | 76.5% | 85.6% |
| `S6_agreement_weighted` | 91.79% | +0.34 | 34.6ms | 100% | 100/86 | 76.5% | 86.8% |
| `S4_gate_p50_median` | 91.70% | +0.25 | 34.9ms | 43% | 60/46 | 76.5% | 86.8% |
| `S5_gate_p50_loo_median` | 91.11% | -0.34 | 35.1ms | 43% | 171/107 | 70.6% | 84.1% |
| `S4_gate_p80_median` | 91.65% | +0.20 | 34.8ms | 20% | 36/18 | 76.5% | 86.6% |
| `S5_gate_p80_loo_median` | 90.86% | -0.59 | 35.5ms | 20% | 94/57 | 70.6% | 83.5% |
| `S4_gate_p90_median` | 91.55% | +0.10 | 35.1ms | 8% | 17/8 | 76.5% | 86.2% |
| `S5_gate_p90_loo_median` | 91.11% | -0.34 | 35.9ms | 8% | 38/22 | 76.5% | 84.5% |
| `S7_oracle_member_pick`（用 GT，上界） | 96.02% | +4.57 | 28.1ms | 100% | 342/0 | 88.2% | 95.5% |

- **共识几乎不涨**：可部署最优 91.8% vs 单次 91.5%（+0.34pp），而逐单元完美选人（用 GT）的上界是 96.0%（+4.57pp）⇒ **共识只关掉上界差距的 7.4%**，且最优解需要 100% 的重算预算。
- **末字被平均弄坏**：末字 hit@100 从单次 82.3% 降到中位/投票/聚类的 76.5%，只有 GT 上界能抬到 88.2% ⇒ 拖长音尾边界需要新的观察角度（更长右上下文、能量衰减判据），不是多份预测取平均。
- 门控版性价比更低：p90 阈值只重算 8% 的单元只换 +0.10pp；用 leave-one-out 中位数替换不稳定单元反而为负（-0.34pp、-0.59pp @p80）。
- 顺带修掉一个实现缺陷：原先 S6 用「支持度加权平均」，单个 gross outlier 仍带 1/N 权重把结果拖走（加权平均会把边界拉偏 ~0.5s），已改为**最大一致簇内取均值**；改完 S6 与中位数一致（0.9179），说明结论对选择规则不敏感。
- **决策含义**：`multi-realign dynamics / audio recrop / multi-view consensus` 这条线，在「现有机制产生的多视图 + 任何选择或平均规则」这个设定下**不值得再花 GPU**。与第 2 轮（后处理只有 +2.4pp 空间）合起来看：**单次解码之后的所有选择/清洗环节加起来的可挽回空间都在几 pp 以内**，推进普通话精度必须回到解码本身（视图生成方式、左上下文、长音尾部判据）。

## 6. 不同 checkpoint 的单元级位移（聚合分数掩盖的东西）

| 预测器对 | 20ms 内一致 | 100ms 内一致 | 中位跨度 | p90 跨度 | 最大跨度 | Δhit@100 |
|---|---:|---:|---:|---:|---:|---:|
| r0_raw_20260724 vs r1_full_20260724 | 45.9% | 85.1% | 80.0ms | 240.0ms | 3440ms | -16.36pp |
| r1_full_20260724 vs r2_full_20260723 | 73.1% | 97.2% | 0.0ms | 80.0ms | 2240ms | -0.44pp |
| r2_full_20260723 vs r2_seed_20260724 | 96.2% | 99.7% | 0.0ms | 0.0ms | 1040ms | +0.20pp |
| r2_full_20260723 vs r2_ood_20260723 | 81.6% | 98.1% | 0.0ms | 80.0ms | 2560ms | -0.49pp |
| base_qwen_raw_v1 vs r2_full_20260723 | 6.0% | 27.1% | 320.0ms | 1920.0ms | 24160ms | -69.14pp |

- 两个 R2 训练 run 的聚合差只有 +0.20pp，但 3.8% 的单元边界位移 >20ms、最大 1040ms ⇒ 聚合指标无法区分 checkpoint，必须看单元级位移；同歌同字在两个 checkpoint 下不一致时，说明这些单元的预测本身不稳定（值得优先 realign）。
- `base_qwen_raw_v1` 与 R2 的中位跨度 320ms——这不是随机噪声而是两套系统的系统性差异，进一步说明它不适合作为集成成员。

## 7. 边界与后续

- 2,035 人工字符 / 17 项 / 单一歌手集合（MIR-1K partial-align 子集），项长为 22–127 s 的自然段落，**不是** 3–5 分钟整曲；窗口/接缝因子在这里仍无法检验。
- 参考是人工逐字 on/off，但不是本项目人工复核（`rule_validated` 类），且 MIR-1K 为 test-only：本轮所有数字只做报告。
- 预测器均来自 2026-07-22/24 的 OOD 评测（batch-size 4、whole-item 推理），没有 posterior/熵字段 ⇒ 无法在此面板上复现第 1 轮的熵基信号，只能测分歧基信号。
- 建议的后续（都不需要新 GPU）：(a) 把『末字 hit@100 + 位移稳定性』加入评测面板的分层报告；(b) 用本项目现有 33 首真实歌曲（无 GT）跑同一套分歧分析，检验 checkpoint 位移是否同样普遍；(c) 若允许一次小 GPU：对这 17 项加跑 windowed(60s) 与 whole-item 两种规划，第一次在**有自然人工 GT** 的数据上判定窗口因子是否真的激活。

## 8. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python -c "from pathlib import Path;
from lyricalign.analysis import mir1k_natural_panel as M;
d=Path('/home/hyan/Data/lyricalign/runs/20260912_mir1k_natural_panel'); d.mkdir(exist_ok=True)
df,audit=M.build_panel(); out=M.analyse(df,audit)
(d/'PANEL_AUDIT.json').write_text(__import__('json').dumps(audit,ensure_ascii=False,indent=2))
(d/'ANALYSIS.json').write_text(__import__('json').dumps(out,ensure_ascii=False,indent=2))
df.to_csv(d/'panel.csv.gz', index=False, compression='gzip')"
PYTHONPATH=src python scripts/evaluation/report_mir1k_natural_panel.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_mir1k_natural_panel.py
```

