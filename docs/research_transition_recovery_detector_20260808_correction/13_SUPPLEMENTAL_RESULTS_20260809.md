# Supplemental 实验结论摘要（11/12 计划）

日期：2026-08-09
权威数据：`runs/research_transition_recovery_detector_20260809_signal_completion/09_reports/SUPPLEMENTAL_REPORT.json`（轻量 manifest；大 evidence 已移出工作目录到 `/root/autodl-tmp/lyricalign_sessions/`）。

## 完成状态

- `supplement_completed: true`、`signal_completion: true`、9/9 gates true。
- Transition 汇总口径已修正（row-level aggregation），T2 仅 nominal、serial 稳健。
- Detector 全信号（H/R/O/RO/V/P/S）真实实现并公平消融；CNN1D 序列模型真实执行。
- PR 真实定义并评测；retry failure decomposition 完成（36 windows）。

## 关键结论

### Transition（v3 权威口径）
- product candidate：T2_core_boundary_serial，250ms correct coverage 0.401（1337/3374）。
- T2−T1 song-level paired CI [-0.0015, +0.0113]（跨 0）→ T2 仅 nominal，不宣称机制优势。
- serial−full-song CI [+0.053, +0.116]（不含 0）→ serial 稳健。
- raw vs official timing ≈ 相同（250ms 34.8% vs 34.7%）→ Demo 观感差异主要来自 250ms 严格性而非 decoder。

### Detector（全信号消融，best combo = R+sel）
| branch | raw AUC | 备注 |
|---|---|---|
| H | 0.499 | 负贡献（真实 negative） |
| R | 0.665 | 最强单信号 |
| O | 0.519 | negative |
| RO | 0.539 | negative |
| V | 0.586 | negative |
| P | 0.491 | negative |
| S | 0.553 | 修复未来泄漏后下降（原 0.589 含泄漏） |
| R+sel(V) | 0.670 | best，selected(V/P/S)=V |

- S 未来 interval 泄漏已修复（rolling 统计只含当前及过去），selected 由 S 变 V。
- CNN1D（AUC 0.636）< 同输入 MLP（0.675）→ sequence model negative。
- H/P evidence 均真实采集并消费（SIGNAL_COVERAGE_AUDIT 185 requests coverage 1.0）。
- O/RO/P unit 级 feature coverage 0.0（records 缺 official end / path 全请求缺失），但模型实际消费 features_used 可用子集并产生真实 AUC。

### PR（propagation-risk）
- corpus：171 high + 81 mild（low 18 / medium 63）。
- PR 特征修复前（错误取 recs[0]）pooled AUC 0.5；修复为 episode 首窗后 pooled AUC 0.608、source-song macro 0.436。
- 结论：pooled 高于 correctness proxy，但 macro ≈ 随机 → 主要学到歌曲先验，per-episode 泛化弱。

### Recovery
- 36 retry windows 分解：worsened 4 / not_improved 27 / improved_detector_accept 3 / improved_detector_block 2。
- 0 writeback 主因：retry 无改善（31/36）+ detector 拒绝全部改善（5/5）双瓶颈。

## 数据治理说明

- 具体 evidence（forward/serial cache、逐窗 records、evidence jsonl）已移出 git 跟踪与工作目录，
  存档至 `/root/autodl-tmp/lyricalign_sessions/`；git 与源码包只保留 manifest/结论/报告。
- 本摘要为轻量结论，权威 JSON 见 runs 目录（可追溯，不随源码包分发）。
