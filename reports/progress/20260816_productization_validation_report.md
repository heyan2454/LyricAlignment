# 2026-08-16 Lyric Align 产品化验证报告

## 范围
使用新获取数据集，在**不训练新模型**的前提下，验证当前 Lyric Align 推理机制是否可产品化，并识别主要质量 gate。

## 数据集覆盖状态
| 数据集 | 状态 | 结果 |
|---|---|---|
| GTSinger Chinese mini | 已完成 75 段 diagnostic 全量 R0/R1/R2 | R2 both_100ms=90.1%, both_200ms=95.5% |
| MIR-MLPop raw mixture | 30s smoke 完成 | 全部 warning，确认必须先做 vocal 派生 |
| PJS Japanese | pjs001 smoke 完成 | 日语路径可运行，但需 phoneme GT 正式评测 |
| JamendoLyrics en | 尚未运行 | 等待 vocal 派生 |

## 已建立的基础设施
- Evaluation V1 grouped split（diagnostic/regression/sealed）
- dataset readiness audit
- baseline identity freeze
- vocal derivation plan
- behavior registry
- GTSinger diagnostic manifest + batch runner + evaluator

## GTSinger 全量 diagnostic 验证（已完成）
- 75 段，1226 非 AP 字符
- 指标：both boundary 100/200/500ms 命中率（vocal/windowed）

| 模型 | both_100ms | both_200ms | both_500ms |
|---|---:|---:|---:|
| R0 | 74.8% | 81.4% | 95.6% |
| R1 | 87.6% | 92.8% | 97.7% |
| R2 | 90.1% | 95.5% | 98.1% |

Canonical: `results/comparisons/20260816_gtsinger_diagnostic_summary.json`

## 主要发现
1. R2 是当前中文 GTSinger diagnostic 上最值得产品化的模型配置。
2. R0 在 end boundary 上明显弱，R1/R2 的适配收益可复现。
3. 约 30–34/75 段存在 `final_zero_duration` warning；R2 的 raw inter-unit overlap 最多（38/75），但多数 final 可修复。
4. R2 低分段集中在 `Paired_Speech_Group`（朗读/说话）和少数 `Glissando`，产品化应对 speech-like input 设置不同 gate/阈值。

## 当前产品化建议
- 默认配置：R2 + vocal/windowed + 现有后处理。
- 必须增加 zero-duration / overlap / timestamp regression 的显式质量 gate。
- 对 speech-like input 单独报告，不混入 singing 总分。
- 在 regression_selection 上做单因素消融，确认各机制贡献后再进入 sealed。

## 尚未完成
- MIR-MLPop / JamendoLyrics vocal-only 派生后自然混音验证
- PJS 日语 phoneme/boundary 评测
- behavior registry 单因素消融执行
- sealed milestone runner 与访问控制端到端验证

## 数据管理
所有详细产物均在 `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_*`，每批含 `cleanup_report.md`。
仓库只保存轻量脚本、manifest 摘要、canonical result 和报告。

## MIR-MLPop raw mixture smoke（补充）
- 30s raw mixture 直接跑 R0/R1/R2：能完成推理，但全部 `warning`（zero-duration/overlap/regression）
- 结论：不能把 raw mixture 当作 operational input，vocal-only 派生是必须前置步骤
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_mir_smoke/`

## Hard-case 子清单
- 已生成 `gtsinger_hard_cases.jsonl`（18 个 R2 both_100ms < 0.85）
- 后续机制消融可直接消费该子清单，避免在全量上盲目搜索

## PJS 日语准备
- 已生成 `pjs_manifest.jsonl`（100 个 song ID，含 phoneme count、song/speech duration、tier）
- 路径：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/pjs_manifest.jsonl`
- 后续日语 phoneme/boundary 评测可直接消费该 manifest

