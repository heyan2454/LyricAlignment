
# Qwen Forced Aligner Raw Smoke

**Updated:** 2026-07-22  
**Metric:** none  
**Current status:** schema-v2 M4Singer short smoke completed

## Model and environment

- model ID: `Qwen/Qwen3-ForcedAligner-0.6B-hf`
- resolved revision: `c07281df297b9905d24a508279258cccf987a064`
- Transformers source commit: `7ea2320c76117e6742364808a666ef6f2fb40a67`
- Python 3.12.3, PyTorch 2.8.0+cu128, Transformers 5.15.0.dev0
- RTX 4080 SUPER, CUDA runtime 12.8

## Schema-v2 result

Run: `runs/smoke/20260721_m4singer_schema_v2_local_model/`

| Count | Result |
|---|---:|
| total | 5 |
| success | 5 |
| failed | 0 |

样本时长约 5.005–11.53 秒。每条结果保存模型身份、配置/输入 hash、外部输出 hash 和分阶段 runtime。首条含模型加载，后续 warm sample wall 约 0.14–0.15 秒；这些只描述当前设备与实现的 smoke runtime，不替代正式 benchmark。

## 已观察结构信号

预览中存在多个 `start_time == end_time` 的零时长字符，但现有 `warnings` 仍为空。下一次 raw baseline 必须增加：

- `zero_duration_count`；
- `near_zero_duration_count`；
- duration quantiles；
- 前后段零时长率；
- large-gap 和 late-drift 统计。

这说明调用链可用，但不能宣称字符边界质量良好。

## 允许结论

- 当前模型和适配器能在 5 条 M4Singer 短样本上完成调用并返回与输入字符数一致的结果；
- 服务器环境和核心身份已有轻量证据；
- 短样本 raw smoke 可以进入数据清洗和自动评测基础设施阶段。

## 禁止结论

- 无 GT smoke 不能给出准确率；
- 5–12 秒样本不能证明完整歌曲稳定；
- 不能根据 Qwen 输出删除或修正 GT；
- synthetic long 不能替代 MIR-1K natural-long OOD 结论。
