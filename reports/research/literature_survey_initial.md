# 初步文献调研：歌词转写与音频-文本对齐

本文件是初步调研记录，不是完整 survey。目标是帮助 当前项目快速建立方法地图，并指导实验设计。

## 1. 任务划分

### Automatic Lyrics Transcription / ALT

```text
audio -> lyrics text
```

核心评测是文本正确性，例如中文 CER 或英文 WER。

### Forced Alignment / Lyrics-to-Audio Alignment

```text
audio + known lyrics -> timestamps
```

核心评测是时间戳正确性，例如 start/end error、within tolerance、monotonic violation。

本项目主线是第二类，第一类作为副线 baseline。

## 2. 方法谱系

### 2.1 ASR / CTC 后验 + 动态规划

典型思想：将歌词文本转为字符或音素序列，声学模型输出 frame-level posterior，再用 CTC / Viterbi / DP 得到时间路径。

代表文献：Multilingual Lyrics-to-Audio Alignment, ISMIR 2020。

启发：

- 对齐可以使用 character 或 phoneme 表示；
- 多语言歌词对齐需要考虑不同语言的中间表示；
- CTC 是常见路线，但它原本服务 transcription，不一定直接优化边界精度。

### 2.2 Anchor-based long audio alignment

典型思想：长歌不一次性全局对齐，先找到 anchor words，再切成短段局部对齐。

代表文献：Low Resource Audio-to-Lyrics Alignment from Polyphonic Music Recordings, ICASSP 2021。

启发：

- 长音频全局对齐容易内存和漂移问题；
- 重复副歌、长间奏、后半段漂移可作为错误分析重点；
- 当前项目可先不实现 anchor 方法，但要统计 token-level drift 和重复歌词错配。

### 2.3 Singing-specific auxiliary tasks

典型思想：歌声不是普通语音，pitch、note onset、duration、chord、genre 等音乐信息会影响歌词边界。

代表文献：Improving Lyrics Alignment through Joint Pitch Detection, ICASSP 2022。

启发：

- 拖音和起音会影响字符或词边界；
- 对齐失败不一定是 ASR 文本错，可能是歌声声学边界本身模糊；
- 当前项目 case study 应记录长音、滑音、间奏、重复歌词。

### 2.4 Cross-modal contrastive alignment

典型思想：学习 audio embedding 与 text embedding 的相似度矩阵，再搜索对齐路径，而不是完全依赖 ASR posterior。

代表文献：Contrastive Learning-Based Audio to Lyrics Alignment for Multiple Languages, ICASSP 2023；Contrastive Lyrics Alignment with a Timestamp-Informed Loss, ICASSP 2025。

启发：

- 新趋势是把目标直接设计成 audio-text alignment；
- 当前阶段不优先训练 contrastive 模型，但报告中可说明 raw baseline 与直接优化对齐目标的方法差距。

### 2.5 Foundation forced aligner / audio LLM

典型思想：使用大规模预训练 ASR / audio foundation model 直接做 forced alignment 或时间戳预测。

代表模型：Qwen3-ForcedAligner-0.6B。

启发：

- 可作为当前 raw baseline 候选；
- 但调用强模型不是项目贡献，贡献应落在评测、误差分析、输入条件控制和可复现 pipeline 上。

### 2.6 Automatic lyrics transcription adaptation

典型思想：将 speech ASR 迁移到 singing domain，常用 wav2vec2 transfer、pitch/duration augmentation、multi-task learning、self-training 等。

代表文献：Transfer Learning of wav2vec 2.0 for Automatic Lyric Transcription, ISMIR 2022；PDAugment, ISMIR 2022；Lyrics Transcription for Humans, ISMIR 2024。

启发：

- audio->text 是重要方向，但若只跑 ASR 横评，贡献较弱；
- 应将其作为副线，重点分析 closed-book 转写错误对下游对齐的影响。

## 3. 初步论文清单

