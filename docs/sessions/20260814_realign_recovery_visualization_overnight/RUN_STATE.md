# Run State — 20260814_realign_recovery_visualization_overnight

单一状态文件：主 agent 原子更新，记录每部分状态/已用预算/resume 命令。

| Phase | 状态 | 说明 |
|---|---|---|
| Merge patch | completed | commit 20e4afb + 4785170，hash 与 PATCH_MANIFEST.sha256 一致 |
| Session review (00-06) | completed | 已读全部 7 份文档 |
| Provenance 核实 (Codex facts 1-10) | completed | 4 subagent 并行，notes B/C/D/E 落盘 |
| 07_CODEX_IMPLEMENTATION_PLAN | completed | 生成 + F/G 两路 review，全部 P0/P1 已修订回 07 |
| WP1 E0 freeze/smoke | pending | Plan §9 WP1 |
| WP2 可视化 adapter + 三路 smoke | pending | Plan §9 WP2 |
| WP3 E1 multi-realign screening | pending | Plan §9 WP3 |
| WP4 E2 fine-split screening | pending | Plan §9 WP4 |
| WP5 E3 k1/k3 + recrop | pending | Plan §9 WP5 |
| WP6 E4 coarse->fine | pending | Plan §9 WP6 |
| WP7 E5 no-GT selector/safety | pending | Plan §9 WP7 |
| WP8 P6 adaptive expansion | pending | Plan §9 WP8 |
| WP9 E6 atlas + E7 serial stress | pending | Plan §9 WP9 |
| WP10 E8/E9 Test Demo 可视化 batch | pending | Plan §9 WP10 |
| WP11 收尾 + free-exploration | pending | Plan §9 WP11 |

## GPU 预算（GPU formal forward）
- 当前累计：0h（尚未跑任何 GPU formal forward）
- target <=10h / hard cap <=12h
- 预估 screening+expansion ≈500-1000 forward ≈ 分钟级 warm GPU（E_note §5）

## Runs（数据目录 /home/hyan/Data/lyricalign/runs/）
- 见 07 §5：P0..P9 一一对应 06 phases。

## Resume 命令（E0 冻结后填）
