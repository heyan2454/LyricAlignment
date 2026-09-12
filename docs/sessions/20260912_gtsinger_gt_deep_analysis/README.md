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
