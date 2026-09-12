# 长时序弱真值面板（detector_v2 M4Singer-concat 证据，2026-09-12 第 3 轮）

> 数字由 `runs/20260912_m4_longform_weakgt/{PANEL_SUMMARY,ANALYSIS}.json` 生成。
> 纯 CPU 复用既有产物；零新增前向；不动任何实现。

## 0. 参考真值的性质（先说清楚，免得被误用）

- 类型：M4Singer per-segment character GT offset into the concatenated timeline (labeler: scripts/research_v7/label_detector_v2_run.py build_song_gt)；分档 {'safe_max': 0.1, 'unsafe_min': 0.25}（safe ≤100ms、unsafe ≥250ms）。
- **弱监督**：M4Singer 逐段字符 GT 平移到拼接时间轴，`rule_validated` 不等于人工确认。
- **长度是合成的**：`m4singer_concat`，段间插入 `artificial_silence_sec=[0.5]` 静音；timeline 时长 198.3–249.6 s。按现行 research_v7 正式口径这不属于"自然长数据"，本面板只能用于机制/方向判断。
- 面板规模：134,538 单元行 / 1,440 证据身份 / 30 首 / 11 位歌手；baseline（未扰动文本）且有真实 GT 的单元 13,454（180 个请求）。
- 视图分布 {'full': 125868, 'sparse': 2899, 'overlap': 5771}；family 分布 {'crop_early': 11348, 'crop_late': 28855, 'end_late': 23084, 'repeated_section': 5771, 'end_early': 28855, 'baseline_legal': 14441, 'cursor_shift': 22184}。

## 1. 方法陷阱（P1，必须先记账）：`timeline.canonical_units` 的时间轴是**伪造均匀轴**

- 把预测边界直接减 `canonical_units[*].start_sec` 得到的"误差"，与本项目冻结标签（真实逐段 GT 平移）算出的误差：一致到 20ms 以内的只有 2.2%，中位分歧 346.0ms，p90 1062.0ms，两种"误差"的相关只有 0.6098。
- 后果量化：同一批 13,454 单元上，错用均匀轴会得到 hit@100 = **5.3%**，用真实 GT 是 **87.9%**（相差 83 个百分点）。
- re-analysis that reads timeline.canonical_units[*].start_sec as ground truth measures a fabricated uniform axis; only the frozen label_* columns (built from per-segment M4Singer GT) are usable。
- 本轮我自己的第一次装配就踩中了它（得到的 baseline 命中率 5.9% 全是假的），是靠"与冻结标签误差对账"这道自检才发现的。**建议把这条对账固化为面板构建的硬门**。

## 2. 长时序 baseline 真实水平（合成拼接轴）

- hit@100：raw 阶段 87.95%、official 阶段 88.00%；unsafe(≥250ms) 2.41% → 2.39%。
- MAE(both)：raw 83.2ms / official 78.9ms；中位 50.0ms。
- 结论：在 200s 级合成长轴上，字符级对齐质量与 GTSinger 短片同量级（≈88% @100ms），**没有观察到长距离整体退化**。

## 3. 后处理在长时序上的表现 ≠ GTSinger 上的表现（关键差异）

- research_v7 的 official 阶段只改动了 1.2% 的单元（GTSinger demo 管线是 5.4%）。
- 被改动的 161 个单元：MAE 由 779.9ms 降到 426.1ms；hit@100 由 60.25% 升到 63.98%；repair 37.27% vs damage 31.06%。
- **机制不同**：被移动的起点中只有 0.6% 等于前一单元尾端（GTSinger demo 管线是 98.3%），平均位移 268.6ms。⇒ 第 2 轮定位到的"重叠消解=把起点钉到前一个尾端"是 **demo 官方管线特有**的行为，不是所有后处理阶段的通性；改造结论不能跨管线套用。
- 净效应在长时序上≈中性：单元级 Δhit@100 +0.045pp；请求级配对 -0.041pp CI [-0.121, 0.037]（13 升 / 20 降 / 147 平）。
- 另：raw 与 official 在本面板零时长率均为 0.0（该阶段不产生零时长单元）。

## 4. 段首效应在长时序上**不存在**（对第 1 轮结论的重要限定）

- 段首单元 hit@100 87.78% vs 其余 87.97%；unsafe 率 2.90% vs 2.35%（n=1449 / 12005，603 段）。
- 按段内位置分桶（官方阶段）：

| 段内位置 | n | raw hit@100 | official hit@100 | raw unsafe≥250ms |
|---|---:|---:|---:|---:|
| 1st unit | 1,449 | 87.8% | 87.8% | 2.9% |
| 2nd | 1,407 | 86.9% | 87.1% | 2.6% |
| 3rd-4th | 2,709 | 87.7% | 87.8% | 2.0% |
| 5th-8th | 4,297 | 88.2% | 88.1% | 2.5% |
| >8th | 3,592 | 88.3% | 88.4% | 2.3% |

