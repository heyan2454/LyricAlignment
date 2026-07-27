# Next Execution Plan

**Date:** 2026-07-28  
**Goal:**运行含 Demo 的补充 smoke/formal，真正测试 GT-oracle local realign、局部自动异常、稳定段辅助窗口推进、未来歌词扩展和 fail-closed incomplete；所有 Demo align 完成后再统一 render。

## S0 — 输入检查

```bash
cd /home/hyan/LyricAlignment
source scripts/demo/inline_realign_env.sh
validate_inline_realign_inputs
```

必须确认：

- Qwen forced-aligner snapshot 和 R2 step-750 完整；
- M4Singer labels/audio 可读；
- MIR-1K `selection.jsonl` 中 development 和 spare 可读；
- Demo 根目录中至少有一首歌词、媒体和 prepared vocal 可配对。

当前 wrapper 使用 `--require-demo`。Demo 未发现应立即修正路径或命名，不再接受一个实际没有 Demo 的 formal。

## S1 — Smoke

```bash
bash scripts/demo/run_inline_realign_smoke.sh
```

阶段必须按以下顺序出现：

```text
01_manifest
02_experiment
03_render_demo_after_all_alignments
04_summarize
05_collect
```

先检查：

```bash
cat "$OUT_ROOT/input_audit.json"
cat "$OUT_ROOT/pipeline_complete.json"
cat "$OUT_ROOT/followup_analysis_summary.md"
```

Smoke 通过条件：

- manifest 同时包含 Demo、MIR-1K、M4Singer native 和 synthetic-long；
- Demo 渲染日志晚于 experiment summary；
- 每首 Demo 只存在 `items/<id>/render/official.mp4`，没有新建第二套歌曲输出目录；
- 自动候选和 GT oracle 候选分别统计；
- 至少 GT oracle 能产生实际 local inference，不能再次全部停在 anchor 搜索前；
- stable-window assistance 包含 cursor 建议，信息性差异窗口会触发主动重跑；
- forced expansion 有 +25%/+50% 结果；
- incomplete guard 生成明确标注的前缀结果；
- evidence 小于默认 8 MiB。

若部分 item 失败，保留输出并重跑同一命令；不要删除整个目录。

## S2 — Smoke 判读

### 2.1 GT-oracle local realign

优先看：

- `local_inference_attempted_count`；
- exact/+2 一致数；
- GT 改善数；
- `would_write_count`；
- 失败原因是否仍集中为缺稳定段。

若 oracle 仍完全无法执行，先修稳定段搜索或输入构造，不进入 formal。

### 2.2 自动候选

确认自动 target 是局部连续范围，不再从整窗第一个字开始。检查候选是否主要对应：

- 零时长；
- 同边界堆叠；
- 已提交核心尾部堆积；
- 有人声但零推进。

未来歌词停在输入末端不应单独触发 realign。

### 2.3 稳定段辅助分窗

比较：

- 基线 cursor 与 GT 理想 cursor；
- 稳定段建议 cursor 与 GT 理想 cursor；
- 改善/持平/恶化数量；
- 主动重跑后稳定前缀是否复现；
- 重跑结果是否制造新坍缩。

### 2.4 强制未来歌词扩展

检查 +25%/+50% 下原有区域：

- 最大和 p90 边界移动；
- 零时长变化；
- GT 变化；
- 高语速样本与普通样本差异。

### 2.5 Demo

最后才看 `items/<demo>/render/official.mp4`。Demo 用于听感、尾部和传播，不据此选择 GT 阈值。

## S3 — Formal development

Smoke 通过后：

```bash
bash scripts/demo/run_inline_realign_formal.sh
```

默认使用：

```text
Demo 12
MIR-1K development + spare 16
M4Singer native 24
M4Singer synthetic-long 12
```

MIR-1K held-out 仍禁止使用。

Formal 报告必须分开：

- Demo；
- MIR-1K natural；
- M4Singer native；
- M4Singer synthetic-long；
- automatic detector；
- GT oracle；
- stable-window assistance；
- forced expansion；
- planner divergence；
- constructed incomplete。

## S4 — 决策门

- **GT oracle 改善且 exact/+2 稳定：**进入单窗口自动写回实验；
- **Oracle 有能力但自动召回低：**继续改检测器，不改 local inference；
- **Oracle 也不改善：**停止放宽 stable segment，研究 official 解码和局部输入；
- **稳定段 cursor 明显优于基线且主动重跑稳定：**实现 shadow serial planner；
- **cursor 更接近 GT但重跑更差：**保留为校验信号，不直接控制分窗；
- **+50% 明显破坏原区、+25% 稳定：**建立软扩展上限和扩展前后检查；
- **raw/official 分歧少：**只分析分歧病例，不再大规模重复 B3；
- **尾部失败保护下游正常：**下一阶段实现自然触发 incomplete/最后两窗回退；
- **Demo 仍弱而 GT 数据正常：**优先检查真实伴唱、高语速、歌词文本和长距离串行传播。

## S5 — Held-out

只有规则和写回策略冻结后运行一次：

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_heldout_20260728 \
  bash scripts/demo/run_inline_realign_formal.sh --include-heldout
```

看到 held-out 后不得继续调整阈值。

Canonical guide:

```text
docs/manual/inline_realign_smoke_formal.md
docs/sessions/20260728_inline_realign_followup_experiments.md
```
