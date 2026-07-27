> **Current status (2026-07-27):** this four-branch shared-raw comparison is retained for controlled historical diagnosis. The active follow-up is the official-controlled B0–B3 and inline shadow pipeline in `docs/manual/inline_realign_smoke_formal.md`. Rendering now defaults to a direct one-pass official O0/O1 review; raw 2×2 is opt-in.

# Decoder × Realign 对照 Demo 使用说明

## 目标

该入口用于在同一 R2、同一 vocal 输入和同一全曲窗口规划下比较：

| 分支 | 时间戳 decoder | Realign |
|---|---|---|
| O0 | official | 关闭 |
| O1 | official | 开启 |
| R0 | raw argmax | 关闭 |
| R1 | raw argmax | 开启 |

默认只生成一个 `2×2` comparison，音轨使用 `mix.wav`。改进期不默认生成 individual、vocal-audio 视频或 mix 推理分支。

## 当前受控设计

- 模型：同一 R2 checkpoint；
- 推理音频：同一 `vocals.wav`；
- 目标 core：30 秒；
- 左右上下文：10 秒；
- 串行 planner：raw argmax 运行一次；
- official/raw 在相同的窗口、歌词切片、ownership 和 cursor 上重放；
- realign 使用各分支 decoder 后的局部结果；
- replacement 只在局部 span 内做 bounded isotonic projection；
- 不做整首歌曲二次 forward compression；
- gap repair 暂未启用。

## 静音感知全曲切窗

切窗前先从完整 vocal 上计算持续活动/持续静音区间，并生成：

```text
alignments/r2_decoder_realign/window_plan.json
```

规则：

1. 长前奏不再创建空 core。若开头存在足够长的持续静音，首个 ownership core 从静音结束处开始；左声学上下文仍可覆盖前奏末端。
2. 所有持续静音区间保留在 `silence_intervals`，既用于切窗，也作为 realign 的稳定边界证据。
3. 名义 30 秒边界会在安全范围内优先吸附到附近静音区。
4. 若最后一个 core 过短：
   - 只有一个前窗：直接将尾窗与前窗合并；
   - 至少两个前窗：删除短尾窗，把其时长均分给前两个窗口。
5. 四个分支共享同一份 `window_plan.json`。

默认参数：

```text
target core                 30 s
silence boundary minimum     0.8 s
strong silence anchor        1.5 s
boundary search radius       6 s
leading silence minimum      2 s
short-tail threshold        18 s
minimum ordinary core       12 s
```

这些是当前 smoke 参数，不是最终冻结值。

### 尾窗均摊示例

初始边界：

```text
10, 40, 70, 80
```

对应 `30s + 30s + 10s`。尾窗 10 秒小于 18 秒，改为：

```text
10, 45, 80
```

最终两个窗口都是 35 秒。

## 静音 anchor 与 realign

静音区不会被当成歌词或凭空生成 timestamp。实现只会：

- 保存静音的起止、时长和强度；
- 将静音两侧最近的非折叠字符标记为 `silence_anchor_before/after`；
- 强静音相邻字符可作为 A4 anchor 的稳定证据；
- local replacement 仍须通过 exact/+2、一致性、结构和边界变化 gate。

因此静音信息增强边界，但不等于 gap repair。

## 运行

```bash
cd /home/hyan/LyricAlignment

python scripts/demo/run_decoder_realign_comparison_batch.py \
  /root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/伊卡洛斯奔向月亮.mp3 \
  --lyrics /root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/伊卡洛斯奔向月亮.txt \
  --language Chinese \
  --reuse-prepared-suffix _qwen_fa \
  --r2-checkpoint \
  /root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750 \
  --force-align \
  --force-render
```

默认只生成：

```text
videos/comparisons/compare_official_raw_realign_2x2_mix.mp4
decoder_realign_demo.mp4
```

显式传入 `--render-pairs` 才额外生成双联 comparison。

## 小体积证据收集

脚本必须使用项目绝对路径，或从项目根目录运行：

```bash
PYTHON_BIN=/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  /home/hyan/LyricAlignment/scripts/demo/collect_decoder_realign_evidence.sh \
  /root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/伊卡洛斯奔向月亮_qwen_fa_decoder_realign \
  --output /root/autodl-tmp/AST_storage/Data/lyricalign/伊卡洛斯_decoder_realign_evidence.tar.gz \
  --max-total-mib 6
```

收集器排除音频、视频、模型权重、完整 raw logits 和完整日志。超限时按以下顺序降级：

```text
全部紧凑字符
→ 异常字符
→ 严重异常字符
→ 仅 summary
```

证据中包含压缩后的 `window_plan`、`windows.jsonl`、分支结构统计和 realign 漏斗。

## 必查结果

1. `window_plan.json` 中首个 core 是否从长前奏结束附近开始；
2. `tail_adjustment.action` 是否符合尾窗规则；
3. raw planner 首窗是否仍异常推进歌词；
4. O0 与 R0 在相同 ownership 下的结构差异；
5. O1/R1 的 `candidate_count`、实际 local inference 数、拒绝原因和写回数；
6. realign 前后是否新增零时长、逆序或 clean-span 退化。
