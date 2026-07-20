# Data Preparation

## 1. 外部存储原则

仓库只保存 manifest、schema、规则和轻量统计。真实音频、模型缓存、checkpoint、分离人声和大型预测放在服务器数据盘。

建议外部结构：

```text
<DataRoot>/lyric_alignment/
  raw/
  derived/
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

## 2. 统一音频契约

原始数据可以是不同格式，但进入训练/正式评测前应在数据清洗阶段统一模型输入，并记录：

- 原始路径与 SHA256；
- 转换后路径与 SHA256；
- 容器/编码、采样率、声道和样本数；
- 转换命令和工具版本；
- 是否发生裁剪、重采样或幅度处理。

当前建议目标为 mono WAV，并由正式配置冻结采样率和编码。smoke 封装通过 ffmpeg 临时解码到 mono 16 kHz float32，不等价于已经完成数据集格式统一。

## 3. manifest 主键与字段

使用 `dataset_id + item_id` 作为稳定标识。推荐字段：

```text
dataset_id
item_id
song_id
singer_id
audio_relpath
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
notes
```

路径使用相对路径，由 local path config 提供根目录。

## 4. 中文字符粒度

- 中文 annotation level：`character`；
- 英文备选 annotation level：`word`；
- 不接收 line-level 作为主研究标注；
- phoneme/syllable/note 到字符必须保留显式映射和 mapping status；
- 仅有 LRC 的数据不能直接作为主评测 GT。

## 5. 长音频与长度来源

长音频准备与字符转换在同一数据清洗阶段完成。每个样本必须标记：

- `native_short`：原生短片段；
- `synthetic_concat`：同歌曲相邻片段按顺序拼接；
- `natural_long`：真实连续长歌声。

### Synthetic concat 规则

- 只拼接同歌曲且顺序可验证的相邻片段；
- 保存 source item IDs、拼接顺序、接缝和可选静音；
- 字符时间戳按每段累计时长平移；
- 保留接缝标记，不能把接缝处异常解释为自然歌声问题；
- 目标长度可分为 20/30/60/120 秒 bucket；
- 同曲原片段、拼接样本必须继承同一 split，禁止跨 split 泄漏。

Synthetic concat 用于长度压力、训练补充和机制验证，但不能替代 natural long 的最终测试。

### Natural long 规则

真实连续长歌声优先作为 test-only，覆盖：

- 长间奏和静音；
- 一字长拖音；
- 重复歌词；
- 漏唱、加词或歌词版本不一致；
- 60–180 秒连续序列。

MIR-1K 只有在完整歌词严格对应时才能进入此类测试，且不加入训练。

## 6. 可追溯性

每次规范化、映射、拼接、切分、过滤和人工修订必须记录：

- 输入 manifest 版本；
- 规则/脚本版本和命令；
- 输出 manifest 版本；
- 变更字段；
- 输入/输出 hash；
- 执行时间；
- 失败恢复和覆盖策略；
- 人工复核者与备注（若有）。
