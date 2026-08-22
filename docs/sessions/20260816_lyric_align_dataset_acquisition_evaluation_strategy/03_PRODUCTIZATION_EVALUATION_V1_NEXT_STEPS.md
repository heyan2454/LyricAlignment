# Productization Research — Evaluation V1 Draft + Behavior Registry

> Status: draft; CPU-only except three short GTSinger smokes (R0/R1/R2, ~8-9s each) that exercised structural quality/warnings.
> Large artifacts are outside git under `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/`.

## 1. 本轮做了什么

- 阅读了 `20260816_lyric_align_dataset_acquisition_evaluation_strategy/`（新数据集获取 + Codex 建议）
  和 `20260814_realign_recovery_visualization_overnight/`（旧 session 的机制行为设计）。
- 新增 `scripts/evaluation/build_evaluation_v1_split_manifest.py`：
  - 按 song/group 生成 `diagnostic_visible : regression_selection : sealed_final` draft manifest；
  - 支持 MIR-MLPop cmn/yue、JamendoLyrics English、PJS、GTSinger Chinese mini；
  - 输出可清理报告、leakage audit、manifest SHA-256；
  - 不触碰原始数据，不写大文件到系统盘。
- 已用 GTSinger Chinese mini 的三个 8-9 秒 diagnostic 片段（Control/Glissando/Control#2）跑通现有 R0/R1/R2 serial demo；其中两个全 passed，一个 R2 出现 raw overlap warning 但 final 干净。
- 已对 8 个 GTSinger 短中文片段做 JSON GT 数值评测：R2 在 117 字符上 both_100ms=97.4%、both_200ms=100%；R1 接近；R0 明显更差。
- 已完成 GTSinger 全量 diagnostic 75 段、1226 字符：R2 both_100ms=90.1%、both_200ms=95.5%；R0 明显更差。
- 同时发现约 30–34/75 段存在 final zero-duration warning，产品化需把零时长后处理作为显式 gate。
- 已生成 draft manifest：
  - `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_split_manifest.jsonl`
  - SHA-256: `f04e0b9b959907a87965c581a615dd1d74b03dbd88dce837e2cc97927602ed8f`
  - 汇总：`evaluation_v1_split_summary.json`、`evaluation_v1_leakage_audit.json`、`cleanup_report.md`

## 2. 本轮新增可清理产物

| 产物 | 路径 | 内容 |
|---|---|---|
| Split draft | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/` | manifest + summary + leakage audit + cleanup report |
| Dataset readiness audit | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_datasets_audit/` | 6 个新数据集的 meta/audio/readiness |
| Baseline identity | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_baseline_identity/` | git commit、模型/checkpoint 默认路径、Python 环境 |
| Vocal derivation plan | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_vocal_plan/` | raw mixture -> vocal-only 的待执行计划（不实际分离） |
| Diagnostic-only manifest | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/evaluation_v1_diagnostic_only.jsonl` | 只含 `diagnostic_visible` 的首轮运行清单 |
| Dataset compatibility matrix | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/dataset_compatibility_matrix.json` | 各数据集粒度/语言/vocal-ready/使用前要求 |
| Behavior registry | `reports/behavior_registry.json` | 单因素消融候选注册表（进 git） |
| GTSinger smoke | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_smoke/`, `..._smoke2/`, `..._smoke3/` | 新数据集三个小规模 R0/R1/R2 可运行性验证；含一个 R2 raw-overlap warning 案例 |
| GTSinger first metrics | `reports/progress/20260816_gtsinger_first_metrics.md` | R0/R1/R2 对 GTSinger 短中文片段的 100ms 命中率/中位误差 first-light |
| GTSinger batch smoke | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_batch/` | 额外 5 段 GTSinger diagnostic，77 字符 R0/R1/R2 评测 |
| GTSinger full diagnostic | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_gtsinger_diag_all/` | 75 段全 diagnostic 完成，1226 字符 R0/R1/R2 评测 |
| PJS Japanese smoke | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_pjs_smoke/` | 日语路径可运行，待 phoneme GT 正式评测 |
| MIR raw mixture smoke | `/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_mir_smoke/` | raw mixture 直接跑全 warning，确认必须 vocal 派生 |

## 3. Draft split 数量

