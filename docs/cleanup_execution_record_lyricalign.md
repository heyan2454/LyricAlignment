# lyricalign 数据清理 —— 执行记录

> 执行时间：2026-08-01（脚本已 `--apply` 由用户本人运行）
> 清理脚本：`scripts/cleanup/cleanup_lyricalign_data.sh`（归档副本；`/home/hyan/a.sh` 为同内容执行版）
> 范围：`/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics` 的 **A、B 两类**（见 `docs/data_cleanup_checklist_lyricalign.md` ## 二）。

## 清理前
- demo_diagnostics 总占用 ≈ **86 GB**（含各版本 run root 的中间产物与历史迭代）。

## 实际清理（--apply 结果）
| 类别 | 对象 | 结果 |
|---|---|---|
| A · 历史迭代 root | 13 个（lazy_v1/v2/v4/v5/v6/v7、smoke_e9/_v2.._v7） | **全部删除（0/13 残留）** |
| B · inline 中间产物 | `inline_realign_formal_v3/v4/v5/items/` 内各 item 除 `item_summary.json` 外全部 | **删除完毕** |
| B · 冗余 zip | `inline_realign_formal_v3_20260728/items.zip` | **已删** |

## 清理后核验
- demo_diagnostics 现占用 **≈ 47 GB**（释放约 **39 GB**）
- B 类三个 inline：各 98 个 item，**非 item_summary 残留 = 0**（每 item 仅保留 item_summary.json）
- **保留完好**：`v8` 正式 root（complete.json、research_summary、run_status、manifest）、
  `v3_gtintervalfix`、`supplemental_20260801`、`realign_quick_*`、`mir1k_subset_v1`、
  `inline v1/v2 及 20260727`、`side_by_side_*`、`realign_gpu_decoder_overnight_v2` 等（均非 A/B 目标，未动）
- 清单中标记“保留”的项（models、tools/fonts、outputs、evidence*、derived 引用、runs 引用 checkpoint、v8 结果）**均未涉及**。

## 复核状态
清理脚本在 `--apply` 前已通过三轮子进程审查：
1. `bash -n` 语法检查；
2. DRY-RUN 枚举核对（DEL 2915 / KEEP 294 item_summary、v8 路径未命中、整 item 目录误删=0）；
3. 清理后实测核验（本记录）。

## 备注 / 后续
- 本次仅清理 demo_diagnostics 的 A/B 两组。清单中其余可清理项（test work/audio、runs 非复用、
  derived 旧版本等）**尚未执行**，如需可另行评估。
- 归档脚本 `scripts/cleanup/cleanup_lyricalign_data.sh` 保留以便复用/复核。