- **综合解释**：GTSinger 的"段首幻觉前奏"发生在 **音频被硬切在起唱点** 的情形（clip 的 GT start 恒为 0）；本面板每个拼接缝前都插了 0.5s 真静音，起唱点不在边界上，于是段首毫无惩罚。⇒ 该失效的触发条件是"窗口左端无真实前奏"，不是"处于边界"本身；长歌分窗时若窗口左端切在演唱中间，风险与 GTSinger 同类，需要专项验证（本轮无法验证，因为这里没有 GT 可用的自然长歌）。

## 5. 无真值信号的跨面板迁移（第 1 轮结论在 200s 轴上更强）

单信号 AUC（预测 official 阶段误差 > 阈值；方向已归一为"越大越差"）：

| 信号 | bad>100ms | bad>200ms | bad>250ms |
|---|---:|---:|---:|
| `max_ent` | 0.7786 | 0.9098 | 0.9276 |
| `ent_mean` | 0.7746 | 0.9019 | 0.9206 |
| `end_entropy` | 0.74 | 0.8813 | 0.9148 |
| `min_ent` | 0.7042 | 0.8092 | 0.8399 |
| `start_entropy` | 0.6854 | 0.7746 | 0.8023 |
| `repair_start_shift_sec` | 0.5064 | 0.5392 | 0.5649 |
| `repair_end_shift_sec` | 0.5048 | 0.522 | 0.543 |
| `start_margin` | 0.6381 | 0.6785 | 0.6948 |
| `min_margin` | 0.7093 | 0.7664 | 0.7664 |
| `end_margin` | 0.6919 | 0.7699 | 0.7793 |

- **熵类信号随阈值变宽而更强**：最强的 `max_ent` 从 0.7786（100ms）升到 0.9276（250ms）；margin 类同向但整体弱一档（bad250 约 0.2336，即方向为"margin 越大越好"）。
- 门控（特征=熵/margin/repair 位移，按请求分组 5 折 OOF）目标 ≥250ms unsafe（与项目 unsafe 档同义）：n=13,454，阳性率 0.0237，**AUC 0.924**，AP 0.4052；复核预算曲线 flag5% 精度 0.2883/召回 0.6082，flag20% 精度 0.1052/召回 0.8871。
- 门控（特征=熵/margin/repair 位移，按请求分组 5 折 OOF）目标 >100ms：n=13,454，阳性率 0.12，**AUC 0.7653**，AP 0.371；复核预算曲线 flag5% 精度 0.5007/召回 0.2087，flag20% 精度 0.3122/召回 0.5201。
- 与第 1 轮对照：GTSinger 人音真值上 posterior-only 门控 bad100 AUC 0.862；本弱真值长轴面板 bad100 只有 0.7653，但 bad250 高达 0.924。**结论：熵信号擅长抓" gross 错位"（≥250ms），对 100ms 级的精细边界判别力有限**——这直接决定了它该被用在哪里：适合当 realign 触发器（抓大错），不适合当微调验收器。

## 6. 冻结标签侧的交叉核对

- 项目自己的 raw 档标签：unsafe 占 2.4%，其平均绝对误差 1298ms，safe 档平均 44ms；标签与 ≥250ms 精确重合（precision/recall/AUC 均 1.0）——这是定义使然，；grey(100–250ms) 占 9.7%。⇒ 现有三档标签在灰区只给了一个笼统档位，没有排序信息；而熵信号在同一目标上给出 AUC≈0.92 的连续分数，可作为分档之上的细粒度补充。

## 7. 下一步（本轮暴露出来的、代价最低的高价值动作）

1. **面板构建硬门**：任何复用 detector_v2/长时序证据的分析，必须先做"重算误差 vs 冻结标签误差"对账（本轮已实现为 `uniform_axis_trap`），不一致率 >5% 直接判定 join 失败并停下——否则会把 5.9% 当成模型性能写进结论。
2. **自然长歌真值仍缺**：本轮的"长"是拼接+插静音；`data/datasets_registry.md` 里 MIR-1K 是行级人工 GT（≤60s 段）、OpenCpop 受授权阻塞。要做真正的窗口/接缝验证，需要先造一个带人工 GT 的自然长歌面板（GTSinger 全曲 pilot 已在 2026-08-21 记录为可行但未执行）。
3. **门控定位调整**：把熵基 no-GT 触发器按"≥250ms gross error"目标来用（AUC≈0.92），并把 100ms 精修另立信号（需要比 entropy 更结构化的特征，例如跨候选/跨视图一致性）。

## 8. 复现

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
cd /home/hyan/LyricAlignment
PYTHONPATH=src python scripts/evaluation/build_m4_longform_weakgt_panel.py
PYTHONPATH=src python scripts/evaluation/report_m4_longform_weakgt.py
PYTHONPATH=src python -m pytest -q tests/evaluation/test_m4_longform_weakgt.py
```

- 面板：`/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt/longform_units.jsonl.gz`（8.5 MB，134,538 行）；
- 分析：`ANALYSIS.json`；抽取/装配自检：`PANEL_SUMMARY.json`。
- run1 被排除并登记原因：[{"run": "run1", "excluded": "reference_timeline_missing", "expected_timeline_manifest": "/home/hyan/Data/lyricalign/runs/research_v7_align_behavior/smoke_20260805_review12/formal_manifest_v3/LONG_TIMELINE_MANIFEST.jsonl"}]

