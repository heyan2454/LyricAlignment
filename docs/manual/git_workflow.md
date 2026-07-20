# Git Workflow

## Remote

```text
git@github.com:heyan2454/LyricAlignment.git
```

用户报告服务器到 GitHub 的 SSH 连接已经建立。该事实不等于仓库已经初始化或推送成功。

## 首次初始化建议

```bash
git init
git branch -M main
git remote add origin git@github.com:heyan2454/LyricAlignment.git
git add .
git commit -m "Initialize LyricAlignment research structure"
git push -u origin main
```

若当前目录已经存在 `.git` 或 remote，先检查：

```bash
git status
git remote -v
git branch --show-current
```

不得重复初始化或覆盖已有历史。

## Git 管理边界

允许提交：

- 代码、配置、文档；
- 轻量 manifest 和 schema；
- 环境摘要、run manifest 和汇总指标；
- 小型测试 fixture。

禁止提交：

- M4Singer、Opencpop、MIR-1K 音频与下载包；
- Hugging Face cache；
- checkpoint 和 optimizer state；
- 大型逐样本预测、特征和日志；
- 私密绝对路径、token、SSH key 或账号信息。

首次 push 前需运行大文件审计，并检查 `.gitignore` 是否覆盖本地外部路径。
