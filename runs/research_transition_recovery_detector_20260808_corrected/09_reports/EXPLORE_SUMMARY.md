# 自由探索摘要（corrected 数据，纯 CPU 重分析）

## 1. 窗首段高危现象（EXPLORE_WINDOW_HEAD.json）——closed loop 零提交的机制解释

- 按距 cursor 距离分桶：窗首行（dist0）REJECT 率 54.9%、d1-5 57.6%、d6-20 51.3%、d21+ 43.8%——**窗首段（前 ~6 行）整体高危**，随距离单调下降。
- 机制归因 = 特征：窗首行 entropy 1.31 vs 深处 1.00（+31%）、top1 0.657 vs 0.696；raw/official diff 恒 0（同 forward 派生）。
- 正确性关联：d0 行 wrong 率 74.6%（首行 REJECT 有真实依据，非纯误杀）；但 reject_on_wrong 仅 64.5%、correct-but-REJECT 6.8-14.8%——存在 1/3 wrong 漏判 + 1/7 正确误杀。
- **L 提交模拟**：792 窗中 54.9% 零提交（首行即非 ACCEPT）；总提交仅 850 行 → 直接解释 corrected closed loop 全配置零提交。
- **skip_k=5 无效**（零提交率 55.3% 几乎不变）；**豁免首行**可消除零提交但放行 74.6% 错误率区（不推荐）。
- **跨窗不稳定**：同 canonical id 在 clean w0 为 ACCEPT（p=0.38）→ w1 变 REJECT（p=0.745）——detector 对同一行在相邻窗上下文输出剧烈变化。
- 结论：零提交 = 窗首段熵高 + SA60 阈值全局偏严（整体 REJECT 44-58%）联合效应；改进需重审阈值策略或跨窗 detector 稳定性，而非扫描起点调整。

## 2. serial 内部偏移分布（补充分析，full-song 逐行缓存已随清理删除）

- full-song 行级对照数据不可得（cache 已清理）；serial records 自身偏移分布与窗边界效应待后续采集（serial_infer 缓存含行级数据可复用）。
- corrected serial（T2 49.6% @0.32s、覆盖 100%）vs full-song 38.8% 的差距留待恢复 full-song 逐行数据后行级归因。

## 3. 探索性结论与建议

1. closed loop 的 L/W 在当前 detector 质量下无产出（零提交）；若要产品化 L 路由，需先在 model_selection 上放宽阈值/改进特征，或接受"保护性路由=零覆盖"作为 conservative 选项。
2. detector 跨窗 p_bad 不稳定（同 id 0.38→0.745）是 V（cross-window consistency）信号最有价值的应用场景——建议后续 collect 含跨窗特征并加入训练。
3. MIR 100% vs M4 45% 的差距仍是 GT 质量（rule_validated）与音频条件（vocal 分离）的重要线索。


## 4. 行级 serial vs full-song（EXPLORE_SERIAL_VS_FULLSONG.json）

- 四格（250ms）：both_correct 928（27.5%）、**serial_only 263（7.8%）**、**full_only 134（4.0%）**、both_wrong 2049（60.7%）。
- serial 独占正确 ≈ full-song 的 2 倍——serial 优势来自窗级上下文对齐精度（60s 窗 < 全曲 230s），非随机噪声。
- 窗边界效应：near-core±2s 错误率 61.4% vs 窗中部 64.9%——**serial 无边界弱点**（错误均匀分布）。

## 5. V（cross-window）特征训练实验（EXPLORE_CROSSWINDOW_FEATURE.json）

- V 覆盖率 30%（committed 行中仅 30% 有跨窗观察——大部分行单窗仅见一次）。
- baseline legacy-8 AUC 0.595 → +V 0.588：**无 heldout 增益（略降）**——按 09 §3 P4 规则停止 V 分支（negative result）。
- 结论：跨窗位移特征在当前数据/标签下不提供判别力；detector 的跨窗 p_bad 不稳定（0.38→0.745）不是可通过该特征简单修复的。
