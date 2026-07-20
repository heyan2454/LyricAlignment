# 合作者文档解读与项目重定向

## 1. 合作者项目原始目标

合作者文档中的项目更接近：

```text
本地媒体 + 本地歌词 -> 时间戳对齐 -> 卡拉 OK 字幕 -> FFmpeg 视频
```

当前项目只继承其中与音频—歌词对齐、输入记录和中间产物可追溯有关的部分，不继承字幕展示和视频生成目标。

## 2. 原始工作流

```text
media -> MediaInspector -> media_input.json
lyrics -> LyricsLoader -> normalized_lyrics.json
media_input -> AudioPreprocessor -> alignment_audio.json
normalized_lyrics + alignment_audio -> Alignment -> alignment.json
alignment.json -> subtitle / render products
```

可用于当前项目的前半段是：

```text
media + lyrics
-> normalized lyrics
-> selected alignment audio
-> model alignment output
```

## 3. 可继承的结构思想

### 歌词输入和规范化

可继承 `.txt` / `.lrc` 输入解析和 `normalized_lyrics.json` 的中间产物思想，但需要改造成：

- 保留原始歌词；
- 生成中文字符或英文单词序列；
- 记录规范化规则版本；
- 记录 original text ↔ normalized token 的映射；
- 不把歌词分段直接当作研究标注单位。

### 媒体探测

`media_input.json` 可用于记录：

- 音频路径和 hash；
- 可解码性；
- 时长、采样率、声道；
- 音频/视频来源；
- 数据版本。

该模块可扩展为数据治理中的音频合法性检查。

### 对齐音频选择

`alignment_audio.json` 区分原始音频和实际送入模型的音频，这一设计可保留。若以后比较 mix 与 vocal stem，需要明确：

- stem 生成模型和版本；
- 输入音频 hash；
- 采样率和时长是否变化；
- stem 是否只是实验变量，而非默认增强。

### 对齐策略和统一输出

合作者文档中存在：

```text
heuristic
qwen
qwen_forced_alignment
auto
```

当前项目优先核验 Qwen forced aligner raw baseline。heuristic 只有在能提供有意义的 token-level sanity check 时才保留；`auto` 不作为科研方法名。

`alignment.json` 的“统一中间产物”思想值得继承，但 schema 必须改造成 token-level。每个 token 至少应能表达：

```text
token_index
original_text
normalized_token
start_seconds
end_seconds
mapping_status
```

实际字段必须以源码和真实输出核验为准。

## 4. 不继承的部分

- ASS 字幕样式；
- subtitle plan；
- 视频烧录；
- GUI；
- 站点下载、Cookie、评论抓词；
- Aegisub / RubyTools 等字幕工具链。

这些内容属于合作者原项目背景，不进入当前目录主线。

## 5. 对当前项目的结构启发

| 合作者能力 | 当前项目处理 |
|---|---|
| lyrics loader | 改造成原文保留、规范化和 token 映射 |
| media inspector | 扩展为数据合法性与版本记录 |
| audio preprocess | 保留为可选输入变量，并记录 lineage |
| alignment adapters | 核验后接入 raw baseline |
| output constraints | 改造成版本化 token prediction schema |
| subtitle / render | 排除 |

## 6. 当前需要补充的研究层

1. raw / curated / split manifest；
2. 字符级 annotation 和 prediction schema；
3. 文本规范化和 token 映射；
4. 数据质量 flags、重复和泄漏检查；
5. token-level 时间戳指标；
6. raw baseline 与 LoRA/PEFT 的公平比较协议；
7. failed cases、人工复核和 case study；
8. 外部大型产物索引与 run lineage。

## 7. 尚未验证的事项

- 合作者源码版本和可运行入口；
- 真实 `alignment.json` schema；
- Qwen forced aligner 是否在该代码中可运行；
- 模型训练接口和 LoRA target modules；
- 现有 LRC/歌词是否能转换为可靠字符级标注；
- UVR 相关观察是否有可复现证据。

因此，本报告只说明可继承的结构思想，不声称已有实现可直接满足当前字符级路线。
