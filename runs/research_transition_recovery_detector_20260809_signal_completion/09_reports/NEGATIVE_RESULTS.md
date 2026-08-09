# Negative Results（11 计划）

- **H（hidden states）**：真实评测为负贡献（negative (H single 0.4985295020934426; H+R+O+sel 0.5602065297807913 < R+sel 0.6703508567667198)）——negative。
- **PR（propagation-risk）**：pooled AUC 0.608（高于 correctness proxy），但 source-song macro 0.436 ≈ 随机 → 主要学到歌曲先验，per-episode 泛化弱——PR 无稳健增益（非未执行）。
- **O/RO/V/P/S 单信号**：全部低于 R（0.52-0.59 vs 0.665）——negative。
- **R95 REJECT-only recall（v2 WP 严格语义）**：16.2%——v2 单阈值 WP 不满足 R95 严格定义（v3 WP 需在 Stage 3 冻结）。
- **T2 vs T1**：song-level 不可区分（CI 跨 0）——T2 仅 nominal。
- **retry**：31/36 无改善、4/36 恶化——retry/re-align 算法本身是瓶颈之一。