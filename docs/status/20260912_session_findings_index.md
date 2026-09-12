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
| A3 | 阶梯 r0→r1 +16pp、r1→r2 ≤0.5pp，在 GTSinger 与 MIR-1K 两个域复现 ⇒ 增益几乎全来自 projector 适配 | ✅ | 同上 + `20260912_gtsinger_gt_deep` |
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
| F4 | 批处理链路补齐 `identity.window` 规划标志与 `identity.audio`/`request_hash`；把同一性门接入批次收尾 | ✅ 可纯 CPU 做 | 门已实现：`evidence_identity_audit.audit_pair()`（duplicate_configuration / not_comparable / not_identified / identified 四类裁定）+ `gtsinger_multiview.factor_content_audit()`；待接入批次收尾 |
| F5 | 3 项 HEAD 自带失败测试（冻结主线语义） | ⛔ 需主线裁定 | 不属于本会话范围，未触碰 |

## G. 会话累计产物（可复用资产）

- 数据：`runs/20260912_gtsinger_gt_deep/`（7.9M）、`runs/20260912_m4_longform_weakgt/`（9.9M，含
  `signed_gt.pkl` 验证过的有符号真值 + `per_unit_*` 汇总）、`runs/20260912_mir1k_natural_panel/`（632K）、
  `runs/20260912_real_song_views/`（1.0M）、`runs/20260912_gtsinger_multiview/`
- 代码：`src/lyricalign/analysis/{gtsinger_gt_evidence,gtsinger_gt_deep,postprocess_replay,m4_longform_weakgt,mir1k_natural_panel,real_song_views,cleanup_simulation,joint_cleanup,longform_signed_gt,cross_window_selection,longform_pipeline_candidate,gtsinger_multiview}.py`
- 入口：`scripts/evaluation/` 下同名 `extract_/analyze_/report_/run_/solve_` 脚本
- 测试：`tests/evaluation/` 81 项（本会话新增），全量 `1523 passed / 3 pre-existing failed`
- 报告：`reports/progress/20260912_*.md` 共 7 份 + 本索引
- 纪律：全程零 GPU 前向、realign 仍 shadow-only、未改任何生产实现、MIR-1K/PJS 仅 test-only 报告用途
