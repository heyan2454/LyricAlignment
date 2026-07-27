# 2026-07-27 Demo / Realign / Decoder 诊断与静音感知切窗归档

## 1. 本次会话目标

本次工作的核心不是单纯追求一版“看起来更好”的 Demo，而是将以下变量拆开并形成可复现实验：

- official decoder 与 raw argmax decoder；
- realign 关闭与开启；
- 30 秒 core 下的串行窗口、歌词 cursor 和 forward compression；
- 长前奏、静音 core、静音边界与短尾窗；
- realign 是没有运行、被 gate 阻止、局部推理失败，还是 splice 后重新失败。

用户要求新的可视化固定为 `official/raw × realign off/on` 四象限，默认只渲染一个 2×2 comparison。

## 2. 初始现象

用户实际试听发现：

- 新 raw-guarded Demo 明显不如旧 `r2_vocal_windowed`；
- 被挤压到极短或零时长的字符反而更多；
- raw 与 guarded 肉眼/听感差异很小；
- 所有 vocal 分支输出视频错误地使用了 vocal 音轨；
- 长前奏歌曲从开头就容易快速提交大量歌词，随后错误累计；
- raw argmax 全曲相对 official 正常，但仍有少数长坍塌。

## 3. 证据审查与关键发现

### 3.1 Realign 实际没有运行

第一批证据中 8 首歌共检测到 341 个候选，但实际写回为 0。所有候选均在局部推理前以：

```text
no_conservative_anchor_pair
```

结束。

因此当时不能得出“realign 无法修复”，只能得出“realign 没有真正执行”。

进一步定位到 A3/A4 gate 的实现错误：

```python
value or math.inf
```

会将合法且最稳定的 `0.0` movement 误判为 `inf`，导致稳定 anchor 全部失败。该问题已修正。

### 3.2 新旧 Demo 不只是 core 或 decoder 不同

旧 `r2_vocal_windowed` 与新 raw-guarded 运行曾同时混入：

- 不同 R2 checkpoint；
- Spleeter 与 Demucs 不同 vocal；
- official 与 raw decoder；
- 60 秒与 30 秒 core；
- 不同串行 cursor/ownership 轨迹；
- realign 实际未运行。

因此之前的听感差异不能归因于单一变量。

### 3.3 Forward compression 是显著的二次坍塌来源

证据显示 raw/selected 阶段已经有大量非正时长或重叠，forward compression 又将更多字符压成零时长。其规则只保证“不逆序”，不保证正时长：

```text
start = max(predicted_start, previous_end)
end   = max(predicted_end, start)
```

所以困难段的错误可能从“重叠/逆序”转化为“结构合法但零时长”。

### 3.4 Official decoder 的首窗坍塌是串行级联

《伊卡洛斯奔向月亮》的首个 30 秒 core 没有歌词，但输入音频为 0–40 秒，首个可靠人声约在 37.84 秒。旧 planner 仍一次输入约 130 字。official decoder 随后出现：

- 前 128 字压到 0 秒；
- 一个字符跨越约 0–63.52 秒；
- 首窗直接提交 129 字；
- 下一窗从字符 129 开始，错误持续累计。

30 秒并非天然比 60 秒差，而是 30 秒把长前奏单独形成空 core，暴露了旧 planner 不允许“当前 core 合法提交 0 字”的缺陷。

### 3.5 Raw argmax 更适合 planner，但仍需区分输出 decoder

raw 首窗可以正确提交 0 字，因此不会立即推进 cursor。上次 decoder 实验中 raw argmax 也是平均表现最好的方案。

最终决定：

- raw argmax 只运行一次，冻结窗口、歌词切片、ownership 和 cursor；
- official/raw 在相同 accepted windows 上重放时间戳；
- O0/O1 与 R0/R1 共享窗口规划，而不是共享某个 decoder 的最终 timestamp。

这使 O0 与 R0 的差异更接近纯 decoder 差异，同时避免 official 首窗坍塌污染四个分支。

## 4. 设计演进

### 4.1 第一版四象限

最初设计为：

| 分支 | Decoder | Realign |
|---|---|---|
| O0 | official | 关闭 |
| O1 | official | 开启 |
| R0 | raw | 关闭 |
| R1 | raw | 开启 |

曾尝试让 official 控制所有分支轨迹，但这会把 official 的异常单调投影传播到 raw 分支。该设计被否定。

### 4.2 各 decoder 独立轨迹

随后曾让 official/raw 各自控制轨迹。这样更接近两个生产系统，但 O0 与 R0 的变化不再是纯 decoder，而包含后续歌词输入级联。

该设计保留为 end-to-end 诊断思想，但不作为当前四象限的因果主比较。

### 4.3 当前设计：shared raw planner

当前实现：

```text
raw argmax planner 一次
→ 冻结 accepted windows / lyric slices / ownership / cursor
→ official timestamp replay
→ raw timestamp replay
→ 各自 realign off/on
```

目的：

