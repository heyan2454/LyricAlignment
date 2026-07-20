# Environment Reproducibility

项目把“可安装依赖”和“某次运行的实际环境”分开记录：

- `pyproject.toml`：项目直接依赖和最低兼容范围；
- `requirements/qwen_smoke_server_known.txt`：2026-07-19 服务器 smoke 已知的关键版本；
- `scripts/environment/capture_environment.py`：在实际机器上记录 Python、CUDA、ffmpeg、包版本和 `direct_url.json`。

Qwen Forced Aligner 当时使用 Transformers 源码开发版。归档证据没有保存具体源码 commit，因此不能把 `5.15.0.dev0` 单独视为可复现锁定。下一次服务器运行前必须执行：

```bash
python scripts/environment/capture_environment.py \
  --out runs/smoke/<run_id>/environment_full.json
```

若 `transformers` 的 `direct_url.json` 中含有 `vcs_info.commit_id`，将该 commit 写入正式环境锁定或安装命令。若无法解析 commit，应在运行报告中显式标为未锁定，不能仅记录 `dev0` 版本号。
