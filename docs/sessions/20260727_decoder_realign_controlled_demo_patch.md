# 2026-07-27 Decoder × Realign 受控 Demo Patch

## 本次问题

新版 raw-guarded Demo 的听感明显弱于旧 `r2_vocal_windowed`，且 raw 与 guarded 几乎没有差异。
上传证据显示 341 个候选实际写回 0 次，全部停在 `no_conservative_anchor_pair`。进一步检查发现：

- A3/A4 将稳定度 `0.0` 通过 `value or inf` 转成 `inf`；
- 新旧运行同时更换过 checkpoint、分离人声、decoder 和 core；
- raw decoder 还控制串行歌词游标，局部误差会改变后续输入并级联；
- realign 使用 local raw 写回，而不是当前分支 decoder 后的结果；
- greedy forward compression 可把区间再次压成零时长。

## Patch 决定

1. 新 baseline 固定为 R2 + official decoder + 30 秒 core。
2. alternative 首先使用上次实验表现最好的 raw argmax。
3. O0/O1/R0/R1 均由 official 控制串行窗口归属和歌词游标。
4. raw end-to-end controller 只作为额外诊断，不进入四象限。
5. realign 使用对应分支 decoder 后的局部结果。
6. exact/+2、异常评分和边界变化检查覆盖完整 replacement span。
7. 只在 replacement span 内做 isotonic 局部约束，不整曲二次 forward compression。
8. 静音 core 跳过是所有分支的共同基本处理，不做消融。
9. 暂不实现 gap repair，`local_minimum_duration_sec=0`。
10. 默认只输出 mix-audio comparison，不输出 individual、vocal 视频或 mix 推理分支。

## 来源定位实验

### E0：四分支轨迹公平性

脚本硬检查 official 与 raw 分支的串行轨迹 hash。

- 通过：O0/R0 差异可以解释为 timestamp decoder + 其局部 merge 结果。
- 失败：仍有未冻结的控制变量，禁止评价 decoder。

### E1：纯 decoder

比较 O0 与 R0：同 checkpoint、同 vocal、同 30 秒窗口、同 official 轨迹。

- raw 平均误差更好且 collapse 不增加：raw 可作为 alternative。
- raw 平均更好但短字/P99/collapse 变差：上次主指标与 Demo 目标错配。
- raw 全面退化：上次 decoder 结果存在域差异或评测构造偏差。

### E2：raw 串行反馈

额外运行：

```bash
python scripts/demo/align_qwen_fa_raw_guarded_demo.py \
  ... \
  --decoder-kind raw \
  --serial-control-decoder-kind raw \
  --disable-realign
```

与 R0 比较：

- R0 正常、raw-e2e 坍塌：主要来源是 decoder 改变 cursor/后续歌词输入。
- 两者都坍塌：raw timestamp 本身不适合生产 Demo。
- 两者都正常：旧退化主要来自 checkpoint、separator 或其他代码漂移。

### E3：30 秒与 60 秒 core

固定 checkpoint、vocal、official decoder、realign off，只改 core。

- 仅 seam 附近小幅变化：窗口增多的正常代价。
- 大范围坍塌：30 秒下文本范围、cursor 或 commit 逻辑有问题。
- 基本不变：core 不是新版巨大退化的主要来源。

### E4：checkpoint

固定同一 vocal、official、30 秒、realign off，比较旧 step1000-seed3407 与新 step750-seed20260724。

- 新 checkpoint 广泛退化：模型权重是主要来源。
- 仅特定语种/高语速退化：训练域或 checkpoint 选择问题。
- 基本接近：继续检查 separator 和串行反馈。

### E5：separator

固定 checkpoint、official、30 秒、realign off，分别使用同歌 Spleeter 与 Demucs vocal。

- Demucs 更好：保留当前默认。
- Spleeter 更好：检查 Demucs 是否损伤主唱或保留伴唱。
- 歌曲依赖：后续应按分离质量做条件分析，而不是选单一平均结论。

### E6：realign 漏斗

比较 O0→O1、R0→R1，并另跑 A2 shadow。

- A4 少量执行、A2 大量 would-select 且真实改善：anchor gate 覆盖不足。
- A2 也无法改善：局部 Qwen 对自然困难段能力不足。
- decoder 后正确、local projection 后退化：局部约束仍有问题。
- local raw 错、official 正确：realign 必须保留二次 decoder。
- clean span 被改坏：safety gate 不足，不能扩大覆盖率。

## 指标口径

基本正确性与严重错误分开：

- 基本：boundary MAE、pair@80/160ms、song-macro、P50/P90/P95/P99、clean-span 退化。
- 严重：零时长、`<=80ms`、新增/修复 collapse、seam failure、最大误差。
- Realign 漏斗：detected、anchor、inference、agreement、decoded valid、projection valid、accepted。

不能用人工篡改最终 timestamp 的 easy collapse 作为主要有效性证据；主要结论应来自自然 serial failure，
人工扰动应从静音、窗口 seam、歌词多给/少给/错给、伴唱或主唱能量等输入侧产生。
