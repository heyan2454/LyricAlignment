# 明早索引（09:17 生成，10:00 前读这份就够）

> 所有数字都由脚本从 `results/by_run/**` 的 JSON 生成；不要从任何 .md 里手抄数字回文档。

| 顺序 | 文件 | 是什么 |
|---|---|---|
| 1 | `docs/status/20260914_plain_summary.md` | 先看这份：大白话，无术语，数字由脚本从 JSON 生成 |
| 2 | `docs/status/20260914_night_report.md` | 技术总报告（20+ 节，每节指向自己的数据源；缺数据显示「未跑」） |
| 3 | `docs/status/20260914_concat_arm_prereg.md` | 预注册主线：§3g-2 预测带、§3i 功效上限、§3j 数据路径关闭、§3l 2×2 决策表、§3n B 的覆盖混杂、§3p 实际填格 |
| 4 | `docs/status/20260914_c_arm_prereg.md` | C 臂（字符级 loss 加权）预注册 + §5 可 falsify 的形状预测 |
| 5 | `docs/status/20260914_robustness_B_vs_A.md` | B vs A 三关稳健性（中位/截尾 + McNemar + ×4 校正） |
| 6 | `docs/status/20260914_robustness_A_vs_start.md` | 对照臂漂移的同一套检查（结论：只是迹象） |
| 7 | `docs/status/20260914_robustness_750_vs_12000.md` | 整条训练史的同款检查（短音改善=确证；长音改善=无证据） |
| 8 | `docs/status/20260914_position_effect.md` | 末字位置效应：被时长混杂解释，不做尾部延长改动 |
| 9 | `docs/status/20260914_gating_calibration.md` | 按预测时长分档的门控阈值：三个预算一致更差 ⇒ 关闭 |
| 10 | `results/by_run/20260914_ab_decision/REPORT.md` | 决策表程序输出的所在格与下一步 |
| 11 | `results/by_run/20260914_long_context_view/` | 五判据长流视图全部存档（含 A/B/拼接/基线） |
| 12 | `results/by_run/20260914_arms_by_bucket/metrics.json` | 时长分段的逐字符计数表（形状与量级） |
| 13 | `results/by_run/20260914_exposure_fit/validation_uniform_f8.json` | 暴露—误差拟合（采用口径：留出曲线 + 臂真实 factor=8） |
| 14 | `results/by_run/20260914_real_song_decoder/metrics.json` | 真歌端到端 official vs DP（压力条件；含两轴位移） |
| 15 | `results/by_run/20260914_review_gating/metrics.json` | 置信度门控交付物的实测数字 |

## 现在正在跑什么

- C 臂（字符级 loss 加权，slot=offset，600 步）在 GPU 上，约 09:44 结束；
- 它的 CPU 评测链（逐字符 dump → 机制画像 → 两组三关稳健性 → 同步数屏幕）已挂哨兵，会自动跑；
- 之后需要手动做的只有一件：C 的长流视图评测（约 6 分钟 GPU，必须等 C 训练退出后跑，保持单卡串行）。

## 今晚的三条硬结论（细节见上述文件）

1. **免费可拿**：DP 解码（8 个独立存档上逐个现算：+0.90 ~ +1.17 pp）与置信度门控（复核 10% 消除 ~55% 缺陷）；但两者必须一起上，因为 DP 会把结构探针全部变绿。
2. **机制**：误差集中在长字符结束点；典型预测并不收缩，收缩是失败子集的条件性偏差；不确定性随时长急剧集中（最低置信四分位占比 14%→80%）。
3. **B 臂（条目复制）净收益为零**：时长分段形状完全命中预测（≥1.5s 新修好 9、最短段新弄坏 4），但总分 123 = 起点 123，而对照 A 退到 129 ⇒ 条目复制不是可用的工程手段，C 是无混杂的下一步判定。
