# Scripts

本目录保存可复现的薄入口；稳定、可测试的纯逻辑优先位于 `src/lyricalign/`。

当前主要分区：

- `assets/`：数据发现、模型下载与外部资产校验；
- `datasets/`：M4Singer、MIR-1K 与 synthetic-long 准备；
- `training/`：Qwen FA LoRA、恢复评估、120s 快速诊断入口；
- `evaluation/`：字符指标、长音频诊断、raw/fixed timestamp 审计与汇总；
- `demo/`：独立歌曲的串行分窗对齐、Spleeter 人声分离与 KTV 视频；
- `maintenance/`：轻量证据收集；
- `environment/`：环境、包来源和 archive 构建。

夜苏打 demo 与 120s 快速反馈的服务器执行说明见：

```text
docs/manual/qwen_fa_120_quick_feedback_and_yessoda_demo.md
```
