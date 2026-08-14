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
| WP5 E3 k1/k3 + recrop | completed | commit 622708b + 4fc3f6f; S review 无 P0/P1; MINOR-1 测试补齐; GPU formal 模板已交付 |
| WP6 E4 coarse->fine | completed | commit b89654b + fef297c; U review P1(A-stage fallback)+P1-2(4th-route hard fail) fixed; 4 coarse_fine tests; 四路可视化经 --fourth-family R-CF 接入; GPU formal 模板已交付 |
| WP7 E5 no-GT selector/safety | completed | commit 202bcba + 76656df; W review 4 P1(proxy producer/true-p85/disjoint heldout/tests) fixed; 11 tests; GPU formal 模板已交付 |
| WP8 P6 adaptive expansion | completed | commit 5f17160 + 6cd5f90; Y review P0(real-field aliases+fail-closed)+P1(mech-id/no-overwrite) fixed; 3 tests; GPU formal 扩量命令模板已交付 |
| WP9 E6 atlas + E7 serial stress | completed | commit 37e88d9 + 97f5399; AA review P1(coarse proportion+recrop schema) fixed; 4 tests; GPU formal 模板已交付 |
| WP10 E8/E9 Test Demo 可视化 batch | completed | commit 416621b + 9f4196e; AC review P1(item-scope + real rerender) fixed; item convergence verified; GPU formal 批量模板已交付 |
| WP11 收尾 + free-exploration | completed | 08_SESSION_FINAL_REPORT.md (+ AD review P1s fixed); 满足 04 §10; free-exploration 递归 todo 已在报告 §8 保留 |

## GPU 预算（GPU formal forward）
- target <=10h / hard cap <=12h
- 当前累计：**GPU 已在 full-access 会话内直接可跑**（RTX 4080 SUPER，Qwen 0.6B 峰值 2.5GB；每 fwd ~0.5s）。
- 已跑真实扩量：E1(40region/200fwd/54s)、E4(40region/87行/20s)、E2(见下)。
- **资源纪律**：run 数据一律写 `/home/hyan/Data/lyricalign/runs/20260814_*`；**GPU 任务串行**（一次一个，避免并发显存/内存峰值）；RAII 顺序：先小 limit 验通 → 扩量到 40；禁止全笛卡尔积（挑关键 cell）。

## Runs（数据目录 /home/hyan/Data/lyricalign/runs/）
- 见 07 §5：P0..P9 一一对应 06 phases。

## Resume 命令（E0 冻结后填）

## 可视化二版（全曲）记录（用户反馈后）
- 反馈：首版 4lang(20260814_viz_4lang)不是全曲(7-60s)、看不清、无过去 baseline 对比。
- 根因：render_current_4way 的 timeline 边界 = unsafe 窗口 R-U/R-S evidence 的 start/end；
  且那几首无全曲逐字对齐；render_b4_vs_current 的 B4 是 raw-argmax 替身。
- 修复：新增 `scripts/realign_recovery/visualization/render_full_song.py`(commit bdc802d)，
  全曲 lane = 现跑 `alignments/r2/mix/windowed/alignment.json`(30s/页 + 5600px 全曲长图)。
- 产全曲 baseline：run_qwen_fa_batch --individual r2:mix:windowed --stage align 于数据盘
  `viz_fullsong_prep/`（不污染 test 源）；4 首饰全曲(203.8/287.0/134.7/229.6s)。
- 产物：
  - 纯全曲版 `runs/20260814_viz_fullsong_4lang/`（lane:历史raw解码 vs 当前精修）
  - overlay 版 `runs/20260814_viz_fullsong_4lang_ovl/`（lane:Current全曲+R-U）
- post-review：`runs/20260814_runs_summary/VIZ_FULLSONG_4LANG_POST_REVIEW.md`
- 遗留：真 B4(pre-slot 串行)lane、R-S/R-CF overlay、此处通往天空多窗 overlay index 冲突。
