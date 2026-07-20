# Asset Module

当前资产能力主要由 `scripts/assets/` 的薄入口实现：

- 数据目录只读发现；
- 模型下载与缓存复用；
- 可恢复 OpenCpop 下载；
- 机器可读 inventory。

尚未建立独立的 Python asset package；在出现多个脚本共享且稳定的核心逻辑前，不为目录完整性提前抽象。所有脚本仍须遵循：不默认复制、删除、覆盖或修改外部数据。
