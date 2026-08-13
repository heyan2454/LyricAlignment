# Run State — 20260814_realign_recovery_visualization_overnight

单一状态文件：主 agent 原子更新，记录每部分状态/已用预算/resume 命令。

| Phase | 状态 | 说明 |
|---|---|---|
| Merge patch | completed | commit 20e4afb，hash 与 PATCH_MANIFEST.sha256 一致 |
| Session review | in_progress | 已读 00-06 |
| Provenance 核实 (Codex facts) | in_progress | 4 subagent 并行 |
| 07_CODEX_IMPLEMENTATION_PLAN | pending | |
| E0 freeze/smoke | pending | |
| 可视化 adapter + 双路/四路 smoke | pending | |
| E1 multi-realign screening | pending | |
| E2 fine-split screening | pending | |
| E3 k1/k3 + recrop | pending | |
| E4 coarse->fine | pending | |
| E5 no-GT selector/safety | pending | |
| E6 atlas / hard-case mining | pending | |
| E7 serial stress | pending | |
| Formal + 运行前后 review | pending | |

## 预算（GPU formal forward）
- 当前累计：0h（尚未跑任何 GPU formal forward）
- target <=10h / hard cap <=12h

## Runs（数据目录 /home/hyan/Data/lyricalign/runs/）
- 待 E0 后创建：`20260814_recovery_visualization_E0_smoke` 等

## Resume 命令（TODO：E0 冻结后填）
