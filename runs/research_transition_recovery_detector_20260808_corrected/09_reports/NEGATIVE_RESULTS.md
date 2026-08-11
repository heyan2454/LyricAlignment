# Negative Results

> **校正注记（2026-08-12 quick-correction，WP5）：** 本表结论基于 synthetic-uniform timeline GT。
> 其中 Oracle-L/W recovery、Closed loop、Fixed-threshold transfer 等均为 **historical synthetic-GT
> oracle diagnostic**，不是 real-GT/no-GT 能力结论；修复后需在 real-GT 口径重新评估。旧 CNN1D
> AUC=1 与 Isotonic 结论与 real-GT 判定无关，保留为协议记录。

- **T1/T2 serial 无法作为产品路线**：提交内正确率 <25%（model_selection），覆盖 40% 下 correct-committed coverage <6%；query 起点估算缺陷导致系统性错位（synthetic-GT 口径；real-GT 见 15 号 §3）。
- **T3 stable-boundary 覆盖率过低**（~12%）：保守提交导致大量未提交；且跨窗观察在已过时行上物理不可行（冷启动需 baseline commit 修正）（synthetic-GT 口径）。
- **Oracle-L/W recovery 上限低**（18.6%/21.4%）：模型重跑同段产生相同偏移，重跑不能修复系统性节奏偏差（**historical synthetic-GT oracle diagnostic，非 real-GT/no-GT 结论**）。
- **Closed loop 净负**：detector 标记段重跑整体变差（delta -110~-283）；detector+recovery 无法提升 full-song 输出（synthetic-GT 口径；detector/recovery 结论均已受 light_merge 修复影响）。
- **Fixed-threshold transfer 漂移**：冻结阈值在 model_selection 上 safe_accept≈0.5%（分布漂移）；未重调（07 §7 契约）（synthetic-GT 口径）。
- **Hidden extraction 不可用**（blocked）：hook 未接入 real inference，availability=0；不声称 hidden 无增益。
- **Cross-view full posterior 未执行**（not_executed_dependency）：topk-only 证据不足以计算精确 JS/L2。
- **旧 CNN1D AUC=1 不得引用为窗口级能力**（协议纠正登记）。
- **Isotonic 不能改善 discrimination**（旧结论确认，不重跑）。