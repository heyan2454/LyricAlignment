
# Data Preparation

## 1. 外部存储原则

仓库只保存 manifest、schema、规则和轻量统计。真实音频、模型缓存、checkpoint、分离人声和大型预测放在服务器数据盘。

建议外部结构：

```text
<DataRoot>/lyricalign/
  raw/
  annotations/
  derived/
    audits/
    audio_normalized/
    character_alignment/
    synthetic_long/
    diagnostics/
  manifests/
  models/
  runs/
  checkpoints/
  cache/
```

不同版本通过 manifest 和 hash 关联，不覆盖原始文件。

## 2. vocal-only 音频合同

正式主输入只允许：

```text
vocal_source_type = native_vocal | official_vocal_channel | model_separated_vocal
```

对于模型分离人声，必须记录：

```text
separator_name
separator_version_or_checkpoint_hash
separator_config_hash
mixture_input_sha256
vocal_output_sha256
sample_rate
channels
conversion_command
tool_versions
```

原生人声、官方声道和模型分离人声可以共同用于研究，但必须保留来源字段并分层报告。

进入训练/正式评测前应冻结 `audio_contract_version`，记录：

- 原始路径与 SHA256；
- 转换后路径与 SHA256；
- 容器/编码、采样率、声道和样本数；
- 转换命令和工具版本；
- 是否发生裁剪、重采样或幅度处理。

默认候选为 mono 16 kHz WAV PCM16，但必须以模型 processor 和正式配置为准。第一版不默认做响度归一化、降噪或额外分离后处理。

## 3. manifest 主键与字段

使用 `dataset_id + item_id` 作为稳定标识。推荐字段：

```text
dataset_id
item_id
song_id
singer_id
audio_relpath
vocal_source_type
separator_identity
lyrics_raw
lyrics_normalized
annotation_relpath
language
duration_sec
split
annotation_level
annotation_source
length_source
source_item_ids
join_points_sec
content_hash
status
quality_flags
rule_versions
notes
```

路径使用相对路径，由 local path config 提供根目录。

## 4. 中文字符粒度

- 中文 annotation level：`character`；
- phoneme token 先组成 Mandarin syllable，再映射到字符；
- 每个字符保留 source phoneme/note indices、mapping method、confidence 和 flags；
- 原始歌词与规范化歌词必须有双向索引映射；
- 仅有 LRC 的数据不能直接作为主评测 GT；
- 为提高覆盖率不得伪造或无依据插值字符边界。

## 5. 长音频与长度来源

每个样本必须标记：

- `native_short`：原生短片段；
- `synthetic_concat`：同歌曲相邻片段按顺序拼接；
- `natural_long`：真实连续长歌声。

### Synthetic concat

- 只拼接同歌曲且顺序可验证的相邻片段；
- 保存 source item IDs、拼接顺序、接缝和可选静音；
- 字符时间戳按累计时长平移；
- 保留 seam mask，不能把接缝异常解释为自然歌声问题；
- 目标 bucket：20/30/60/120 秒；
- 同曲原片段、拼接样本必须继承同一 split。

### Natural long

真实连续长歌声优先作为 test-only，覆盖长间奏、拖音、重复歌词和歌词版本差异。MIR-1K 的 17 首人工字符标注整曲固定为 vocal-only OOD test。

## 6. 可恢复与覆盖策略

所有批处理入口必须：

- 原始数据只读；
- 临时文件写完并校验后 atomic rename；
- 输入/规则/输出身份一致时可跳过；
- 身份冲突时报错；
- 只有显式 `--overwrite` 才覆盖；
- 记录失败样本并允许重跑；
- 不把失败记录当作成功缓存。

## 7. 可追溯性

每次规范化、映射、拼接、切分、过滤和人工修订必须记录输入/输出 manifest、规则版本、命令、hash、执行时间、失败恢复方式和人工备注。