## PJS 日语 smoke（补充）
- 从 PJS MusicXML 提取日文歌词，跑通 pjs001 的 R0/R1/R2
- 12/12 alignment 完成，但全部 `warning`（zero-duration/overlap）
- 说明日语路径可运行，但需要 phoneme-level GT 做正式评测
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_pjs_smoke/`

## Sealed runner 访问控制
- 新增 `scripts/evaluation/guarded_run.py`
- 默认拒绝 `sealed_final`，仅显式 `--allow-sealed` 可放行
- 可用于正式评测命令包装，防止误读 sealed

## PJS 日语 batch（补充）
- 5 段 pjs001-pjs005，113 个日语 word units
- R2：2 passed / 3 warning；R1：1/4；R0：2/3
- warning 主要为 raw overlap 和小量 final zero-duration
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_pjs_batch/`

## GTSinger hard-case 机制消融（首个）
- 机制：`--compress-silence-audio`
- 样本：3 个 hard cases（Control_0009, Glissando_0010, Glissando_0011）
- 结果：与 baseline 的 R2 both_100ms/200ms 完全一致，无变化
- 说明：⚠️ 口径限定——样本为 7–9s 单窗口短片段，机制未被实际激活（compress 前后时长相同），
  本结果属 inconclusive（未检验），**不能视为机制无效**；长歌场景需 ≥60s 多窗口样本再验
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_ablation_compress/`

## GTSinger hard-case 机制消融（strict-silence-boundary-plan）
- 机制：`--strict-silence-boundary-plan`
- 样本：同一批 3 个 hard cases
- 结果：与 baseline 完全一致，无变化
- 说明：⚠️ 口径限定——样本为 7–9s 单窗口短片段，无窗口边界可保护，
  本结果属 inconclusive（未检验），**不能视为机制无效**；长歌场景需 ≥60s 多窗口样本再验
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_ablation_strict/`

## 质量检查脚本
- 新增 `scripts/evaluation/run_quality_checks.sh`
- 一键执行：pytest、compileall、git diff --check、cleanup-report audit
- 当前所有 evaluation_v1 batch 均有 `cleanup_report.md`

## GTSinger hard-case 机制消融（skip-silent-windows）
- 机制：`--skip-silent-windows`
- 样本：同一批 3 个 hard cases
- 结果：与 baseline 完全一致，无变化
- 说明：⚠️ 口径限定——样本为 7–9s 单窗口短片段，无窗口可跳过，
  本结果属 inconclusive（未检验），**不能视为机制无效**；长歌场景需 ≥60s 多窗口样本再验
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_ablation_skip/`
- 综合三个消融：compress/strict/skip 均未改变这些短 hard case 指标（三项均为单窗口短片段上的
  inconclusive 结果，非"机制无效"证据），下一步应转向 recovery 类机制

## GTSinger hard-case 机制消融（decoder-kind=raw）
- 机制：`--decoder-kind raw`（对比默认 official）
- 样本：同一批 3 个 hard cases
- 结果：Glissando_0011 的 both_100ms 从 0.750 提升到 0.833，其他不变
- 这是目前唯一出现正向变化的消融，值得在更大 hard-case 集合上验证
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_ablation_rawdec/`

## GTSinger hard-case 消融：raw decoder 全 18 段
- 机制：`--decoder-kind raw`
- 样本：全部 18 个 hard cases，309 字符
- 结果：
  - both_100ms：78.32% -> 84.47%（+6.15pp）
  - both_200ms：90.29% -> 91.59%（+1.30pp）
  - 14 个提升，0 个回退，4 个持平
- 这是当前最有希望的产品化机制候选，下一步应在全量 diagnostic 上验证
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_ablation_rawdec_all/`

## GTSinger 全量 raw decoder 验证
- 机制：`--decoder-kind raw`
- 样本：全部 75 段 diagnostic，1226 字符
- 结果：
  - both_100ms：90.05% -> 91.84%（+1.79pp）
  - both_200ms：95.51% -> 96.00%（+0.49pp）
  - both_500ms：98.12% -> 98.21%（+0.09pp）
  - 20 个提升，2 个回退，53 个持平
- 结论：raw decoder 是全量级别有统计方向收益的产品化候选，建议进入 regression_selection 进一步验证
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_rawdec_all/`