- 允许长前奏的首窗合法提交 0 字；
- 不让 official 的异常时间戳控制未来输入；
- 保证 O0/R0 使用相同窗口与字符归属；
- 保留 official 作为正式 baseline decoder，raw 作为 alternative。

## 5. Realign 当前实现

Realign 流程：

```text
自然异常检测
→ anchor pair
→ exact local inference
→ matched +2 local inference
→ 当前分支 decoder
→ 完整 replacement span 一致性检查
→ replacement span 内 bounded isotonic projection
→ non-GT safety gate
→ 局部写回
```

已修正：

- `0.0 → inf` anchor bug；
- local realign 不再固定使用 raw 写回；
- exact/+2 比较覆盖完整 replacement span；
- 仅局部约束，不做整首二次 forward compression；
- 默认最低字符时长仍为 0，未提前引入 gap repair。

当前未知：

- 修复 gate 后，真实 local inference 的成功率；
- 未修复候选是因为 Qwen 仍失败、decoder 失败、agreement 失败，还是 splice/safety gate 失败；
- gap repair 是否必要。

## 6. 静音感知全曲窗口规划

### 6.1 为什么改成全曲规划

逐窗“发现空窗再跳过”无法解决：

- 首窗输入仍可能包含长静音前缀；
- 名义 30 秒边界可能切在持续发声中；
- 静音虽然被跳过，却没有作为稳定边界保留；
- 贪心移动边界可能留下过短尾窗。

因此先在完整 vocal 上生成并冻结 `window_plan.json`。

### 6.2 当前算法

1. 从 vocal 能量构建持续活动 mask；
2. 将持续非活动区间提取为 `silence_intervals`；
3. 若开头存在长静音，ownership 从静音结束处开始；
4. 以 30 秒生成名义边界；
5. 在安全搜索半径内优先吸附到静音区中部；
6. 检查最后一个 core；
7. 若尾窗过短：
   - 只有一个前窗：直接合并；
   - 至少两个前窗：删除尾窗，将其时长均分给前两个窗；
8. 四分支复用同一 plan；
9. 所有静音区继续作为 realign anchor 证据。

### 6.3 尾窗规则

若边界为：

```text
[..., A, B, C, END]
```

尾窗时长：

```text
T = END - C
```

当 `T` 小于尾窗门槛时，删除 `C`，并将 `B` 移到：

```text
B' = B + T / 2
```

得到：

```text
[..., A, B', END]
```

前两个窗口各增加 `T/2`。若总共只有“前窗 + 尾窗”，直接合并为一个窗口。

### 6.4 静音 anchor

静音不生成虚构歌词 timestamp。实现保留：

- silence ID；
- 起止时间；
- 时长；
- normal/strong 强度；
- 静音两侧最近非折叠字符。

强静音相邻字符可绕过普通置信度/overlap gate，作为 A4 稳定 anchor，但仍禁止使用 collapsed/compressed 字符。

## 7. 实验设计、目的、预期结果与解释

### E0：窗口规划 smoke

目的：确认窗口规划本身不再制造空首窗与短尾窗。

检查：

- 长前奏歌曲的 `active_span_start_sec`；
- 第一 core 是否从持续人声附近开始；
- `tail_adjustment.action`；
- 每个 core 时长；
- 静音 interval 是否完整保留。

预期与解释：

- 首窗从起唱附近开始：长前奏问题被正确处理；
- 仍从 0 开始：活动检测或 leading-silence 条件失败；
- 尾窗被均摊/合并：规则生效；
- 尾窗仍很短：plan 参数或边界吸附之后的再平衡存在问题。

### E1：O0 与 R0 基本正确性

目的：比较相同窗口轨迹下 official 与 raw decoder。

指标：

- 零时长、`<=80ms`；
- forward-compression 新增 collapse；
- pair@80/160ms（有 GT 时）；
- song-macro boundary MAE；
- P50/P90/P95/P99；
- clean-span 退化。

预期与解释：

- raw 基本正确性更好且严重错误更少：raw 可继续作为 alternative；
- raw 平均更好但 tail/collapse 更差：上次主指标与 Demo 目标错配；
- official 在共享 planner 后仍大面积归零：official decoder 本身不适合这类窗口输出；
- official 恢复正常：之前主要是 official 控制 cursor 的级联问题。

### E2：Realign 漏斗

目的：区分“没运行”和“运行后修不好”。

记录：

```text
detected
→ anchor available
→ exact completed
→ +2 completed
→ decoder structural valid
→ exact/+2 agree
→ local projection valid
→ safety accepted
→ written back
```

预期与解释：

- anchor coverage 显著增加但仍无写回：局部推理或后续 gate 是主因；
- exact/raw 错、official decoded 对：local decoder 必需；
- decoder 后正确、projection 后折叠：局部约束算法有问题；
- O1/R1 修改 clean span：safety gate 不足；
- natural failure 修复率低：不能以人工 timestamp collapse 的 easy case 证明方案有效。

### E3：静音 anchor 价值

目的：验证强静音边界是否提高 realign 的保守 anchor coverage，而非增加误修。

