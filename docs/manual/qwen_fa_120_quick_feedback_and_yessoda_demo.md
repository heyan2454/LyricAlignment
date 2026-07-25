# 120s 快速反馈与“夜苏打”独立 Demo

## 1. 范围与边界

本 patch 新增两条彼此独立的入口：

1. **120s 快速机制诊断**：在冻结的 M4Singer test 短样本上，区分“绝对时间位置”与“总输入长度”。
2. **夜苏打 Demo**：对真实完整歌曲生成 R0/R1/R2 × 原音频/分离人声 × 不分窗/串行分窗的 12 组结果，并渲染 KTV 视频。

两条入口均满足：

- 不训练；
- 不改变 R0/R1/R2 checkpoint；
- 不使用 demo 结果选择模型；
- 不覆盖历史正式评测；
- 新入口只接受 validation 选出的 `best_checkpoint.json`，不会退回最后一个 step。

---

# 2. 120s 快速反馈

## 2.1 实验内容

对相同短样本分别运行：

### A. 绝对时间位置实验 `shift`

在原短样本前增加静音：

```text
0, 90, 105, 115, 120, 125, 135, 150 秒
```

音频内容、歌词和局部声学难度不变，只改变 GT 所在的绝对时间位置。

### B. 总输入长度实验 `tailpad`

短样本仍在开头，尾部补静音，使总输入达到：

```text
native, 60, 90, 105, 115, 120, 125, 135, 150, 180 秒
```

目标字符位置保持不变，只改变总输入长度。

两类实验都保存：

- raw timestamp boundary error；
- 官方 fixed timestamp boundary error；
- repaired-slot rate；
- repair amplification；
- 模型、checkpoint、标签、字符标注与参数 identity。

## 2.2 最快首轮：先看 R2 单样本

为了尽快判断是否值得继续，先只跑 R2，且只保留 120s 邻域的关键点：

```bash
cd /home/hyan/LyricAlignment

OUT_ROOT=/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_120_quick_r2_smoke \
MODELS=r2 \
SAMPLE_COUNT=1 \
SHIFT_OFFSETS=0,105,115,120,125,135,150 \
TARGET_DURATIONS=0,105,115,120,125,135,150 \
bash scripts/training/run_qwen_fa_120_quick_feedback.sh
```

查看进度：

```bash
tail -f /home/hyan/Data/lyricalign/runs/20260725_qwen_fa_120_quick_r2_smoke/pipeline.log
```

查看结果：

```bash
cat /home/hyan/Data/lyricalign/runs/20260725_qwen_fa_120_quick_r2_smoke/QUICK_READOUT.md
```

## 2.3 标准快速反馈：R0/R1/R2 × 3 样本

```bash
cd /home/hyan/LyricAlignment
bash scripts/training/run_qwen_fa_120_quick_feedback.sh
```

默认输出：

```text
/home/hyan/Data/lyricalign/runs/20260725_qwen_fa_120_quick_feedback/
├── timestamp_coverage.json
├── r0/
│   ├── shift/
│   └── tailpad/
├── r1/
│   ├── shift/
│   └── tailpad/
├── r2/
│   ├── shift/
│   └── tailpad/
├── final_summary.json
├── QUICK_READOUT.md
└── pipeline.complete
```

## 2.4 续跑与身份检查

每个模型、每种实验单独保存 request hash。以下内容任一变化，旧目录都会改名为 `.identity_mismatch*`，不会静默复用：

- model revision；
- projector/adapter 文件 hash；
- labels/characters hash；
- 样本数；
- shift offsets；
- target durations；
- timestamp unit。

正常中断后直接重新执行同一命令即可。

强制重跑：

```bash
FORCE=1 bash scripts/training/run_qwen_fa_120_quick_feedback.sh
```

只跑指定模型：

```bash
MODELS=r2 bash scripts/training/run_qwen_fa_120_quick_feedback.sh
MODELS=r0,r1 bash scripts/training/run_qwen_fa_120_quick_feedback.sh
```

## 2.5 初步解释规则

| 观察 | 优先解释 |
|---|---|
| `shift` 在 115–125s 附近恶化，而 `tailpad` 稳定 | 绝对 timestamp 类别或晚时间校准 |
| `tailpad` 恶化，而 `shift` 相对稳定 | 总输入长度、mask 或长序列注意力 |
| raw 稳定，但 fixed 与 repaired-slot rate 恶化 | 单调修复放大 |
| 只有 R2 明显恶化 | LoRA/适配引入的长时校准变化 |
| R0/R1/R2 同位置共同恶化 | processor、timestamp vocabulary 或基础结构 |

