# Tests

当前测试覆盖：

- overlap 与真正 start/end 逆序的区分；
- revision/config/input-aware resume；
- asset inventory 输出父目录创建；
- HTTP 服务器忽略 Range 时安全重启下载而非追加。

运行：

```bash
python -m pytest -q
```

归档构建时结果为 `5 passed`。这些测试不加载 Qwen 权重，也不能替代服务器模型 smoke。

后续数据清洗阶段再增加字符映射、manifest、泄漏检查和 metric fixture 测试。
