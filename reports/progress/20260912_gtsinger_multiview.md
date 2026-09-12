# GTSinger 多视图选择实验（人工真值，2026-09-12 第 10 轮）

> 数字由 `runs/20260912_gtsinger_multiview/MULTIVIEW.json` 生成。纯 CPU、零新增前向。
> 参考是 GTSinger **人工逐字/逐词标注**（比第 9 轮的弱标签硬）。

## 0. 结论：这里没有可用的多视图，且任何选择器都不如现装配置

- 名义上每个单元有 **12 个视图**（3 checkpoint × mix/vocal × full/windowed），但按因子分解后：**同一 checkpoint 内的 4 个单元格几乎完全相同**（start 边界差中位 0.0s、audio_input 与 mode 同样为 0.0s）⇒ 第 1 轮的『3×2×2 矩阵退化』结论现在有了定量版本：**GTSinger 无法提供真正的输入多样性视图**。
- 唯一有效的差异轴是 **checkpoint**（r0/r1/r2 相差最多 20.5pp hit@100），而 r2 恰好是最好的一档 ⇒ 所谓『12 视图的 oracle 上界』只有 **+2.97pp**（因为差距基本来自 r0/r1 在个别单元上偶然更好，而不是视图信息更多）。
- **所有无真值选择器都是负的**：共识 87.29%（-0.75pp）、最近共识 -0.67pp、熵最低 -2.28pp、支持度最高 -2.78pp；现装视图 r2|vocal|windowed = 88.04% 已经是最优单视图。
- 原因很直白：把 r0（67.5%）和 mix/vocal、full/windowed 这些**同质但更差**的输出混进共识，只会把 r2 的正确答案稀释掉。

## 1. 视图质量表（official 阶段）

| 视图 (model\|audio\|mode) | hit@100 | hit@250 | MAE |
|---|---:|---:|---:|
| `r2|mix|full` | 88.04% | 95.18% | 67.9ms |
| `r2|mix|windowed` | 88.04% | 95.18% | 67.8ms |
| `r2|vocal|full` | 88.04% | 95.18% | 67.9ms |
| `r2|vocal|windowed` ← 现装 | 88.04% | 95.18% | 67.8ms |
| `r1|mix|full` | 85.53% | 94.04% | 75.6ms |
| `r1|mix|windowed` | 85.53% | 94.04% | 75.5ms |
| `r1|vocal|full` | 85.53% | 94.04% | 75.6ms |
| `r1|vocal|windowed` | 85.53% | 94.04% | 75.5ms |
| `r0|mix|full` | 67.53% | 78.00% | 176.2ms |
| `r0|mix|windowed` | 67.53% | 78.00% | 176.2ms |
| `r0|vocal|full` | 67.53% | 78.00% | 176.2ms |
| `r0|vocal|windowed` | 67.53% | 78.00% | 176.2ms |

## 2. 因子退化诊断（这就是『多视图』不成立的原因）

| 因子 | 层级（比较次数） | start 边界差中位 | start >100ms 比例 | end >100ms 比例 |
|---|---|---:|---:|---:|
| `model` | r0, r1, r2 （9,660 组固定其他因子的比较）| 0.0s | 8.4% | 21.5% |
| `audio_input` | mix, vocal （14,490 组固定其他因子的比较）| 0.0s | 0.0% | 0.0% |
| `mode` | full, windowed （14,490 组固定其他因子的比较）| 0.0s | 0.0% | 0.0% |

- 跨视图整体分歧：中位 0.08s、p90 0.4s、>100ms 占 27.1%——但这些分歧几乎全部发生在 checkpoint 之间，而不是视图之间。

## 2b. 内容审计：那些因子到底有没有换过输入

`request_hash` 不同 ≠ 输入内容不同（路径也是身份的一部分）。按「其他因子固定」逐组比较
`audio_sha256`：