这里只是快速机制判断。3 个样本不足以形成自然长音频 benchmark 结论。

---

# 3. “夜苏打”独立 Demo

## 3.1 输入位置

服务器上准备：

```text
/home/hyan/LyricAlignment/夜苏打/
├── 歌词.txt
└── 夜苏打.mp4
```

输出统一写入新目录：

```text
/home/hyan/LyricAlignment/夜苏打/qwen_fa_demo_serial/
```

仓库 `.gitignore` 已忽略整个 `/夜苏打/`，避免歌词、音频、alignment JSON 和视频被误提交。

## 3.2 Spleeter 环境

入口优先使用 PATH 中的 `spleeter`；若不存在，则尝试：

```bash
conda run -n spleeter spleeter ...
```

建议将 Spleeter 与 Qwen Python 3.12 环境分开。例如：

```bash
conda create -n spleeter python=3.10 -y
conda run -n spleeter pip install spleeter
```

自定义环境名：

```bash
SPLEETER_ENV=my_spleeter_env bash scripts/demo/run_yessoda_serial_demo.sh
```

## 3.3 推荐分阶段执行

### 阶段 1：提取原音频并分离人声

```bash
cd /home/hyan/LyricAlignment
STAGE=prepare bash scripts/demo/run_yessoda_serial_demo.sh
```

检查：

```bash
ls -lh /home/hyan/LyricAlignment/夜苏打/qwen_fa_demo_serial/work/audio/
```

应包含：

```text
mix.wav
vocals.wav
vocals.identity.json
```

其中：

- `mix.wav`：从 `夜苏打.mp4` 提取的原始混合音轨；
- `vocals.wav`：Spleeter 2-stem 的纯人声；
- 人声 identity 绑定 mix hash，源视频改变后不会误用旧 stem。

### 阶段 2：串行完成 12 组对齐

```bash
STAGE=align bash scripts/demo/run_yessoda_serial_demo.sh
```

查看：

```bash
tail -f /home/hyan/LyricAlignment/夜苏打/qwen_fa_demo_serial/alignment.log
```

加载顺序固定为：

```text
R0 -> 释放 -> R1 -> 释放 -> R2 -> 释放
```

每个模型加载一次后依次完成：

```text
原音频 + 不分窗
原音频 + 串行分窗
分离人声 + 不分窗
分离人声 + 串行分窗
```

分窗默认：

```text
60s 核心区
15s 左上下文
15s 右上下文
单窗最大输入约 90s
```

窗口结果独立生成，不读取、不初始化于不分窗结果。

### 阶段 3：生成 KTV 视频

```bash
STAGE=render bash scripts/demo/run_yessoda_serial_demo.sh
```

也可一条命令完成全部阶段：

```bash
bash scripts/demo/run_yessoda_serial_demo.sh
```

## 3.4 12 个单独视频

目录：

```text
夜苏打/qwen_fa_demo_serial/videos/individual/
```

文件：

```text
r0_mix_full.mp4
r0_mix_windowed.mp4
r0_vocal_full.mp4
r0_vocal_windowed.mp4
r1_mix_full.mp4
r1_mix_windowed.mp4
r1_vocal_full.mp4
r1_vocal_windowed.mp4
r2_mix_full.mp4
r2_mix_windowed.mp4
r2_vocal_full.mp4
r2_vocal_windowed.mp4
```

音轨口径：

- `mix` 视频只使用原始混合音轨；
- `vocal` 视频只使用分离人声，不混回伴奏。

## 3.5 4 个 R0/R1/R2 三联视频

目录：

```text
夜苏打/qwen_fa_demo_serial/videos/comparisons/
```

文件：

```text
compare_models_mix_full.mp4
compare_models_mix_windowed.mp4
compare_models_vocal_full.mp4
compare_models_vocal_windowed.mp4
```

每个视频包含 R0/R1/R2 三个面板，并使用对应的 mix 或 vocal 共享音轨。

## 3.6 3 个同模型四联视频

```text
compare_inputs_r0.mp4
compare_inputs_r1.mp4
compare_inputs_r2.mp4
```

四个面板顺序：

```text
左上：原音频 + 不分窗
右上：原音频 + 串行分窗
左下：分离人声 + 不分窗
右下：分离人声 + 串行分窗
```

一个复合视频无法同时播放 4 条音轨，因此四联视频统一使用原始 mix 作为时间轴。需要听分离人声时，以 12 个单独视频为准。

## 3.7 KTV 画面规则

