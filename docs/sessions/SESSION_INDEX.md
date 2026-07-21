
# Session Index

温度表示当前阶段需要读取该 session 的频率，而不是内容质量：

- `hot`：当前执行入口或近期必须持续参考；
- `warm`：关键决策仍有效，但通常可通过 status/manual 推进；
- `cold`：历史依据已被稳定文档吸收，仅追溯时读取。

| Date | Session | Temperature | Summary |
|---|---|---|---|
| 2026-07-22 | `20260722_codex_dataset_cleaning_prompt.md` | hot | 当前 Codex 执行入口；要求完成数据清洗、长音频、metric 与 raw baseline 自动化并逐阶段通过 gate。 |
| 2026-07-22 | `20260722_dataset_cleaning_execution_archive.md` | hot | 本轮 review、数据清洗决策、negative results、协作和依赖状态。 |
| 2026-07-21 | `20260721_mir1k_acquisition_and_ood_preparation.md` | warm | MIR-1K 原始资产与 17 首 OOD 字符标注事实仍有效。 |
| 2026-07-20 | `20260720_smoke_infrastructure_archive.md` | warm | smoke 恢复、身份、证据、runtime 和诊断设计的历史依据。 |
| 2026-07-19 | `20260719_asset_preparation_and_raw_smoke_scope.md` | cold | no-GT smoke 范围已被当前 status/manual 吸收。 |
| 2026-07-19 | `20260719_chinese_dataset_training_route.md` | warm | 中文数据角色和长期适配路线仍有效。 |
| 2026-07-19 | `20260719_structure_and_data_curation_revision.md` | cold | 结构职责已迁移到 README/principles/status/manual。 |
