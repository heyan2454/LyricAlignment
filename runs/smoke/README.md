# Smoke Runs

每次标准 smoke 在此保存轻量证据索引：

```text
runs/smoke/<run_id>/
  command.txt
  environment_summary.json
  run_summary.json
```

`run_summary.json` 保存模型 revision、配置 hash、样本状态、结构诊断、runtime 定义、外部结果路径和外部 JSON SHA256。完整 timestamps、音频和大日志仍位于仓库外。

历史 2026-07-19 smoke 发生在该机制完善前，因此本包只保存诚实的 legacy 摘要；未来运行应由脚本自动生成完整轻量索引。
