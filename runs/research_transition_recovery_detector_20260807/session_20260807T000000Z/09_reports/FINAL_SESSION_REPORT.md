# Final Session Report: Transition–Recovery–Detector

session_root: `runs/research_transition_recovery_detector_20260807/session_20260807T000000Z`
GPU seconds recorded: 900.0

## 1. Transition 比较（model_selection 9 首，tolerance 0.32s, raw decoder, retained 3.0s）

| transition | pooled correct* | 备注 |
|---|---|---|
| T0 oracle-independent | 0.4552 | 诊断上界（GT query） |
| T1 direct serial | 0.1519 | 提交内正确率，覆盖 ~40% |
| T2 core-boundary serial | 0.1456 | 同上 |
| T3 stable-boundary serial | 0.4645 | 提交内高但覆盖 ~12% |
| **full-song align** | **0.3883** | **Product candidate（non-serial 胜出）** |

*T1/T2/T3 分母=committed units（覆盖 40%/12%），T0/full-song 分母=全部 units。

## 2. 关键发现
- **serial 系统性失效机制**：query 起点用 density 估算，歌词密度变化（如开头 0.5s/字、后段 1.25s/字）时把已唱过的歌词塞进后续窗 → 模型整体错位。
- **正确切片下的单窗能力 59-66%**：模型本身不差；serial 的失败来自 query 构造而非模型。
- **Oracle recovery 上限低**：L=18.6% / W=21.4%；模型重跑产生相同系统性偏移（~0.4-1.3s），无法通过重跑修复。
- **Closed loop 净负**：36-88 段重跑 delta -110~-283，detector+recovery 不能提升 full-song 质量。
- **MIR 100% vs M4 38-55%**：vocal 分离+短歌+人工 GT 下模型完美；M4 的误差含 GT 质量（rule_validated）与长歌上下文因素。
- **Detector 有效但阈值漂移**：train AUC 0.84；SA60/SA80/R95 冻结可行；fixed-threshold transfer 跨歌漂移显著。

## 3. 交付物清单
- [x] `01_precheck/PRECHECK.json`
- [x] `02_transition/TRANSITION_REPORT.json`
- [x] `02_transition/CANDIDATE_SELECTION.json`
- [x] `03_propagation/EPISODES.jsonl`
- [x] `04_oracle_recovery/ORACLE_SUMMARY.json`
- [x] `05_legacy_gaps/LEGACY_GAP_STATUS.json`
- [x] `06_detector/FROZEN_WORKING_POINTS.json`
- [x] `07_closed_loop/CLOSED_LOOP_SUMMARY.json`
- [x] `08_transfer_demo/MIR_TRANSFER_SUMMARY.json`
- [x] `08_transfer_demo/TEST_DEMO_SUMMARY.json`

## 4. 状态
- Transition: complete（T0-T3 + full-song 比较完成）
- Propagation: complete（170 episodes，机制为 T2 系统性错位）
- Oracle recovery: complete（L/W 上限低）
- Legacy gaps: 见 LEGACY_GAP_STATUS.json（2 complete + 1 blocked + 2 not_executed_dependency + 1 complete 替代）
- Detector: complete（SA60/SA80/R95 冻结 + joint 可行 + transfer 漂移报告）
- Closed loop: complete（negative result）
- MIR transfer: complete（100% 对照）
- Demo: complete（23 首结构分析 + suspicious ranking）

结论：non-serial（full-song）为当前最佳路线；detector/recovery 的收益受模型固有对齐偏差限制；
下一步应聚焦模型对齐质量（新 decoder/校准/GT 质量）与 M4 GT 审计。

## 5. 自由探索补充（Phase 9 后，CPU 重分析）

- **M4 GT 质量审计**：长歌 GT 的 mapping_status 全部为 review_required（auto phoneme grouping），
  非人工 GT——M4 38-55% vs MIR 100% 的差异含 GT 质量贡献，不能单因归因模型。
- **系统性偏移校正**：pooled median bias -0.30s，但全局/每歌中位数校正均使 correct rate 下降
  （0.388→0.359）——偏差非全局常数，校正类改进不可行。
- **容差敏感性**：0.32s 恰好卡在分布上升段中部（46.8%）；0.5s→66.0%、1.0s→88.2%——
  产品端应评估业务可接受容差。

详见 `09_reports/EXPLORE_1_SUMMARY.md` 与 `EXPLORE_GT_AUDIT/BIAS_CORRECTION/TOLERANCE.json`。
