# Configs

本目录保存可复现配置，不保存数据、权重或运行产物。

- `assets/`：外部数据、模型缓存和 smoke 样本的可提交模板；真实路径使用 gitignored local 文件。
- `models/`：模型来源、revision、输入输出与阶段范围。
- `paths/`：通用外部路径模板。
- `curation/`、`metrics/`、`training/`、`experiments/`：后续阶段设计；本轮不得据此提前实现字符转换、metric 或训练。

进入子目录前先读其 `README.md`。配置中的未确认字段必须显式标为 `to_verify`，不能填入猜测值。
