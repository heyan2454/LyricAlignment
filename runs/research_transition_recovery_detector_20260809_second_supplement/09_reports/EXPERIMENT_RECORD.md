# 二次补充实验记录（Transition-Recovery-Detector）

**日期：2026-08-09 → 08-10**
**Session：`runs/research_transition_recovery_detector_20260809_second_supplement/`**
**GT 口径：real_gt_pinyin_overlay（20260723 overlay + 段偏移投影）**

---

## 1. 执行脉络

1. **二次补充计划（11/12 方案 review）**：修复第一次补充的 committed-view 混用、P 未完成、interval Grey 污染、recovery 复现链缺失。
2. **修复提交-view 混用（P0）**：`detector_observations.py` 按 committed request 绑定，标签与 authoritative 一致（后因真实 GT 切换为 3093/97/38）。
3. **P exact k-best DP**：`posterior_paths.py` 重写为 exact k-best monotonic DP（top_n 稀疏化）。
4. **interval evaluator v2**：Grey 不入 unsafe 分母 + per-song intervalization + REJECT/protected 分离。
5. **PR held-out**：source-song disjoint OOF/LOSO + 冻结 detector correctness。
6. **recovery 真实分解**：before/after 同集合对比。
7. **自由探索（30+ 角度）** → 发现两大 P0：
   - **评估 GT 根本性错误**：synthetic-uniform GT（段内均匀）被误用作评估，真实 GT（pinyin overlay）覆盖 97%。
   - **H/P evidence 窗口污染**：collect_evidence_v3 复用 last_evidence，每歌 4 窗指向同一 npy。
8. **真实 GT 重建**：`real_gt.py` 投影加载器，detector/interval/recovery/PR 全部重算。
9. **H/P evidence 修复**：`recollect_evidence_v3.py` 按 records request 逐窗重新 forward（185 窗，0 mismatch）。

---

## 2. 关键结论（真实 GT 下）

### 模型对齐质量（重大修正）
- 真实 GT 下 model_selection：safe 3093 / grey 97 / unsafe 38（**91.7% Safe**），err 中位 0.025s。
- uniform GT（旧）误判 60% unsafe → **模型实际对齐极好**，旧"对齐质量差需修复"主线前提不成立。

### Detector（真实 GT + 修复 H/P evidence）
| 信号 | AUC | 信号 | AUC |
|---|---|---|---|
| H | 0.882 | V | 0.660 |
| R | **0.976** | P | 0.830 |
| O | 0.798 | S | 0.818 |
| RO | 0.773 | H+R+O | 0.972 |

- best_combo = R（单信号 0.976 最强）。
- R95 unsafe_reject 0.913，SA60+R95 joint 差 3.7pp 到 95%（不可行）。

### P（coherent second path）
- exact k-best DP；修复后 evidence_P：model_selection 34 ok / 2 no_monotone_path。

### PR（held-out）
- OOF 0.510 / LOSO 0.550 / correctness 0.510 → negative（决策时信息不足以预测传播）。

### Recovery
- 36 windows：30 not_improved / 6 worsened / 0 block。真实 unsafe 极少，retry 无可修错误。

### Sequence
- MLP 0.976 vs CNN1D 0.774（公平 train-only scaler）→ sequence negative。

---

## 3. 待办 / 遗留

- 旧 uniform GT 结论（549/804/2021、R=0.632）已在报告作废，但历史 commit/report 仍可追溯，不覆盖。
- H/P 的 `_old.jsonl` 备份已删。
- 完整命令链见 `00_meta/RUN_META.json`。
- 自由探索 backlog 见 `00_meta/EXPLORATION_NOTES_20260809.md`（30+ 角度，含 H1 头部策略、亚网格解码等后续方向）。

---

## 4. 环境与复现

- conda env：`lyricalign-qwen`（transformers 5.15.0.dev0, torch 2.8.0+cu128, GPU RTX 4080 SUPER）。
- 关键入口：`train_detector_v3.py`、`recollect_evidence_v3.py`、`recompute_evidence_P_v2.py`、`run_recovery_decomposition.py`、`report_second_supplement.py`。
- GT 投影：`src/lyricalign/research_transition_recovery_detector/real_gt.py`。
- 180 tests pass。
