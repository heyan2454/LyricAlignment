# Scripts

本目录保存可复现的薄入口；稳定核心逻辑优先位于 `src/lyricalign/`。

当前已实现：

- `assets/`：AST 数据发现、Qwen 下载、OpenCpop 可恢复下载、外部资产校验；
- `smoke/`：revision-aware Qwen Forced Aligner 非指标 smoke 与轻量证据；
- `environment/`：实际环境、包来源和 VCS commit 捕获。

字符转换、正式 metric、训练和 LoRA 入口仍推迟到数据清洗和 schema 冻结之后。
