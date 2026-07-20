# Asset Scripts

已实现的薄入口：

- `discover_ast_datasets.py`：只读发现 AST 外部数据；
- `download_qwen_model.py`：下载或复用 Qwen 模型缓存；
- `download_opencpop.py`：对用户确认的官方直链执行可恢复下载；
- `verify_assets.py`：输出机器可读资产摘要。

关键行为：

- `verify_assets.py` 会先创建输出目录，并对缺失关键资产返回非零状态；
- `download_opencpop.py` 校验 HTTP 206、`Content-Range`、最终大小和可选 SHA256；
- 服务器忽略 Range 并返回 200 时会安全重写 `.part`，不会把完整文件追加到旧 partial；
- HTML 登录/授权页面会被拒绝，不会伪装成数据压缩包；
- OpenCpop 当前仍受官方授权流程阻塞，脚本修复不代表数据已经获取。
