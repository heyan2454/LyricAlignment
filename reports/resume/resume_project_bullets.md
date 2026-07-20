# Resume Project Bullets Draft

当前已有 Qwen Forced Aligner 短片段 raw smoke 和可复现基础设施实现，但尚无字符 GT、正式 metric、训练或论文结果。以下仅为后续候选结构，不能把计划项写成已完成经历。

## 当前可事实化描述

- 搭建中文歌声歌词强制对齐实验骨架，完成 Qwen3 Forced Aligner 官方推理接口封装，并在 M4Singer 短片段上验证音频—歌词输入可返回结构化字符时间戳。
- 建立模型 revision、输入 hash、配置 hash、失败恢复、分阶段 runtime 和轻量 run evidence 机制，支持可追踪的 raw smoke 执行。
- 审计并只读复用约 20 GB M4Singer 共享数据，避免跨项目重复存储；设计后续字符数据清洗与长短音频分型方案。

上述内容仍需在服务器使用 schema-v2 入口重跑后，再决定是否进入正式简历。

## 等待真实结果后补充

- 数据集、split 和真实长音频规模；
- 字符转换及人工复核数量；
- raw / LoRA 的真实配置；
- peak VRAM、训练时间和 checkpoint 策略；
- onset / offset、coverage 等正式指标；
- 典型 case、negative results 和结论强度。