比较：

- 普通 A4 anchor pair 数；
- 含 silence evidence 的 anchor pair 数；
- local inference 数；
- accepted repair 数；
- 静音附近误修改数。

预期与解释：

- coverage 增加且 clean 区不退化：静音 anchor 有效；
- coverage 增加但大量误修：silence promotion 过强；
- coverage 不变：字符时间本身无法定位静音两侧，后续可能需要虚拟边界设计。

### E4：30 秒与旧 60 秒 baseline

目的：确认剩余差异来自窗口长度、模型/分离输入，还是旧实现。

必须固定：

- checkpoint；
- vocal 文件；
- decoder；
- realign off；
- 文本规范化；
- commit/metric schema。

预期与解释：

- 仅 seam 小幅变化：30 秒可作为默认；
- 仍广泛退化：文本预算、ownership 或短窗上下文不足；
- 30 秒更稳：长窗内部路径漂移是主要问题。

## 8. 当前实现文件

新增：

```text
src/lyricalign/demo/window_planning.py
```

主要修改：

```text
scripts/demo/align_qwen_fa_serial_demo.py
scripts/demo/align_qwen_fa_decoder_realign_comparison.py
scripts/demo/run_decoder_realign_comparison_batch.py
scripts/demo/collect_decoder_realign_evidence.py
scripts/demo/collect_decoder_realign_evidence.sh
scripts/demo/align_qwen_fa_raw_guarded_demo.py
src/lyricalign/demo/raw_guarded.py
src/lyricalign/demo/realign_diagnostics.py
tests/test_decoder_realign_comparison_patch.py
```

默认 rendering 仍仅输出一个 2×2 comparison。

## 9. 验证状态

已完成：

- 长前奏静音起点单元测试；
- 尾窗均摊测试；
- 单前窗直接合并测试；
- 强静音相邻 anchor 测试；
- shared raw planner / official/raw replay 测试；
- replacement-span isotonic 约束测试；
- 小体积 evidence fallback 测试；
- focused Demo/realign/decoder 测试集通过。

未完成：

- 当前环境无真实 Qwen/R2 GPU 权重，未进行实际模型推理；
- 尚未获得 v4 服务器运行后的 realign 漏斗；
- 尚未确认静音检测参数对弱主唱/伴唱残留的鲁棒性；
- gap repair 仍未设计或实现。

## 10. Negative results 与被否决方案

1. **将 official 轨迹共享给 raw**：official 首窗坍塌会污染四个分支，否决。
2. **official/raw 各自控制轨迹作为主因果比较**：会混入后续歌词输入差异，仅保留为端到端诊断。
3. **只跳过静音 core**：不能解决长静音前缀、静音边界保留和短尾窗，替换为全曲规划。
4. **立刻使用 gap repair**：尚不清楚 realign 是被阻止还是能力不足，暂缓。
5. **人工直接压缩正确 timestamp 作为主要实验**：属于 easy case，仅适合作为结构 smoke。
6. **整首歌曲 realign 后二次 forward compression**：可能把局部正确结果再次传播并压坏，否决。

## 11. 下一步执行

优先只跑一首具有长前奏和明显坍塌的歌曲：

```bash
cd /home/hyan/LyricAlignment
python scripts/demo/run_decoder_realign_comparison_batch.py \
  /root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/伊卡洛斯奔向月亮.mp3 \
  --lyrics /root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/伊卡洛斯奔向月亮.txt \
  --language Chinese \
  --reuse-prepared-suffix _qwen_fa \
  --r2-checkpoint /root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750 \
  --force-align --force-render
```

首先检查 `window_plan.json`，再试听 2×2。若窗口规划正确，才继续评价 O0/R0 与 O1/R1。

收集：

```bash
PYTHON_BIN=/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  /home/hyan/LyricAlignment/scripts/demo/collect_decoder_realign_evidence.sh \
  /root/autodl-tmp/AST_storage/Data/lyricalign/test/Chinese/伊卡洛斯奔向月亮_qwen_fa_decoder_realign \
  --output /root/autodl-tmp/AST_storage/Data/lyricalign/伊卡洛斯_decoder_realign_v4_evidence.tar.gz \
  --max-total-mib 6
```

## 12. AI 协作与依赖状态

本次 AI 协作完成了：

- 对证据包和代码调用链的逐层审查；
- 区分 detector、anchor gate、local inference、decoder、splice 和 forward compression；
- 识别 `0.0 → inf` bug；
- 识别 official 首窗单调投影导致的 cursor 级联；
- 设计 shared raw planner；
- 实现静音感知全曲切窗、尾窗均摊和静音 anchor；
- 增补测试、手册、证据收集与归档记录。

理解依赖：

- 当前结论依赖用户提供的真实试听、日志和工作目录；
- 没有真实 GPU 推理结果时，只能确认实现逻辑与测试，不能宣称 Demo 已改善；
- 后续结论必须基于同 checkpoint、同 vocal、同 window plan 和一致 metric schema。
