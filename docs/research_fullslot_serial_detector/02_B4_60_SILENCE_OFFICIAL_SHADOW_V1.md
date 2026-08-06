# `b4-60-silence-official-shadow-v1` 冻结对照

## 1. 定位

该 profile 用于复现此前 `B4_60_silence_official` 的主要行为，并附加 **shadow-only local realign**。它是历史对照，不是新的自动修复路线。

`shadow_only` 可以生成候选、诊断与“假如写回”的离线评价，但不得改变：

- baseline alignment rows；
- committed prefix；
- canonical cursor；
- 下一窗口输入；
- window trajectory；
- 最终实际输出。

## 2. 冻结字段

```ini
core_sec = 60
left_context_sec = 10
right_context_sec = 10

decoder_kind = official
serial_control_decoder_kind = same

silence_aware_window_plan = true
strict_silence_boundary_plan = false
compress_silence_audio = false
skip_silent_windows = true

silence_boundary_min_sec = 0.8
strong_silence_anchor_sec = 1.5
silence_boundary_search_sec = 6.0
leading_silence_min_sec = 2.0
tail_min_core_sec = 18.0
minimum_core_sec = 12.0

local_realign = shadow_only
actual_writeback = 0
```

这些字段与当前 `B4_60_silence_official` 代码定义基本一致：60 秒 core、silence snap、official 同路控制、跳过纯静音窗，并使用当前默认静音和短尾窗参数。

## 3. 需要同时冻结的隐含默认值

为避免以后代码默认值改变导致“同名不同实验”，还应解析并写入：

```ini
silent_active_ratio_max = 0.01
silent_peak_margin_db = 3.0
silent_min_sustained_sec = 0.40

startup_vocal_preroll_sec = 2.0
startup_minimum_forward_characters = 24

minimum_forward_characters = 64
future_character_ratio = 1.35
future_line_padding = 1
max_candidate_expansions = 4

timestamp_segment_sec = 0.08
next_input_backtrack_units = 0
```

若实际代码或运行合同中的默认值不同，以运行时 resolved profile 为准，但必须记录差异，不能静默继承。

## 4. Shadow 硬断言

正式运行必须验证：

```text
actual_writeback_count == 0
baseline_alignment_hash_before_shadow == baseline_alignment_hash_after_shadow
baseline_trajectory_hash_before_shadow == baseline_trajectory_hash_after_shadow
baseline_committed_prefix_hash_before_shadow == baseline_committed_prefix_hash_after_shadow
baseline_cursor_trace_hash_before_shadow == baseline_cursor_trace_hash_after_shadow
```

任何断言失败，该 run 不得作为 B4 对照。

## 5. 成本口径

分别统计：

```text
baseline_forward_count
baseline_wall_time
shadow_forward_count
shadow_wall_time
total_forward_count
total_wall_time
```

与新 Base 比较历史 B4 效率时，只使用 baseline 部分；shadow 成本单独报告。

## 6. 数据覆盖

该对照应运行于：

- M4 formal 配对子集；
- MIR fixed-transfer 子集；
- 全部自动发现的 test demo；
- 重复段专项中的共享输入子集。

它不参与 detector 阈值选择，也不与所有 mutation 强度、工作点和 route 形成全排列。

## 7. YAML 状态

`configs/research_fullslot_serial_detector/b4_60_silence_official_shadow_v1.yaml` 是声明式冻结 profile。当前 patch 不修改执行代码，因此在实现 agent 完成参数接线、resolved-profile 导出和上述断言前，不应声称该 YAML 已可直接驱动现有 pipeline。
