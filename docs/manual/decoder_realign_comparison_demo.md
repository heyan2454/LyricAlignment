# Decoder × Realign 对照 Demo 使用说明

## 目标与固定条件

该入口用于改进 Demo 期间的受控比较，不替代旧 `r2_vocal_windowed` 归档结果。
四个分支固定使用：

- 同一份 R2 checkpoint；
- 同一份分离人声；
- 30 秒 core、10 秒左右上下文；
- 静音 core 跳过；
- official decoder 控制窗口归属和下一窗歌词游标；
- comparison 视频统一使用 `mix.wav`；
- 不生成 individual 和 vocal-audio 视频；
- 不启用 gap repair。

四个分支：

| ID | 时间戳 decoder | Realign |
|---|---|---|
| O0 | official | 关闭 |
| O1 | official | 开启 |
| R0 | raw argmax | 关闭 |
| R1 | raw argmax | 开启 |

R0/R1 只替换时间戳 decoder，复用 official 的串行控制轨迹。脚本会比较两次运行的
窗口/歌词游标轨迹；不一致时直接失败，避免把 decoder 与后续输入轨迹混在一起。

## 运行

单首中文歌曲：

```bash
bash scripts/demo/run_decoder_realign_comparison_batch.sh \
  /home/hyan/Data/lyricalign/test/Chinese/四季折之羽.mp3 \
  --language Chinese \
  --r2-checkpoint /path/to/fixed-r2-checkpoint
```

媒体和歌词不同名：

```bash
bash scripts/demo/run_decoder_realign_comparison_batch.sh /data/song.mp4 \
  --lyrics /data/lyrics.txt \
  --language Chinese \
  --r2-checkpoint /path/to/fixed-r2-checkpoint
```

按语言分别批量运行，不要用一个语言参数混跑整个多语言 test 根目录：

```bash
bash scripts/demo/run_decoder_realign_comparison_batch.sh \
  /home/hyan/Data/lyricalign/test/Chinese \
  --language Chinese
```

测试目录已经有旧 `_qwen_fa/work/audio/` 时，可以直接复用，不复制 WAV，也不重新分离：

```bash
bash scripts/demo/run_decoder_realign_comparison_batch.sh \
  /home/hyan/Data/lyricalign/test/Chinese \
  --language Chinese \
  --reuse-prepared-suffix _qwen_fa
```

也可用 `_qwen_fa_raw_guarded`，但应确保该目录中的 `vocals.wav` 正是本轮希望固定的分离输入。

## 输出

默认目录：

```text
<歌曲名>_qwen_fa_decoder_realign/
├── alignments/r2_decoder_realign/
│   ├── branches/
│   │   ├── official_no_realign/
│   │   ├── official_realign/
│   │   ├── raw_no_realign/
│   │   └── raw_realign/
│   ├── comparison_manifest.json
│   └── complete.json
├── videos/comparisons/
│   ├── compare_official_raw_realign_2x2_mix.mp4
│   ├── compare_official_realign_off_vs_on_mix.mp4
│   ├── compare_raw_realign_off_vs_on_mix.mp4
│   └── compare_official_vs_raw_no_realign_mix.mp4
├── decoder_realign_demo.mp4
├── batch_plan.json
├── batch_manifest.json
└── render_manifest.json
```

没有 `videos/individual/`。用于 composite 的临时 panel 位于 `work/render_panels/`，成功后默认删除。

## Realign 实现

局部推理仍保存 raw 与 branch-decoded 两层，但写回候选使用当前分支 decoder：

```text
局部 Qwen 推理
→ official 或 raw argmax decoder
→ exact 与 matched +2 在完整 replacement span 上比较
→ replacement span 内 bounded isotonic projection
→ safety gate
→ 只替换局部区间
```

不会对整首歌再次执行 forward compression。`--local-minimum-duration-sec` 默认为 `0`，
因此本 patch 没有自行定义 gap repair 或最低字时长分配策略。

## Anchor gate 诊断

A3/A4 中 `raw_decoded_movement_max_sec=0.0` 曾被 `value or inf` 错判为无限大，导致稳定
anchor 全部失败。该错误已修复。

生产四分支使用 A4。要测试“realign 无法修复”还是“A4 阻止了推理”，使用旧的单分支入口做
A2 shadow，不写回最终结果：

```bash
python scripts/demo/align_qwen_fa_raw_guarded_demo.py \
  --lyrics /data/song.txt \
  --audio /data/vocals.wav \
  --out-root /data/probes/song_a2_shadow \
  --r2-checkpoint /path/to/fixed-r2-checkpoint \
  --decoder-kind official \
  --serial-control-decoder-kind official \
  --anchor-policy-family A2 \
  --realign-shadow-only \
  --core-sec 30
```

重点比较：

- `candidate_count`；
- `no_conservative_anchor_pair` 数量；
- `would_select_count`；
- exact/+2 disagreement；
- decoder 前后结构异常；
- local projection 后是否重新产生折叠。

## 小体积证据收集

```bash
python scripts/demo/collect_decoder_realign_evidence.py \
  /home/hyan/Data/lyricalign/test \
  --output /home/hyan/Data/lyricalign/decoder_realign_evidence.tar.gz \
  --max-total-mib 12
```

收集器排除音频、视频、模型权重、完整日志和 shadow-row 大对象。若压缩包超过上限，会依次降级：

1. 全部字符的紧凑字段；
2. `<=80ms`、被 compression 或 realign 修改的字符；
3. 仅零时长/压成零/realign 修改等严重字符；
4. 仅 summary。

每次降级都会写入 `collection_manifest.json`，不会静默超出大小上限。

可将 A2/A4 shadow 目录一并纳入（可重复传入）：

```bash
python scripts/demo/collect_decoder_realign_evidence.py \
  /home/hyan/Data/lyricalign/test \
  --probe-root /home/hyan/Data/lyricalign/probes/song_a2_shadow/alignments/r2_raw_guarded \
  --output /home/hyan/Data/lyricalign/decoder_realign_evidence.tar.gz \
  --max-total-mib 12
```
