# Runs

仓库内只保存轻量 run 事实：命令、配置/输入身份、环境摘要、失败清单和外部 artifact index。大型预测、raw response、checkpoint 和详细日志放在外部数据盘。

当前已有：

- `smoke/20260719_m4singer_short_legacy/`：旧 smoke 的 report-level 摘要；
- 标准新 run 应位于 `smoke/<run_id>/`，由 smoke 脚本自动生成。

未来可增加 `curation/`、`raw_baseline/`、`training/` 和 `evaluation/`，但目录存在不代表对应实验已完成。
