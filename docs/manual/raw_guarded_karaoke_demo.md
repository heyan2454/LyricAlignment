# Raw + guarded karaoke Demo 使用说明

## 1. 这个 Demo 做什么

推荐入口：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh <输入>
```

它保留旧通用 Demo 的文件发现、批处理、语言参数、音频分离、字幕和视频渲染能力，
只替换对齐策略：

```text
R2 Qwen raw timestamp
→ 串行分窗 baseline
→ 异常检测
→ exact 局部重推理
→ matched +2 独立验证
→ 安全门
→ final alignment
→ 卡拉 OK 视频
```

默认分离器是 **Demucs 4.1.0 / htdemucs_ft / CUDA**。Spleeter 仅保留为显式的历史兼容选项，
不会作为 Demucs 失败后的自动回退。

## 2. 四个常见词分别指什么

### raw

`raw` 是 Qwen timestamp slot 的 argmax 时间类别，位于官方 processor 的单调修正之前。
它描述的是**时间戳解码来源**。

### baseline / raw baseline

`baseline` 是使用 raw 时间戳完成整首歌串行分窗、窗口归属和冻结前缀合并后的完整对齐。
它已经包含串行窗口的 overlap compression，但**尚未执行局部 realign**。

主要文件：

```text
alignments/r2_raw_guarded/baseline_raw/alignment.json
```

### guarded

`guarded` 不是另一个 decoder。它是局部干预机制：宽松检测可疑区间，但只有 exact 与
matched +2 结果一致、结构合法、异常分数下降且边界变化受限时才允许写回。

### final / guarded final

`final` 是 baseline 应用所有通过安全门的局部修复后的实际输出。没有任何修复通过时，
final 与 baseline 完全相同。

主要文件：

```text
alignments/r2_raw_guarded/alignment.json
```

## 3. 输入文件规则

同一首歌使用相同文件名主体：

```text
歌曲A.mp4
歌曲A.wav       # 可选；存在时优先作为分离和对齐音频
歌曲A.txt
```

必须有 TXT，且至少有一个同名视频或音频。支持：

```text
视频：.mp4 .mkv .mov .webm .avi .m4v
音频：.wav .flac .mp3 .m4a .aac .ogg .opus .wma
```

有视频时保留其画面；有同名独立音频时，独立音频优先进入 Demucs 和对齐。

## 4. 单文件、名字和文件夹用法

### 直接输入媒体文件

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A.mp4
```

### 输入 TXT

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A.txt
```

### 只输入名字

当前目录存在 `歌曲A.txt` 和同名媒体时：

```bash
cd /data
bash /home/hyan/LyricAlignment/scripts/demo/run_raw_guarded_karaoke_demo.sh 歌曲A
```

也可以输入带目录的无扩展名主体：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A
```


### 媒体与歌词不同名

单首歌可显式指定歌词：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/夜苏打.mp4 \
  --lyrics /data/歌词.txt
```

`--lyrics` 只允许一个已发现的媒体任务，不能用于一次覆盖整个批量目录。

### 处理一个文件夹

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/songs
```

只处理文件夹内指定主体：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/songs --name 歌曲A
```

递归扫描子文件夹：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/songs --recursive
```

只查看会发现哪些任务，不运行：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/songs --dry-run
```

## 5. 语言参数

默认中文：

```bash
--language Chinese
```

常用别名和单位：

```text
zh / 中文       -> Chinese，汉字字符级，连续拉丁词按词
yue / 粤语     -> Cantonese，汉字字符级
 en / 英文      -> English，词级
 ja / 日语      -> Japanese，Nagisa 词级
```

示例：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/en_song \
  --language English
```

R2 使用中文歌唱数据微调，英文、日文、粤语目前属于可运行但未正式验证的跨语种用途。

## 6. Demucs 默认配置

默认值：

```text
separator       demucs
version         4.1.0
model           htdemucs_ft
device          cuda
shifts          0
overlap         0.25
jobs            0
TORCH_HOME      /root/autodl-tmp/AST_storage/Data/lyricalign/models/torch
```

入口依次尝试：

1. PATH 中的 `demucs`；
2. 当前 Python 环境的 `python -m demucs`；
3. `conda run -n demucs python -m demucs`。

显式指定：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A \
  --separator demucs \
  --demucs-command '/root/autodl-tmp/AST_storage/conda/envs/demucs/bin/python -m demucs' \
  --demucs-model htdemucs_ft \
  --demucs-device cuda
```

32 GB vGPU 若出现 OOM，可先尝试：

```bash
--demucs-segment 7
```

不要静默切换到 CPU；如必须使用 CPU，应显式传 `--demucs-device cpu` 并在结果中保留 identity。

## 7. 默认模型与权重

```text
Qwen snapshot:
/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/
models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/
c07281df297b9905d24a508279258cccf987a064

R2 checkpoint:
/root/autodl-tmp/AST_storage/Data/lyricalign/runs/
20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
```

覆盖方式：

```bash
MODEL_SOURCE=/path/to/model \
MODEL_REVISION=revision \
R2_CHECKPOINT=/path/to/checkpoint \
  bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A
```

也可直接传 CLI：

```bash
--model /path/to/model --revision revision --r2-checkpoint /path/to/checkpoint
```

## 8. 输出目录

默认在源文件旁建立：

```text
歌曲A_qwen_fa_raw_guarded/
├── work/audio/
│   ├── mix.wav
│   ├── vocals.wav
│   ├── accompaniment.wav
│   ├── vocals.identity.json
│   └── separation_quality.json
├── alignments/r2_raw_guarded/
│   ├── baseline_raw/alignment.json
│   ├── alignment.json
│   ├── raw_guarded_realign.json
│   └── complete.json
├── subtitles/
├── videos/individual/
├── videos/comparisons/
├── raw_guarded_demo.mp4
├── batch_plan.json
└── batch_manifest.json
```

统一输出根目录：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/songs \
  --output-dir /home/hyan/Data/lyricalign/demo_outputs
```

单首歌精确指定目录：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A \
  --single-output-dir /home/hyan/Data/lyricalign/demo_outputs/歌曲A
```

## 9. 分阶段恢复

```bash
# 媒体提取和 Demucs
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A --stage prepare

# 使用已有 stems 对齐
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A --stage align

# 使用已有 alignment 渲染
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/歌曲A --stage render
```

强制重跑：

```bash
--force-separation
--force-align
--force-render
--force              # 全部强制
```

缓存 identity 包含源文件 hash、语言、模型、R2 checkpoint、窗口参数、Demucs 请求和 realign 阈值。

## 10. 视频含义

```text
raw_baseline_mix.mp4        raw baseline 字幕 + 原混音
raw_baseline_vocal.mp4      raw baseline 字幕 + Demucs 人声
guarded_final_mix.mp4      final 字幕 + 原混音
guarded_final_vocal.mp4     final 字幕 + Demucs 人声
compare_raw_vs_guarded_*    baseline/final 双画面对比
raw_guarded_demo.mp4        对外主视频：原画面、原混音、final 字幕
```

主视频使用原混音，不会用分离人声替换正常听感。人声版本只用于诊断。

## 11. 当前安全策略

生产默认只使用：

```text
exact + matched +2 agreement
```

`+2` 表示在两侧各增加两个歌词单位，同时按 baseline 对应边界扩展音频 crop。它是 verifier，
不是更激进的自动 fallback。`+4` 不进入默认 Demo。

若 detector 报警但修复没有通过安全门，final 保持 baseline；这只增加计算，不影响输出准确率。