| Dataset | Diagnostic | Regression | Sealed | 说明 |
|---|---:|---:|---:|---|
| MIR-MLPop cmn | 4 | 10 | 6 | 官方 Test 全 sealed；Train 14 首按 seed 分 4/10 |
| MIR-MLPop yue | 1 | 1 | 1 | 3 首探针，不强统计 |
| JamendoLyrics en | 4 | 10 | 6 | raw mixture；vocal 派生未完成 |
| PJS | 20 | 50 | 30 | 100 个 song ID，song/speech/lab 同组 |
| GTSinger mini | 1 | 2 | 2 | 5 个 song root，按 root 分组 |
| AMLL | - | - | - | 无音频，仅 silver pool |
| iKala | - | - | - | 未获授权，排除 |

> 当前是 draft，不是 frozen。正式使用前需要 review 分层与泄漏报告、冻结 manifest hash，
> 并且 Jamendo/GTSinger 还需完成 vocal derivation / 条款澄清。

## 4. 旧 session 行为设计 → 产品化研究入口

旧 session（20260814）把 Lyric Align 机制分为多个行为层。产品化评测不应枚举开关笛卡尔积，
而应按下列 registry 逐步做单因素消融。

| 层 | 机制/行为 | 目标故障 | 新数据集可提供的证据 |
|---|---|---|---|
| 输入/文本规范化 | 中日英/粤语字符映射、假名/汉字、word vs char | 跨语言漏字、错字、分词不一致 | PJS 日语音素边界、MIR-MLPop 粤语/普通话、GTSinger 中文 |
| 窗口/上下文 | 60s silence-aware window、skip-silent、boundary protection、full-slot vs pre-slot serial | 长歌窗口退化、静音切碎、上下文漂移 | MIR-MLPop/Jamendo 自然流行混音、PJS 短句边界 |
| 候选/选择 | R-U coarse proposal、R-S fixed context isolation、R-CF coarse→fine | 困难区 recovery、上下文副作用 | MIR-MLPop 自然混音困难片段、GTSinger 技巧唱法、Jamendo overlap/polyphonic |
| 安全/恢复 | shadow writeback、no-GT gate、multi-iteration、recrop/split | 错误 writeback、越修越坏、serial drift | 新数据 hard-case mining + regression selection |
| 后处理 | 单调性、最小时长、边界平滑、KTV 可视化 | 零时长、跨行、时间倒置 | 所有带 GT/时间标注数据集 |

## 5. 产品化关键 gate（下一步）

1. **冻结 Evaluation V1 split manifest**：
   - review `evaluation_v1_leakage_audit.json`；
   - 把 seed/算法/源 revision 写入 manifest，冻结 SHA-256；
   - 常规 runner 默认拒绝 `sealed_final`，需显式 `--allow-sealed`。
2. **补齐 vocal-only 派生**：
   - JamendoLyrics 和 MIR-MLPop raw mixture 需先做分离，记录 separator identity/config/input-output hash；
   - 产物放 `/home/hyan/Data/lyricalign/derived/`，不覆盖 raw。
3. **冻结旧模型 baseline**：
   - 固定模型 revision、checkpoint、代码 commit/config、vocal source；
   - 先在 `diagnostic_visible` 上跑 error taxonomy，不做 sealed。
4. **单因素消融**：
   - 每次只改一个行为；先 diagnostic，再 regression；
   - 报告按数据集/语言/粒度分开，不合并成单一 accuracy。
5. **Sealed milestone**：
   - 只在阶段版本开启；若根据 sealed 调参，必须发布新版本并重新封存。

## 6. 资源与数据管理

- 本批只生成小 JSON/JSONL/MD，总大小 < 1 MB；
- 已清理 `/tmp/opencode` 等历史临时工作树，系统盘可用空间从 ~6G 恢复到 ~18G；
- 原始音频/大文件继续留在 `/home/hyan/Data/datasets/`；
- 删除本批可直接 `rm -rf /home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft`；
- 后续每个实验批次都应保留 `cleanup_report.md` 和可复现命令。

## 7. 待办

- [ ] review 并冻结 evaluation_v1 split manifest
- [ ] Jamendo/GTSinger vocal derivation + provenance
- [ ] MIR-MLPop/Jamendo operational input manifest
- [ ] 旧模型 baseline on diagnostic subset
- [ ] behavior registry 单因素消融第一批
- [ ] sealed runner access control
