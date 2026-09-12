# 2026-09-12 真值深度分析轮（goal 自由行动，只读挖掘；共 3 轮）

> 目录名保留 `gtsinger_gt_deep_analysis`（第 1 轮入口）；第 2 轮（后处理策略重放）与第 3 轮
> （长时序弱真值面板）记录追加在本文件后半部分，代码与产物路径各自独立。

本轮不启动任何 GPU 前向、不新增训练，只做一件事：把 2026-08-16 evaluation_v1 已经落盘的
GTSinger 评测产物**逐单元**重读一遍，回答旧浅层汇总（hit-rate 表）回答不了的问题。
存储成本：数据目录新增约 8 MB（一个 gzip 证据面板 + 7 个 JSON），Git 侧新增约 60 KB。

## 入口

1. `reports/progress/20260912_gtsinger_gt_deep_analysis.md` — 结论与全部数字（由 JSON 生成）。
2. `results/by_run/20260912_gtsinger_gt_deep/metrics.json` — 轻量 canonical 指标（进 Git）。
3. `/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/` — 证据面板与分析产物（外置）。

## 代码

- `src/lyricalign/analysis/gtsinger_gt_evidence.py` — 逐单元证据抽取（GT 清洗/协变量、
  raw/fixed/selected 三阶段、decoder posterior、window 归属、音频与请求 provenance）；
  计数不一致的配置**显式跳过并记录原因**，绝不静默按索引拼接。
- `src/lyricalign/analysis/gtsinger_gt_deep.py` — 五个分析段：`compute_effects`（配对因子效应 +
  段聚类 bootstrap）、`compute_signals`（无真值置信信号判别力/校准/分组 CV 门控）、
  `compute_structure`（有符号偏置、协变量分层、误差传染、游程聚簇 + 协变量零模型）、
  `compute_matrix`（配置矩阵同一性审计）、`compute_postprocess`（后处理修复/破坏分解与规则归因）。
- 入口脚本：`scripts/evaluation/{extract_gtsinger_unit_evidence,analyze_gtsinger_gt_deep,report_gtsinger_gt_deep,collect_gtsinger_gt_results}.py`。
- 测试：`tests/evaluation/test_gtsinger_gt_deep_analysis.py`（8 项，纯合成 fixture，0.6s）。

## 主要发现（按强度）

1. **P1 数据完整性：evaluation_v1 的 3×2×2 配置矩阵是退化的。** 每段只有一个音频 sha256，
   `mix` 与 `vocal` 喂的是同一个 wav（GTSinger 只发干声），逐单元起止 100% 相同；
   `full` 与 `windowed` 在短片段上 start 100%、end 98.6% 相同。12 个标注配置每段只剩 3.52 个
   不同预测向量（冗余 3.4×）。⇒ 既有结果里不存在"混音 vs 分离""整曲 vs 分窗"的任何证据；
   约 3/4 前向是重复计算。
2. **官方后处理在真值上净负收益**：配对 hit@100 `official − raw = −1.66pp`
   （CI [−1.83, −1.51]，符号检验 p≈1e-94）；被改动的 5.4% 单元里破坏 46.9% vs 修复 24.5%，
   越界翻转 out/in = 548/24，零时长率 1.26%→4.61%。规则可归因：后移的 start 有 98.3% 精确等于
   前一单元 end（重叠消解），而 end 端改动 39.2% 是修复、仅 2.8% 破坏 ⇒ **拆两端**而非整体关闭。
   现有 posterior 置信度无法预判哪次改动是修复（AUC 0.43–0.52）。
3. **无真值置信信号在真演唱真值上确实有效**：最强单信号 end 边界熵 AUC 0.858；
   去重后的跨模型分歧 0.782；组合门控（按段分组 CV，只用无真值特征）OOF **AUC 0.913 / AP 0.789 /
   ECE 0.010**，仅比"偷看 GT 时长与 IoU"的 oracle 门控（0.9485）低 3.5 点。
   复核预算曲线：flag 5% 精度 0.96、10% 精度 0.90/召回 0.52、20% 精度 0.65/召回 0.75。
   原始 top-1 概率系统性欠自信（0.73 vs 实测 0.91，ECE 0.184，可靠性曲线单调）→ 一次重标定即可用。
4. **误差是"区域"而不是独立噪声，且不能归因于机械传染**：67.6% 的坏单元落在长度≥2 的连续游程里；
   i.i.d. 零模型下长度 5 的游程超额 17×；用可观测量（GT 时长/音节结构/位置/技法组，OOF AUC 0.736）
   做伯努利零模型后仍只解释到 29.2%（观测 67.6%），长度 9 的游程观测 16 次而零模型期望≈0。
   同时预测并不强制连续（仅 1.1% 精确首尾相接），start 误差与前驱 end 误差相关 −0.01 ⇒
   区域级 realign 的实证依据成立，但机制不是误差传染。
5. **两个可定位的失效层**：(a) 段首幻觉前奏——GTSinger 段首 GT start 恒为 0，74.8% 的段首正确落在 0，
   其余 40 段虚构平均 518ms 前奏，这部分 hit@100 只有 5.0%；(b) 零声母音节 hit@100 72.0% vs
   多音素 93.3%，与段首叠加后掉到 36.4%。两者合计只占 6.6% 单元，用总体均值看不见。
6. 模型阶梯边际：`r0→r1` +19.9pp，`r1→r2` +1.9pp；r0 的缺陷集中在尾边界（end MAE 153ms vs start 79ms）。

## 边界

- 只有 2 位歌手 / 2 首歌 / 159 个 5–15s 片段；段内相关用段聚类 bootstrap 处理，跨歌手泛化未测。
- GTSinger 是 word-level GT（未人工二次校正）；"后处理净负"以 100ms 口径衡量，±200ms 产品口径代价小得多。
- 门控是诊断产物（特征与标签同源），不得用于 checkpoint 选择或真实 writeback；realign 仍 shadow-only。
- 本轮没有验证"混音 vs 分离"，因为该批数据根本不含混音条件（见发现 1）。

## 建议下一步（不启动 GPU 也能推进的前两项）

1. 把 `compute_matrix()` 做成评测批次收尾 gate：因子输入同一性不成立时标 `not_identified` 并拒绝出"效应"。
2. 在**同一证据面板**上重放后处理变体（只保留 end 修剪 / start 不强推），纯 CPU 复评。
3. 若要真正的音频输入因子：自造 mix（干声叠加伴奏/噪声）或在带伴奏数据集上另建 GT 面板。
4. 段首与零声母专项消融，评价指标改用分层命中率（段首桶 / 单音素桶 / 交集桶）。

## 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/extract_gtsinger_unit_evidence.py \
    --preset gtsinger --out-root /home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep
