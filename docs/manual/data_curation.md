# Data Curation Protocol

## 1. 目标

数据治理用于构建可追溯的歌声—歌词训练与评测数据，不等同于简单删除异常样本。

## 2. 流程

```text
raw manifest
-> audio validity checks
-> lyrics normalization
-> duplicate and leakage audit
-> raw-aligner diagnostics
-> quality flags
-> accepted / review_required / rejected
-> manual spot check
-> curated manifest
```

## 3. 自动检查范围

### 音频

- 文件存在且可解码；
- 时长、采样率、声道；
- 静音占比、极低音量、削波；
- 音频 hash 和近重复特征；
- mix 与可选 vocal stem 的来源对应关系。

### 歌词

- 编码与空文本；
- 原文与规范化文本均保留；
- 简繁、全半角、大小写、标点、空格、数字和中英混排；
- 括号、衬词、重复标记和实际演唱内容差异；
- 中文字符序列、拼音/音素序列及其显式映射。

### 一致性与泄漏

- 文本长度与音频时长异常；
- 精确重复、近重复和切片包含；
- 同曲不同版本、翻唱和歌手分布；
- train / validation / test 交叉泄漏。

### raw aligner 诊断

- token coverage；
- missing / extra token；
- 单调性；
- 负时长、零时长、异常短时长；
- 大片未对齐；
- 前后段漂移；
- token 映射失败。

## 4. 状态规则

- `accepted`：自动规则通过，或经人工确认可用；
- `review_required`：存在可疑信号，需要人工或第二种方法复核；
- `rejected`：有明确、可解释且可复查的不可用原因。

模型失败、低 coverage 或异常时间戳不能单独触发 `rejected`。

## 5. 推荐输出

每个样本至少记录：

```yaml
item_id: sample_id
status: review_required
rule_version: curation_v1
quality_flags:
  - possible_lyrics_mismatch
metrics:
  duration_sec: null
  silence_ratio: null
  alignment_coverage: null
manual_review:
  reviewed: false
  decision: null
  notes: null
```

原始诊断可放外部数据盘；仓库仅保留 schema、摘要统计和小型示例。
