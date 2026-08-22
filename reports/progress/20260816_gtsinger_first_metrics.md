# 2026-08-16 GTSinger First Metrics（新数据集数值评测）

> 使用 GTSinger JSON word-level GT（过滤 `<AP>`）与现有 R0/R1/R2 vocal/windowed 对齐结果对比。
> 样本量小，仅为 first-light，不是最终结论。

## 结果

| Smoke | 片段 | 模型 | 单元数 | Start median | End median | Start P90 | End P90 | 100ms hit (start/end/both) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `倒带/Control_0000` | R0 | 12 | 20ms | 161ms | 80ms | 1508ms | 100% / 50% / 50% |
| 1 | `倒带/Control_0000` | R1 | 12 | 20ms | 20ms | 80ms | 73ms | 100% / 100% / 100% |
| 1 | `倒带/Control_0000` | R2 | 12 | 20ms | 20ms | 80ms | 80ms | 100% / 100% / 100% |
| 2 | `倒带/Glissando_0000` | R1 | 12 | 10ms | 33ms | 60ms | 76ms | 100% / 100% / 100% |
| 2 | `倒带/Glissando_0000` | R2 | 12 | 10ms | 28ms | 50ms | 76ms | 100% / 100% / 100% |
| 3 | `倒带/Control_0001` | R0 | 16 | 35ms | 30ms | 130ms | 130ms | 87.5% / 87.5% / 75% |
| 3 | `倒带/Control_0001` | R1 | 16 | 30ms | 25ms | 58ms | 53ms | 100% / 100% / 100% |
| 3 | `倒带/Control_0001` | R2 | 16 | 30ms | 30ms | 58ms | 58ms | 100% / 100% / 100% |

## 初步观察
- R1/R2 在 GTSinger 短中文片段上表现很好，多数 100ms 命中率 100%。
- R0 在 end 边界上明显更差（smoke1 end P90 1.5s），说明现有 LoRA/Projector 适配对中文边界有实际帮助。
- smoke3 的 R0 有 4/16 个单元超过 100ms，R2 全部进入 100ms。

## 数据与复现
- 评测脚本：`scripts/evaluation/evaluate_gtsinger_alignment.py`
- 原始 eval JSON：
  - `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke/eval_{r0,r1,r2}_vocal_windowed.json`
  - `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke2/eval_{r1,r2}_vocal_windowed.json`
  - `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke3/eval_{r0,r1,r2}_vocal_windowed.json`

## 边界
- 这是 3 个短片段、40 个字符级别的 first-light，不代表完整 GTSinger 或真实流行歌曲。
- GT 是 GTSinger JSON word-level，过滤了 `<AP>`；未与 phoneme 级 GT 对齐。
- 尚未做跨模型显著性、困难技巧分类或 sealed 评测。

## 补充：5 段 batch（77 字符）

| 模型 | both_100ms 范围 | both_200ms 范围 | 备注 |
|---|---|---|---|
| R0 | 0.625–0.857 | 0.688–0.929 | 明显偏低 |
| R1 | 0.750–1.000 | 0.875–1.000 | 多数 100% |
| R2 | 0.875–1.000 | 1.000 | 全部 200ms 内 |

详细 JSON：
- `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_batch/eval_batch_r{0,1,2}.json`

## 汇总（当前 GTSinger first-light 全部样本）

| 模型 | 单元数 | both_100ms | both_200ms | both_500ms | Start median | End median |
|---|---:|---:|---:|---:|---:|---:|
| R0 | 105 | 72.4% | 79.0% | 94.3% | 30ms | 50ms |
| R1 | 117 | 96.6% | 98.3% | 100% | 20ms | 20ms |
| R2 | 117 | 97.4% | 100% | 100% | 20ms | 20.5ms |

> 样本包含 8 个短中文片段（3 个早期 smoke + 5 个 batch），非完整评测。

## 全量 GTSinger diagnostic（75 段，1226 字符）

| 模型 | both_100ms | both_200ms | both_500ms |
|---|---:|---:|---:|
| R0 | 74.8% | 81.4% | 95.6% |
| R1 | 87.6% | 92.8% | 97.7% |
| R2 | 90.1% | 95.5% | 98.1% |

详细数据：
- `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all/eval_batch_r{0,1,2}.json`
- `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all/aggregate_summary.json`

## Quality warning 观察（75 段）

- R0/R1/R2 都有约 30–34/75 段出现 `final_zero_duration` warning
- R2 的 `raw_inter_unit_overlap` 最多（38/75），但多数 final 后处理可修复
- 产品化必须把 zero-duration 后处理作为显式质量 gate，不能只看 100ms 命中率

详细：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all/quality_warnings_summary.json`

## R2 失败模式初探

- 18/75 段 both_100ms < 0.85，主要集中在 `Paired_Speech_Group`（朗读/说话）和少数 `Glissando_Group`
- 最差 `Paired_Speech_Group_0006` both_100ms=64.7%
- 说明产品化应对 speech-like input 与 singing input 分层报告/设不同 gate
