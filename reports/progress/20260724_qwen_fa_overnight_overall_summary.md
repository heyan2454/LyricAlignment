# Qwen Forced Aligner LoRA Overnight 整体总结

**日期：** 2026-07-24  
**状态：** 原 overnight 主流程完成；后续缺失评测补齐完成；当前没有必须重新训练的实验。

## 1. 本轮目标与实验口径

本轮围绕 Qwen3 Forced Aligner 0.6B，建立并执行了完整的歌词字符边界微调闭环：

- R0：原始模型，不训练；
- R1：只训练 `multi_modal_projector`；
- R2：训练 projector，并在 audio tower 上半层 attention 注入 LoRA；
- 使用冻结的 M4Singer train/validation/test 划分；
- MIR-1K 仅作为 vocal-only OOD test，不参与训练、选 checkpoint 或调参；
- checkpoint 以 M4Singer validation 的 `song_macro_boundary_mae_sec` 选择，越低越好；
- 另做约 20、30、60、150 秒的合成长音频诊断；
- 使用第二个 seed 检查 R2 结果是否稳定。

数据基础为 20,298 条 accepted M4Singer 弱监督样本；598 条 review-required 样本排除。MIR-1K OOD 包含 17 首歌曲、2,035 个字符。

## 2. 主结果

主指标为 **song-macro、缺失/非法结果受惩罚的字符边界 MAE**，单位为毫秒，越低越好。

| 配置 | Validation | M4Singer test | MIR-1K OOD | 说明 |
|---|---:|---:|---:|---|
| R0 raw | — | 251.391 | 97.108 | 未训练基础模型 |
| R1 projector-only，seed3407 | 55.649 | 90.775 | 44.007 | 与 R2 匹配训练预算 |
| R2 audio-LoRA，seed3407 | 46.734 | 79.590 | 42.557 | 正式选择 step 1000 |
| R2 audio-LoRA，seed20260724 | 47.160 | 80.920 | 40.459 | 正式选择 step 750 |

相对变化：

- R0 → R1：M4Singer test 改善 63.89%，MIR-1K OOD 改善 54.68%；
- R1 → R2 seed3407：validation 改善 16.02%，M4Singer test 改善 12.32%，MIR-1K OOD 改善 3.30%；
- 两个 R2 seed 的差异很小：validation 相差 0.425 ms，M4Singer test 相差 1.330 ms；MIR-1K 上 seed2 反而好 2.098 ms。

因此，当前最有力的实验结论是：

1. **projector-only 已经贡献了最大部分的收益**，说明原始模型的音频表示与当前歌声/标注任务之间存在明显接口适配问题；
2. **audio tower 上半层 attention LoRA 在 projector-only 基础上继续带来稳定的域内收益**；
3. MIR-1K 上的额外收益较小，但没有出现 OOD 退化；
4. 两个完整 R2 seed 的结果接近，说明 R2 结果不是单一随机种子的偶然现象。

## 3. 第二个 seed 与 checkpoint 选择

seed20260724 完成 1,110 optimizer steps，训练耗时约 5,734.7 秒，即 95.6 分钟。各 validation checkpoint：

| Step | Validation MAE |
|---:|---:|
| 250 | 50.985 ms |
| 500 | 47.511 ms |
| 750 | **47.160 ms** |
| 1000 | 48.372 ms |
| 1110 | 48.412 ms |

因此正式选择 step 750。选择过程只使用 validation，没有使用 M4Singer test 或 MIR-1K OOD。

seed3407 的历史自动选择为 step 1000，MAE 46.734 ms；terminal step 1110 后来记录到 46.634 ms，但没有进入当时的周期性 checkpoint 选择流程。正式 test/OOD 仍沿用先前冻结的 step 1000，以避免事后改变评测协议。该差异很小，但说明 terminal checkpoint 应在后续统一纳入选择候选。

## 4. 长音频诊断

合成长音频来自冻结的 M4Singer test，同歌手、同歌曲相邻片段拼接，因此是诊断集，不是独立 benchmark。

| 实际平均时长 | R0 | R1 | R2 |
|---:|---:|---:|---:|
| 22.35 s | 248.581 | 74.180 | **59.255** |
| 33.05 s | 246.980 | 75.258 | **54.019** |
| 48.12 s | 228.250 | 92.549 | **72.068** |
| 152.50 s | 101.615 | **51.831** | 102.825 |

排除拼接点附近 0.5 秒字符后，约 152.5 秒档仍为 R1 46.215 ms、R2 90.923 ms，因此不能只归因于拼接接缝。

结论：

- R2 在约 22–48 秒范围内稳定优于 R1；
- 在约 150 秒范围出现明确负面结果，R2 显著退化并落后于 R1；
- 最长档只有少量歌曲，且 R0 在该档反而比短档更好，说明歌曲组成和难度分布存在混杂，不能直接声称误差随时长单调上升；
- 当前模型还不能被描述为已解决完整长歌对齐。

## 5. 执行稳定性与失败恢复

最终结果均成功完成，补跑的四个评测返回码均为 0：