PYTHONPATH=src python scripts/evaluation/analyze_gtsinger_gt_deep.py
PYTHONPATH=src python scripts/evaluation/report_gtsinger_gt_deep.py
PYTHONPATH=src python scripts/evaluation/collect_gtsinger_gt_results.py
PYTHONPATH=src python -m pytest -q tests/evaluation
```

## 仓库既有失败（非本轮引入，记录备查）

`python -m pytest -q tests` 在 HEAD（本轮只新增文件、未改动既有代码）上有 3 项失败：

- `tests/test_archive_builder.py::test_repository_root_has_no_obsolete_patch_or_archive_copies`
  — 仓库根仍存在 `PATCH_MANIFEST.sha256`；
- `tests/test_inline_realign_v4_full_mechanism.py::test_strict_silence_windows_never_cross_gap`
  — 期望 `continue_from_committed_cursor_after_region`，实现返回
  `per_region_soft_continue_from_committed_cursor`；
- `tests/unit_realign/test_request_families.py::test_local_context_is_family_specific`
  — `audio_end_sec` 5.0 vs 期望 4.5。

其余 1458 项通过（含本轮新增 8 项）。这三项属主线实现与测试的口径漂移，
修它们会改动 2026-08-14 冻结语义，留给主线轮次处理，不在本轮擅自改写。

---

# 第 2 轮（同日）：后处理策略重放实验

同上面板、纯 CPU、零前向：先归因现装规则，再重放 14 个预注册规则变体，回答
"改成什么规则能挽回多少"。

- 代码：`src/lyricalign/analysis/postprocess_replay.py`；入口
  `scripts/evaluation/replay_gtsinger_postprocess_policies.py` +
  `scripts/evaluation/report_postprocess_policy_replay.py`；测试
  `tests/evaluation/test_postprocess_policy_replay.py`（9 项，1.4s）。
- 产物：`POLICY_REPLAY.json`、`policy_replay_by_sequence.csv.gz`（156 KB）、
  `reports/progress/20260912_postprocess_policy_replay.md`、
  `results/by_run/20260912_gtsinger_gt_deep/policy_replay.json`。

## 结论

1. **现装规则的行为已被数据确认**：1,292 个重叠单元对里，882 次推后起点、只有 12 次修剪尾端；
   被推后的起点 97.3% 精确等于前单元尾端；决策与解码置信度无关（AUC 0.373，p=0.13）。
   后处理新增 976 个零时长单元（1.26%→4.61%），其中 55.7% 就是被推扁的那个起点。
2. **最优可部署规则 `V9_end_trim_min0.05s`（只修剪前单元尾端 + 0.05s 最短时长保护）**：
   hit@100 83.01%（比现装 **+2.10pp**，CI [+1.89, +2.34]，段级 464 胜 / 32 负 ≈ 14:1），
   hit@200 87.71%、IoU 0.758，零时长率回到 raw 水平 1.29%。
   GT-oracle 逐重叠上界也只有 83.27%（+2.38pp）⇒ 该规则拿到了 88% 的空间，不必再造更复杂的仲裁器。
3. **关键变量是"让哪一侧动"**：只推起点 `V3` 比现装还差 −2.25pp；对半分 `V4` +0.01pp；
   按置信度加权 `V5` +0.24pp；只处理小重叠的阈值版 `V6/V7b` 反而不如无条件修尾端。
4. **口径澄清**：raw 评测管线并非"无后处理"——其 selected 相对自身 raw 仍调整 208 单元（0.72%，
   全部 end-only，含 32 个负时长钳零），所以第 1 轮的 A/B 是"完整清理 vs 最小清理"。
5. **前向可复现性为正**：同一 identity 两次独立前向的 raw 阶段 **0 差异**（28,980 单元），
   内容寻址 evidence 缓存的前提成立。
6. 分层增益仍在：段首单元 63.3%→66.2%、零声母 63.7%→67.2%；但**段首幻觉前奏**（起点被推迟 ~0.5s）
   发生在解码本身，任何后处理规则都救不了 → 第 3 轮起的主攻方向。

## 未做（明确登记）

- 未改任何实现：`V9` 只是重放证据，真实实现改动会使既有 official 口径产物失效并需作废受影响 identity，
  留给主线按冻结参数纪律决定；长歌串行合并/跨窗口缝合阶段未被重放覆盖。

---

# 第 3 轮（同日）：长时序弱真值面板（detector_v2 M4Singer-concat 证据）

GTSinger 面板答不了的问题（窗口/接缝、非零起唱点、门控跨域迁移）需要长时序数据。
本轮从 `research_v7_detector_v2/run{1,2}` 的既有证据装配了一个 **200s 级长时序面板**：
逐单元 raw/official 两阶段边界 + 熵/margin/repair 位移 + 项目冻结的逐单元真值误差标签。
纯 CPU、零前向、数据目录 +16 MB。

- 代码：`src/lyricalign/analysis/m4_longform_weakgt.py`
- 入口：`scripts/evaluation/{build_m4_longform_weakgt_panel,report_m4_longform_weakgt}.py`
- 测试：`tests/evaluation/test_m4_longform_weakgt.py`（5 项，0.6s）
- 产物：`runs/20260912_m4_longform_weakgt/{longform_units.jsonl.gz,PANEL_SUMMARY.json,ANALYSIS.json}`、
  `reports/progress/20260912_m4_longform_weakgt_panel.md`、
  `results/by_run/20260912_m4_longform_weakgt/metrics.json`

## 结论

1. **P1 方法陷阱（本轮最重要的产出）**：`LONG_TIMELINE_MANIFEST.canonical_units[*].start_sec`
   是**合成均匀轴**（labeler 的真实 GT 来自逐段 M4Singer 字符标注平移）。
   直接拿它当真值：hit@100 = **5.3%**；用冻结的真实 GT 误差：**87.9%**（相差 83pp，
   两种"误差"相关仅 0.61、中位分歧 346ms）。本轮我自己第一次装配就踩中了它，
   靠"重算误差 vs 冻结标签误差"对账才发现 ⇒ 该对账已实现为 `uniform_axis_trap` 段，
   建议作为一切复用 detector_v2 证据分析的硬门。
2. **run1 不可复用（登记）**：其冻结引用
   `research_v7_align_behavior/smoke_20260805_review12/formal_manifest_v3/LONG_TIMELINE_MANIFEST.jsonl`
   已不在盘上 ⇒ run1 的 137k 单元证据无法重算（面板构建器显式输出
   `excluded: reference_timeline_missing`，而不是静默换一份同名 timeline）。
   同时发现 evidence_v2 以 attempt 身份命名、与 manifest 的 request 身份**无留存链接**
   （`cached/` 已清理）⇒ 这批证据的 window/request 级归因不可重建。
3. **长时序 baseline 真实水平**：hit@100 raw 87.95% / official 88.00%，MAE(both)
   83.2 / 78.9ms，unsafe(≥250ms) 2.4% ⇒ 合成长轴上未见整体退化。
4. **后处理并非处处有害（限定第 2 轮结论）**：research_v7 official 阶段只动 1.2% 单元，
   被动的单元 MAE 780ms→426ms、hit@100 60.3%→64.0%，repair 37.3% vs damage 31.1%，
   净效应单元级 +0.045pp、请求级 −0.041pp（CI [−0.121,+0.037]）≈ 中性；
   且被移动起点只有 **0.6%** 等于前一单元尾端（demo 管线 98.3%）
   ⇒ "把起点钉到前一个尾端"是 **demo 官方管线特有**，第 2 轮的改造建议只适用于那条管线。
5. **段首效应在长时序上不存在**：段首 87.78% vs 其余 87.97%（603 段）。
   因为这里每个拼接缝前有 0.5s 真静音；GTSinger 的"幻觉前奏"发生在**音频被硬切在起唱点**时。
   ⇒ 触发条件是"窗口左端没有真实前奏"，不是"处于边界"；自然长歌分窗若左端切在演唱中，
   风险与 GTSinger 同类，但本面板无自然长歌 GT，无法验证。
6. **熵基 no-GT 信号的定位被澄清**：`max_ent` AUC 随阈值变宽升高
   （100ms 0.779 → 200ms 0.910 → 250ms 0.928）；门控 OOF AUC bad250 0.924 / bad100 0.765。
   ⇒ 熵适合当 **gross error（≥250ms）触发器**，不适合当 100ms 精修验收器。
   项目现有三档标签（safe/grey/unsafe）在 100–250ms 灰区内无排序信息，熵可补这一层。

---

# 第 4 轮（同日）：普通话**自然录音**人工逐字真值面板（MIR-1K partial-align）

用户指示优先普通话效果。MIR-1K partial-align 子集带**人工逐字符 on/off 标注**
（`MIR1k_partial_align.json` 的 `on_offset`，预处理只做单调性/时长校验 ⇒ 不是第 3 轮那种伪造均匀轴），
2,035 字 / 17 首真实伴奏流行歌（官方人声通道，22–127 s）。项目 2026-07-22/24 在**同一集合**上留下
6 份预测（上游 base、r0、r1、r2×3 个不同训练 run/配置），但历史只汇总成一个标量 `loss`。
本轮做首次单元级分析；纯 CPU、零前向、+612 KB。

- 代码：`src/lyricalign/analysis/mir1k_natural_panel.py`
- 入口：`scripts/evaluation/report_mir1k_natural_panel.py`（含 metrics 输出）；`build_panel()/analyse()` 由模块暴露
- 测试：`tests/evaluation/test_mir1k_natural_panel.py`（8 项，含"位置轴必须来自真实字数"的回归护栏）
- 产物：`runs/20260912_mir1k_natural_panel/{PANEL_AUDIT,ANALYSIS}.json + panel.csv.gz`、
  `reports/progress/20260912_mir1k_natural_panel.md`、
  `results/by_run/20260912_mir1k_natural_panel/metrics.json`

## 结论

1. **对账门通过**：面板重算 `mean_iou` 与 canonical `metrics.corrected.json` 三个 r2 预测器全部
   `join_ok`（Δ≤3e-5）；MAE 差异完全由 canonical 的 song-macro/invalid 罚项口径解释。
2. 真实水平：hit@100 **91.8–92.3%**、hit@250 98.6–98.8%、MAE(start) 35–37ms、IoU 0.832；
   上游 base 只有 **22.7%**（且 20.1% 零/负时长）⇒ 项目适配贡献是决定性的，不可用上坡分数当基线。
3. 阶梯在第 3 个域上复现：r0→r1 **+16.4pp**、r1→r2 **+0.4pp**；r0 缺陷仍在尾边界（end 95ms vs start 60ms）。
4. **新失效层 = 每项最后一个字**：r2 末字 hit@100 82.3%（中间 91.1%、首字 94.1%），
   末字 end 偏移随模型翻号（r2 +101ms / r1 −77ms / r0 −468ms）；
   首字在自然录音上**没有**惩罚且预测 start 从不塌 0 ⇒ 与第 3 轮解释一致：
   GTSinger 的"段首幻觉前奏"需要"音频硬切在起唱点"作触发条件。
5. **长度不是因素、密度才是**：hit@100 与项时长相关 0.0025（13/17 项 >60s、3 项 >90s），
   与逐项字数相关 **+0.31** ⇒ "长音频更难"在自然数据上不成立，难度来自唱法/字密度。
6. 无真值分歧信号迁移成立但有前提：强集合（r0/r1/r2 三 run）AUC(≥250ms) **0.839**、AUC(>100ms) 0.628；
   把上游 base 放回来 AUC 掉到 0.789、flag10% 精度从 0.092 崩到 0.020
   ⇒ 已把成员规则写进代码（自身 hit@100 < 参考一半者自动 `weak_excluded`）。
7. 误差聚簇在自然录音上明显减弱（坏单元落 ≥2 游程占比 **42%**，GTSinger 是 67.6%）
   ⇒ 区域级 realign 的收益上限**按域不同**，不能把 GTSinger 聚簇率当通用常数。
8. 两个 checkpoint 的聚合差只有 +0.20pp，但 **3.8% 单元位移 >20ms**（最大 1.04s）
   ⇒ 聚合指标无法区分 checkpoint；单元级不稳定集合就是最该优先 realign 的候选。

## 纪律

MIR-1K 是 test-only：本轮全部数字只做报告，未用于任何 checkpoint 选择或机制调参；未改任何实现。

---

# 第 5 轮（同日）：多视角共识离线模拟 —— 主线 realign 的负结果

用 MIR-1K 自然录音面板上 5 个独立推理配置（同音频同歌词、不同 checkpoint/run）预注册 12 个策略，
在人工逐字 GT 上离线量化"共识/选择能救回多少、要花多少重算预算"。纯 CPU、零前向。

- 代码：`src/lyricalign/analysis/multiview_consensus.py`（S0 单次 / S1 中位 / S2 截尾均值 /
  S3 20ms 桶投票 / S4 分位门控+中位 / S5 门控+leave-one-out 中位 / S6 最大一致簇 / S7 GT 上界）
- 测试：`tests/evaluation/test_multiview_consensus.py`（5 项）
- 产物：`runs/20260912_mir1k_natural_panel/CONSENSUS_SIM.json`、报告 §5b、metrics 增补

## 结论（负结果，省 GPU）

| 事实 | 数值 |
|---|---|
| 单次基线 hit@100 | 91.45% |
| 可部署共识最优（S1 中位 / S6 一致簇，需 100% 重算） | 91.79%（**+0.34pp**） |
| 逐单元完美选人（用 GT，不可部署） | 96.02%（+4.57pp） |
| 共识关掉的上界差距 | **7.4%** |
| 门控版（只重算 p90 不稳定的 8% 单元） | +0.10pp |
| 门控 + leave-one-out 中位 | −0.34pp（p90）/ −0.59pp（p80） |
| 末字 hit@100 | 单次 82.4% → 共识 76.5%（被平均弄坏），GT 上界 88.2% |

⇒ **`multi-realign dynamics / audio recrop / multi-view consensus` 在"现有机制的多视图 + 任意选择/平均规则"
设定下不值得再花 GPU**；与第 2 轮"后处理只有 +2.4pp 空间"合起来：**单次解码之后的选择/清洗环节
合计可挽回空间都在几 pp 以内**，普通话精度要再涨必须回到解码本身（视图生成、左上下文、长音尾部判据）。
末字被平均拉坏这件事还额外说明：对拖长音尾边界，"多份预测"彼此高度相关，平均只会稀释正确答案。

## 顺带修掉的实现缺陷

S6 原为"支持度加权平均"，单个 gross outlier 仍带 1/N 权重（实测可把边界拖偏 ~0.5s）；
改为**最大一致簇内取均值**后与中位数一致 ⇒ 结论对选择规则不敏感（也说明这不是规则设计问题）。

---

# 第 5 轮续：真实长歌跨视图普查（25 首 · 无真值）——又一个"假因子"，而且带身份记录缺口

- 代码：`src/lyricalign/analysis/real_song_views.py`；入口 `scripts/evaluation/report_real_song_views.py`；
  测试 `tests/evaluation/test_real_song_views.py`（4 项）
- 产物：`runs/20260912_real_song_views/{real_song_views.jsonl.gz,VIEWS_PANEL_SUMMARY.json,VIEWS_ANALYSIS.json}`（964 KB）、
  `reports/progress/20260912_real_song_cross_views.md`、`results/by_run/20260912_real_song_views/metrics.json`

## 结论

1. **三个视图只有一个配对可按索引比较**：`full_slot` 有 **23.6%** 的位置落在不同字符上
   （该 run 跳过/重复单元造成索引漂移），且音频 sha 与 B4 完全不同（同 sha 占比 0%）⇒ 不可逐单元比较。
   （第一版普查没做这个检查，得出 p90 分歧 7s、max 114s 的假结论——是本目录**第二次**因索引/坐标不一致而险些误判。）
2. **唯一可比的配对 B4 vs current_silence 输出几乎完全相同**：>100ms 分歧只有 **0.08%**（9/10,909 单元），
   窗口计划逐字段一致（同 policy、60s core、10s 左上下文、同 committed 区间）
   ⇒ 2026-08-14 交付的 `B4 vs Current` 对照视频**不构成已识别的因子对比**。
3. **身份记录缺口**：三个视图由三个不同写入器产出——
   B4=`qwen_fa_serial_demo_v7_silence_aware_windows`（记录 22 个窗口标志，含 skip_silent/silence_aware/anchor）、
   批处理视图=`qwen_fa_batch_alignment_v4_forward_overlap_compression`（记录 12 个，**不含任何 silence 标志**）、
   `full_slot`=identity.schema_version **为空**。
   ⇒ 批处理链路上即使传了 skip-silent/边界保护标志，产物里也无法核对；
   这是 AGENTS"缓存身份须并入配置"要求在长歌 demo 链路上的破口。
4. 顺带得到一个**可靠**的单视图事实：真实伴奏流行歌上零时长/退化单元比例远高于录音室
   （中文 7.2%、英文 23.2%、日文 45-53%，GTSinger 干净数据只有 2-4%）
   ⇒ 产品化首要结构 gate 是消灭退化区间，而不是继续打磨边界。
5. 熵仍能预测"哪个单元跨视图不稳"（AUC 0.776–0.780），与第 1/3 轮同向。

---

# 第 6 轮：真实歌曲上的**后处理归因**（无真值，纯结构）

同一批 25 首真实歌（10,909 单元）同时记录了 raw 与 selected 两个阶段，因此不需要真值就能回答
"退化单元是谁造的"。数据源：`runs/20260912_real_song_views/POSTPROCESS_ATTRIBUTION.json`；
代码 `analyse_postprocess_attribution()`（`src/lyricalign/analysis/real_song_views.py`）；
报告 §3b；测试 +1 项（tests/evaluation 50 passed）。

## 结论

1. **干净结构是靠压扁单元换来的**：退化（零/负时长）单元清理前 11.2% → 清理后 **17.1%**；
   清理创建 947、修复 305（净 +642）。
2. 机制与第 2 轮同型但更温和：被移动的起点 72.0% 落在前一单元 selected 尾端、53.9% 的尾端落在
   下一单元起点；相邻重叠率 12.2% → 0.09%（连续性确实被强制）。
3. **raw 解码在真实伴奏歌上结构本身不成立**：负时长 6.6%、时长>3s 3.9%、单单元最长 raw 时长
   **108.7s**（中位 0.24s）、起点回退 7.1%；清理后分别 0.0%/0.4%/0.1% —— 是被"压成零长"抹平，不是修好
   （被压扁的单元里 42.7% 原本 raw 时长 >1s）。
4. **按单元类型分层是本轮最有用的图**：
   | 单元类型 | 单元数 | raw 退化 | 清理后退化 | raw 负时长 |
   |---|---:|---:|---:|---:|
   | japanese_word | 1,269 | 40.1% | **52.8%** | 25.1% |
   | word（英文） | 1,951 | 14.3% | 23.1% | 8.7% |
   | cjk_character（普通话） | 7,689 | 5.7% | **9.7%** | 3.0% |
   ⇒ 普通话是最健康的路径；**word 单元化 + 缺乏结构约束才是主要故障源**。
   普通话侧真正的下一步是把 9.7% 退化率压下去（约束解码/单调性修复），不是继续磨边界毫秒。
5. 方法论提醒（第三次踩同类坑）：第一版归因用均值报出"start 平均位移 15.7s"，
   实为少量极端 raw 区间（如 raw=(87.88, 66.76)）拉爆均值 ⇒ 本模块现在只报中位/p90，
   均值字段显式改名 `..._USE_WITH_CARE`。

## 第 6 轮续：清理规则离线模拟（无真值，只比结构与破坏度）

代码 `src/lyricalign/analysis/cleanup_simulation.py`（R0 不清理 / R1 现装 / R2 朴素单调钳位 /
R3 只修尾端+0.05s 下限 / R4 置信加权拆分 / R5 修尾端后钳位 / R6 先钳制异常再修尾端 / R7 只钳制异常）；
产物 `runs/20260912_real_song_views/CLEANUP_SIM.json`；报告 §3c；测试 5 项（tests/evaluation 55 passed）。

| 规则 | 退化单元 | 重叠 | 起点回退 | 可信时长损失 | 被移动单元 | 移动者中高置信占比 |
|---|---:|---:|---:|---:|---:|---:|
| R0 不清理 | 11.25% | 12.17% | 7.10% | 0% | 0% | — |
| R1 现装 | **17.13%** | 0.09% | 0.06% | **33.3%** | 22.5% | 4.5% |
| R2 朴素单调钳位 | 0% | **97.85%** | 0% | −1.2% | **97.9%** | **51.1%** |
| R3 只修尾端(V9 式) | 0% | 11.71% | 7.10% | 16.1% | 22.2% | 6.4% |
| R6 先钳制异常再修尾端 | 0% | 11.71% | 7.10% | **14.1%** | 23.8% | 6.0% |
| R7 只钳制异常 | 0% | 18.41% | 7.10% | −7.8% | 15.1% | 1.1% |

要点：
1. **现装规则用"压扁"换干净**（退化 17.1%、可信时长损失 33.3%）；
   **R6 可以在完全不制造零长单元的前提下把破坏度降到约一半（14.1%）**，
   但重叠/起点回退仍未解决 ⇒ 正确做法是**联合约束求解**（一次性解一个受约束的区间序列），
   不是逐步 if-else 修补。
2. **负结果**：朴素单调化会级联（R2 移动 97.9% 单元、位移中位 163s、重叠反而升到 97.9%），
   因为单个 raw 异常（尾端早于首端数十秒）在强制排序后把后续全部推走
   ⇒ 任何单调性修复**必须先钳制异常区间**（R6 的第一步），这也解释了为什么 15.7s 的"平均位移"是假象。
3. 置信代理可用：R1/R6 移动的高置信边界仅 4.5%/6.0%，而 R2 高达 51.1%
   ⇒ "少动高置信边界"应作为清理规则的**第二目标函数**（与退化率一起看）。
4. 度量口径教训：raw 时长中位 0.24s 但最长 108.7s ⇒ 破坏度必须按**封顶可信时长**计，
   否则"删掉异常"会被误记成"毁掉内容"（首版 mass_lost 78% 就是这么来的，已改为 33.3%）。

---

# 第 7 轮：联合约束求解式清理（首个**带真值验证为正**的规则改进）+ 长时序口径更正

- 代码：`src/lyricalign/analysis/joint_cleanup.py`（LP：min 0.05s / max 3s / 起点保序 / 相邻非重叠 /
  加权 L1 贴近"钳制后的 raw"；权重由记录下来的边界熵按秩给出，不用真值）
- 入口：`scripts/evaluation/solve_joint_cleanup.py`（三面板）+ `scripts/evaluation/report_joint_cleanup.py`
- 产物：`runs/20260912_real_song_views/JOINT_CLEANUP.json`、
  `runs/20260912_m4_longform_weakgt/ANALYSIS_CALIBRE.json`、
  `reports/progress/20260912_joint_cleanup.md`、`results/by_run/20260912_joint_cleanup/metrics.json`
- 测试：`tests/evaluation/test_joint_cleanup.py`（6 项，含两个真实 bug 的回归护栏）

## 三面板结果（α=0，未用真值调参）

| 面板 | 指标 | raw | 现装后处理 | 联合求解 |
|---|---|---:|---:|---:|
| GTSinger（人工真值，28,980 单元） | hit@100 | 83.34% | 81.57% | **83.59%** |
| | 退化单元 | 1.26% | 4.61% | **0.00%** |
| | MAE(both) | 103.9ms | 106.5ms | **101.2ms** |
| M4 长时序（弱 GT，116,369 行/1,380 请求序列） | hit@100 | 86.54% | 86.00% | **86.57%** |
| | 重叠 | 1.81% | 0.00% | 0.00% |
| 真实伴奏歌（无真值，10,909 单元） | 退化单元 | 11.25% | 17.13% | **0.00%** |
| | 重叠 / 起点回退 | 12.17% / 7.10% | 0.09% / 0.06% | **0.00% / 0.00%** |

⇒ **建议用一次联合求解替换顺序 if-else 清理**：它在带真值面板上比现装高 +2.02pp、
在自然长时序上精度中性、在三类数据上都把退化/重叠/回退降到 0。
置信加权 α 只做敏感性检查（α=2/4/8 略降 0.8pp 但更少动高置信边界），不据此调参。

## 对第 3 轮的口径更正（attempt ≠ unit）

长时序面板每行是 **(request, view, 单元)** 一次尝试（滑窗重叠 ⇒ 同一单元最多被 24 次尝试覆盖；
134,538 行 = 14,441 个唯一单元，扇出 9.3×）。此前文字把行级统计称作"单元级"，属口径错标。
正确单元键必须含 song：`(view_id, song, canonical_unit_id)`。修正后的分层：

| 口径 | raw hit@100 | raw MAE | official hit@100 | official MAE |
|---|---:|---:|---:|---:|
| attempt 级（旧报告口径） | 84.97% | 242.1ms | 86.20% | 157.4ms |
| unit 级·尝试中位 | 87.33% | 101.4ms | 87.66% | 86.2ms |
| unit 级·尝试最差 | 73.65% | 1.06s | 75.64% | 604.8ms |
| unit 级·尝试最优（跨窗 oracle，用真值） | 90.53% | 74.8ms | 90.74% | 63.8ms |

由此得到两个新事实：
1. **现装 official 阶段的真正贡献是跨窗口方差收缩**：每单元误差极差 p90 从 raw 的 3.56s 压到 0.40s（约 9×），
   而单元级中位精度几乎不变（87.33%→87.66%）⇒ 解释了它为什么值得存在（第 2/3 轮"净损害"的说法需要这一层补充）。
2. **跨窗选择 headroom +3.2pp**（90.53% vs 87.33%）远大于第 5 轮跨 checkpoint 共识的 +0.34pp
   ⇒ 值得下一步做"**可无真值选人**的多窗口实验"（用极差/熵/边界一致度作选择器），
   而不是再换 checkpoint。

## 本轮自查纠正的三个错误

1. LP 目标函数把 S/E 本身计入成本（应只惩罚偏差 u/v）⇒ 解被拉向 t=0；已在测试中固化为
   "可行解必须原样复现"回归护栏。
2. 绝对值线性化的两条右端项符号写反 ⇒ 平均位移出现 15.7s 荒谬值。
3. 长时序序列误按 (view, segment) 分组（把同一单元的多次尝试混进一条序列）⇒ 首次跑出 6% hit@100；
   正确分组是 **(request_identity, view_id)**，并把 (view,cid) 缺少 song 导致的"40% 冲突行"假象一并澄清。

---

# 第 8 轮：长时序跨窗口选择（先修好尺子，再量 headroom 能不能无真值吃到）

- 代码：`src/lyricalign/analysis/{longform_signed_gt,cross_window_selection}.py`
- 入口：`scripts/evaluation/{rebuild_longform_signed_gt,run_cross_window_selection,report_cross_window_selection}.py`
- 产物：`runs/20260912_m4_longform_weakgt/{signed_gt.pkl,SIGNED_GT_STATS.json,CROSS_WINDOW_SELECTION.json,per_unit_attempt_summary.csv.gz}`（1.3M + 160K，删掉了临时 64MB 特征 pickle）
- 测试：`tests/evaluation/test_cross_window_selection.py`（3 项；tests/evaluation 64 passed）
- 报告：`reports/progress/20260912_cross_window_selection.md`；指标：`results/by_run/20260912_cross_window_selection/metrics.json`

## 0. 尺子问题（本轮先解决它）

面板的 `label_*_err_sec` 是**无符号**绝对误差 ⇒ `raw − err` 反推真值有 ± 号歧义；
面板自带 `gt_*` 又是第 3 轮证明的伪造均匀轴。按 labeler 的公式重建
（段局部 `timestamp_class_ids × 0.08s` + `segment_offsets.global_start_sec`）后：

- **与冻结误差偏差 max = 0.0s、corr = 1.0（raw 与 official 两阶段都是）** ⇒ 与 labeler 用的是同一份参考；
- 与 raw 距离 ≤100ms 的比例：面板伪造轴 15.9% vs 重建参考 89.1%（中位 327.5ms vs 33.0ms）
  ⇒ 第 3 轮"伪造均匀轴"结论获得定量版本；
- 同单元跨尝试的重建真值极差中位 0.0s、≤5ms 占比 100% ⇒ **此前看到的"24% 单元跨尝试分歧 >100ms"是 ± 号假象**；
- 参考性质：`rule_validated`、模型产出、80ms 量化 ⇒ 有一切一致性指标都有 ±40ms 底噪，不是人工 GT。

## 1. 结果（13,743 单元 / 127,923 次尝试；每单元最多 24 个窗口覆盖）

| 方法 | hit@100 | MAE | Δ vs 跨窗中位 | 吃掉 oracle 差距 |
|---|---:|---:|---:|---:|
| 任意单一窗口（现状） | 84.81% | 271.5ms | −2.14pp | −64% |
| 跨窗误差中位（参考线） | 86.95% | 117.9ms | 0 | 0 |
| 跨窗边界取中位（共识输出） | 86.97% | 116.7ms | +0.02pp | 0.6% |
| 离共识最近的那一次 | 86.97% | 118.0ms | +0.02pp | 0.6% |
| **与其余尝试一致度最高（no-GT）** | **87.55%** | 118.0ms | **+0.60pp** | **18%** |
| 熵最低 / margin 最大 | 87.04% / 87.11% | 135.1 / 150.8ms | +0.09 / +0.16pp | 2.7% / 4.8% |
| 单元在窗口内最居中 | 85.80% | 209.8ms | **−1.15pp** | −34.5% |
| 先用 ≤100ms 门控再取熵最低 | 87.34% | **112.7ms** | +0.39pp | 11.7% |
| 用真值挑最好尝试（上界） | 90.28% | 87.8ms | +3.33pp | 100% |

1. **长时序的真实风险来自窗口选择，不是解码器平均质量**：随机用一个窗口比跨窗中位差 2.14pp；
   最差尝试只有 64.85%（MAE 1.85s）。
2. **无真值可部署的支持度选择器拿到 +0.60pp**（oracle 差距的 18%）——显著好于第 5 轮跨 checkpoint 共识（+0.34pp、7.4%）
   ⇒ 视图多样性（不同裁窗）才是值得花钱的变量，同裁窗换模型不是。
3. **置信信号不足以选窗**：熵 +0.09pp、margin +0.16pp ⇒ 它们能抓 gross 错误（第 1/3/5 轮），
   但不能在多个"合格"尝试中挑出最好的。
4. **反直觉负结果**：把单元放在窗口中央反而更差（−1.15pp）
   ⇒ 削弱"重新裁窗把困难单元居中"这类 realign 设计的理论依据。
5. 工程上可直接输出跨窗**中位边界**（86.97%，等价于回选尝试），无需保留多个尝试。

## 2. 本轮自查纠正

- 首版重建给 end 多加了一个量化格点（`(id+1)×0.08`），与 labeler 的 `id×0.08` 不符 ⇒ 端点命中率一度只有 0.38%；
  修正后端点也 100% 命中（`max_deviation 0.0`）。
- 首版按 `(view_id, canonical_unit_id)` 分组得出"面板 40% 冲突行"，实为漏了 `song` 维度
  （cid 是**歌曲内** timeline 下标）；加入 song 后跨尝试自洽率 100%。
- 临时写的 64MB 特征 pickle 已删除，改存 160KB 逐单元汇总（`per_unit_attempt_summary.csv.gz`）。

---

# 第 9 轮：长时序端到端候选输出 + realign 触发器价值

- 代码：`src/lyricalign/analysis/longform_pipeline_candidate.py`
- 入口：`scripts/evaluation/{run_longform_pipeline_candidate,report_longform_pipeline_candidate}.py`
- 产物：`runs/20260912_m4_longform_weakgt/{REALIGN_TRIGGER.json,PIPELINE_CANDIDATE.json,per_unit_disagreement.csv.gz}`（+~300KB）、
  `reports/progress/20260912_longform_pipeline_candidate.md`、
  `results/by_run/20260912_longform_pipeline_candidate/metrics.json`
- 测试：`tests/evaluation/test_longform_pipeline_candidate.py`（4 项；tests/evaluation 68 passed）

## 端到端对照（13,743 单元，参考=已验证有符号弱标签）

| 系统 | hit@100 | hit@250 | MAE | 退化 | 重叠 | 回退 |
|---|---:|---:|---:|---:|---:|---:|
| A 单个窗口（谁先覆盖用谁） | 84.46% | 94.03% | 271.5ms | 1.46% | 3.11% | 0.89% |
| B 现装 official（同一窗口） | 83.99% | 93.71% | 197.1ms | **3.10%** | 0.07% | 0.06% |
| C 跨窗口共识（边界取中位） | **86.60%** | 96.57% | 116.7ms | 0.56% | 2.37% | 0.18% |
| D 共识 + 联合求解 | 86.07% | 96.24% | **102.4ms** | **0%** | **0%** | **0%** |
| E 真值挑最好尝试（上界） | 89.99% | 97.47% | 87.8ms | — | — | — |

1. **共识 > 现装**：+2.14pp hit@100、MAE 271.5→116.7ms。
2. **共识+求解 = 结构零缺陷**，且 MAE 是可部署里最好的（102.4ms），代价 0.53pp hit@100。
3. **自我修正**：先前猜"0.5pp 损失来自 3s 时长上限"是**错的**——max_dur 3/6/12s 的 hit@100 为
   86.07/86.08/86.08%（几乎不变）⇒ 损失来自**非重叠+保序约束本身**（把重叠长音压回下一单元起点）。
4. 现装 official 在**第三个数据域**再次复现"制造退化单元 + 掉精度"（raw 1.46%→official 3.10%，−0.47pp），
   与第 2 轮（GTSinger −1.66pp）、第 6 轮（真实歌 11.2%→17.1%）同向。

## 触发器（realign 该由什么触发）

只在 ≥2 次尝试的单元上可评估（**仅 39.97% 的单元有多窗口尝试**，中位 1 次、最多 24 次）：

| 目标 | 阳性率 | 分歧度 AUC | 支持度 AUC | **熵 AUC** | loo 距离 | 尝试次数 |
|---|---:|---:|---:|---:|---:|---:|
| 误差>100ms | 13.6% | 0.584 | 0.653 | **0.779** | 0.505 | 0.528 |
| 误差≥250ms | 3.62% | 0.705 | 0.850 | **0.881** | 0.479 | 0.527 |

- 错误捕获曲线（按分歧度排序）：top 5/10/20/30/50% 预算只捕获 **8.1/15.3/26.9/41.5/66.3%** 的单窗错误
  ⇒ 分歧度接近随机排序，**不足以支撑"只重算分歧单元"**；loo 距离尤其差（AUC≈0.48）。
- 结论与第 1/3/5 轮一致并加强：**触发特征应该用边界熵**（四轮独立复现），
  跨窗分歧度只能在"已有多个窗口"的 4 成单元上作次要信号。
- 若把资源花在"重算并按某种规则选"，上界是 E 的 +5.53pp（其中 2.14pp 已由免费的共识拿到），
  剩余 3.4pp 才是多视图+选择器的真实目标区间。

## 建议（可直接进产品讨论）
- 长时序输出：默认用**跨窗共识**；若产品要求非重叠/无零长（卡拉OK 高亮），再叠加**联合求解**（+0 结构缺陷，−0.5pp）。
- 触发器：以**边界熵**为主特征；分歧度作为可选辅助，且必须先主动生成多视图才有输入。
- 任何进一步收益需要新前向；本会话至今零 GPU 消耗，GPU 申请建议以"+3.4pp 可及区间"为量化依据。

---

# 第 10 轮：GTSinger 多视图选择（人工真值）+ 因子内容审计

- 代码：`src/lyricalign/analysis/gtsinger_multiview.py`（`build_view_frame/view_quality/selection_experiment/factor_content_audit`）
- 入口：`scripts/evaluation/{run,report}_gtsinger_multiview.py`
- 产物：`runs/20260912_gtsinger_multiview/{MULTIVIEW.json,view_rows_*.csv.gz,consensus_*.csv.gz}`、
  `reports/progress/20260912_gtsinger_multiview.md`、`results/by_run/20260912_gtsinger_multiview/metrics.json`
- 测试：`tests/evaluation/test_gtsinger_multiview.py`（3 项，含"不等质量视图混入共识必然变差"的复现护栏）

## 结论 1：名义 12 视图，实际只有 1 个有效轴

2,415 单元 × 12 视图（3 checkpoint × mix/vocal × full/windowed），人工逐字真值：

| 因子（其他因子固定） | 比较组数 | start 边界差中位 | start >100ms | end >100ms |
|---|---:|---:|---:|---:|
| model | 9,660 | 0.0s | 8.4% | 21.5% |
| audio_input | 14,490 | 0.0s | **0.0%** | **0.0%** |
| mode | 14,490 | 0.0s | **0.0%** | **0.0%** |

内容审计给出根因：
- **`audio_input` 是 DEAD CONFIGURATION（P1 历史缺陷）**：954 组 mix/vocal 配对的 `audio_sha256`
  **100% 相同** ⇒ 那次消融从未真的换过输入，只有 request_hash 因路径不同而变了；
  基于 evaluation_v1 该因子的任何结论作废（第 1 轮的"矩阵退化"现在有根因）。
- `mode` 不是 bug：短片 5–15s 短于一个 60s 窗口 ⇒ 分窗与整曲必然同结果，属"此数据上无信息"。
- ⇒ 真正有差异的只有 checkpoint 轴（r0/r1/r2 相差最多 20.5pp）。

## 结论 2：基线已是最优视图时，一切无真值选择器都是负的

| 方法 | hit@100 | Δ vs 现装视图 |
|---|---:|---:|
| 现装视图 r2\|vocal\|windowed | **88.04%** | 0 |
| 离共识最近的视图 | 87.37% | −0.67pp |
| 跨视图共识（取中位） | 87.29% | −0.75pp |
| 现装视图若与共识≤100ms 否则换支持度 | 87.19% | −0.85pp |
| 熵最低的视图 | 85.76% | −2.28pp |
| 支持度最高的视图 | 85.26% | −2.78pp |
| 随机一个视图（视图平均） | 80.37% | −7.67pp |
| oracle（真值挑最好视图，上界） | 91.01% | +2.97pp |

raw 阶段同向（现装 89.74%，共识 −0.46pp，oracle +2.93pp）。
原因：把 r0（67.5%）与同质但更弱的单元格混进共识只会稀释 r2 的正确答案。

## 三轮合并出的规律（本轮真正产出）

| 证据 | 视图差异来源 | 基线 | 融合效果 |
|---|---|---|---|
| 第 5 轮 MIR-1K | 同裁窗换 checkpoint | 现装单视图 | +0.34pp（oracle 4.57pp，吃 7.4%） |
| 第 9 轮 M4 长时序 | **不同裁窗**（同 checkpoint） | 任意覆盖窗口 | **+2.14pp（免费）** |
| 第 10 轮 GTSinger | 混合（且输入侧未变） | 已选好的最优视图 | **−0.75pp（共识反而更差）** |

1. 只有**输入层面真的不同**（不同裁窗/不同音频条件）的视图才有信息量；同裁窗换模型≈零收益，
   同文件换退化因子＝零收益。
2. 参与共识的视图**质量必须齐平**（不等质量混入是净损害），且能力门不能靠真值来定。
3. **先确认基线是什么再谈融合**：基线是随机视图时融合赚 2.14pp，基线已是最优视图时融合亏 0.75pp。
4. 熵作**触发器**有效（第 1/3/5/9 轮 AUC 0.78–0.88），作**视图选择器**无效（−2.28pp）：
   它回答"这个单元可不可信"，不回答"哪个视图对它更好"。
5. 流程：`factor_content_audit()` 是第 2 轮就提议的**配置矩阵同一性门**的最小实现，
   应挂进批次收尾（内容哈希相同而标签不同 ⇒ `not_identified`，拒绝出对比结论）。

---

# 第 11 轮：末字尾边界的声学锚点实验（两条简单判据均被否证）

- 代码：`src/lyricalign/analysis/tail_acoustics.py`（RMS 衰减锚点、人声/伴奏比值锚点、混合规则、结构化对照）
- 入口：`scripts/evaluation/{run,report}_tail_acoustics.py`；测试 `tests/evaluation/test_tail_acoustics.py`（5 项）
- 产物：`runs/20260912_tail_acoustics/TAIL_ACOUSTICS.json`、`reports/progress/20260912_tail_acoustics.md`、
  `results/by_run/20260912_tail_acoustics/metrics.json`
- 纪律：阈值只在 GTSinger（人工真值）上导出，冻结迁移到 MIR-1K（test-only）；ρ 族整族报告不选点；零 GPU、音频只读。

## 结果

1. **RMS 衰减锚点在末字上几乎不触发**：GTSinger 末字 168 单元中最多 6 个有锚点；MIR-1K 末字 17 单元中**只有 1 个**
   ⇒ 它没有机会修我们已定位的失效层（末字多为拖到片段结束的长音，区间内不存在可判定的相对衰减）。
2. **阈值不可迁移**：GTSinger 长音最优 θ=0.15（+3.69pp）冻结到 MIR-1K 长音后 **−13.37pp**（全单元 −22.08pp）。
3. **人声/伴奏比值锚点覆盖极高但完全不够准**：覆盖 88–99%（含全部 17 个末字），
   hit@100 最好 61.5% vs 同一批单元上模型 95.8%；末字子集 29.4% vs 模型 88.2%。
4. **oracle 界**（模型 vs 各锚点逐单元用真值挑最优）：GTSinger 全单元 +0.75pp、**末字 +0.00pp**；
   MIR-1K 全单元 +1.67pp、**末字 +0.00pp**。长音 +7.14pp 属 test 上的事后观察，不构成可部署结论。
5. 模型自身端点已很强：GTSinger MAE(end) 38.9ms、MIR-1K 35.8ms（长音 69/74ms，末字 33/122ms）。

⇒ **关闭 F3 的简单版本**：末字/长音残余误差**不能**用事后声学阈值判据修复；需要模型侧改动
（更长右上下文、拖长音 offset 的训练信号）。与文献结论一致（歌声音符 offset 无稳健通用解）。
另记：本轮再次印证第 10 轮根因——GTSinger 的 mix/vocal `audio_path` 指向同一个文件。

## 第 11 轮续：可复用的证据同一性门 + 历史批次审计

- 代码：`src/lyricalign/analysis/evidence_identity_audit.py`（`collect/audit_pair/audit_identity_hygiene`）
- 入口：`scripts/evaluation/{audit_evidence_identity,report_evidence_identity_audit}.py`
- 产物：`runs/20260912_evidence_identity_audit/IDENTITY_AUDIT.json`、`reports/progress/20260912_evidence_identity_audit.md`、
  `results/by_run/20260912_evidence_identity_audit/metrics.json`；测试 5 项（tests/evaluation 81 passed）

门把批次两两比较归为四类裁定：`identified` / `not_identified` / `duplicate_configuration` / `not_comparable`，
关键改进是**「输出不同只在输入字节也不同的歌上发生」单独成类**，于是第 5 轮的结论被收紧为机器可判定的形式：

| 比较对 | 裁定 |
|---|---|
| ktv_B4 vs current_silence | **同一配置的重复运行**：25/25 窗口计划相同、23/25 歌曲输出逐字节相同，剩余 2 首差异全部落在音频 sha 也不同的歌上 |
| current_silence vs slot_align | **不可比**：33/33 首单元数相同但逐索引文本不同（索引漂移） |
| ktv_B4 vs slot_align | **不可比**：25/25 同上 |
| current_silence vs textmode3 | **不可比**：33/33 首单元数不同（word vs char 单元化） |

身份卫生表另给出一个硬事实：`20260815_slot*` 两批的
`identity.schema_version` / `audio_sha256` / `request_hash` **100% 缺失** ⇒ **不可归因**（连用了哪份音频都无法证明）；
四批的退化单元比例 16.7%–19.7%，与第 6 轮 17.1% 一致（独立复核）。

⇒ 2026-08-14/15 那套真实歌对比套件**不能支撑任何机制结论**；同时门已可用，建议接入批次收尾（F4）。

---

# 第 12 轮：已交付时间线的结构合规审计 —— **定位到后处理制造零长单元且自检计数器失明**

- 代码：`src/lyricalign/analysis/structural_compliance.py`（`load_batch / flag_violations / repair / summarise / export_repair_list / compression_damage`）
- 入口：`scripts/evaluation/{run,report}_structural_compliance.py`；测试 `tests/evaluation/test_structural_compliance.py`（6 项）
- 产物：`runs/20260912_structural_compliance/{COMPLIANCE.json,repair_list_*.csv.gz}`（~170KB）、
  `reports/progress/20260912_structural_compliance.md`、`results/by_run/20260912_structural_compliance/metrics.json`
- 不需要真值：全部是已交付 timeline 自身的结构属性；修复=第 7 轮联合求解；realign 仍 shadow-only。

## 核心发现（P1 候选）

33 首批次（`20260814_ktv_current_silence`，13,735 单元）：

| 量 | 数值 |
|---|---:|
| raw 阶段零长单元 | 1,483（10.80%） |
| 交付后零长单元 | **2,236（16.28%）** |
| 后处理**新造**零长 | **1,112 单元（8.10%）** |
| 后处理同时修复的 raw 零长 | 359 |
| 净增 | +752 |
| 产物自带计数器 `overlap_compression_collapsed_to_zero_count` 总和 | **4** |
| ⇒ 计数器对自身损害的失明率 | **99.6%** |

归因：逐歌交付零长比例与 `seam_repaired_character_rate` / `overlap_compressed_character_rate`
相关 **r = 0.9216** ⇒ 损坏发生在**接缝修复/重叠压缩**那一步，不是解码器；且"没有任何一首歌是 raw 无零长而交付有"
⇒ raw 也带零长，压缩在其上再放大约 8pp。

最严重：初音未来的消失（JP，raw 47.4%→76.5%，新造 193，计数器 0）、
I See Fire（EN，51.4%→88.1%，新造 123，计数器 0）、
**画下灯塔水母（中文，21.1%→38.5%，新造 103，计数器 2）**。

## 语言分层（对"优先普通话"的直接含义）

| 语言 | 单元 | 交付非法率 | 零长率 | 修复需移动 | 新造零长 |
|---|---:|---:|---:|---:|---:|
| Chinese | 7,206 | **6.58%** | 6.27% | 9.44% | 279 |
| Cantonese | 2,439 | 15.09% | 14.68% | 21.28% | 165 |
| English | 2,108 | 22.68% | 21.87% | 29.70% | 227 |
| Japanese | 1,982 | **49.29%** | 48.69% | 63.12% | 441 |

⇒ 普通话是最健康路径；**结构治理的优先级在非中文 word 单元路径**；中文侧收益集中在少数歌
（画下灯塔水母 38.9%、梦良衣 14.3%）。

## 修复效果与分诊

- 联合求解逐歌施加后：两批的 zero / overlap / overshoot / regression 全部 **0.00%**。
- 位移必须分层报：全量 p90 4.5s 吓人，**剔除超长单元后 p90 = 4.44s→中位 0.1s**；
  大位移全部来自把 40+ 秒离谱区间钳回合法范围。
- 分诊规则（33 首分布：≤2% 4 首、2–5% 8 首、5–15% 9 首、15–35% 6 首、35–60% 3 首、>60% 3 首）：
  **>35% 档应重解码/回查压缩逻辑，而非打补丁**（如 I See Fire 88% 单元被压成同一时间戳 64.48，
  其 raw 边界其实各不相同）。

## 三条可执行建议
1. 给压缩步骤补**真实**的 collapsed-to-zero 计数与告警（现在报 4 / 实际 1,112）。
2. 把本审计作为**交付前 gate**：非法率 >5% 不允许出片。
3. 把 >35% 档歌曲列入重解码队列（清单已导出 `repair_list_*.csv.gz`，只含非法单元）。

## 第 12 轮附带的健壮性修复（由测试不稳定引出，结果是产品侧也更稳）

现象：全量套件在同一命令内刚写完大文件时会多出一批失败，且集合会变（11 → 8 → 6 → 5）。
定位：受控 I/O 负载复现后抓到真实原因——**高负载下 `scipy.optimize` 的导入本身会失败**
（`lp_raised:ModuleNotFoundError`），于是 LP 求解不可达。

- 旧行为：`solve_block` 回退到"钳制后的 raw"⇒ **重叠/回退/零长又回来了**（结构保证依赖求解器运气）。
- 新行为：回退走 `_legal_sweep`（构造性合法：min/max 时长、起点保序、非重叠、落在音频内），
  实测在退化/负长/超长/已合法四类输入上都保持合法，且不扰动已合法序列。
- 测试口径修正：断言**合法性**而不是 `status == "ok"`；比较加权与无加权结果的用例在求解器不可达时显式 skip。
  （测试不应把环境运气写进断言。）
- 结论：机器上跑测试时避免与大批量写盘并发；本会话规则记为"测试单独跑"。

---

# 第 13 轮：F6 根因 —— 塌陷发生在 **fixed 阶段**，并推翻我第 12 轮的归因

- 代码：`structural_compliance.stage_lineage_attribution()`（逐阶段退化谱系 + 「钉到窗口锚点」检测）
- 测试：`tests/evaluation/test_stage_lineage.py`（4 项）；报告新增 §0b；产物 `STAGE_LINEAGE.json`
- 全部读产物 + 读代码，零前向、不改生产行为

## 归因修正（重要）

第 12 轮我用逐歌相关（交付零长率 vs `seam_repaired_character_rate`，r=0.9216）把责任指向
**重叠压缩**。逐阶段核对四个阶段（raw → fixed → selected → final）后该归因**错误**：
相关只是「既坏又常被修的歌」的共因。真实分布（三批一致）：

| 批次 | raw | fixed | selected | final | fixed 阶段净新造 | 压缩阶段净新造 |
|---|---:|---:|---:|---:|---:|---:|
| current_silence_33 | 10.80% | **16.28%** | 16.28% | 16.31% | **+807** | +4 |
| B4_25 | 11.25% | **17.13%** | 17.13% | 17.15% | **+697** | +2 |
| slot_align_33 | 12.42% | 14.98% | 14.98% | 14.98% | +426 | +0 |

`selected_*` 恒等于 `fixed_*`（压缩步不改 `selected`），压缩只贡献个位数 ⇒
**退化是 fixed（官方边界修正 / 窗口→全局时间回映射）阶段制造的**。

## 机制签名（可复核）

被弄坏的整块单元在 fixed 阶段**等于所属窗口的 `input_start_sec`**：
`I See Fire` window 0 的 `core_start=66.48`、左上下文 2.0 ⇒ `input_start=64.48`；
该歌 262/311（84.2%）单元的 `fixed_global_*` 恰为 64.48，
而它们自己的 `raw_global_start_sec` 在 64.48–119.28 间正常递增 ⇒ 预测是好的，回映射把块钉死了。

跨批次规模：33 首批次 **946 单元（6.89%，10 首歌）**、B4 **832（7.63%，8 首）**、slot 批次 0
（该批次无 window_trace 锚点，说明还有第二条路径，但其 fixed 净新造 +426 依然存在）。
最严重：初音未来的消失 351（62.6%）、I See Fire 262（84.2%）、**画下灯塔水母 135（25.4%，中文）**、冬之花 112（50.4%）。

## 两个独立缺陷（不要混为一谈）+ 观测缺口位置也要修正

1. **解码器侧**：raw 阶段就有 10.8–12.4% 退化，其中 **870 个是负时长**（end 早于 start）——
   这与第 6 轮「r0 缺陷在尾边界」、第 11 轮声学锚点在末字不触发相互印证。
2. **fixed 阶段回映射**：把块钉到窗口锚点，额外 +426~+807 单元。
3. 观测缺口不是「压缩计数器漏计」：那个计数器对自己的定义是自洽的（`original_duration>0 → final==0`）；
   真正缺的是 **fixed 阶段没有任何退化计数**，也没人检测「块被钉到同一时间戳」。

⇒ 最小修复建议（不改现有产物）：summary 里按阶段输出 `degenerate_share` + `pinned_to_anchor` 计数，
并把交付 gate 设在阶段谱系上（任一阶段净新增退化 > 1% ⇒ 不出片并指明是哪个阶段）。

## 方法论收获（写给自己）

相关性可以指向错误的阶段；**阶段谱系比对**（同一单元的多个阶段值）才是因果证据。
本轮同时把「逐歌净值」与「单元级新造数」两个口径分开命名（`net_added_by_*` vs `created_by_postprocess`），
避免净值抵消掩盖问题。

## 第 13 轮续：统一批次自检入口 `scripts/evaluation/audit_batch.py`

一条命令回答三件事（全部零真值、零前向）：
1. **可归因吗**：每首歌是否记录 audio sha / request_hash / schema / 规划标志；
2. **结构合法吗**：零长/重叠/回退/离谱时长，并且**按阶段谱系定位是谁造的**（第 13 轮教训：
   相关性会骗人，必须逐阶段比同一单元的四个阶段值）；
3. **修得回来吗**：用联合求解当检查器，报告"合法化需要移动多少单元、位移多大"。
另可选 `--compare-batch` 走第 11 轮的配对门（identified / not_identified /
duplicate_configuration / not_comparable）。

对真实批次的实际输出（就是本会话已诊断的那批）：

```
VERDICT=blocked  blocking=['structural_legality','stage_attribution','window_anchor_pinning']
   [OK ] attributable_identity   {..., records_silence_flags: 0.0}
   [FAIL] structural_legality     illegal_share 16.72% (gate 5%)
   [FAIL] stage_attribution      worst_stage=net_added_by_fixed (+807)
   [FAIL] window_anchor_pinning  pinned 946 (6.89%, 10 首)
   [OK ] repair_feasibility      post_repair_illegal_share 0.0, moved 22.4%, 中位 0.1s