| 因子 | 期望 | 相同音频 sha 的比例 | 判定 |
|---|---|---:|---|
| `model` | 同文件换 checkpoint | 100.0% | same file by design (checkpoint axis); differs in output => informative |
| `audio_input` | 应换音频字节 | 100.0% | DEAD CONFIGURATION: mix and vocal cells were fed the *same bytes* (identical audio_sha256) => this ablation never happened |
| `mode` | 同文件换计划 | 100.0% | same file by design; uninformative on clips shorter than one window (outputs identical, see factor_decomposition) |

- **发现历史实验缺陷（P1）**：954 组 mix/vocal 配对的 `audio_sha256` **100.0% 相同** ⇒ 那次「混音 vs 人声」消融**从未真的换过输入**，只有 request_hash 因路径不同而变了；所有基于 evaluation_v1 该因子的结论都作废（第 1 轮已标记矩阵退化，本轮给出根因）。
- `mode` 不是 bug：短片（5–15s）本来就短于一个 60s 窗口，分窗与整曲必然同结果⇒ 该因子**在此数据上无信息**，要检验必须用长音频（第 9 轮的长时序面板正是这种数据）。
- 这也解释了为什么「12 视图」的跨视图分歧只来自 checkpoint：输入侧根本没有变化。
- **流程教训（第 2 轮就提过、这轮再次命中）**：批次收尾必须跑**配置矩阵同一性门**——凡两单元格内容哈希相同而标签不同，就直接判 `not_identified` 并拒绝出对比结论。本模块的 `factor_content_audit()` 就是该门的最小实现，可挂到任意批次上。

## 3. 与第 5/9 轮合并后的规律（本轮真正的产出）

| 证据 | 视图差异来源 | 基线 | 共识/选择效果 |
|---|---|---|---|
| 第 5 轮（MIR-1K 自然录音） | 同一裁窗换 checkpoint | 现装单视图 | +0.34pp（oracle +4.57pp，吃 7.4%） |
| 第 9 轮（M4 长时序） | **不同裁窗**（同 checkpoint） | 任意一个覆盖窗口 | **+2.14pp**（免费） |
| 本轮（GTSinger，人工真值） | 混合：换 checkpoint + 退化因子 | **已选好的最优视图** | -0.75pp（共识反而更差） |

⇒ **三条一起给出的可执行规则**：
1. 只有当视图在**输入层面真的不同**（不同裁窗/不同音频条件）时，多视图才有信息量——同一裁窗换模型几乎无收益（第 5 轮），同一模型换退化因子是零收益（本轮）。
2. 参与共识的视图**质量必须齐平**：把明显更差的视图（r0、或未适配的上游系统）混进来是净损害（本轮 −0.75pp；第 5 轮把上游 base 混进集合时 AUC 从 0.839 掉到 0.789）。⇒ 任何 multi-view 设计都需要**成员能力门**，且门的依据不能是用真值挑出来的。
3. 选择器的价值取决于『基线是否已经是最优视图』：当基线是随机/任意视图时长序共识赚 2.14pp，当基线已是最好视图时任何选择都亏 ⇒ **先确认基线是什么，再谈融合**。
- 另一个一致的细分结论：熵作为**触发器**有效（第 1/3/5/9 轮 AUC 0.78–0.88），作为**视图选择器**无效（本轮 -2.28pp）⇒ 它回答『这个单元可不可信』，不回答『哪个视图对这个单元更好』。

## 4. 边界

- 人工真值只覆盖 GTSinger mini（2,415 单元 / 录音室短片段），而它恰恰是**唯一没有真实视图多样性**的数据源；因此本轮结论是『该数据不能用来证明多视图有效』，而不是『多视图在所有数据上无效』。
- raw 阶段同向：现装视图 89.74%，共识 89.28%（−0.46pp），oracle 差距 +2.93pp。
- 未做任何 GPU 实验；若要真正验证多视图收益，需要**同一最好 checkpoint + 多个不同裁窗**的前向，这在长时序上已有留存证据（第 9 轮），在短片段上需要新数据。

## 5. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/run_gtsinger_multiview.py
PYTHONPATH=src python scripts/evaluation/report_gtsinger_multiview.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_gtsinger_multiview.py
```

