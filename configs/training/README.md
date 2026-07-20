# Training Configs

保存 LoRA/PEFT smoke 与正式训练配置，包括数据版本、随机种子、优化器、checkpoint、resume 和显存相关开关。

- `qwen_fa_chinese_adaptation_plan.yaml`：当前中文分阶段训练设计；仅表达模块顺序，不是可直接运行配置。

模型训练接口、loss、实际模块名和标签构造核验前，不创建伪造的可运行参数。
