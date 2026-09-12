# 2026-09-12 会话结论索引（第 1–10 轮）

目的：让后续任何一轮（或人类同事）不必重读会话即可引用结论。每条都标注
**状态**（confirmed / refuted / superseded / blocked）、**支撑产物**与**可否据此行动**。
所有数字由 JSON 生成，不手抄；本文件只登记索引，不是 canonical metric source。

图例：✅=已确认（含多域复现）｜❌=已被否证｜♻️=被后续轮次修正｜⛔=需要新数据/新前向才能推进

## A. 关于当前对齐器的真实水平

| # | 结论 | 状态 | 支撑 |
|---|---|---|---|
| A1 | 录音室短句（GTSinger，人工真值）：r2 hit@100 90.0%（早期轮次口径）/ 88.0%（12 视图口径） | ✅ | `results/by_run/20260912_gtsinger_gt_deep/metrics.json`、`20260912_gtsinger_multiview` |
| A2 | 自然伴奏普通话（MIR-1K，人工逐字 GT）：r2 hit@100 91.8–92.3%、hit@250 98.6–98.8%、IoU 0.832、MAE(start) 35–37ms | ✅ | `reports/progress/20260912_mir1k_natural_panel.md`、`runs/20260912_mir1k_natural_panel/ANALYSIS.json` |
| A3 | ♻️**第 32 轮给出可计算界**（r2 vs r1 在 50ms 差 +2.78pp 但格点余量界 9.96pp ⇒ 不可归因；100ms 差 +2.51pp 勉强超出界 2.47pp），故本条"r1→r2 ≤0.5pp"应表述为"低于指标可分辨限"：阶梯 r0→r1 +16pp、r1→r2 ≤0.5pp，在 GTSinger 与 MIR-1K 两个域复现 ⇒ 增益几乎全来自 projector 适配 | ✅ | 同上 + `20260912_gtsinger_gt_deep` |
| A4 | 上游未适配系统（base_qwen_raw_v1）在 MIR-1K 只有 22.7% hit@100（20.1% 零/负时长）⇒ 不可当基线 | ✅ | `mir1k_natural_panel` |
| A5 | 长时序（M4 拼接，弱 GT）：单窗 84.5%、现装 official 84.0%、跨窗共识 86.6% | ✅ | `20260912_longform_pipeline_candidate` |

## B. 失效结构（哪里坏）

| # | 结论 | 状态 | 支撑 |
|---|---|---|---|
| B1 | 自然录音上的失效层是**每项最后一个字**（82.3% vs 中间 91.1%），根因是拖长音尾边界（末字 GT 均长 1.43s vs 中间 0.43s），非截断（超界比例 0%） | ✅ | `mir1k_natural_panel` §2/§2b |
| B2 | GTSinger 的"段首幻觉前奏"需要**音频硬切在起唱点**才触发；自然录音上首字无惩罚、start 从不塌 0 | ✅♻️ | `mir1k_natural_panel`、`20260912_m4_longform_weakgt_panel.md` |
| B3 | 误差聚簇强度**按域不同**：录音室 67.6% 坏单元落 ≥2 游程 vs 自然录音 42% ⇒ 区域级收益需按域标定 | ✅ | `20260912_gtsinger_gt_deep_analysis.md`、`mir1k_natural_panel` §5 |
| B4 | 精度与**项时长无关**（r=0.003），与**字密度正相关**（r=+0.31）⇒ "长音频更难"不成立 | ✅ | `mir1k_natural_panel` §3 |
| B5 | 真实伴奏歌上退化（零/负时长）单元比例远高于录音室：中 7.2%、英 23.2%、日 45–53%（GTSinger 2–4%）；word 单元路径最差（日词 raw 负时长 25.1%） | ✅ | `20260912_real_song_cross_views.md` §3/§3b |