- seed3407 R2 MIR-1K OOD；
- seed2 terminal validation；
- seed2 M4Singer sealed test；
- seed2 MIR-1K OOD。

本轮暴露并修复了三类工程问题：

1. MIR-1K 原始 manifest 不包含 `timestamp_class_ids`，错误地直接送入训练 collator，导致 `KeyError`；随后改用确定性生成的 Qwen FA labels；
2. processor 的 `timestamp_segment_time=80` 为毫秒，曾被当作秒使用；修正为除以 1000；
3. evaluator 在离线模式下解析到不完整 Hugging Face snapshot，缺少基础模型权重；后续总控脚本改为验证完整固定 revision、本地绝对路径、权重大小和 hash 后再离线加载。

补跑脚本保留失败目录、不覆盖已验证结果，并能在结果身份匹配时安全跳过，恢复性基本达到预期。

## 6. 修复与归档状态

本归档已经完成以下修复：

- `valid_only_boundary_mae_sec` 使用同一有效集合计算分子和分母；
- valid / invalid / missing 状态互斥；
- zero-duration 属于 invalid，不再同时计为 missing；
- `song_coverage` 改为“歌曲中至少有一个有效字符”；
- 新增 `complete_song_coverage`；
- seed2 请求限制值 `0` 与实际样本数分开记录；
- terminal checkpoint 自动进入 validation 评测和 best-checkpoint 选择；
- evaluator identity 显式记录 checkpoint step 与 metric schema；
- 一次性补跑入口验证完整 base-model snapshot 与 MIR-1K 派生标签身份。

十九组保存了逐字符 reference/prediction 的结果已使用
`character_interval_metrics_v3_tolerant` 重算。所有重算的
`song_macro_boundary_mae_sec` 均保持不变，因此主结论不受辅助指标修复影响。
原始 v2 文件保留，修正版单独保存。

seed2 terminal validation 的辅助指标尚未重算，因为上传的重算包没有包含该
validation split 的 reference rows；其主指标和 checkpoint 选择已经验证。

## 7. 长音频补充审计

约 152.5 秒 R2 退化主要集中在一个 Tenor-6《寻人启事》样本：模型在约
120–140 秒区间出现连续的数秒提前漂移，之后部分恢复。

- R2 pooled penalized MAE：115.085 ms；
- 移除该单个样本后：64.534 ms；
- R1 移除同一样本后：48.929 ms。

因此，该负面结果包含一个强离群崩溃，同时还存在较小的残余 R2 劣势。它更像
局部 alignment-path collapse，而不是均匀的 timestamp 量化误差。当前仍不能
断言误差随时长单调增加。

## 8. 当前结论强度

**较强结论：**

- projector-only 提供主要收益；
- matched-budget R2 在 seed3407 上进一步改善 validation/test；
- 两个完整 R2 seed 的 M4Singer test 结果接近；
- 两个 R2 seed 均未在 MIR-1K OOD 上相对 R1 退化；
- 训练、恢复、terminal validation、test/OOD 和证据路径已形成闭环。

**中等结论：**

- R2 的 OOD 追加收益较小，且 MIR-1K 仅 17 首歌曲；
- 约 150 秒失败主要由单个 late-sequence collapse 驱动，但移除后仍有残余差距。

**尚不能下结论：**

- R2 对自然完整长歌是否普遍退化；
- R2-R1 差值是否跨 seed 稳定，因为没有第二个完整 R1；
- collapse 来自 context length、重复歌词、弱标注、timestamp class，还是 synthetic join；
- 增大 LoRA scope/rank 或训练时长是否有效。

## 9. 下一步

优先运行 dominant-outlier 的 full-context 与 overlapping-window 对照：

```text
0–90 s
90–120 s
120–140 s
140 s–end
full 150 s
```

如果窗口推理恢复而 full-context 失败，应优先发展 chunked/windowed inference；
如果同一区域在窗口中仍失败，则优先检查局部音频、重复歌词和弱监督边界。
在该机制被隔离前，不建议直接扩大 LoRA 或延长训练。

## 10. AI 协作与反思记录

本轮 AI 协作在可恢复编排、validation-only checkpoint 选择、失败证据保留和补跑
入口整合方面有效。主要不足是 schema、时间单位、模型缓存完整性和 metric 逻辑
没有在最初 preflight/单元测试中被充分覆盖，导致后续补救。

这些缺口现在已转化为代码检查和回归测试：输入标签 schema、固定 revision 权重、
时间单位、prediction state partition、terminal validation 与 archive manifest 都应
在执行前或归档时自动验证。

## 最终判断

本轮已经完成首轮 Qwen Forced Aligner LoRA 可行性闭环并达到可归档状态：

> projector 适配解决了主要任务域差异；top-half audio-attention LoRA 在此基础上
> 提供稳定但相对较小的追加收益。该收益在短到中等长度和两个 R2 seed 上成立；
> approximately 150-second diagnostic 暴露出一个严重 late-sequence collapse。
> 下一阶段应优先隔离和修复长上下文机制，而不是扩大训练规模。
