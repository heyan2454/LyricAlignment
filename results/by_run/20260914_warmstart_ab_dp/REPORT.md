# 热启动 A/B 判决（生成，勿手改）

> 主判据 = 长上下文视图 `fixed` 的 0.2s 命中率，逐歌配对；预注册规则见 `docs/status/20260914_concat_arm_prereg.md`。可用存档：[]；缺失：['old-r2-750', 'warmstart-control', 'warmstart-oversample', 'uniform-12000']。

| 比较 | 歌数 | 差(pp) | SE | z | 更好/更差 |
|---|---|---|---|---|---|
| B（上采样）vs 线上旧 750 — 主指标 | — | — | — | — | 未测到（insufficient_data） |
| A（对照）vs 线上旧 750 — 续训漂移 | — | — | — | — | 未测到（insufficient_data） |
| B vs A — 上采样的**净效应**（判定用这一行） | — | — | — | — | 未测到（insufficient_data） |
| B vs 热启动来源（均匀终点） | — | — | — | — | 未测到（insufficient_data） |
| A vs 热启动来源（均匀终点） | — | — | — | — | 未测到（insufficient_data） |

## 机制检查（不参与判决，只解释成因）

- control：2-+s 桶失败子集时长比 0.452（该桶超差率 0.126，n=127）
- treatment：未测（跑 `duration_ratio_profile.py` 后重跑本工具）

**判决**：主指标 `insufficient_data`；净效应 `insufficient_data`。