- 黑色 1280×720 背景；
- 上下两行交替；
- 当前行逐字推进，下一行提前显示；
- 使用 ASS `\kf` 实现字内时间填充；
- 长句自动缩小字号，避免超出画面；
- 左上角显示模型、输入音频与分窗模式；
- `歌词.txt` 中的行内空格只用于视觉分句，不送入模型；
- 重复歌词按 occurrence/global character ID 区分，不按文字内容去重。

默认字体：

```text
Noto Sans CJK SC
```

服务器缺少该字体时：

```bash
KARAOKE_FONT='Source Han Sans SC' \
STAGE=render bash scripts/demo/run_yessoda_serial_demo.sh
```

实际选用字体记录在：

```text
夜苏打/qwen_fa_demo_serial/render_manifest.json
```

## 3.8 续跑与失败恢复

- `STAGE=prepare`：mix hash 未变化时复用现有人声 stem；
- `STAGE=align`：每种组合按歌词、音频、模型、checkpoint 和窗口参数 identity 判断是否跳过；
- `STAGE=render`：视频按 alignment/audio/render identity 判断是否跳过；
- 中断后重新执行相同阶段即可；
- 不完整模型不会阻止已完成模型结果保留；
- 模型严格串行，降低显存峰值。

强制重跑：

```bash
FORCE_ALIGN=1 STAGE=align bash scripts/demo/run_yessoda_serial_demo.sh
FORCE_RENDER=1 STAGE=render bash scripts/demo/run_yessoda_serial_demo.sh
```

修改窗口参数：

```bash
CORE_SEC=60 \
LEFT_CONTEXT_SEC=15 \
RIGHT_CONTEXT_SEC=15 \
STAGE=align bash scripts/demo/run_yessoda_serial_demo.sh
```

参数变化会改变 request hash，不会静默复用旧结果。

## 3.9 回传 review 的最小文件

### 快速反馈

```text
.../20260725_qwen_fa_120_quick_feedback/QUICK_READOUT.md
.../20260725_qwen_fa_120_quick_feedback/final_summary.json
```

### Demo

```text
夜苏打/qwen_fa_demo_serial/alignment_matrix.complete.json
夜苏打/qwen_fa_demo_serial/render_manifest.json
夜苏打/qwen_fa_demo_serial/pipeline.log
夜苏打/qwen_fa_demo_serial/alignments/**/alignment.json
夜苏打/qwen_fa_demo_serial/videos/comparisons/*.mp4
```

若某个复合视频表现异常，再补对应的单独视频即可，不必第一轮上传全部 12 个单视频。

## 3.4 Spleeter 权重失败与相同音频防护

Spleeter 首次运行会下载预训练模型。若下载失败，不能只依据命令返回码或
`vocals.wav` 是否存在来判断成功；必须同时检查模型缓存和输出差异。

本 demo 现在固定使用显式模型目录，并在写入正式 stem 前执行质量检查：

- `mix.wav` 与 `vocals.wav` 若近似为同一信号，直接失败；
- `vocals.wav` 与 `accompaniment.wav` 若近似一致，直接失败；
- 任一 stem 近似静音，直接失败；
- 保存 `separation_quality.json`，记录相关系数、拟合残差、RMS 和重构残差；
- 只有 identity、两条 stem 和质量报告全部存在时才允许复用。

建议将权重放在项目目录之外：

```bash
export SPLEETER_MODEL_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter
```

若此前下载中断或已经产生错误 stem，优先使用可断点续传下载脚本：

```bash
cd /home/hyan/LyricAlignment
SPLEETER_MODEL_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter \
  bash scripts/demo/download_spleeter_model_resumable.sh
```

随后强制重新分离，禁止复用旧结果：

```bash
SPLEETER_MODEL_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/models/spleeter \
FORCE_SEPARATE=1 \
STAGE=prepare \
  bash scripts/demo/run_yessoda_serial_demo.sh
```

也可让主入口删除缓存并触发 Spleeter 自己重新下载，但该下载不支持断点续传：

```bash
FORCE_SPLEETER_MODEL_REDOWNLOAD=1 \
FORCE_SEPARATE=1 \
STAGE=prepare \
  bash scripts/demo/run_yessoda_serial_demo.sh
```

成功后检查：

```bash
cat 夜苏打/qwen_fa_demo_serial/work/audio/separation_quality.json
ls -lh 夜苏打/qwen_fa_demo_serial/work/audio/{mix,vocals,accompaniment}.wav
```

`passed` 必须为 `true`。旧版 `yessoda_spleeter_v1` identity 不再足以证明分离有效。
