
# Data Curation Protocol

## 1. 目标

数据治理用于构建可追溯的歌声—歌词训练与评测数据，不等同于简单删除异常样本。当前第一目标是形成可信的高置信字符级训练子集，而不是强制接受所有 M4Singer 样本。

## 2. 流程

```text
raw inventory
-> schema/audio audit
-> lyrics normalization
-> phoneme -> syllable -> character mapping
-> duplicate and leakage audit
-> quality flags
-> A/B/C quality tier
-> stratified manual spot check
-> frozen manifests
```

raw aligner diagnostics 仅用于模型行为和人工 case 筛查，不能单独决定样本删除。

## 3. 自动检查范围

### 音频

- 文件存在且可解码；
- 时长、采样率、声道、编码；
- 静音占比、极低音量、削波；
- 音频 hash 和近重复；
- `vocal_source_type` 与 separator identity；
- 音频时长与标注累计时长一致性。

### 歌词与映射

- 编码与空文本；
- 原文、规范化文本和双向索引；
- 全半角、标点、空格、数字、中英混排、括号和衬词；
- phoneme/syllable/character 显式映射；
- slur、重复韵母、特殊非歌词 token；
- 字符边界来源、置信度和异常原因。

### 一致性与泄漏

- 文本长度与音频时长异常；
- 精确重复、近重复和切片包含；
- 同曲不同版本、翻唱和歌手分布；
- train / validation / test 交叉泄漏；
- 同曲 native short 与 synthetic concat 跨 split。

## 4. 质量状态

推荐主层级：

- `A_high_confidence`：可进入主训练；
- `B_review_or_robustness`：待复核或后续鲁棒训练候选；
- `C_invalid`：明确不可用且原因可复查。

映射状态单独保存，例如：

```text
accepted_exact
accepted_rule_based
review_special_token
review_ambiguous_syllable
review_text_phoneme_mismatch
review_duration_mismatch
rejected_metadata_invalid
```

模型失败、低 coverage、零时长预测或大 gap 不能单独触发 `C_invalid`。

## 5. M4Singer mismatch taxonomy

至少区分：

```text
punctuation_or_space
special_non_lyric_token
mandarin_syllable_parse_failure
slur_or_repeated_vowel
latin_or_digit
lyrics_phoneme_count_mismatch
duration_metadata_mismatch
audio_metadata_invalid
unknown
```

`unknown` 必须报告比例并持续细分，不能成为逃避分析的大桶。

## 6. 人工抽检

不要求全量人工标注。按 accepted_exact、accepted_rule_based、各 mismatch 类、不同歌手/歌曲/时长和 synthetic seam 分层抽样，记录：

```text
accept
correctable
ambiguous
wrong
review_notes
```

由此估计自动规则精度，而不是只看覆盖率。

## 7. 同音伪歌词副实验

同音同调随机常用字、异调、错音和乱序文本属于后续鲁棒性/低标准标注实验。它们不得替换主训练的正确歌词，也不得用于修改冻结 GT。生成必须固定 seed，保存逐字符替换映射。