| B6a | **归因修正（第 13 轮）**：退化实际由 **fixed 阶段（窗口→全局回映射）**造成（+807/+697/+426 三批一致；`selected_*` 恒等于 `fixed_*`，压缩只加 4/2/0）；第 12 轮基于 r=0.92 相关性的「压缩造成」归因**作废** | ❌→♻️ | `runs/20260912_structural_compliance/STAGE_LINEAGE.json`、报告 §0b |
| B6b | 机制签名：整块单元在 fixed 阶段被钉到所属窗口 `input_start_sec`（I See Fire 262/311=84.2% 恰为 64.48=core 66.48−左上下文 2.0，而其 raw 起点 64.48–119.28 正常递增）；规模 33 首批次 946 单元（6.89%，10 首）、B4 832（7.63%，8 首） | ✅ | 同上 + `stage_lineage_attribution()` |
| B6c | 观测缺口的正确位置：**fixed 阶段完全没有退化计数**（压缩计数器对自身定义自洽）；另解码器侧 raw 有 870 个负时长单元 | ✅ | 同上 |
| B6 | **后处理自己制造零长单元，且自检计数器失明**：33 首批次 raw 1,483 (10.80%) → 交付 2,236 (16.28%)，新造 1,112（8.10%）、同时修复 359；产物自带的 `overlap_compression_collapsed_to_zero_count` 只报 **4** ⇒ 失明 99.6%。逐歌交付零长与 seam/overlap-compressed 率相关 **r=0.9216** ⇒ 定位在接缝修复/重叠压缩步骤 | ✅ | `reports/progress/20260912_structural_compliance.md`、`runs/20260912_structural_compliance/COMPLIANCE.json` |
| B7 | 结构合规按语言分层：Chinese 6.58% 非法（最健康）、Cantonese 15.09%、English 22.68%、**Japanese 49.29%**；三批独立一致 ⇒ 结构治理优先级在非中文 word 单元路径，普通话侧集中在个别歌（画下灯塔水母 38.9%） | ✅ | 同上 |
| B8 | 联合求解逐歌施加后两批 zero/overlap/overshoot/regression 全为 0.00%；位移必须分层报（剔除超长单元后中位 0.1s），否则被 40+s 异常区间钳制主导 | ✅ | 同上 |
| B9a | **raw 起止倒序是后续塌陷的强前兆**：钉锚点 lift 10.1×、fixed 退化 lift 8.3×、25/25 首歌内部方向一致（符号检验）；最终塌陷单元中 **50.3% 在 raw 阶段已退化** ⇒ 免费的 raw 顺序自检可提前拦下一半塌陷（无需真值/前向） | ✅ | `runs/20260912_raw_degeneracy/RAW_DEGENERACY.json`、报告 §1 |
| B9b | raw 负时长有两个子群：同窗口小幅倒序（多数，中位 2.5s，可由约束解码/单调化消除）与**跨窗口起止混配**（23.1%，最大 105.5s，属窗口→全局组装索引 bug，必须改代码）；且不是量化格点抖动（70.6% >1s）、不是接缝现象（窗口内位置平坦） | ✅ | 同上 |
| B9d | **根因落地**：`karaoke.py::append_strict_core_commits` 在压缩前钳位 `end := max(end, start)` ⇒ 解码器起止倒序被**静默转成零长单元**（870 中 595=68.4%，解释 fixed 阶段净 +807 的 73.7%），且因此**同时骗过 `overlap_compressed` 与 `collapsed_to_zero` 两个计数器**；已用生产函数复现（3 项测试）并加 `start_after_end_at_<stage>` 警告 + `start_order_integrity` gate | ✅ | `tests/test_inversion_clamp_observability.py`、`RAW_DEGENERACY.json.inversion_clamp` |
| B9e | 「raw_classes 槽位整体错位 k=1」假设**被否证**：若成立则 `e[i]==s[i+1]` 应≈100%，实测 0.31–0.68（相邻单元天然连续）⇒ 负时长确为解码器输出倒序；另 GPU 路径有 `2*len(selected)` 断言而 raw 路径没有（可选加固点） | ❌ | `run_raw_degeneracy_forensics` 位移检验 |
| B9c | 中文 raw 负时长仅 **1.1%**（cjk_character 3.0%），日文词 22.6%、英文 word 8.2% ⇒ 普通话侧解码质量明显更好 | ✅ | 同上 |
| C5 | **口径提示**：本会话所有"后处理可挽回 X pp"的数字都应理解为**在可达单元上**的上界；对 40% 不可达的长音端点，任何后处理都无法计分（见 B16） | ✅ | `20260912_decodability_ceiling` |
| C4a | **联合求解不伤末字**（GTSinger 人工真值：末单元 74.8% 持平、首单元 +2.78pp、总 MAE 77.6→68.3ms），但**长音末字三系统完全同分**（55.9%，MAE 372ms）⇒ 该层只能靠解码信息，与第 11 轮一致 | ✅ | `runs/20260912_last_unit_validation/LAST_UNIT.json` |
| B9 | 分诊规则：交付非法率 >35% 的歌应重解码而非修复（I See Fire 88% 单元被压成同一时间戳 64.48，而其 raw 边界本不相同） | ✅ | 同上 §3 |

| B11 | **测量有效性附注**：同一钳位也在评测链路里 ⇒ 本会话前几轮的绝对精度是**含退化单元的保守下界**（GTSinger official +3.31pp、MIR-1K +3.21pp、真实歌钳位净造 1,623 个零长）；且**跨预测器不等量**（base +5.38pp vs LoRA +0.23~0.54pp）⇒ 新规则：**两系统退化率差 >1pp 时，其 hit@100 差距不可直接归因于边界精度**；已复核第 4/5 轮的弱成员排除结论在此口径下**不变** | ✅ | `reports/progress/20260912_measurement_validity.md`、`results/by_run/20260912_measurement_validity/metrics.json` |
| B12 | `pipeline=raw` 面板保留倒序（不经钳位），其 38 个倒序单元 hit@100 = **0.0%**、MAE(end) 654.6ms ⇒ 钳位没有把坏单元变好，只是把它们变成"没有时间长度的字" | ✅ | 同上 |

