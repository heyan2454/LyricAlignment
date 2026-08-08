# Transition Formal Report (development_selection)

role: model_selection | songs: 9 | pooled units: 3374

| transition | pooled correct* | correct-committed coverage | macro correct | wrong committed |
|---|---|---|---|---|
| T0_oracle_independent | 0.455 | 0.4547 | 0.448 | 1836 |
| T1_direct_serial | 0.152 | 0.0578 | 0.153 | 1089 |
| T2_core_boundary_serial | 0.146 | 0.0554 | 0.147 | 1097 |
| T3_stable_boundary_serial | 0.465 | 0.0542 | 0.471 | 211 |
| full_song_align | 0.388 | - | 0.384 | - |

*pooled correct: T0/full-song 分母=全部 units；T1/T2/T3 分母=committed units。跨口径公平比较用 correct-committed coverage（分子=correct committed，分母=全部 units）。

**Product candidate: `full_song_align`** — non-serial 胜出：full-song 单次对齐 pooled correct 与 T0 oracle 上界相当
**Mechanism candidate: `T2_core_boundary_serial`** — T2 提交量最大（carried-state error 足量），core ownership 语义清晰、可解释; T2 total_wrong_committed 高 → 传播研究所需错误进入 carried state

tolerance: 0.32 s | decoder: raw | compress: retained 3.0 s + silence snap | query: full-slot