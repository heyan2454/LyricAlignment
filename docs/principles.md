# Project Principles

本文件记录长期稳定的项目原则。阶段状态、临时阻塞和单次实验结果不得写入这里。

## 任务原则

- 主任务是 `audio + known Mandarin lyrics -> character timestamps`。
- 中文统一以 character-level 为研究与评测粒度。
- 当前不推进英文路线；未来若加入英文 word-level，必须单独配置、单独聚合、单独报告。
- 项目不保留 line-level 输出、GT、匹配策略或指标。
- audio-to-text 可作为辅助研究，但不得与 oracle-text forced alignment 混为同一任务。

## 数据原则

- 原始数据不可覆盖；任何规范化、字符边界转换、切分、过滤均生成新版本和 manifest。
- 原始歌词、规范化歌词、音素/音节标注、字符序列及其映射必须可追溯。
- 数据清洗采用 `accepted / review_required / rejected` 分层，不使用不可解释的一次性删除。
- 自动质量信号用于筛查，不单独作为删除依据。
- 重复样本、同曲不同版本、切片包含关系和歌手泄漏需要显式审计。
- split 必须以 song 为最小隔离单位；不得把同一歌曲的 utterance 随机分到不同 split。
- train / validation / test 冻结后严格隔离；官方 test 永不参与开发决策。

## 模型与实验原则

- 先建立 raw foundation-model baseline，再进行分阶段域适配。
- 第一适配阶段完整训练多模态投影层与时间戳分类头；第二阶段再评估 audio tower LoRA；language model LoRA 不是当前前置条件。
- 强 baseline 不是项目自身贡献；贡献应来自可验证的数据转换、数据治理、域适配、评测和误差分析。
- raw 与训练后模型比较必须保持数据 split、输入音频、文本规范化、切片策略、后处理和 metric schema 一致。
- 所有合理假设必须标记为假设；未验证的模型能力、显存占用和数据字段不得写成事实。
- 每次 run 必须可追溯到 manifest、配置、模型 revision、环境、命令、随机种子和输出位置。

## 存储与仓库原则

- Git 管理代码、配置、文档、轻量 manifest、摘要指标和可复现入口。
- 数据集、模型缓存、checkpoint、大型日志、逐样本预测和中间音频放在外部数据盘。
- 仓库内不得复制同一大型产物；使用外部路径、hash 和 run manifest 建立引用。
- checkpoint 默认只保留 `best`、`last` 和少量有明确用途的 milestone。
