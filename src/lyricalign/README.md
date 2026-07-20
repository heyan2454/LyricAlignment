# lyricalign

当前阶段只允许建立两个最小模块：

- `assets/`：外部资产 registry、路径解析和只读校验；
- `inference/`：Qwen Forced Aligner 的薄推理封装和统一输出 schema。

本轮不实现：

- dataset conversion / adapter；
- curation；
- character boundary generation；
- metrics；
- training / LoRA；
- 大型 pipeline 框架。

核心逻辑进入 `src/lyricalign/`，`scripts/` 仅保留命令入口。当前目录仍是待 Codex 实现的结构，不表示代码已完成。
