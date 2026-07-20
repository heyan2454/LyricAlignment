# Dataset Split and Leakage Protocol

## 1. 基本单位

split 的最小隔离单位是 song，不是 utterance、segment 或音频切片。同一首歌的所有片段必须属于同一 split。

## 2. 当前数据角色

- M4Singer：自定义 song-level train / validation；
- Opencpop official train：train / in-domain validation；
- Opencpop official test：final in-domain test；
- MIR-1K character-aligned subset：final OOD test。

## 3. 官方 test 封存

测试集不得用于：

- 文本规范化规则选择；
- 数据清洗阈值；
- LoRA 层级、rank 或学习率选择；
- checkpoint 选择；
- 音频切片或后处理调节；
- 失败样本驱动的迭代修复。

若发现 test schema 无法解析，只允许修复通用解析错误，并必须在不查看指标的条件下对所有 split 使用同一修复。

## 4. validation 设计

建议同时保留：

- `val_opencpop_indomain`：从 Opencpop official train 按 song 划出；
- `val_m4singer_multispeaker`：从 M4Singer 按 song 划出，并尽量维持 singer、voice part 和时长分布。

训练前固定一个 primary checkpoint 选择规则。可选方案：

1. 两个 validation 的 per-song macro 平均；
2. 指定 M4Singer validation 为 primary，Opencpop validation 仅诊断；
3. 指定 Opencpop validation 为 primary，但必须说明其单歌手偏置。

不得在看到 final test 后更换规则。

## 5. 跨数据集泄漏检查

至少使用：

- 标准化 title / artist；
- normalized lyrics 的精确 hash；
- 字符 n-gram 相似度；
- 音频 hash；
- 音频指纹或 embedding 近重复；
- 完整歌曲与切片包含关系。

对于同一歌曲的不同翻唱版本，默认视为潜在 song leakage。是否允许保留必须在实验前冻结，并分别说明“严格 song-OOD”与“允许 cover overlap”的口径。