| B13 | **倒序单元无法局部挽救**：人工真值上最好的策略（交换端点）hit@100 仅 10.5%（现状 0.0%），弱真值 M4 上所有策略 0.0%（MAE 4–5s）；且 M4 倒序在 train/val/test 都有（1056/248/**258**）⇒ 不是可忽略噪声 | ✅ | `reports/progress/20260912_inversion_policy.md` |
| B14 | **交换端点是结构净亏**：真实歌非法率 16.72%→**19.64%**（重叠 0.10%→6.19%、回退 0.07%→3.28%），因倒序幅度中位 2.48s、p90 65.5s 会吞掉邻居；**邻居顺延(P4)最差**（MAE 1.17s、偏置转正）⇒ 不要用局部修补代替重解码 | ❌（否证了直观修法） | 同上 §2 |
| B15 | 可行组合 = **倒序作重解码触发器**（代价：真实歌 6.33%、M4 1.161%、GTSinger 0.229% 单元）**+ 全局联合求解保结构**（swap 后求解非法率 0.01%） | ✅ | 同上 |

| B19 | **多视图选择路关闭（录音室中文）**：12 视图并集 oracle 仅比生产视图高 +2.40pp（长音 +0.88pp），因为 8.4% 单元（长音 15.8%、首单元 30.8%）**12 个视图全错**，且错误与生产视图相关系数 0.69–0.89 ⇒ 给第 9/10 轮"共识只赚 2.3pp"提供机制解释 | ✅ | `reports/progress/20260912_multi_view_ceiling.md` |
| B20 | 真实录音留白更大但一半需新证据：MIR-1K 并集比生产 +4.77pp（长音 +10.71pp、corr 仅 0.414），而实测共识 +2.3pp ⇒ 剩余差距不是"更好的平均"，要换窗口/重解码；**且这些是 test-only 回溯上界，不用于任何选择** | ✅ | 同上 |
| B24 | **伴奏泄漏机制（回溯）**：MIR-1K 长音真值结束后 0.3s 引导区里人声通道 **91.2% 的能量来自伴奏**（短音对照 48.8%）；落晚 >100ms 的单元该占比 85.8% vs 按时 49.5%，AUC(泄漏占比→落晚)=0.78（基准率 3.2%）⇒ **落晚的单元确实落在"人声已停、伴奏仍在"的区段** | ✅ | `reports/progress/20260912_accompaniment_leak.md` |
| B25 | 但机制**不是"该点伴奏更响"**（配对不显著/略低），而是**人声能量更低**（长音 rb=−0.507、p≈0；corr(误差, 人声@pred)=−0.40）⇒ 解码器跟"通道不再变化"而非"嗓音停止"；且**层内无判别力（AUC 0.52）**，泄漏占比只能圈位置不能定量。这把 B23 的跨域反向偏置解释成机制，并暴露一个从未测试的杠杆：**真实伴奏链路的输入是声道选择而非源分离**（改分离需 GPU 批准）；GTSinger 清唱基准结构上测不到此失效 ⇒ 录音室指标只能当 lower bound | ✅ | 同上 |
| B22 | **不可达真值的几何**：不可达时 top-1/top-2 候选跨度中位数只有 **0.08s（相邻 1 格）** ⇒ 真值几乎不在两者之间（全体 9.7%、长音 4.0%），长音 **96.0% 落在跨度之外**（外移中位 0.8s）⇒ "插值/重排造出真值"这条路关闭 | ❌ | `reports/progress/20260912_decodability_geometry.md` |
| B23 | **偏置方向跨域相反**：长音端点录音室**截早**（中位 −40.0ms、偏晚比 0.239）、真实伴奏**拖晚**（+32.4ms、偏晚比 0.741），机判 `same_direction=false`（late-share 差 0.502）⇒ 全局偏移修正不可迁移；这同时回收第 11 轮"θ 不可迁移"的疑问（根因是误差方向相反而非阈值选错）。另注：末单元不可达 100% 偏右、首单元 78.5% 偏左 | ❌ | 同上 + `results/by_run/20260912_decodability_geometry/metrics.json` |
| B21 | **容差口径警告**：50ms 时并集 oracle 掉到 79.8%（GTSinger）/75.2%（MIR-1K），20.2%/24.8% 单元无任何视图可达 ⇒ 50ms 尺度上指标测的是解码上限而非选择能力；detector_v2 SAFE ≤100ms 恰在分界上 | ✅ | 同上 + `tolerance_sensitivity` |
| B16 | **可解码上限（新发现，解释本会话所有"后处理只有个位数 pp"）**：长音（≥1s）端点有 **40.0%** 的 GT 格点**不在模型 top-2 候选内**（全体 15.7%、首单元 44.0%）⇒ 这些单元上任何基于本次解码的选择/共识/门控在原理上都不可能选对 | ✅ | `reports/progress/20260912_decodability_ceiling.md`、`runs/20260912_decodability_ceiling/CEILING.json` |
| B17 | **训练在抬这个上限**：长音端点不可达率 r0 **70.8%** → r1 27.5% → r2 **21.7%**（top-1 恰中 12.5%→55.0%），r1→r2 增益变小 ⇒ 该层预算应投训练侧且仍有余量；旁证 `pipeline=raw` 包含率一致（39.9% vs 40.0%）⇒ 上限来自解码器而非第 16/17 轮的钳位 | ✅ | 同上 |
| B18 | 置信度可预示"真值是否可达"（无参考触发器基础）：AUC(top1_prob→真值在候选±1格内) 全体端点 0.792、末单元 0.955，但**长音只有 0.616** ⇒ 恰在最需要处变弱；另 GTSinger 末单元（硬切尾，可达 90.6%）≠ MIR-1K 末字（自然衰减长音），不可互相推断 | ✅ | 同上 |

| B26 | **两处更正（读产物后）**：真实歌产品链路的输入是 **demucs 分离**（`htdemucs_ft`、`two_stems=vocals`，见 `vocals.identity.json`），不是声道选择（声道选择只在 MIR-1K 评测输入）；且项目**已有**全局分离质检 `audio_separation_quality_v1`（本批 33/33 `passed=true`，全局 v↔a 相关 0.04–0.12）⇒ 第 22 轮的"泄漏发生在产品输入上"不成立，未测的只是**时间局部泄漏** | ♻️ | `reports/progress/20260912_separation_leakage.md` §0 |
| B27 | **泄漏强形式被反驳**：只在真字间隙（≥50ms，本批仅 19.9% 单元有）用**相对判据**测，间隙残余达单元核心能量 **0.917 倍**（长音 0.977）、活跃比例 69.4%，但**与伴奏 stem 不相关**（corr 0.090、长音 0.126）⇒ 残余不是伴奏泄漏镜像；三种剩余解释中 (b) 下一字起始、(c) **时间线截早** 比 (a) 混响更像主因；若 (c) 成立则产品也在截早（与 B23 录音室方向一致） | ✅ | 同上 §2–3 |
| B28 | **方法纪律**：能量类判据必须尺度无关（除以该单元自身核心能量）且只在真间隙上计算——绝对 RMS 下限 + naive 引导窗会得出"84% 边界都有残余"的假发现（合成用例可复现：人声已停但绝对判据仍判活跃） | ✅ | `tests/evaluation/test_separation_leakage.py`、清单第 14 条 |

| B29 | ♻️**已被 B37 降级**：原称"第一个在部署视图上复现的零成本可疑边界检测器"：`gap_over_core` = 字后真间隙能量 / 该字自身核心能量。GTSinger 人工真值 pooled AUC **0.925**，按片段 within-median 1.0（CI [0.906,0.963]），按检查点 r0 0.927 / r1 0.841 / r2 0.873，**生产视图 r2\|vocal\|windowed 单独 AUC 0.8726**（233 间隙、截早率 15.9%）；长音子集截早率 65.5%（flat 组 86.4%） | ✅ | `reports/progress/20260912_gap_shape.md`、`runs/20260912_gap_shape/GAP_SHAPE.json` |
| B30 | **间隙"形状"假设被干净否证**：上升/下降并不区分"下一字起始"与"本字尾巴"（rise_ratio AUC 0.58；截早率 falling 34.5% < flat 61.1% > rising 32.9%）⇒ 真正有信息的是**残余水平**（持平≈整字能量）而非升降方向；绝对能量 `gap_rms` 含响度混杂（按检查点分组掉到 0.70），必须用比值 | ❌ | 同上 |
| B31 | 真实歌（无真值、冻结判据）2,938 个可测间隙里 **34.2% 为 flat 且 gap/core 中位 1.014** ⇒ 与 B27 一致，但只算流行率；定性仍需那个人工标注小实验 | ✅(有限) | 同上 §3 |

| B32 | **融合触发器已验证**（GTSinger 人工真值，目标端点误差>100ms，流行率 12.0%）：批内分位融合 AUC **0.850**、20% 复核预算召回 **67.1%**（精度 40.3%）；单件里 high_entropy 0.845 / gap_residual **0.884（精度 98%，但只覆盖 15% 单元，覆盖内 r@20%=49%）**；对"端点被切早"gap_residual AUC **0.9205**、**长音层 0.9407**（该层最强信号，尽管覆盖率低）；inversion 对端点误差 AUC 0.50（它预示后续塌陷而非精度）⇒ **三件分工不同，不可混用** | ✅ | `reports/progress/20260912_trigger_fusion.md` |
| B33 | 真实歌冻结应用（无真值）：inversion 6.33% / gap_residual 11.0% / 高熵(top20%) 20.0% ⇒ 任一 **29.0%**；重解码队列前 8 全为非中文（I See Fire 97.8%、初音 93.0%、p.h 83.0%…），**中文歌无一进前十**（第 6/12/15 轮结论第四次复现） | ✅ | `runs/20260912_trigger_fusion/redecode_queue_real_songs.csv.gz` |
| B34 | **两条口径纪律（本轮踩到）**：① 绝对熵阈值不跨域——GTSinger 上 `≥1.0 nats` 用到产品批会 flag 68.7%，必须改**批内分位**；② 部分覆盖特征必须同时报"全体召回"与"覆盖内召回"（间隙特征仅覆盖 12.7–15%），否则高精度件会被读成弱件 | ✅ | 同上 §3 |

| B35 | **重解码预算的可达上界**（GTSinger 人工真值，零前向）：生产视图基线 88.0%，用第 27 轮触发器选单元重解码，5%/10%/20% 预算的**可达上界**只有 **+1.02 / +1.88 / +2.67pp**（乐观上界 +3.18/+4.63/+6.20pp；同预算随机 +0.24/+0.75/+1.33pp；oracle +5.02/+7.02/+7.02pp）；**错单元中 41.3%（长音层 61.3%）真值不在候选内 ⇒ 同窗口重解码救不了**；触发器只 capture oracle 的 0.20–0.38 | ✅ | `reports/progress/20260912_redecode_budget.md` |
| B36 | **长音层的预算结论**：20% 预算下触发器 +3.33pp **不超过随机 +3.40pp** ⇒ 在长音层花重解码预算等于随机挑；应先提升可达性（训练/新证据），或改用能产生新候选的重解码参数 | ✅ | 同上 |

## 0b. 第 22–29 轮新增结论（一段话版）

- **后处理与观测已落地**：per-stage 退化观测 + `start_after_end` 告警接入生产写入器（additive）；
  统一批次自检 `audit_batch.py` 六个 gate；一页交付前检查清单（16 条）。
- **两处静默缺陷被定位**：fixed 阶段把整块单元钉到窗口 `input_start_sec`（真实歌 946 单元/6.89%）；
  `karaoke.py` 预钳位把解码器起止倒序**静默转成零长**（870 中 595 个，解释 fixed 阶段净新增的 73.7%），
  从而同时骗过两个既有计数器。
- **三条"看起来能省算力"的路被否证**：事后声学阈值（末字 oracle +0.00pp）、局部修补倒序
  （swap 使非法率 16.72%→19.64%）、插值/重排候选（不可达时候选跨度中位仅 1 格、长音 96% 在跨度外）。
- **上限与预算的定量关系**：长音端点 40% 的 GT 不在 top-2 内；训练已把它从 70.8% 压到 21.7%；
  多视图选择在录音室中文上只剩 +2.4pp（长音 +0.88pp，错误相关性 0.69–0.89）；
  重解码预算在生产视图 5–20% 的**可达上界**只有 +1.0~+2.7pp，长音层与随机无异。
- **口径被正式限定**：本会话早期绝对精度是**含退化单元的保守下界**（GTSinger +3.31pp、MIR-1K +3.21pp、
  base 预测器 +5.38pp）；两系统退化率差 >1pp 时不得把 hit 差解释成精度差；绝对熵阈值不跨域；
  部分覆盖特征必须双分母报召回。
- **免费触发器已成型但未上线**：倒序（预示塌陷 lift 8–10×）+ 批内分位高熵（AUC 0.85/0.87）
  + 间隙残余（切早 AUC 0.92、长音层 0.94、精度 98% 但覆盖 12–15%）；融合 AUC 0.850、
  20% 复核预算召回 67.1%；真实歌任一触发 29.0%，中文歌无一进重解码队列前十。

| B37 | ♻️**复现语料不可比（见 B39）**，原表述"跨语料复现失败"应降级为"除 GTSinger 外无正证据"：`gap_over_core` 是语料特异信号——同一代码路径下 GTSinger ρ=+0.777（十分位跨度 483ms、AUC 0.921）而 **M4Singer ρ=−0.060、跨度 97ms、AUC 0.506**（且切早流行率 65.7% ⇒ 标签近常数使 AUC 失去意义，必须并报连续量排序）；**只有边界置信度勉强同向**（M4 对误差>100ms AUC 0.662，train 0.676/val 0.639，弱于 GTSinger 0.845）；margin 方向反（0.397）⇒ **间隙残余不得上线**，第 27 轮融合里可移植成分仅熵（预算结论不变，实现应只用熵） | ❌→♻️ | `reports/progress/20260912_trigger_replication.md` |
| B38 | 方法学：**跨语料复现必须同时报 AUC 与抗饱和连续量（ρ/十分位）+ 标签流行率**；只看 AUC 会在近常数标签语料上得出"全都无效"的错误结论，只看 ρ 会漏掉覆盖率差异 | ✅ | 同上 |

| B39 | **100ms 阈值被 80ms 格点污染**：GTSinger 上 **73.4%** 单元的误差落在阈值 ±1 格内（M4 12.9%）；剔除后同一分数 AUC 0.7993→**0.8662**（M4 0.6619→0.7003）⇒ **以 100ms 为界的判别力评估系统性低估真实判别力**，detector_v2 SAFE ≤100ms 正落在该区间；且 AUC 随容差单调上升（80→250ms：0.776→0.853）⇒ 触发器擅长抓粗错。另：M4 面板中位误差 525ms、96.4% 单元超 100ms ⇒ **它不是可比的复现语料**（第 30 轮否证强度下调），而 M4 的 `baseline_legal_only` 子集 AUC 仅 0.627 ⇒ 标签质量解释不了全部差距，不得声称熵的跨语料一致性已被证明 | ✅ | `reports/progress/20260912_label_noise_ceiling.md`、`runs/20260912_label_noise_ceiling/LABEL_NOISE.json` |

| B40 | **指标可分辨限（本轮新增的硬口径）**：以"落后方差距不足一个 80ms 格点的单元数"为界，`r1 vs r0` 在 100ms 上 +18.00pp **超过界 4.82pp**（扎实差异 1,784 单元）⇒ projector 增益为真；而 `r2 vs r1` 50ms +2.78pp **低于界 9.96pp**、MIR-1K `r2_full vs r1_full` +0.29pp（界 3.54pp）、`r2_full vs r2_ood` −0.69pp（界 2.85pp）⇒ **均不可归因，两个 r2 checkpoint 谁更好现有指标判不了**。单系统侧：hit@50/hit@100 可被一个格点同向偏移推动 ±42.1/±36.7pp（刀尖判定 84.2%/73.4%），200ms 后才稳定 | ✅ | `reports/progress/20260912_metric_stability.md`、`runs/20260912_label_noise_ceiling/{STABILITY,GAP_ARTIFACT}.json` |

| B41 | **detector_v2 的 SAFE ≤0.100s 带边是格点脆弱的**：把带边移动一个 80ms 格点，带内占比摆幅 65.9–81.0pp（生产视图 88.04% 摆 77.9pp）⇒ **不能单独作为产品 gate 依据**；而 **UNSAFE ≥0.250s 在好系统上稳定**（摆幅 1.4–8.5pp）⇒ 需要可下判断的带时用 250ms，100ms 仅作报告口径。副产品：250ms 摆幅可当质量体检量（生产 2.7pp / MIR-1K 1.4pp / M4 22.8pp） | ✅ | `runs/20260912_label_noise_ceiling/BAND_EDGE.json`、报告 §2b |
| B42 | 工程教训：**列名与 DataFrame 方法名冲突时（`mode`/`count`/`max`/`abs`…）必须用 `df["col"]` 取列**；`df.mode` 返回方法，比较后恒 False ⇒ 切片静默变空（本轮生产视图 units=0 的真实原因） | ✅ | 本会话第 33 轮记录 |

| B43 | **冻结 detector_v2 标签的格点稳定性**（8 个 LABELS 文件、972,330 已标单元）：① 血统完好——重算分带与冻结标签一致 ≥ **0.9793**；② **100ms（SAFE/GREY）边在好系统上格点脆弱**——刀尖占比最高 **75.1%**、带边移一格摆 **65–73pp** ⇒ 以 100ms 为界的精度/召回含大量舍入成分；③ **250ms（GREY/UNSAFE）边在全部 8 个文件上都稳定**（刀尖 ≤3.1%、摆幅 ≤3.1pp）⇒ **可下判断的 gate 应建立在 UNSAFE ≥0.250s**，SAFE 侧用 ≥2 格缓冲（≈160–200ms）或仅作报告 | ✅ | `runs/20260912_label_noise_ceiling/DETECTOR_LABEL_STABILITY.json` |

## C. 后处理与选择环节的可挽回空间（预算决策类）

| # | 结论 | 状态 | 支撑 |
|---|---|---|---|
| C1 | demo 管线现装后处理**净损害**（−1.66pp），其规则把 start 钉到前一尾端（98.3%）；改造空间 +2.4pp，其中 88% 已被"修尾端+最短时长"捕获 | ✅ | `20260912_postprocess_policy_replay.md` |
| C2 | 后处理在自然录音上**制造退化单元**：清理前 11.2% → 清理后 17.1%（净 +642 单元），可信时长损失 33.3% | ✅ | `20260912_real_song_cross_views.md` §3b |
| C3 | **朴素单调化会级联失控**（移动 97.9% 单元、重叠反升到 97.9%）⇒ 任何保序修复必须先钳制异常区间 | ✅ | 同上 §3c |
| C4 | **联合约束求解**（min 50ms/max 3s/保序/非重叠/加权 L1 贴近钳制后的 raw，权重来自记录熵）是首个带真值验证为正的规则改动：GTSinger +2.02pp vs 现装且退化 4.61%→0；M4 精度中性且结构零缺陷；真实歌唯一做到 0/0/0 | ✅ | `20260912_joint_cleanup.md`、`20260912_longform_pipeline_candidate.md` |
| C5 | 联合求解在长音材料上的 −0.53pp **不是 3s 上限造成**（3/6/12s 均为 86.07–86.08%），而是非重叠+保序约束本身的代价 | ✅♻️ | 同上 |
| C6 | 跨 checkpoint 共识几乎无用：MIR-1K 上 +0.34pp（oracle +4.57pp，只吃 7.4%）；leave-one-out 中位替换为负 | ✅ | `20260912_mir1k_natural_panel.md` §5b |
| C7 | **多视图是否有价值取决于视图是否真不同 + 质量是否齐平**：不同裁窗同模型 ⇒ 共识免费 +2.14pp；同裁窗换模型 ⇒ +0.34pp；GTSinger 的 mix/vocal/mode 输入侧没变 ⇒ 共识 −0.75pp（基线已是最优视图时一切选择器为负） | ✅ | `20260912_gtsinger_multiview.md` §3 |
| C8 | 集成/共识的**成员必须过能力门**（把弱系统混入使 AUC 0.839→0.789、flag10% 精度 0.092→0.020）；门不能用真值来定 | ✅ | `mir1k_natural_panel` §4、`longform_pipeline_candidate` |
| C9 | 熵是可靠的**触发器**（四轮独立复现 AUC 0.78–0.88，且只抓 gross 错误：0.78@100ms vs 0.93@250ms），但是差的**视图选择器**（−2.28pp） | ✅ | `20260912_gtsinger_gt_deep_analysis.md`、`mir1k_natural_panel` §4、`cross_window_selection`、`gtsinger_multiview` |
| C10 | 跨窗**分歧度**作触发器接近随机（AUC 0.584@100ms；20% 预算只捕获 26.9% 错误），且 60% 单元无多尝试输入 | ✅ | `20260912_longform_pipeline_candidate.md` §2 |

## D. 数据/证据完整性（踩坑登记，后续必须先过这些门）

| # | 结论 | 状态 | 支撑 |
|---|---|---|---|
| D1 | `LONG_TIMELINE_MANIFEST.canonical_units[*].start_sec` 是**伪造均匀轴**；量化版：与 raw 距离 ≤100ms 只有 15.9%（重建真值为 89.1%） | ✅ | `20260912_m4_longform_weakgt_panel.md` §5b、`SIGNED_GT_STATS.json` |
| D2 | 面板 `label_*_err_sec` 是**无符号** ⇒ `raw − err` 反推真值有 ± 歧义（曾被误读为"24% 单元跨尝试分歧"）；正确重建 = 段局部 `timestamp_class_ids × 0.08` + `global_start_sec`，与冻结误差 **max dev 0.0** | ✅ | `src/lyricalign/analysis/longform_signed_gt.py`、`SIGNED_GT_STATS.json` |
| D3 | 长时序面板每行是 **(request, view, 单元) 一次尝试**（134,538 行 = 14,441 单元，扇出 9.3×，最多 24 窗）；单元键必须含 `song` | ✅♻️ | `ANALYSIS_CALIBRE.json` |
| D4 | evaluation_v1 的 `audio_input` 因子是 **DEAD CONFIGURATION**：mix/vocal 954 组配对 `audio_sha256` 100% 相同 ⇒ 消融从未换过输入，相关结论作废 | ✅ | `20260912_gtsinger_multiview.md` §2b |
| D5 | `20260814_ktv_B4` vs `20260814_ktv_current_silence` 是**同一配置的重复运行**（收紧版）：25/25 窗口计划相同、23/25 歌曲输出逐字节相同，剩余 2 首的差异全部落在音频 sha 也不同的歌上；`20260815_slot*` 批次 identity.schema_version/audio_sha256/request_hash **100% 缺失**（不可归因）且与 B4/current 逐索引文本 100% 漂移 ⇒ 三批之间不存在任何可支持的对比；textmode3 单元数不同（word vs char）；批处理视图不记录 silence 标志、`full_slot` 不记 schema/音频 sha 且 23.6% 索引错位 | ✅ | `20260912_real_song_cross_views.md` §0/§1 |
| D6 | 前向是确定性的（0/28,980 位移）⇒ 按 identity 缓存安全，但必须保留参考时间轴与 attempt↔request 映射 | ✅ | `20260912_postprocess_policy_replay.md` |
| D7 | 跨视图/跨尝试比较前必须过**可比性门**：逐位文本一致 + 同音频 sha + 计划确实不同 | ✅ | `src/lyricalign/analysis/real_song_views.py`（`comparability` 段） |
| D8 | 均值类指标在含 gross 异常的证据上无意义（两次事故：位移均值 15.7s、mass lost 78%）⇒ 一律中位/p90 + 封顶口径 | ✅ | `cleanup_simulation`、`real_song_views` |

## E. 已否证 / 不再重复尝试的方向

| # | 方向 | 状态 | 依据 |
|---|---|---|---|
| E1 | 换 checkpoint / 同裁窗多配置来提精度 | ❌ | A3、C6、C7（12 视图里 11 个是同质的） |
| E2 | 顺序 if-else 式清理增强（单调钳位、只修尾端） | ❌ | C1/C2/C3、C4（联合求解在三个域都更好） |
| E3 | 用"把困难单元重新裁窗居中"来救 realign | ❌ | 第 8 轮：居中选择器 −1.15pp；第 9 轮：窗口中央无优势 |
| E4 | 用分歧度作为唯一 realign 触发器 | ❌ | C10 |
| E6 | 事后声学阈值判据修末字/长音尾边界（RMS 衰减、人声/伴奏比值） | ❌ | `20260912_tail_acoustics`：末字 oracle 界 +0.00pp、迁移 −13.4pp、比值锚点 61.5% vs 模型 95.8% |
| E5 | 日语（PJS）线 | ⛔（已按指示降级，未继续） | 用户指示：优先普通话 |

## F. 仍未解决（需要新前向或新数据）

| # | 问题 | 状态 | 最小实验 |
|---|---|---|---|
| F1 | 同一**最好 checkpoint + 多个不同裁窗**能否吃到 +3.4pp（长时序跨窗 oracle 与现装的差） | ⛔ 需 GPU | 对 17 首 MIR-1K 或 GTSinger 整曲加跑 windowed 计划；先过 D7 门 |
| F2 | 真实整曲 ≥180s 的自然长音频 + 人工 GT（当前 MIR-1K 最长 126.7s） | ⛔ 需标注 | GTSinger 整曲试点（25 连续段、wav==labels，2026-08-21 记录） |
| F3 | 末字拖长音尾边界判据 | ❌ **REFUTED（第 11 轮）** | 相对 RMS 衰减与「人声/伴奏能量比」两条事后声学判据均不可用：前者在末字上几乎不触发（MIR-1K 1/17、GTSinger 6/168），导出阈值迁移后 −13.4pp；后者覆盖 88–99% 但 hit@100 仅 6–62%（同单元模型 95.8%）。oracle 界末字 +0.00pp ⇒ 需模型侧改动 |
| F6 | **已定位（第 13 轮）**：塌陷来自 fixed 阶段的窗口→全局回映射（块被钉到 `window.input_start_sec`），压缩计数器并无漏计；缺的是 fixed 阶段没有退化计数 | ✅ 修复方案已给出 | 按阶段输出 `degenerate_share`/`pinned_to_anchor` + 交付 gate（净新增 >1% 不出片）；见 `stage_lineage_attribution()` |
| B10 | 分诊带（illegal >35% re-decode / >15% repair+review / >5% review / else ship-ok）：中文 16 首中 **仅 1 首需重解码**（画下灯塔水母 38.9%，135 单元钉锚点），4 首复核，11 首可发布；其余问题只是零长单元需 ≥50ms 下限（联合求解中位位移恰 0.05s） | ✅ | `runs/20260912_structural_compliance/mandarin_triage_list.csv.gz` |
| F4b | 统一自检入口已就绪：`scripts/evaluation/audit_batch.py`（可归因性 + 结构合法性 + 阶段归因 + 钉锚点 + 修复可行性 + 可选配对门，含 gate 默认值） | ✅ | `runs/...` 无产物；测试 3 项 |
| F4a | **已落地（第 14 轮）**：`stage_degeneracy_audit()` 接入两个写入器的 `summary.degeneracy_audit`（additive、无行为变化，20 项既有 pipeline 测试通过） ⇒ fixed(processor_decoded) 阶段的退化计数与钉锚点检测从此可见 | ✅ | `src/lyricalign/demo/alignment_artifacts.py` |
| F4 | 批处理链路补齐 `identity.window` 规划标志与 `identity.audio`/`request_hash`；把同一性门接入批次收尾 | ⛔ 仍需（标志记录属写入器配置项，本会话只做了退化观测） | 门已实现：`evidence_identity_audit.audit_pair()`（duplicate_configuration / not_comparable / not_identified / identified 四类裁定）+ `gtsinger_multiview.factor_content_audit()`；待接入批次收尾 |
| F5 | 3 项 HEAD 自带失败测试（冻结主线语义） | ⛔ 需主线裁定 | 不属于本会话范围，未触碰 |

## G. 会话累计产物（可复用资产）

- 数据：`runs/20260912_gtsinger_gt_deep/`（7.9M）、`runs/20260912_m4_longform_weakgt/`（9.9M，含
  `signed_gt.pkl` 验证过的有符号真值 + `per_unit_*` 汇总）、`runs/20260912_mir1k_natural_panel/`（632K）、
  `runs/20260912_real_song_views/`（1.0M）、`runs/20260912_gtsinger_multiview/`
- 代码：`src/lyricalign/analysis/{gtsinger_gt_evidence,gtsinger_gt_deep,postprocess_replay,m4_longform_weakgt,mir1k_natural_panel,real_song_views,cleanup_simulation,joint_cleanup,longform_signed_gt,cross_window_selection,longform_pipeline_candidate,gtsinger_multiview}.py`
- 入口：`scripts/evaluation/` 下同名 `extract_/analyze_/report_/run_/solve_` 脚本
- 测试：本会话新增 177 项
- 交接页：`docs/status/20260912_session_handoff.md`（机器生成）（`tests/evaluation/` + `tests/test_alignment_artifacts_degeneracy.py` +
  `tests/test_inversion_clamp_observability.py`），全量 `1617 passed / 3 pre-existing failed`（第 34 轮后隔离复跑）。
  负载敏感现象再次确认：大批量写盘后紧接着跑全套会多出 2 项 LP 相关失败 + 1 项 skip（第 14 轮定位的
  "高 I/O 负载下 scipy.optimize 导入失败"），隔离复跑即干净 ⇒ 收尾必须单独跑测试
- gate 清单（`audit_batch.py`）：attributable_identity / structural_legality 5% / stage_attribution 1% /
  window_anchor_pinning 2% / start_order_integrity 2% / repair_feasibility
- 序列身份教训：**任何"逐序列"求解/统计的分组键必须含 `run`**（不同 run 的同名单元混在一个序列会让单调约束互相打乱）
- 阶段名对照：生产 `processor_decoded` == 本索引/分析模块所称 `fixed`（同一个 `fixed_global_*` 阶段）
- **一页式交付前检查清单**：`docs/status/20260912_predelivery_checklist.md`（13 条判据 + 3 条已否证路径）
- 自检入口：`PYTHONPATH=src python scripts/evaluation/audit_batch.py --batch <dir> [--compare-batch <dir>]`
- 报告：`reports/progress/20260912_*.md` 共 7 份 + 本索引
- 纪律：全程零 GPU 前向、realign 仍 shadow-only、未改任何生产实现、MIR-1K/PJS 仅 test-only 报告用途
