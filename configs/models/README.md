# Model Configs

本目录只记录模型身份、revision 策略、输入输出与阶段边界，不保存权重。

- `qwen_forced_aligner.yaml`：当前 raw smoke 主模型；
- 真实缓存路径写入 gitignored local asset config；
- 每次运行必须把 requested revision 和 resolved revision 写入逐样本结果与 run summary。
