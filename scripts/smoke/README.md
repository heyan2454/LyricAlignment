# Smoke Scripts

`run_qwen_forced_aligner_smoke.py` 是当前标准的非指标 raw smoke 入口。

它负责：

- 每条样本独立执行、失败隔离和原子落盘；
- 仅在模型 ID、resolved revision、行为配置、音频 hash 和文本 hash 均一致且旧结果成功时跳过；
- 失败结果、损坏 JSON、模型/配置/输入变化时重新执行；
- 在逐样本 JSON 中记录模型身份、输入身份、结构诊断和分阶段 runtime；
- 在 `runs/smoke/<run_id>/` 写入轻量 `run_summary.json`、`command.txt` 和环境摘要；
- 完整 timestamps 仍保存在仓库外 output root。

结构诊断会区分：

- start/end 真正逆序；
- 负时长；
- 区间 overlap；
- token 间 gap；
- 越界和数量不匹配。

overlap 与 gap 是诊断信号，不自动等价于错误。当前不计算 GT metric，也不生成长音频；长音频构造纳入下一阶段数据清洗。
