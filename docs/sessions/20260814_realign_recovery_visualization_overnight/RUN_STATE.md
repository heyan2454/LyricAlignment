# Run State — 20260814_realign_recovery_visualization_overnight

单一状态文件：主 agent 原子更新，记录每部分状态/已用预算/resume 命令。

| Phase | 状态 | 说明 |
|---|---|---|
| Merge patch | completed | commit 20e4afb + 4785170，hash 与 PATCH_MANIFEST.sha256 一致 |
| Session review (00-06) | completed | 已读全部 7 份文档 |
| Provenance 核实 (Codex facts 1-10) | completed | 4 subagent 并行，notes B/C/D/E 落盘 |
| 07_CODEX_IMPLEMENTATION_PLAN | completed | 生成 + F/G 两路 review，全部 P0/P1 已修订回 07 |
| WP1 E0 freeze/smoke | completed | commit 94fa0bf + e2729fa + 4785170; H/I review P1s fixed; 243→351 tests |
| WP2 可视化 adapter + 三路 smoke | completed | commit 714d514 + 44cc51d; K/L review P0+P1s fixed (doc-global index restore, batch namespacing, rerender hash, B4 stand-in labeled); 6 track_view tests |
| WP3 E1 multi-realign screening | completed | commit 3d19152 + 0da7424; N/O review P0(oscillation signed)+3 P1+best_error fixed; 6 multi_iteration tests; GPU formal 命令模板已交付 |
| 待 formal 补齐 | open | ① 正式 B4 alignment 替换 raw stand-in；② `<out>/scientific/` 落盘纳入 rerender hash；③ R-U->sparse 第四路（WP6）；④ WP3 wall_time 真实计时；⑤ WP4 串行链 identity 脆弱点（backlog） |
| WP4 E2 fine-split screening | completed | commit e257542 + 7b7422d + aaaf3e8; Q review P0(unit-state wiring + state_missing_fallback) + P1-2(identity 脆弱,backlog) fixed; 4 split tests; GPU formal 命令模板已交付 |
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
- **环境约束（2026-08-14 实测）**：`nvidia-smi` 返回 "Failed to initialize NVML"，当前会话沙箱内 **GPU 不可直接访问**。
  - 影响：WP3+ 的模型 forward（需要 Qwen 推理 + checkpoint）在本会话内无法直接执行；WP2 可视化（matplotlib/ffmpeg，纯 CPU）可跑。
  - 决策：先完成所有 CPU 可做的实现与 smoke（WP2 渲染、E1/E2/E4 的 request 构造与 CPU smoke 借助 --smoke executor），并把 GPU formal 作为"需用户在可访问 GPU 的运行环境执行的批命令"产出；不强行在无 GPU 会话里跑 forward 造成资源或假跑。
- **资源纪律**：load 已 10+；不在后台并发多个渲染/训练；每次 smoke 用小样本；超时兜底。

## Runs（数据目录 /home/hyan/Data/lyricalign/runs/）
- 见 07 §5：P0..P9 一一对应 06 phases。

## Resume 命令（E0 冻结后填）
