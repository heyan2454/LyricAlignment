# LyricAlignment

面向普通话歌声的已知歌词强制对齐研究项目。仓库根目录固定为
`LyricAlignment/`；日期后缀只用于 archive、run 和报告。

## 当前状态（2026-07-24）

Qwen Forced Aligner 首轮 LoRA 实验链已经完成并归档：

- R0 raw；
- matched-budget R1 projector-only；
- R2 projector + top-half audio-attention LoRA；
- M4Singer validation-only checkpoint selection；
- M4Singer sealed test；
- MIR-1K vocal-only OOD；
- approximately 22/33/48/152-second diagnostics；
- second full R2 seed；
- missing-evaluation recovery；
- metric and identity repair。

Primary song-macro penalized boundary MAE:

| Model | M4Singer test | MIR-1K OOD |
|---|---:|---:|
| R0 raw | 251.391 ms | 97.108 ms |
| R1 projector-only | 90.775 ms | 44.007 ms |
| R2 seed3407 | 79.590 ms | 42.557 ms |
| R2 seed20260724 | 80.920 ms | 40.459 ms |

当前不应立即扩展 LoRA；下一步是定位 approximately 150-second 序列中的
局部对齐崩溃。

## 必读入口

1. `AI_SESSION_ENTRY.md`
2. `docs/status/project_current.md`
3. `docs/sessions/20260724_qwen_fa_followup_repair_archive.md`
4. `reports/review/20260724_qwen_fa_followup_repair_review.md`
5. `reports/audits/20260724_qwen_fa_long_b180_outlier_audit.md`
6. `docs/status/next_execution_plan.md`

## 指标口径

Canonical schema:

```text
character_interval_metrics_v3_tolerant
```

关键规则：

- valid / invalid / missing 互斥；
- 主指标为带缺失惩罚的 per-song macro boundary MAE；
- valid-only 使用完全相同的有效集合计算分子与分母；
- `character_coverage` 为有效字符比例；
- `song_coverage` 为至少有一个有效字符的歌曲比例；
- `complete_song_coverage` 为整首全部字符有效的歌曲比例。

原始 v2 指标不覆盖；修正版位于：

```text
results/recomputed/20260724_character_metrics_v3/
```

## Canonical result files

```text
results/comparisons/20260724_qwen_fa_followup_final_summary.json
reports/progress/20260724_qwen_fa_overnight_overall_summary.md
reports/audits/20260724_qwen_fa_long_b180_outlier_audit.md
```

旧的 provisional summary 保留作为历史证据，不作为当前正式结果表。

## 强约束

- checkpoint 只允许使用 validation 选择；
- 不根据 test/OOD 修改 checkpoint；
- 不静默覆盖原始 aggregate JSON；
- metric 修正必须从逐字符 reference/prediction 重算；
- `rule_validated` 是 weak supervision，不等同于人工 GT；
- synthetic approximately 152.5-second set 不是自然三分钟 benchmark；
- checkpoint、模型缓存、音频和大型 prediction 文件不进入 Git/archive。

## 顶层目录

| 路径 | 作用 |
|---|---|
| `configs/` | 模型、训练、数据和 metric 配置 |
| `data/` | 轻量 schema、registry 和 manifest 模板 |
| `src/lyricalign/` | 核心实现 |
| `scripts/` | 可复现入口 |
| `runs/` | 轻量执行证据与外部产物索引 |
| `results/` | 原始、修正和比较结果 |
| `reports/` | 审计、进展和研究报告 |
| `docs/` | 原则、状态、manual 和 session |
| `tests/` | 回归与执行合同测试 |

Remote:

```text
git@github.com:heyan2454/LyricAlignment.git
```
