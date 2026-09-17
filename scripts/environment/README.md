# Environment Scripts

`capture_environment.py` 记录当前 Python、关键包、包安装来源、VCS commit、CUDA/GPU 和 ffmpeg 信息。

它应在服务器正式 smoke、训练和评测前执行。开发版 Transformers 只有在记录具体 commit 后才可视为精确锁定。

## 打包入口

- `build_archive.py`：从 Git tracked 快照构建 ZIP，提供稳定根目录、逐文件 SHA-256 manifest、
  新鲜 manifest 写入与成员唯一性自检；支持 `--exclude-root`（可重复）与 `--verify-only`。
- `pack_lyricalignment.sh`：主入口，打包**完整** tracked 快照（含 `docs/`、`results/`、`reports/`）。
- `pack_lyricalignment_portable.sh`：便携源码变体，额外排除模型/备份/`runs`/`results`/`reports`/
  `docs/sessions`、`docs/archive`、`docs/manual`、`docs/status` 与 training/research/evaluation 脚本，
  只用于对外分享的瘦身包。其 exclude 清单是 2026-08-08 口径（2026-09-17 归位自仓库外散落的
  `/home/hyan/pack_lyricalignment.sh`，见 `docs/sessions/20260821_two_repo_planning_audit/README.md`），
  目录结构此后有演进，启用前需按当前结构复核。

两者调用方式相同：`bash scripts/environment/<script>.sh <NOTE>`，输出到 `$OUTPUT_DIR`（默认 `/home/hyan`）。