## Raw decoder 回退段分析
- 2/75 回退均为轻微边界偏移（≤0.22s），非灾难性
- Control_0006：2 字刚过 100ms
- Glissando_0014：1 字 start error 0.219s
- 建议：考虑 hybrid/按片段选择 decoder，或对 raw decoder 增加局部精修

## PJS raw decoder 5 段对比
- raw decoder 减少 final zero-duration（R0 3->0, R1 4->1, R2 3->2）
- 但增加 selected overlap / cross-window compression warning
- 整体 passed/warning 分布不变
- 需要 phoneme-level GT 才能判断日语收益
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_pjs_rawdec_batch/`

## GTSinger regression_selection raw decoder smoke
- 首次在 regression_selection 上跑 raw decoder（5 段，94 字符）
- both_100ms ≈ 93.6%，both_200ms ≈ 95.7%
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_regression_rawdec_smoke/`
- 全量 regression_selection 尚未运行

## GTSinger regression_selection 全量 raw decoder
- 84/84 段完成，1189 字符
- R2 raw decoder：
  - both_100ms=89.49%
  - both_200ms=93.86%
  - both_500ms=98.32%
- 低分段（<80% @100ms）：11 段，多为 Paired_Speech / Pharyngeal / Falsetto
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_regression_rawdec_all/`

## GTSinger regression_selection official vs raw decoder（同集合对比）
- 84/84 段，1189 字符
- official：both_100ms=87.47%, both_200ms=92.77%, both_500ms=98.40%
- raw decoder：both_100ms=89.49%, both_200ms=93.86%, both_500ms=98.32%
- 方向：22 提升 / 1 回退 / 61 持平
- 结论：raw decoder 在 regression_selection 上同样优于 official，产品化候选进一步强化

## Regression quality warning 对比（official vs raw decoder）
- raw decoder 大幅减少 final zero-duration：
  - R2：44 -> 9
  - R0/R1 同样显著减少
- 但 raw decoder 新增 selected_inter_unit_overlap / cross_window_overlap_compression
- 整体 passed/warning 分布不变
- 结论：raw decoder 在减少零时长上有明显收益，但需处理 overlap gate

## MIR vocal 分离 smoke
- 使用 Spleeter 2stems 成功分离 MIR 30s crop 的 vocals
- 用分离 vocals 跑 R0/R1/R2：全部完成但仍为 warning
- 说明 vocal 派生可执行，但不自动解决短片段对齐 warning；需更多歌曲评测
- 产物：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_mir_smoke/vocal_run/`

## Raw decoder Quality Gate 汇总（GTSinger diagnostic 75 段）
- 严格 gate：任何 overlap 即失败
- 33/75 pass，42/75 fail
- 失败原因：overlap 38、zero-duration 10、regression 1
- 说明 raw decoder 虽提升指标，但产品化 gate 必须处理 overlap

## Regression Quality Gate 对比
- official：53 pass / 31 fail，全部因 zero-duration
- raw decoder：45 pass / 39 fail，主要因 overlap（34），zero-duration 仅 8
- 结论：official 与 raw decoder 的失败模式互补，产品化 gate 应考虑 hybrid 选择或两阶段后处理

## Hybrid Gate 分析（重要）
- raw decoder 的指标提升主要集中在 raw gate 失败子集：
  - raw gate fail 子集（39 items, 612 units）：official 82.52% vs raw 86.44%
  - raw gate pass 子集（45 items, 577 units）：两者均为 92.72%
- 因此“只在使用 raw 且 gate 通过时选 raw”不会带来收益
- 产品化应选择：raw + overlap 修复，或设计不同于最终 overlap gate 的选择信号
