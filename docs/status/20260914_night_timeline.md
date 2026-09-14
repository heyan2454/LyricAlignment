# 今晚的时间线（自动汇总：日志与哨兵，不手抄）

> 生成于 2026-09-14 23:05:49，来源目录 `/home/hyan/Data/lyricalign/runs/_launch_logs`；只收录带时间戳的关键行（开始/结束/exit/等待/触发/跳过/停止）。

## 事件流

| 时间 | 来源日志 | 内容 |
|---|---|---|
| 01:47:27 | `night_stage_L3_full.log` | exit=0 |
| 03:36:08 | `warmstart_ab.log` | A/B 排队中，等 GPU 空出 |
| 06:52:00 | `warmstart_ab.log` | warmstart_control 开始（磁盘 23G） |
| 07:50:48 | `warmstart_ab.log` | warmstart_control 结束 exit=0 |
| 07:51:33 | `warmstart_ab.log` | warmstart_oversample 开始（磁盘 22G） |
| 07:57:44 | `mech_dumps.log` | control 开始 dump（/home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_warmstart_control_seed20260724/checkpoints/step-000600） |
| 08:11:31 | `mech_dumps.log` | control dump 结束 exit=0 |
| 08:11:32 | `mech_dumps.log` | control duration_ratio 结束 exit=0 |
| 08:11:32 | `mech_dumps.log` | control mass_in_tolerance 结束 exit=0 |
| 08:49:27 | `warmstart_ab.log` | warmstart_oversample 结束 exit=0 |
| 08:49:27 | `warmstart_ab.log` | A/B 全部结束 |
| 08:49:44 | `mech_dumps.log` | treatment 开始 dump（/home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_warmstart_oversample_seed20260724/checkpoints/step-000600） |
| 08:56:44 | `c_arm.log` | C 开始（磁盘 22G，配置 slot=offset） |
| 09:02:54 | `mech_dumps.log` | treatment dump 结束 exit=0 |
| 09:02:55 | `mech_dumps.log` | treatment duration_ratio 结束 exit=0 |
| 09:02:55 | `mech_dumps.log` | treatment mass_in_tolerance 结束 exit=0 |
| 09:02:56 | `mech_dumps.log` | A/B 配对比较结束 exit=0 |
| 09:10:26 | `c_verdict.log` | 等 C 臂完成哨兵 |
| 09:55:17 | `c_arm.log` | C 结束 exit=0 |
| 09:55:26 | `c_verdict.log` | C 哨兵出现，开始 CPU 评测 |
| 10:07:58 | `c_verdict.log` | C dump 结束 exit=0 |
| 10:07:58 | `c_verdict.log` | C duration_ratio 结束 exit=0 |
| 10:07:59 | `c_verdict.log` | C mass 结束 exit=0 |
| 10:07:59 | `c_verdict.log` | C 配对稳健性 control vs C 结束 exit=0 |
| 10:08:00 | `c_verdict.log` | C 配对稳健性 validation_uniform vs C 结束 exit=0 |
| 10:08:00 | `c_verdict.log` | C 同步数屏幕结束 exit=0 |
| 16:48:46 | `duration_arm.log` | 开始（磁盘 22G，6000 步，timestamp_target=duration） |
| 16:58:02 | `duration_verdict.log` | 等结构臂完成哨兵 |
| 17:40:28 | `duration_trend.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_duration_target_seed20260724/checkpoints/step-0001000 |
| 17:41:02 | `duration_trend.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_duration_target_seed20260724/checkpoints/step-001000 |
| 17:58:08 | `duration_trend.log` | step 1000 探针 exit=0 |
| 17:58:08 | `duration_trend.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_duration_target_seed20260724/checkpoints/step-002000 |
| 17:59:32 | `start_kill.log` | 等 step2000 探针产物 |
| 19:10:32 | `start_kill.log` | 已按预注册判据停止臂 pid=299609 |
| 19:10:33 | `duration_arm.log` | 结束 exit=143 |
| 19:11:11 | `duration_trend.log` | step 2000 探针 exit=0 |
| 19:11:11 | `duration_trend.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_duration_target_seed20260724/checkpoints/step-003000 |
| 19:11:11 | `duration_trend.log` | 3000 无存档，跳过 |
| 19:11:11 | `duration_trend.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_duration_target_seed20260724/checkpoints/step-004500 |
| 19:11:11 | `duration_trend.log` | 4500 无存档，跳过 |
| 19:11:11 | `duration_trend.log` | 趋势探针全部结束 |
| 19:11:32 | `duration_verdict.log` | 哨兵出现（或失败标记），开始判决 |
| 19:13:22 | `absolute_control.log` | 对照臂开始（磁盘 22G，6000 步，absolute 语义） |
| 19:13:22 | `absolute_control.log` | 结束 exit=1 |
| 19:14:46 | `absolute_control.log` | 对照臂开始（磁盘 22G，6000 步，absolute 语义） |
| 19:22:50 | `matched_compare.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-000500 |
| 19:22:50 | `matched_compare.log` | 500 无存档，跳过 |
| 19:22:50 | `matched_compare.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-001000 |
| 19:22:50 | `matched_compare.log` | 1000 无存档，跳过 |
| 19:22:50 | `matched_compare.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-002000 |
| 19:22:50 | `matched_compare.log` | 2000 无存档，跳过 |
| 19:22:50 | `matched_compare.log` | 同步数对比链结束 |
| 19:23:30 | `matched_compare.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-000500 |
| 19:52:38 | `matched_compare.log` | step 500 对照导出 exit=0 |
| 19:52:38 | `matched_compare.log` | step 500 配对完成 exit=0 |
| 19:52:38 | `matched_compare.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-001000 |
| 20:01:52 | `stop_control.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-002000 |
| 20:27:48 | `matched_compare.log` | step 1000 对照导出 exit=0 |
| 20:27:48 | `matched_compare.log` | step 1000 配对完成 exit=0 |
| 20:27:48 | `matched_compare.log` | 等 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_absolute_control_seed20260724/checkpoints/step-002000 |
| 21:03:05 | `gpu_followups.log` | 等 GPU 空闲 |
| 21:21:01 | `gpu_followups.log` | 等 GPU 空闲 |
| 21:39:04 | `matched_compare.log` | step 2000 对照导出 exit=0 |
| 21:39:04 | `matched_compare.log` | step 2000 配对完成 exit=0 |
| 21:39:04 | `matched_compare.log` | 同步数对比链结束 |
| 21:59:06 | `absolute_control.log` | 结束 exit=143 |
| 22:00:24 | `gpu_followups.log` | 冒烟 exit=1 |
| 22:00:24 | `gpu_followups.log` | 冒烟失败 ⇒ 跳过全量（不产出可能误导的结论） |
| 22:00:42 | `gpu_followups.log` | 整首对比 exit=0 |

## 哨兵与标记文件（存在即说明那一步发生过）

| 文件 | 最后修改 | 内容 |
|---|---|---|
| `20260913_qwen_fa_r2_from_official.done` | 00:56:51 | 2026-09-14T00:56:51+08:00 |
| `20260914_qwen_fa_r2_concat20.done` | 06:50:06 | DONE 2026-09-14T06:50:06+08:00 |
| `20260914_qwen_fa_r2_concat20.done.failed` | 02:47:35 | FAILED 143 2026-09-14T02:47:35+08:00 |
| `START_KILL_TRIGGERED` | 19:10:32 | 0.0722 |
| `absolute_control.done.failed` | 21:59:06 | FAILED 143 |
| `absolute_control.done.failed.stale-from-1913-attempt` | 19:13:22 | FAILED 1 |
| `absolute_control.done.failed.stale-from-1913-attempt.note` | 19:23:30 | [2026-09-14T19:23:30+08:00] 这个 .failed 来自 19:13 那次因配置生成脚本语法错误而失败的启动；对照臂已于 19:16 重新启动并在跑。改名保留以避免误判。 |
| `absolute_control.stopped_after_verdict` | 21:56:39 | PLANNED_STOP by user-facing checkpoint 21:55 — §9 三个同步数对比点全部产出（step500/1000/2000），继续训练无科学用途；执行者：主会话（原 stop_control_after |
| `c_verdict.done` | 10:08:00 | DONE 2026-09-14T10:08:00+08:00 |
| `duration_target.done.failed` | 19:10:33 | FAILED 143 |
| `duration_verdict.done.failed` | 19:11:32 | SKIP arm-failed FAILED 143 |
| `gpu_followups.done` | 22:00:44 | DONE 2026-09-14T22:00:44+08:00 |
| `mech_control.done` | 08:11:32 | DONE 2026-09-14T08:11:32+08:00 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_warmstart_control_seed20260724/checkp |
| `mech_dumps.done` | 09:02:56 | DONE 2026-09-14T09:02:56+08:00 |
| `mech_treatment.done` | 09:02:55 | DONE 2026-09-14T09:02:55+08:00 /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_warmstart_oversample_seed20260724/che |
| `night_long_note_mechanism.done` | 02:05:26 | DONE 2026-09-14 02:05:26 |
| `night_stage_A.done` | 01:26:08 | DONE 2026-09-14 01:26:08 |
| `night_stage_L3_full.done` | 01:47:27 | DONE 2026-09-14 01:47:27 |
| `run_pred_vs_gt_new12000.done` | 01:20:39 | DONE 2026-09-14 01:20:39 |
| `run_pred_vs_gt_old750.done` | 22:54:51 | DONE 2026-09-13 22:54:51 |
| `run_pred_vs_gt_old750_v2.done` | 23:23:14 | DONE 2026-09-13 23:23:14 |
| `run_pred_vs_gt_old750_v3.done` | 23:53:02 | DONE 2026-09-13 23:53:02 |
| `warmstart_ab.done` | 08:49:27 | DONE 2026-09-14T08:49:27+08:00 |
| `warmstart_warmstart_control.done` | 07:50:48 | DONE warmstart_control 2026-09-14T07:50:48+08:00 |
| `warmstart_warmstart_lossweight.done` | 09:55:17 | DONE warmstart_lossweight 2026-09-14T09:55:17+08:00 |
| `warmstart_warmstart_oversample.done` | 08:49:27 | DONE warmstart_oversample 2026-09-14T08:49:27+08:00 |

## 怎么用

- 想知道"某条预注册规则有没有真的被执行"：看事件流里的 `触发`/`停止` 行与哨兵表是否对应；
- 想知道"某段结果是哪一步产出的"：按时间对齐日志名与 `results/by_run/` 下的目录时间戳；
- 本文件只反映启动器层面，科学判据的正文仍在各预注册与判决文件里。
