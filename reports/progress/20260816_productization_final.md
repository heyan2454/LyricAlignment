# 2026-08-16 Lyric Align 产品化验证最终摘要

## 结论
当前 Lyric Align 已具备可产品化验证的基础设施，并在 GTSinger 新数据上完成两轮（diagnostic + regression）raw decoder 对比。

## 关键结果

### GTSinger Diagnostic（75 段，1226 字符）
| 配置 | both_100ms | both_200ms | both_500ms |
|---|---:|---:|---:|
| Official R2 | 90.05% | 95.51% | 98.12% |
| Raw Decoder R2 | 91.84% | 96.00% | 98.21% |

### GTSinger Regression（84 段，1189 字符）
| 配置 | both_100ms | both_200ms | both_500ms |
|---|---:|---:|---:|
| Official R2 | 87.47% | 92.77% | 98.40% |
| Raw Decoder R2 | 89.49% | 93.86% | 98.32% |

### Hard Cases（18 段，309 字符）
- Official 100ms：78.32%
- Raw Decoder 100ms：84.47%

## 质量 Warning 观察
- raw decoder 在 regression 上大幅减少 final zero-duration（R2 44->9）
- 但新增 selected overlap / cross-window compression warning
- 产品化 gate 必须同时覆盖 zero-duration 与 overlap

## 产品化建议
1. 默认模型：R2
2. Decoder：raw decoder 作为强候选，建议进入 sealed 前最终验证
3. 质量 gate：zero-duration / overlap / timestamp regression 必须显式
4. Speech-like input 单独报告
5. sealed 默认关闭，milestone 显式 `--allow-sealed`

## 数据覆盖
- GTSinger：已全量验证 diagnostic + regression
- PJS：日语 smoke 已跑通，待 phoneme GT
- MIR/Jamendo：待 vocal 派生
- sealed：尚未正式运行

## 产物索引
- `results/comparisons/20260816_productization_status.json`
- `results/comparisons/20260816_gtsinger_diagnostic_summary.json`
- `results/comparisons/20260816_gtsinger_regression_official_vs_rawdec.json`
- `reports/progress/20260816_productization_validation_report.md`
- `reports/progress/20260816_productization_recommendations.md`
