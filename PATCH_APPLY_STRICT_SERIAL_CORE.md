# 严格串行核心分窗补丁

本补丁将 demo 的 `windowed` 模式改为严格串行核心分窗。它不改变 `full` 模式，不改变 R0/R1/R2 的模型与检查点加载方式。

## 新机制

- 核心区固定为相邻的 60 秒区间：`[0,60)`、`[60,120)`、`[120,180)`……
- 每窗音频在核心区左右各延伸 10 秒；延伸区只提供声学上下文。
- 一个字符按其对齐起点归属核心区。
- 起点位于当前核心区、但结束时间跨过右边界的字符，完整归当前窗口。
- 后一个窗口从该跨界字符的下一个字符开始输入歌词，不再输入跨界字符。
- 已提交歌词不会在后续窗口中重新输入，也不会参与跨窗候选竞争。
- 当前窗口只有在观察到核心边界之后的下一个字符，或已经覆盖全部剩余歌词时，才接受该窗口结果；文本不够时会扩大未来歌词并重跑同一窗口。
- 取消 windowed 模式中的全局累计单调压平。核心接缝只允许默认不超过 0.16 秒的小修正；更大冲突直接失败并保留诊断现场。
- 旧的 `character_backtrack`、按整首时长估计歌词起点、逐字符跨窗 winner 选择均不再用于 windowed 模式。

## 应用

在补丁压缩包所在目录执行：

```bash
unzip -o LyricAlignment_strict_serial_core_window_patch_20260726.zip -d /home/hyan
cd /home/hyan/LyricAlignment
```

## 重新运行完整夜苏打 demo

推荐强制重新生成 windowed/full alignment 与视频，避免查看旧产物：

```bash
cd /home/hyan/LyricAlignment

FORCE_ALIGN=1 \
STAGE=align \
bash scripts/demo/run_yessoda_serial_demo.sh

KARAOKE_FONT='Noto Sans CJK SC' \
FORCE_RENDER=1 \
STAGE=render \
bash scripts/demo/run_yessoda_serial_demo.sh
```

虽然 `schema_version` 和 request hash 已变化，理论上旧 alignment 会自动失效，但第一次验证仍建议使用 `FORCE_ALIGN=1`。

## 重新运行 03:05 / 03:12 独立尾段

```bash
cd /home/hyan/LyricAlignment

FORCE_ALIGN=1 \
STAGE=align \
bash scripts/demo/run_yessoda_tail_windowed.sh

KARAOKE_FONT='Noto Sans CJK SC' \
FORCE_RENDER=1 \
STAGE=render \
bash scripts/demo/run_yessoda_tail_windowed.sh
```

## 结果检查

新的 windowed alignment 中应看到：

```json
"window_policy": "hard_core_audio_context_v2"
```

每个字符会记录：

- `owner_window_index`
- `owner_core_start_sec`
- `owner_core_end_sec`
- `ownership_rule: character_start_in_core`
- `seam_repaired`
- `seam_repair_sec`

每个 `window_trace` 会记录：

- `cursor_before` / `cursor_after`
- `committed_character_start` / `committed_character_end`
- `next_window_character_start`
- `boundary_character`
- `next_character`
- 候选文本扩展的每次 `attempts`

对于 windowed 模式，`cross_window_repaired_character_count` 应保持为 `0`。若接缝冲突超过允许范围，程序会直接报错，不再把后续多句压到同一时间点。

## 可调参数

默认值已经固定为本次确认口径：

```text
core_sec = 60
left_context_sec = 10
right_context_sec = 10
```

仅在诊断时建议调整：

```text
future_character_ratio = 1.35
minimum_forward_characters = 64
future_line_padding = 1
max_candidate_expansions = 4
boundary_start_tolerance_sec = 0.32
seam_tolerance_sec = 0.16
```

## 验证范围

已完成：

- Python 编译检查；
- 两个 shell 入口的 `bash -n`；
- 15 项相关测试（含 Spleeter 质量门禁回归）；
- 纯逻辑串行集成测试，验证边界跨字不会重新输入给后窗。

完整项目测试在本地收集阶段仍会因缺少 `pypinyin` 而中止；这与本补丁无关，相关 demo 定向测试均已通过。

未完成：服务器上的真实 R0/R1/R2 GPU 推理。模型、LoRA 检查点和实际分离人声不在本地执行环境中，因此真实 demo 结果需要在服务器按上述命令重新生成。
