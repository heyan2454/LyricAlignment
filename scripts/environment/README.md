# Environment Scripts

`capture_environment.py` 记录当前 Python、关键包、包安装来源、VCS commit、CUDA/GPU 和 ffmpeg 信息。

它应在服务器正式 smoke、训练和评测前执行。开发版 Transformers 只有在记录具体 commit 后才可视为精确锁定。