pairwise -> DUPLICATE_CONFIGURATION: 23/25 逐字节相同 ...
```

gate 阈值写在 `GATES`（illegal 5% / 阶段净新增 1% / 钉锚点 2%），是**建议默认值**而非已裁定标准，
调整需要在项目内讨论；本会话没有改动任何生产实现。测试 3 项（合成批次 + 子进程冒烟）。

---

# 第 14 轮：观测接入生产写入器 + 普通话逐歌分诊清单

## 1) additive 观测（不改任何行为）
`src/lyricalign/demo/alignment_artifacts.py::stage_degeneracy_audit(rows, window_trace)`：
按生产阶段名（`raw / processor_decoded / selected / final`，其中 `processor_decoded` 就是我审计里叫的
`fixed`）输出 `degenerate_share`、`net_added_degenerate_units`（跨阶段净值）、
`pinned_to_window_anchor_units/rate`，并按阈值产出 `warnings`
（`degeneracy_added_by_<a>-><b>`、`pinned_to_window_anchor`）。
已接入两个写入器的 `summary`（键 `degeneracy_audit`）：
`scripts/demo/run_qwen_fa_batch.py`、`scripts/demo/align_qwen_fa_serial_demo.py`。
只做记录，不改任何边界；现有测试 `tests/test_qwen_fa_serial_demo.py` 20 项全过 ⇒ 无回归。

这补上了第 13 轮定位的缺口：**fixed(processor_decoded) 阶段此前完全没有退化计数**。

## 2) 逐歌分诊清单（`triage_by_song` + `audit_batch.py --triage-language`）
分诊带：illegal >35% → re-decode；>15% → repair+review；>5% → review；否则 ship-ok。

中文（`20260814_ktv_current_silence`，16 首 / 7,206 单元）：

| 歌曲 | 单元 | 非法率 | 钉锚点 | fixed 净新造 | 修复位移中位 | 分诊 |
|---|---:|---:|---:|---:|---:|---|
| 画下灯塔水母 | 532 | **38.9%** | 135 | +93 | 1.175s | **re-decode** |
| 梦良衣 | 112 | 14.3% | 0 | +6 | 0.05s | review |
| TH讠NK | 450 | 7.1% | 0 | +16 | 0.05s | review |
| 画下灯塔水母 - 副本 | 381 | 6.6% | 0 | +14 | 0.05s | review |
| 四季折之羽 | 637 | 5.7% | 1 | +19 | 0.05s | review |
| 其余 11 首 | ≤4.9% | 0 | — | 0.05s | ship-ok |

⇒ **普通话侧只需处理 1 首重解码 + 4 首复核**；其余中文歌的问题都是"零长单元需要 ≥50ms 下限"，
联合求解的中位位移恰为 0.05s（即恢复最短时长），代价极小。这也说明第 7 轮的最小_dur 约束
正好命中真实痛点。
清单：`runs/20260912_structural_compliance/mandarin_triage_list.csv.gz`（698 字节）。

新增测试：`stage_degeneracy_audit` 4 项 + 分诊 2 项（tests/evaluation 与 tests 根目录各一份），
`tests/evaluation` + artifacts 共 102 passed。

---

# 第 15 轮：raw 负时长取证 + 末字分层的真值验证

- 代码：`src/lyricalign/analysis/raw_degeneracy_forensics.py`（`load_all_stages / profile / predicts_collapse / top_examples`）
- 入口：`scripts/evaluation/{run_raw_degeneracy_forensics,run_last_unit_validation,report_raw_degeneracy}.py`
- 产物：`runs/20260912_raw_degeneracy/RAW_DEGENERACY.json`、`runs/20260912_last_unit_validation/LAST_UNIT.json`、
  `reports/progress/20260915_raw_degeneracy_and_last_unit.md`、`results/by_run/20260912_raw_degeneracy/metrics.json`
- 测试：`tests/evaluation/test_raw_degeneracy_forensics.py`（5 项）；报告另有 1 处数字口径 bug 被自己抓到并修正

## 1. raw 负时长（33 首、13,735 单元、870 个负时长）

| 语言 | 单元 | 负时长率 | 幅度中位 | 最坏 | 后来被钉锚点 |
|---|---:|---:|---:|---:|---:|
| **Chinese** | 7,206 | **1.1%** | 2.16s | −67.1s | 29.1% |
| Cantonese | 2,439 | 7.5% | 1.04s | −68.8s | 0.0% |
| English | 2,108 | 8.2% | 2.96s | −71.8s | 43.4% |
| Japanese | 1,982 | 21.9% | 5.2s | −105.5s | 33.8% |

按单元类型：japanese_word 22.6% / word 8.2% / **cjk_character 3.0%**。
- 不是量化格点抖动：70.6% 幅度 >1s（中位 2.48s、p90 65.5s），仅 2.8% 在 0.08s 格点内；
- 不是接缝现象：按窗口内位置分组负时长率 5.9% / 4.3% / 2.9% / 6.5%（平坦）。
- **否证我自己的上一版假设**：「起终点来自不同窗口」只解释 **23.1%**（201/870）⇒ 多数是同窗口内起止倒序，
  少数是跨窗口混配（最大 105.5s）。⇒ 两个子群要分开治理：①约束解码/单调化可消除；②窗口→全局组装的索引 bug 必须改代码。

## 2. raw 退化是后续塌陷的强前兆（这决定能否少花 GPU）

- 钉锚点率：raw 退化 34.9% vs raw 干净 3.5% ⇒ **lift 10.1×**；
- 到 fixed 变退化：75.8% vs 9.1% ⇒ **lift 8.3×**；
- **符号检验 25/25 首歌内部方向一致**（无跨歌混杂）；
- 反向覆盖：最终 2,236 个塌陷单元里 **50.3% 在 raw 阶段已退化**
  ⇒ **只做 raw 起止顺序自检（免费、无需真值）就能提前拦下一半塌陷**。

## 3. 末字分层的真值验证（GTSinger 人工真值，30,600 单元 / 2,016 序列）

| 系统 | 全部 | 首单元 | 中间 | 末单元 | 末单元·长音(n=708) |
|---|---:|---:|---:|---:|---:|
| raw | 82.1% | 64.1% | 84.0% | 74.8% | 55.9% |
| 现装 official | 80.4% | 64.1% | 82.0% | 74.6% | 55.9% |
| **联合求解** | **82.4%** | **66.9%** | 84.1% | 74.8% | 55.9% |

MAE(end) 全部 77.6→68.3ms、首单元 119.9→59.4ms；末单元 177.7→173.4ms。
⇒ **联合求解不伤末字**（持平），改善首字与整体；但**长音末字三系统完全同分**（55.9%、MAE 372ms）
⇒ 再次证明那一层只能靠解码信息（右上下文 / 长音 offset 训练信号），与第 11 轮声学否证一致。

## 本轮自查纠正三处
1. 序列键漏 `run`（不同 run 的同名单元混进一条序列，单调约束互相打乱）⇒ 第一版误报 joint 只有 77.5%；修正后 82.4%；
2. `raw_negative_share` 误算为负时长集合内的比例（显示 100%）⇒ 改为全单元比例并加断言；
3. 「跨窗口错配是大头」这一自我假设被数据否证（只 23.1%）。

---

# 第 16 轮：倒序→零长的静默钳位（根因落地）+ `start_after_end` gate

- 代码：`raw_degeneracy_forensics.inversion_clamp_accounting()`；
  `alignment_artifacts.stage_degeneracy_audit()` 新增 `start_after_end_units` 与
  `start_after_end_at_<stage>` 警告；`audit_batch.py` 新增 gate `start_order_integrity`（默认 2%）
- 测试：`tests/test_inversion_clamp_observability.py`（3 项，直接对生产函数 `append_strict_core_commits` 复现）

## 一、否证我自己的"槽位索引错位"假设
若真是 `raw_classes` 槽位整体错位 k=1，则 `e[i] == s[i+1]` 应接近 100%；实测各歌只有 0.31–0.68
（而负时长单元仅 6–10%），且每首歌最佳 k 都是 1 —— 那正是**相邻单元天然连续**的表现，不是错位。
⇒ 负时长是解码器**自身的起止倒序**（end 槽位类小于 start 槽位类）；另注：GPU 解码路径有
`2*len(selected)` 长度断言，raw_classes 没有（潜在加固点，但本批数据不支持它已发生）。

## 二、真正的机制链（有行号、有复现用例）
`src/lyricalign/demo/karaoke.py::append_strict_core_commits` 在重叠压缩**之前**执行
`original_end = min(max(fixed_end, original_start), duration_sec)` ⇒ end 不可能小于 start：
实测下游 selected/final 的负时长均为 **0/0**（33 首全部）。于是：

| 量 | 数值 |
|---|---:|
| raw 起止倒序 | 870（6.33%） |
| 其中最终变成零长单元 | **595（68.4%）** |
| 仍保持非零长 | 275 |
| 来自原本干净单元的新零长（钉锚点/压缩） | 1,112 |
| 解释第 13 轮 `net_added_by_fixed=+807` 的比例 | **73.7%** |

分语言：Japanese 435→315、Cantonese 183→98、English 173→127、**Chinese 79→55**。

**为什么一直静默**：钳位把 `original_duration` 变成 0，而
`overlap_compression_collapsed_to_zero` 的定义要求 `original_duration > 0`；若该行起点已在上一单元尾端之后，
连 `overlap_compressed` 都不置位 ⇒ **两个现有计数器同时漏计**（复现用例断言这两点）。
第 14 轮的 per-stage 观测 + 本轮 `start_after_end_at_*` 警告补上了这个洞。

⇒ 建议的策略决定（仍未改行为，等人裁定）：对 raw 倒序不要静默钳成零长，而是
(a) 交换/按下一单元起点重排，(b) 标 `needs_redecode`（第 15 轮：这批后来塌陷率 lift 8–10×），
(c) 至少计入 summary 的 `start_after_end_units`（已实现）。

## 三、`audit_batch.py` 现在的 gate 集合
`attributable_identity` / `structural_legality`(5%) / `stage_attribution`(1%) /
`window_anchor_pinning`(2%) / **`start_order_integrity`(2%，本轮新增)** / `repair_feasibility`。
对真实批次输出 `VERDICT=blocked`，blocking 含 `start_order_integrity: raw 6.33%, fixed/selected/final 0%`。

---

# 第 17 轮：测量有效性 —— 已报出的精度里有多少是在测钳位

- 代码：`src/lyricalign/analysis/measurement_validity.py`（`stage_shape / clamp_signature / metric_impact`）
- 入口：`scripts/evaluation/{run,report}_measurement_validity.py`；测试 5 项
- 产物：`runs/20260912_measurement_validity/MEASUREMENT_VALIDITY.json`、
  `reports/progress/20260912_measurement_validity.md`、`results/by_run/20260912_measurement_validity/metrics.json`
- 只重读既有面板，**不改指标口径**（仍 canonical `both_abs_err`），零新增前向，历史数字不重算

## 结果

| 面板 | 阶段 | 倒序率 | 零长率 | 钳位在链路 | hit@100 | 剔除退化后 | 差 |
|---|---|---:|---:|---|---:|---:|---:|
| GTSinger official | raw slots | 0.248% | 1.02% | **是** | 80.37% | 83.68% | **+3.31pp** |
| GTSinger official | shipped | 0% | 4.44% | | | | |
| GTSinger raw pipeline | shipped | 0.114% | 1.15% | 否 | 82.42% | 83.13% | +0.71pp |
| MIR-1K（6 预测器合计） | shipped | 0% | 4.05% | （面板无 raw 列） | 77.10% | 80.31% | **+3.21pp** |
| M4 长时序 | raw slots | 1.161% | 1.003% | （面板无下游列） | | | |
| 真实伴奏 33 首 | raw | 6.334% | 4.463% | **是**（交付 0% 倒序、16.28% 零长，钳位多造 1,623 个） | | | |

要点：
1. **同一处钳位确实在评测链路里**（GTSinger official 面板：raw 有倒序、交付恒无、零长 1.02%→4.44%）。
   所以本会话前几轮的绝对精度数字应读作**含退化单元的保守下界**（GTSinger −3.31pp、MIR-1K −3.21pp）。
2. **跨预测器不等量**：base（无 LoRA）退化率 20.15%，剔除后 hit@100 22.31%→27.69%（+5.38pp）；
   LoRA 各检查点只有 +0.23~+0.54pp。⇒ 用 hit@100 判"弱成员排除"（第 4/5 轮方法）时，
   被排除者同时背着退化率与边界误差两个原因；**但排除结论方向不变**（27.69% 仍 < 阈值 45.72%，
   已在 metrics.headline.ensemble_exclusion_conclusion_unchanged 机判为 true）。
3. `pipeline=raw` 的 38 个倒序单元 hit@100 = 0.0%、MAE(end) 654.6ms ⇒ 倒序单元本就是灾难单元，
   钳位只是把它们变成"没有时间长度的字"，并没有让它们变对。
4. 处置建议（不改历史数字，只加伴生列）：每个 `hit@tol` 配一列
   `hit@tol_excluding_degenerate` + `degenerate_share`；并写死解释规则
   **两系统退化率之差 >1pp 时，其 hit@100 差距不可直接归因于边界精度**。

本轮自查：一版合成 fixture 里"退化单元与 GT 同点"造成口径歧义（0.75≠1.0），重排为 5 单元、
方向明确的用例；`metric_impact` 成功分支漏 `available` 标志导致驱动少打印一段，已补。

---

# 第 18 轮：倒序处理策略决策简报 —— **没有局部策略是净赢**

- 代码：`src/lyricalign/analysis/inversion_policy.py`（5 个策略 + `evaluate_policies` + `decision_summary`
  + `structural_consequence`）
- 入口：`scripts/evaluation/{run_inversion_policy_brief,report_inversion_policy}.py`；测试 6 项
- 产物：`runs/20260912_inversion_policy/{INVERSION_POLICY,STRUCTURAL_CONSEQUENCE}.json`（<20KB）、
  `reports/progress/20260912_inversion_policy.md`、`results/by_run/20260912_inversion_policy/metrics.json`
- **shadow-only**：只在既有面板上逐单元施加策略并度量，未改生产行为、未回写

## 一、有真值处：对正确率的影响（只施加在倒序单元上）

GTSinger `pipeline=raw`（人工词级真值，33,228 单元，倒序 76 个）：

| 策略 | hit@100 | MAE(end) | 偏置(end) | 零长率 |
|---|---:|---:|---:|---:|
| P1 交换端点 | **10.5%** | 465ms | −366ms | 0% |
| P3 最小时长下限 | 10.5% | 618ms | −598ms | 0% |
| P2 取中点 | 5.3% | 545ms | −507ms | 100% |
| P0 现状（钳零） | 0.0% | 465ms | −366ms | 100% |
| P4 邻居顺延 | 0.0% | 1173ms | +393ms | 0% |

M4 长时序（弱真值，134,538 单元，倒序 1,562 个 = 1.161%）：**所有策略 hit@100 = 0.0%**，MAE 4.0–5.1s。
按 split：train 1056 / validation 248 / **test 258** ⇒ 不是能靠重训偶然消失的噪声。

## 二、无真值处：对结构合法性的影响（33 首真实歌）

| 策略 | 零长/负长 | 重叠 | 起点回退 | 超长 | **非法合计** |
|---|---:|---:|---:|---:|---:|
| P0 现状（钳零） | 16.28% | 0.10% | 0.07% | 0.37% | 16.72% |
| P1 交换端点 | 11.95% | **6.19%** | **3.28%** | 3.25% | **19.64%（更差）** |
| P3 最小时长下限 | 11.95% | 5.23% | 3.28% | 0.31% | 19.02%（更差） |
| P1 交换 + 全局联合求解 | 0.00% | 0.00% | 0.00% | 0.01% | **0.01%** |

倒序幅度中位 2.48s、p90 65.52s ⇒ **交换后的区间会吞掉邻居**：它只是把一种非法形态换成另一种。

## 三、结论与留给你的三个决定点

1. 倒序单元在两个真值面板上都是**灾难单元**（现状 hit@100 = 0%；最好的局部策略也只有 10.5%）
   ⇒ **不要用局部修补代替重解码**；
2. **放弃"交换端点"这个看起来最自然的修法**（结构净亏 +2.9pp 非法率，正确率仍≈0）；
3. 可行组合是：**倒序 → 重解码触发器**（代价 真实歌 6.33% / M4 1.161% / GTSinger 0.229% 单元）
   + **全局联合求解保结构**（非法率归零）。第 15 轮已证这批单元后来塌陷 lift 8–10×，
   所以这个触发器的性价比很高。
4. 若采用第 17 轮的伴生列口径，则跨系统比较不会再被退化率差异污染。

本轮自查：一次插入把两个测试函数留成重复定义（Python 以后者生效 ⇒ 好用例被坏用例覆盖），
已删除重复并确认 6 项各自有效；`evaluate_policies` 对过滤后的非零基索引帧会 IndexError，
已 `reset_index(drop=True)` 并加回归用例；结构后果测量原先只存在于临时脚本，
现由驱动自产 `STRUCTURAL_CONSEQUENCE.json`（一条命令可复现）。

---

# 第 19 轮：可解码上限 —— 真值边界到底在不在模型候选里

- 代码：`src/lyricalign/analysis/decodability_ceiling.py`（`containment / strata_analysis / compare_checkpoints`）
- 入口：`scripts/evaluation/{run,report}_decodability_ceiling.py`；测试 6 项（一次通过）
- 产物：`runs/20260912_decodability_ceiling{,_raw}/CEILING.json`、`reports/progress/20260912_decodability_ceiling.md`、
  `results/by_run/20260912_decodability_ceiling/metrics.json`
- 只读既有面板（top-1 概率、margin、entropy、**top-2 类别索引**）⇒ 只测 k=1/2 的确切包含，k≥3 记为未知不猜。

## 结果（GTSinger 人工词级真值，30,600 单元 / 159 片段 / 格点 0.08s）

| 层 | 单元 | 端点 top-1 恰中 | ∪top-2 恰中 | **不在 top-2** | ∪ ±1格 |
|---|---:|---:|---:|---:|---:|
| all_units | 30,600 | 64.5% | 84.3% | **15.7%** | 94.0% |
| **long_note (≥1s)** | 1,440 | 40.3% | 60.0% | **40.0%** | 79.4% |
| first_unit | 159 | 38.4% | 56.0% | **44.0%** | 78.0% |
| last_unit | 159 | 67.3% | 90.6% | 9.4% | 98.7% |
| short_note | 14,340 | 69.9% | 89.7% | 10.3% | 97.1% |

1. **长音端点有 40% 连 top-2 都不是真值格点** ⇒ 这些单元上"选择/共识/门控"在原理上不可能选对；
   这解释了第 5/6/7/12/15/18 轮反复测到的"后处理空间只有个位数 pp"。
2. **训练确实在抬这个上限**（长音端点不可达率）：**r0 70.8% → r1 27.5% → r2 21.7%**；
   top-1 恰中 12.5% → 55.0%。r1→r2 增益已变小 ⇒ 该层的预算应主要投训练侧，且尚未见底。
3. **置信度可预示可达性**（无参考触发器的基础）：AUC(top1_prob → 真值在候选 ±1 格内)
   全体端点 0.792、末单元 0.955，但**长音只有 0.616** ⇒ 恰好在最需要的层变弱，触发器会漏。
4. **旁证排除混淆**：`pipeline=raw`（不经钳位）包含率几乎一致（长音不可达 39.9% vs official 40.0%）
   ⇒ 上限来自解码器本身，不是第 16/17 轮那处钳位。
5. **GTSinger 的末单元 ≠ 真实歌的末字**：这里是片段硬切尾（可达性 90.6%），
   MIR-1K 末字是自然衰减长音（第 11 轮声学锚点不触发）⇒ 不可互相推断。

## 路线含义（按证据强度排序）
1. 训练侧（已证明能压 70.8%→21.7%，仍有余量）；
2. 换窗口重解码（给不可达单元新候选；与第 15/16 轮的免费触发器 raw 起止倒序 + 低置信度配合）；
3. 后处理只负责**结构合法性**（第 7/12/18 轮：能把非法率清零），不再期待它提升精度。

自查：AUC 第一版把标签定为"不可达"导致读数 <0.5 易被误读，已改成正向口径并写明方向；
报告生成器另修两处取数/措辞错误（"全体"误取长音 AUC、首单元表述串行）。

---

# 第 20 轮：多解码选择的空间（并集 oracle + 错误相关性）+ 一页式交付前检查清单

- 代码：`src/lyricalign/analysis/multi_view_ceiling.py`（`correctness_matrix / ceiling_by_stratum / build_long_from_wide`）
- 入口：`scripts/evaluation/{run,report}_multi_view_ceiling.py`；测试 5 项
- 产物：`runs/20260912_multi_view_ceiling/MULTI_VIEW_CEILING.json`、
  `reports/progress/20260912_multi_view_ceiling.md`、`docs/status/20260912_predelivery_checklist.md`、
  `results/by_run/20260912_multi_view_ceiling/metrics.json`
- 纪律：MIR-1K（test-only）数字只作**回溯上界**，不用于选 checkpoint/视图/阈值

## 结果（tol=100ms，both_abs_err 口径）

GTSinger 12 视图（人工真值，非 test）：

| 层 | 单元 | 生产视图 | 并集 oracle | 选择可挽回 | **无任何视图正确** | 错误相关性 |
|---|---:|---:|---:|---:|---:|---:|
| all | 2,415 | 89.19% | 91.59% | **+2.40pp** | 8.4% | 0.694 |
| long_note | 114 | 83.33% | 84.21% | +0.88pp | **15.8%** | 0.602 |
| short_note | 1,153 | 90.37% | 93.24% | +2.86pp | 6.8% | 0.746 |
| is_first | 159 | 67.30% | 69.18% | +1.89pp | **30.8%** | 0.888 |

MIR-1K 6 checkpoint（test-only，仅上界）：all 91.79% → 96.56%（**+4.77pp**，0ofk 3.4%，corr 0.543）；
long_note 84.82% → 95.54%（**+10.71pp**，corr 仅 0.414）；last_char 82.35% → 88.24%（+5.88pp，n=17）。

## 三条结论

1. **录音室中文数据上"多视图选择"这条路可以关掉**：最多再赚 +2.4pp，长音层只有 +0.88pp，
   因为 15.8% 的长音单元 12 个视图**全错**、且错误与生产视图高度相关（0.69–0.89）——
   选择需要的是去相关，而这里恰恰没有。这给第 9/10 轮"共识只赚 2.3pp / 选择器无效"提供了机制解释。
2. **真实录音上留白更大但一半要新证据**：MIR-1K 并集比生产高 4.77pp（长音 10.71pp），
   而第 9 轮实测共识只拿到 +2.3pp ⇒ oracle 与实际选择器还差约一半，
   这部分不是"更好的平均"能拿到的，需要**换窗口/重解码**产生新候选。
3. **容差口径警告**：50ms 时并集 oracle 掉到 79.8%（GTSinger）/75.2%（MIR-1K），
   且 20.2%/24.8% 的单元无任何视图可达 ⇒ **在 50ms 尺度上指标主要测解码上限，不测选择能力**；
   detector_v2 的 SAFE ≤100ms 带正好落在这条分界上，解释其指标时应引用本表。

## 交付前检查清单（docs/status/20260912_predelivery_checklist.md）
13 条，每条对应本会话一次实测并给出判据/阈值/依据轮次（身份可归因、批内因子、批间可比、口径声明、
结构合法 ≤5%、阶段归因 ≤1%、起止顺序 ≤2%、钉锚点 ≤2%、退化率伴生列、可达性标注、分诊带、
禁止从 test/OOD 选择、realign shadow-only），并列出**三条已否证路径**避免重复投入。

自查修正：`best_single_view_hit` 第一版写成 `m.any(axis=0).max()`（恒 1.0）⇒ 改为 `m.mean(axis=0).max()`；
GTSinger 的 unit_key 误用 `UNIT_KEY[:-1]`（漏 unit_index）导致塌成 item 级（假 100%）⇒ 修正后单元数 2,415。

---

# 第 21 轮：不可达真值的几何 + 偏置可否跨域（又关掉两条省算力幻想）

- 代码：`decodability_ceiling.unreachable_geometry / signed_bias / bias_by_stratum / transfer_direction_check`
- 入口：`scripts/evaluation/{run,report}_decodability_geometry.py`；测试 5 项
- 产物：`runs/20260912_decodability_ceiling/GEOMETRY.json`、`reports/progress/20260912_decodability_geometry.md`、
  `results/by_run/20260912_decodability_geometry/metrics.json`

## 结论 (a)：插值/重排不可行
不可达时**候选跨度中位数 = 0.08s（1 格）** ⇒ top-1 与 top-2 是相邻格点，真值几乎不可能落在它们之间：
全体不可达里只有 9.7% 在跨度内、**长音只有 4.0%**；长音的 **96.0% 落在跨度之外**（外移中位 0.8s）。

| 层 | 单元 | 不可达率 | 在跨度之间 | 在跨度之外 | 偏左 | 偏右 |
|---|---:|---:|---:|---:|---:|---:|
| all | 30,600 | 6.04% | 9.7% | 90.3% | 44.2% | 46.1% |
| long_note | 1,440 | 20.56% | 4.0% | **96.0%** | 10.8% | **85.1%** |
| first_unit | 2,016 | 18.45% | 11.8% | 88.2% | **78.5%** | 9.7% |
| last_unit | 2,016 | 9.92% | 0.0% | **100.0%** | 0.0% | **100.0%** |

## 结论 (b)：全局偏置修正不可跨域
端点偏置（pred − 人工真值）：

| 域 | 层 | 中位 | 偏晚比例 |
|---|---|---:|---:|
| GTSinger r2（录音室清唱） | long_note | **−40.0ms** | 0.239（截早） |
| GTSinger r2 | last_unit | −30.0ms | 0.096 |
| MIR-1K r2_full（真实伴奏） | long_note | **+32.4ms** | 0.741（拖晚） |
| MIR-1K r2_full | last_char | +20.0ms | 0.706 |

机判 `same_direction=false`、late-share 差 0.502 ⇒ **一个域上校准的整体偏移会伤害另一个域**。
这同时**回收了第 11 轮的疑问**：当时声学衰减阈值最优 θ 不可迁移（迁移后 −13.4pp），
根因不是阈值选错，而是**两个域端点误差方向本身相反**。

## 合起来的路线含义
长音尾边界不是"选错了"而是"候选里根本没有、且两域错向相反"⇒
可往前走的两件事仍是 (i) **训练信号**（已证可把长音不可达率 70.8%→21.7%）、
(ii) **产生新候选的重解码**（更长右上下文；且必须按域分别验证，不能共用修正规则）。
另注意：真实伴奏输入目前来自**声道选择**而非源分离（第 10 轮已证 GTSinger 面板的 mix/vocal 是同一文件），
"分离质量"这个变量在普通话链路上**从未被真正测试过**。

自查修正：`unreachable_geometry` 初版对 `raw_top2cls_*` 又除了一次格点步长（它本来就是格点索引），
导致候选跨度被夸大成 42–99s、且"偏右"恒为 0%；修正后跨度中位 0.08s 并与第 19 轮包含率自洽。

---

# 第 22 轮：伴奏泄漏机制检验 —— 假设成立，但机制比"伴奏更响"更精确

- 代码：`src/lyricalign/analysis/accompaniment_leak.py`（`unit_features / _paired_stats / profile_leak`）
- 入口：`scripts/evaluation/{run,report}_accompaniment_leak.py`；测试 5 项
- 产物：`runs/20260912_accompaniment_leak/{LEAK.json,per_unit_features.csv.gz}`（~150KB）、
  `reports/progress/20260912_accompaniment_leak.md`、`results/by_run/20260912_accompaniment_leak/metrics.json`
- 零 GPU（soundfile + numpy 包络，只读不复制音频）；**MIR-1K 是 test-only ⇒ 全部为回溯机制测量**，
  不用它选阈值/模型/视图

## 测量（MIR-1K r2_full，2,035 单元；引导区 = 真值结束后 0.3s）

| 层 | 单元 | 落晚比例 | 引导区伴奏占比 | 伴奏@pred vs @gt | 人声@pred vs @gt |
|---|---:|---:|---:|---|---|
| long_note | 112 | 74.1% | **91.2%** | 中位差 −0.00059，更高 36.6%，p=0.006 | 中位差 −0.0052，更高 **23.2%**，rb=−0.507，p≈0 |
| short_note（对照） | 1,246 | 48.3% | 48.8% | ≈0 差 | ≈0 差 |

| 结果分组 | 引导区伴奏占比中位 |
|---|---:|
| 落晚 >100ms（全体） | **85.8%**（p90 97.0%） |
| 落晚 >100ms（长音） | 90.3% |
| 按时（|err| ≤50ms） | 49.5% |

AUC(泄漏占比 → 落晚) 全体 **0.7818**（基准落晚率仅 3.2%）；长音层内 **0.5244**（无判别力）。
误差幅度与"预测点人声能量"负相关（全体 −0.2654、长音 **−0.4005**），与泄漏占比仅弱相关（+0.07）。

## 结论

1. **落晚的单元确实落在「人声已停、伴奏仍在」的区段**（85.8% vs 49.5%），这是定位性证据；
2. **但不是"该点伴奏更响"**（配对不显著甚至略低）——真正显著的是**人声能量更低**；
   ⇒ 解码器在跟「通道不再变化」而不是「嗓音停止」，过冲幅度取决于人声消失后通道里还剩多少可跟的东西；
3. **层内无判别力（AUC 0.52）**：长音一旦进入该层，引导区几乎总是泄漏主导（0.91）⇒ 泄漏占比能圈出错误发生的位置，但不能给错误定量；
4. **这把第 21 轮的跨域反向偏置解释成机制而非巧合**：清唱一停就静（偏早），伴奏一停还在响（偏晚）；
5. **由此产生的明确待验证杠杆**：把真实伴奏链路的输入从**声道选择**换成**源分离**（demucs 已在仓库依赖里）后重测同一层——
   这是 GPU 实验，需批准；预期观察量是长音端点偏置与 hit@100（并配第 17 轮的伴生列防污染）。
   同时提醒：GTSinger 这类清唱基准**结构上测不到这个失效**，若产品主要在伴奏真实歌曲上，录音室指标只能当 lower bound。

自查：一版 `_binom_tail` 用 `2.0**n` 在 n≈200 时溢出 ⇒ 改用 `scipy.stats.binomtest`（带正态近似兜底）并加边界测试；
合成包络 fixture 的边界帧用 `t<=2.0` 使 2.0s 仍算人声，导致占比 0.81≠0.99 ⇒ 改严格 `<`；
报告生成器再次因 f-string 内嵌 ASCII 双引号被截断 ⇒ 内层统一改用「」。

---

# 第 23–24 轮：分离链路的真相 + 字间隙局部泄漏测量（两处自我更正 + 一个方法坑）

- 代码：`src/lyricalign/analysis/separation_leakage.py`（`_envelope / measure_song / measure_batch`，
  含绝对与**相对**两套活跃判据）
- 入口：`scripts/evaluation/{run,report}_separation_leakage.py`；测试 4 项
- 产物：`runs/20260912_separation_leakage/SEPARATION_LEAKAGE.json`、
  `reports/progress/20260912_separation_leakage.md`、`results/by_run/20260912_separation_leakage/metrics.json`
- 数据：**33 首真实伴奏歌（产品批、非 test）**，无真值、无新前向；音频只读不复制

## 更正一：产品链路的输入其实是**源分离**，不是声道选择
`work/audio/vocals.identity.json`：`schema_version=qwen_fa_batch_demucs_v1`、`separator=demucs`、
`model_name=htdemucs_ft`、`two_stems=vocals`、`device=cuda`；批目录同时含 `accompaniment.wav`/`mix.wav`。
⇒ 第 22 轮"真实歌是声道选择"的说法**错误**；声道选择只发生在 **MIR-1K 评测输入**
（`20260722_mir1k_vocal_channel1_ood`）。这也意味着第 22 轮测到的"伴奏域拖晚"**不能归因于产品链路的分离器**。

## 更正二：分离质量**已有**全局质检
`work/audio/separation_quality.json`（`audio_separation_quality_v1`：RMS、mix 重构残差、
vocals↔accompaniment 相关、通过/失败门），本批 **33/33 `passed=true`**，
全局 vocals↔accompaniment 相关仅 0.04–0.12。⇒ "分离质量从未被测试"说法**错误**；
未测的是**时间局部**的泄漏，也就是本轮的测量对象。

## 方法坑（第三处自我修正）：绝对能量判据会造出假结论
"单元结束后 0.3s 是否还有能量"**没有信息量**——歌词单元天然连续，该窗通常落在**下一个字**里；
且绝对 RMS 下限会被跨边界的 25ms 分析窗骗过（合成用例里人声明明已停，绝对判据仍判"活跃"，
只有相对判据正确）。⇒ 正确口径：**只在可测量字间隙**（≥50ms，本批只有 **19.9%** 单元有）
+ **相对判据**（残余 / 该单元自身核心能量）。

## 结果：泄漏假设的强形式被反驳
| 量（跨歌中位） | 值 |
|---|---:|
| 有可测量字间隙的单元比例 | 19.9% |
| 间隙残余活跃（**相对** >25%） | 69.4%（长音 79.1%）；中文 70.6% / 长音 75.0% |
| 间隙残余 / 单元核心能量（中位） | **0.917**（长音 0.977） |
| **corr(间隙人声能量, 间隙伴奏能量)** | **0.090**（长音 0.126；naive 引导窗 0.065） |

- 残余能量**很大**（几乎等于整字能量）却**不跟随伴奏 stem** ⇒ 不是分离器泄漏的镜像；
- 剩下三种解释（无真值无法区分）：(a) 人声混响尾、(b) 下一字起始被切进间隙、
  **(c) 时间线把该字提前切断了**（残余其实是这个字自己的声音）；
  残余比例 ≈0.92 使 (b)(c) 比 (a) 更像主因；
- 若 (c) 成立，则与第 21 轮"录音室长音截早"同一偏向 ⇒ **产品在伴奏歌上可能也在截早**，
  而 MIR-1K 的声道选择输入让我们看到了相反方向（拖晚）。

## 要区分 (a)/(b)/(c) 需要什么（写成可批准的一次性实验）
对同一批伴奏中文取 3–5 首人工逐字真值，比较 `分离人声 stem 包络 / 混音 / GT 端点`：
残余在 GT 端点之后仍显著 → (c)；在 GT 端点处已消失 → (a)/(b)。
现有资产可复用：三 stem + 质检 JSON + 本模块的包络与间隙口径（CPU 部分零成本，标注或复用少量 GPU）。

## 沉淀进清单的一条纪律
`docs/status/20260912_predelivery_checklist.md` 新增：能量类判据必须**尺度无关**（相对该单元自身能量）
且**只在真间隙上算**，否则会得出"84% 边界都有残余"这类假发现。

---

# 第 25–26 轮：字间隙能不能免费检测"把字切早了"（形状假设否证，比值假设成立）

- 代码：`src/lyricalign/analysis/gap_shape.py`（`shape_features / classify / gap_rows /
  score_truncation_predictor / grouped_auc / prevalence_by_shape`）
- 入口：`scripts/evaluation/{run,report}_gap_shape.py`；测试 6 项
- 产物：`runs/20260912_gap_shape/{GAP_SHAPE.json,gtsinger_gap_features.csv.gz,real_song_gap_features.csv.gz}`
  （~60KB）、`reports/progress/20260912_gap_shape.md`、`results/by_run/20260912_gap_shape/metrics.json`
- 纪律：判别器在 **GTSinger 人工真值（非 test）** 上拟合与验证，再**冻结**应用到 33 首真实歌（只报流行率）

## 结果（保护带 GUARD_SEC=0.03 后；截早定义 gt_end − pred_end > 0.08s）

| 间隙形状 | 占比 | **截早率** | gap/core 中位 |
|---|---:|---:|---:|
| falling（下降） | 49.7% | 34.5% | 0.222 |
| **flat（持平）** | 28.1% | **61.1%** | **1.025** |
| rising（上升） | 22.2% | 32.9% | 0.206 |

- **形状假设被干净否证**：`rise_ratio` 的 AUC 只有 **0.58**（未加保护带时是 0.657，那部分是边界伪影）；
- **但"间隙残余 / 该字自身核心能量"这个比值是很强的截早预测器**：pooled AUC **0.925**；
  按片段分组 within-median **1.0**（q25–q75 0.94–1.0，聚类自助 CI [0.906, 0.963]）；
  按检查点分组 r0 **0.927** / r1 **0.841** / r2 **0.873**；
  **生产视图 r2|vocal|windowed 单独复现：233 个间隙、截早率 15.9%、AUC 0.8726**；
- 长音子集（gt_dur≥1s，580 个间隙）截早率 **65.5%**，其中 flat 组 **86.4%**；
- 绝对能量 `gap_rms` 也能到 0.86，但按检查点分组后掉到 0.70 ⇒ **必须用比值口径**（清单第 14 条）。
- 真实歌（无真值、冻结判据）：2,938 个可测间隙中 **34.2% 是 flat 且 gap/core 中位 1.014**
  ⇒ 与"产品批字间隙普遍留有接近整字能量的残余"一致，但**不能读成精度**，需那个人工标注小实验定性。

## 意义
这是本会话找到的**第一个在部署视图上复现、零成本、无需真值**的可疑边界检测器：
`gap_over_core`（= 字后真间隙里的能量 / 该字自身核心能量）。
它可以作为重解码触发器的候选特征，与第 15/16 轮的 raw 起止倒序、第 19 轮的低置信度互补。
注意仍**不建议直接上线阈值**：阈值应在非 test 数据上另行标定，且真实歌上的有效性未经验证。

## 自查修正（本轮共三处）
1. AUC 方向标注错误：第一版对 `rise_ratio`/`log_slope` 取了 `1−AUC` 却仍标作"预测截早"，
   读数 0.34 引起误判；现统一报告 **raw AUC + 方向文字**；
2. 特征定义偏差：25ms 分析窗跨过边界会把前一个字能量混进间隙头段，使"恒定残余"被测成下降
   （合成用例复现并写成回归测试）⇒ 引入 `GUARD_SEC=0.03` 保护带；修正后形状假设被干净否证、
   比值判别器反而更强（0.893→0.925 pooled，生产视图 0.82→0.873）；
3. 测试夹具采样率写错（SR=100 使 25 点窗＝250ms），导致形状分类断言失败 ⇒ 改 SR=1000 与真实窗长一致。

---

# 第 27 轮：三个免费触发器合成一个重解码 flag（GTSinger 验证 + 真实歌队列）

- 代码：`src/lyricalign/analysis/trigger_fusion.py`（`build_features / any_flag / evaluate_triggers / redecode_queue`）
- 入口：`scripts/evaluation/{run,report}_trigger_fusion.py`；测试 5 项
- 产物：`runs/20260912_trigger_fusion/{TRIGGER_FUSION.json,redecode_queue_real_songs.csv.gz}`、
  `reports/progress/20260912_trigger_fusion.md`、`results/by_run/20260912_trigger_fusion/metrics.json`
- 全部特征无需真值、无需额外前向；在 GTSinger（人工真值、非 test）验证后**冻结**应用到真实歌

## 验证结果（GTSinger 全视图 30,600 单元）

目标＝端点误差 >100ms（流行率 12.0%）：

| 触发器 | 打分单元 | AUC | r@5% | r@10% | r@20% | p@5% | p@20% | 覆盖内 r@20% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| inversion | 30,600 | 0.504 | 7.8% | 11.4% | 19.3% | 18.8% | 11.6% | 19.3% |
| low_conf_end (1−top1) | 30,600 | 0.805 | 21.7% | 38.9% | 59.8% | 52.2% | 35.9% | 59.8% |
| high_entropy_end | 30,600 | 0.845 | 20.9% | 37.9% | 64.0% | 50.3% | 38.5% | 64.0% |
| **gap_residual** | 4,588 | **0.884** | 6.1% | 12.4% | 24.0% | **98.2%** | 96.1% | **49.0%** |
| **fused_mean_rank** | 30,600 | **0.850** | 22.0% | 42.0% | **67.1%** | 52.9% | 40.3% | 67.1% |

目标＝端点被切早（9.4%）：`gap_residual` AUC **0.9205**；**长音层（最难那层）AUC 0.9407**，
而该层熵只有 0.695、融合 0.678 ⇒ 在最难的层上**间隙残余是现有最强信号**（代价是覆盖率低）。

生产视图 `r2|vocal|windowed`（2,550 单元）：high_entropy_end **0.872**、fused 0.846、
low_conf 0.839、gap_residual 0.652（仅 239 个单元有间隙特征）、inversion 0.502。

## 真实歌（33 首，13,735 单元，无真值）
flag 触发比例：inversion 6.33%、gap_residual 11.0%、high_entropy_end 20.0% ⇒ **任一 29.0%**。
重解码队列前 8：I See Fire（97.8% 被 flag）、初音 futures 的消失 93.0%、p.h 83.0%、冬之花 79.3%、
皱鳃鲨 77.8%、Camelia 68.6%、炉心融解 62.6%、电灯胆 50.0%
⇒ **中文歌无一进入前十**（第 6/12/15 轮结论第四次独立复现）。

## 分工结论（不要混用）
- `inversion` 对端点误差 AUC ≈ 0.50 —— 它预示的是**后续塌陷/退化**（第 15 轮 lift 8–10×），不是端点精度；
- 熵 / 1−top1 是**主力**（覆盖全、AUC 0.85/0.87）；
- `gap_residual` 是**高精度低覆盖**的专用件（p≈98%、覆盖内 r@20%=49%、长音层 AUC 0.94）；
- 融合（批内分位平均）在全体上略优于任何单信号（0.850 vs 0.845），但**在最难层不如 gap_residual 单独用**。

## 本轮踩到并修掉的两处口径坑（都已写进代码注释/清单）
1. **绝对熵阈值不跨域**：GTSinger 上 `entropy ≥ 1.0 nats` 看似合理，用到产品批会 flag **68.7%** 单元
   （等于没有筛选力）⇒ 改为**批内分位**（top 20%），触发比例回到设计值；
2. **召回分母必须区分全体 vs 被覆盖子集**：间隙特征只覆盖 15%（真实歌 12.7%）单元，
   只报全体召回会把这个高精度件读成弱件 ⇒ 两列并报。
另外 pandas 3 下 `groupby([单列])` 的键行为、`np.nanminimum` 不存在（用 `np.fmin`）、
以及又一次 f-string 内嵌 ASCII 引号导致语法错误，都已修正。

---

# 第 29 轮：重解码预算值多少分（按可达性给上界，供 GPU 申请用）

- 代码：`src/lyricalign/analysis/redecode_budget.py`（`reachability / bound_budget_value`）
- 入口：`scripts/evaluation/{run,report}_redecode_budget.py`；测试 4 项
- 产物：`runs/20260912_redecode_budget/REDECODE_BUDGET.json`、`reports/progress/20260912_redecode_budget.md`、
  `results/by_run/20260912_redecode_budget/metrics.json`
- 只读既有面板（GTSinger 人工真值），零前向零 GPU；**这是上界表，不是已实现效果**

## 两个上界必须分清
- **optimistic**：假设被选中单元重解码后全对（含真值不在候选内的）；
- **reachable**：只有**两边界的真值格点都落在 top-1/top-2 候选 ±1 格内**的单元才算修得动 —— 能拿去承诺的数字。

## 数字（生产视图 `r2|vocal|windowed`，基线 hit@100 88.0%，错单元 305 个）
| 复核预算 | 触发器·乐观 | **触发器·可达** | 随机·可达 | oracle（按可救排序） | 效率 |
|---|---:|---:|---:|---:|---:|
| 5% | +3.18pp | **+1.02pp** | +0.24pp | +5.02pp | 0.20 |
| 10% | +4.63pp | **+1.88pp** | +0.75pp | +7.02pp | 0.27 |
| 20% | +6.20pp | **+2.67pp** | +1.33pp | +7.02pp | 0.38 |

全视图基线 80.37%：20% 预算可达 +5.22pp（随机 +2.22pp、oracle +11.19pp）；
错单元中 **43.0% 不可救**（生产视图 41.3%）。起点可达率 95.5%、端点 94.0%。

## 最难层（长音 1,440 单元，基线 56.94%）的坏消息
错单元 620 个里 **380 个（61.3%）不可救**；20% 预算下触发器 +3.33pp **不超过随机 +3.40pp**
⇒ **在长音层把重解码预算花下去等于随机挑**；该层的正确顺序是先提升可达性（训练/新证据），再谈重解码。

## 取舍建议（写进报告 §3）
1. 若要花 GPU：**生产视图 5–10% 预算**（可达上界 +1.0~+1.9pp，且显著优于随机 +0.8~+1.1pp）；
2. 但**先修触发器排序质量**（现在只 capture oracle 的 0.20–0.38），或改用能产生**新候选**的重解码参数
   （窗口右移/更长右上下文），否则一半以上预算会浪费；
3. 长音层**不要**用同窗口重解码（61.3% 不可救），要投训练侧（第 19 轮已证 70.8%→21.7%）。

自查修正：第一版只给"按误差排序的 oracle"，在长音层出现 capture>1 的荒谬读数 ⇒
根因是**在可达上界下正确的天花板应按"错且可救"排序**，补 `oracle_by_recoverable` 策略并同时保留
`oracle_by_error`（乐观上界的天花板）；另修 `bound_budget_value` 成功分支缺 `available` 标志、
`reachability` 缺列不优雅、测试夹具里对数组用 `in`（改 `np.isin`）。
