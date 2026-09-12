# 2026-09-12 GTSinger 真值深度分析轮（goal 自由行动，只读挖掘）

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
