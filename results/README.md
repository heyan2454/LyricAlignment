# Results

结构化结果目录。`results/` 保存从 run 抽取的轻量结构化指标与比较表，并为
`reports/` 提供可追溯数据来源。reports 不应反向成为 canonical metric source。

子目录：

- `by_run/`：单次 run 的 per-token、per-item 和 summary 指标，保留 run lineage；
- `comparisons/`：在冻结协议下可比的跨 run 比较表；
- `recomputed/`：metric 修正产物（从逐字符 reference/prediction 重算），作为 canonical 结果。

## 与 `runs/`、数据目录的分工

| 目录 | 主要问题 | 当前文件 |
|---|---|---|
| `/home/hyan/Data/lyricalign/runs/` | “这次运行是什么、源路径在哪里、证据是否完整？” | 各 run 的原始输出/日志/checkpoint（不进 git） |
| `results/` | “哪些已登记，指标是多少、从哪个 run/source 来？” | by_run/comparisons/recomputed 轻量汇总（进 git） |
| `reports/` | “面向人的阶段材料与叙事” | progress/research/review/audits 等 md |

大型 per-item/checkpoint/cache 一律外置数据目录，不进本目录与 git。

## 当前已登记结果

- `by_run/`：qwen_fa R2 全量训练（seed 20260724）的 sealed test / MIR-1K OOD / validation
  step001110，以及 R0/R1/R2 早期评测（20260723–20260724），每个 run 独立目录含 metrics、
  evaluation_identity、return_code、stderr 等。
- `comparisons/`：LoRA 摘要、R2 cross-seed follow-up、long b180 outlier audit 等跨 run 比较。
- `recomputed/20260724_character_metrics_v3/`：character metric v3 修正重算的
  `metrics.corrected.json`（canonical，禁止再被原始 aggregate 覆盖）。