| 序号 | 论文/资源 | 年份/出处 | 任务 | 主要方法 | 对本项目启发 |
|---:|---|---|---|---|---|
| 1 | Multilingual Lyrics-to-Audio Alignment | ISMIR 2020 | alignment | RNN + CTC，character/phoneme，多语言 | 建立歌词对齐任务定义；说明 CTC/phoneme 路线 |
| 2 | Automatic Lyrics Alignment and Transcription in Polyphonic Music: Does Background Music Help? | ICASSP 2020 | alignment + ALT | 背景音乐/genre/music-informed acoustic model | mix audio 不一定只是噪声；vocal stem 需实测 |
| 3 | Low Resource Audio-to-Lyrics Alignment from Polyphonic Music Recordings | ICASSP 2021 | alignment | anchor words + segmentation + second-pass alignment | 长歌对齐、漂移、重复歌词分析 |
| 4 | User-Centered Evaluation of Lyrics-to-Audio Alignment | ISMIR 2021 | evaluation | 用户感知导向评价 | within tolerance 比单一 mean error 更适合展示 |
| 5 | Improving Lyrics Alignment through Joint Pitch Detection | ICASSP 2022 | alignment | pitch detection multi-task + boundary detection | 歌声特有 pitch/onset 信息会影响边界 |
| 6 | Contrastive Learning-Based Audio to Lyrics Alignment for Multiple Languages | ICASSP 2023 | alignment | audio-text contrastive embeddings | 最新趋势：直接优化跨模态对齐 |
| 7 | Contrastive Lyrics Alignment with a Timestamp-Informed Loss | ICASSP 2025 | alignment | contrastive + timestamp-informed box loss | 时间戳可直接进入 loss，说明边界精度是核心 |
| 8 | Qwen3-ASR Technical Report / Qwen3-ForcedAligner | 2026 tech report | ASR + forced alignment | NAR timestamp predictor / slot filling | 当前项目强 baseline，支持 word/character timestamps |
| 9 | Transfer Learning of wav2vec 2.0 for Automatic Lyric Transcription | ISMIR 2022 | ALT | wav2vec2 transfer + CTC/attention | audio->text 副线的方法背景 |
| 10 | PDAugment: Data Augmentation by Pitch and Duration Adjustments for ALT | ISMIR 2022 | ALT | speech pitch/duration augmentation | speech->singing domain gap，说明歌声 ASR 不可直接等同普通 ASR |
| 11 | Lyrics Transcription for Humans: A Readability-Aware Benchmark | ISMIR 2024 | ALT evaluation | Jam-ALT，可读性、格式、段落 | CER/WER 不足以描述歌词文本质量 |
| 12 | Enhancing Lyrics Transcription on Music Mixtures with Consistency Loss | INTERSPEECH 2025 | ALT | foundation ASR + LoRA + mix/vocal consistency | mix/vocal stem 可作为实验变量，分离不一定是唯一方案 |

## 4. 重点阅读顺序

当前阶段不需要精读全部论文。建议：

1. ISMIR 2020 multilingual lyrics alignment：读任务定义和 baseline；
2. ICASSP 2021 low resource alignment：读长歌/anchor 思路；
3. ICASSP 2022 joint pitch detection：读歌声特有因素；
4. ICASSP 2023 contrastive alignment：读近年方法趋势；
5. Qwen3-ASR technical report：读 Qwen3-ForcedAligner 的输入输出和适用边界；
6. ISMIR 2024 Jam-ALT：读 audio->text 副线评测提醒。

## 5. 对当前实验设计的落地建议

### 主线 alignment

raw baseline 阶段先验证 Qwen forced aligner 在中文字符级歌声上的输出 schema、覆盖率和边界质量。是否加入 heuristic 或 vocal stem，应在确认其研究价值、实现成本和存储开销后再决定。

指标：

```text
character onset/offset signed and absolute error
within 50/100/200/500 ms
token coverage and mapping failures
monotonic violation
near-zero or negative duration tokens
drift / collapse / repeated lyrics mismatch
```

### 副线 transcription

只选 1–2 个模型：

```text
Qwen3-ASR / Whisper / FunASR / SenseVoice
```

指标：

```text
CER
deletion/repetition/hallucination cases
```

严格区分：

```text
closed-book
retrieval-assisted
oracle lyrics alignment
```

## 6. 当前调研限制

- 本文件仅完成初步方法地图；
- 还没有系统阅读每篇论文的实验设置、数据集和指标；
- 对 ICASSP 2025 / 2026 技术报告等较新工作，需在后续复核正式版本与代码可用性；
- 当前项目计划在 raw baseline 和数据治理之后评估 LoRA/PEFT 域适配。

## 7. 参考链接

- Multilingual Lyrics-to-Audio Alignment, ISMIR 2020: https://archives.ismir.net/ismir2020/paper/000101.pdf
- Automatic Lyrics Alignment and Transcription in Polyphonic Music: Does Background Music Help?, ICASSP 2020: https://arxiv.org/abs/1909.10200
- Low Resource Audio-to-Lyrics Alignment from Polyphonic Music Recordings, ICASSP 2021: https://arxiv.org/abs/2102.09202
- Improving Lyrics Alignment through Joint Pitch Detection, ICASSP 2022: https://arxiv.org/abs/2202.01646
- Contrastive Learning-Based Audio to Lyrics Alignment for Multiple Languages, ICASSP 2023: https://arxiv.org/abs/2306.07744
- Contrastive Lyrics Alignment with a Timestamp-Informed Loss, ICASSP 2025: https://ieeexplore.ieee.org/document/10888807/
- Qwen3-ASR Technical Report, 2026: https://arxiv.org/abs/2601.21337
- Qwen3-ASR / ForcedAligner blog: https://qwen.ai/blog?id=qwen3asr
- Transfer Learning of wav2vec 2.0 for Automatic Lyric Transcription, ISMIR 2022: https://arxiv.org/abs/2207.09747
- PDAugment, ISMIR 2022: https://arxiv.org/abs/2109.07940
- Lyrics Transcription for Humans, ISMIR 2024: https://arxiv.org/abs/2408.06370
