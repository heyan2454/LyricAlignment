# 热启动 A/B 判决（生成，勿手改）

> 主判据 = 长上下文视图 `fixed` 的 0.2s 命中率，逐歌配对；预注册规则见 `docs/status/20260914_concat_arm_prereg.md`。可用存档：['uniform-12000', 'warmstart-control', 'warmstart-lossweight', 'warmstart-oversample']；缺失：[]。

| 比较 | 歌数 | 差(pp) | SE | z | 更好/更差 |
|---|---|---|---|---|---|
| B（上采样）vs 线上旧 750 — 主指标 | 29 | -0.03 | 0.14 | -0.24 | 10/5 |
| A（对照）vs 线上旧 750 — 续训漂移 | 29 | -0.01 | 0.05 | -0.31 | 4/3 |
| B vs A — 上采样的**净效应**（判定用这一行） | 29 | -0.02 | 0.12 | -0.16 | 8/7 |
| B vs 热启动来源（均匀终点） | 29 | -0.03 | 0.14 | -0.24 | 10/5 |
| A vs 热启动来源（均匀终点） | 29 | -0.01 | 0.05 | -0.31 | 4/3 |

## 机制检查（不参与判决，只解释成因）

- control：未测（跑 `duration_ratio_profile.py` 后重跑本工具）
- treatment：未测（跑 `duration_ratio_profile.py` 后重跑本工具）

**判决**：主指标 `measured`；净效应 `measured`。
