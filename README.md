# LyricAlignment

面向普通话歌声的已知歌词强制对齐研究项目。仓库根目录永久保持为 `LyricAlignment/`；日期和阶段后缀只用于压缩包、run 与报告名称。

## 当前研究主线

```text
vocal-only singing audio + known Mandarin lyrics
-> character-level timestamp labels
-> Qwen Forced Aligner raw baseline
-> projector-only / audio-tower LoRA adaptation
-> frozen validation checkpoint selection
-> sealed M4Singer test
-> MIR-1K vocal-only OOD
```

## 当前状态（2026-07-23）

### 数据

M4Singer 当前 operational canonical：

```text
/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/
```

- 20,896 items；
- 20,298 `accepted`，解释为 `rule_validated` weak-supervision candidates；
- 598 `review_required`，本轮训练全部排除；
- manifest SHA-256：`22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`；
- character annotation SHA-256：`ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d`。

MIR-1K OOD：

- 17 首、2,035 字符；
- zero-based channel index 1 经用户人工确认并按交错 PCM 声道提取为 vocal-only；
- 只用于 `ood_test_only`；
- manifest SHA-256：`bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f`；
- character JSONL SHA-256：`78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9`。

### LoRA 首轮实验

模型：`Qwen/Qwen3-ForcedAligner-0.6B-hf`，revision `c07281df297b9905d24a508279258cccf987a064`。

Pilot validation：

| 配置 | Step | Song-macro boundary MAE |
|---|---:|---:|
| R0 raw | 0 | 169.925 ms |
| R1 projector-only | 100 / 200 | 90.823 / 65.699 ms |
| R2 projector + audio top-half LoRA | 100 | **55.247 ms** |
| R3 projector + audio all-layer LoRA | 100 | 61.078 ms |

R2 全量训练完成 1,110 optimizer steps，最终 validation MAE 为 **46.634 ms**。程序周期 selector 记录 step 1000 为 validation-best（46.734 ms）；step 1110 的最终 evaluation 更低 0.100 ms，但没有进入周期 selector。

full R2 M4Singer sealed test 已产生结果：

- song-macro boundary MAE：**79.590 ms**；
- onset/offset MAE：41.854/51.249 ms；
- joint within 80 ms：89.755%；
- mean IoU：84.579%；
- invalid rate：0.959%。

现有 MIR-1K OOD 指标属于 earlier pilot R2。**full R2 validation-best checkpoint 的 MIR-1K OOD 尚未完成。**

## 当前入口

1. `AI_SESSION_ENTRY.md`
2. `docs/status/project_current.md`
3. `docs/sessions/20260723_qwen_fa_lora_full_r2_archive.md`
4. `reports/progress/20260723_qwen_fa_lora_results.md`
5. `docs/status/next_execution_plan.md`

服务器下一步：

```bash
cd /home/hyan/LyricAlignment
conda activate lyricalign-qwen
bash scripts/training/finalize_qwen_fa_r2_manual.sh inspect
bash scripts/training/finalize_qwen_fa_r2_manual.sh run-ood
bash scripts/training/finalize_qwen_fa_r2_manual.sh summarize
```

入口默认只读检查；不会重复运行 sealed test；`run-ood` 使用 `best_checkpoint.json` 指向的 validation-best checkpoint，并拒绝覆盖已有 final OOD 目录。

## 顶层目录

| 路径 | 定位 |
|---|---|
| `configs/` | 模型、训练、数据和 metric 配置 |
| `data/` | 轻量 schema、registry 和 manifest 模板 |
| `src/lyricalign/` | 核心 Python 逻辑 |
| `scripts/` | 可复现薄入口 |
| `runs/` | 轻量 run 证据和外部产物索引 |
| `results/` | 结构化指标和比较结果 |
| `reports/` | 实验、进展、审查和研究报告 |
| `docs/` | 原则、状态、manual 和 session |
| `requirements/` | 环境复现说明 |
| `tests/` | 不依赖大型真实资产的工程检查 |

## 外部资产与 Git

- remote：`git@github.com:heyan2454/LyricAlignment.git`；
- 数据、模型缓存、checkpoint、音频、predictions 和大型日志位于仓库外；
- 仓库保存实现、配置、命令、数据/模型身份、轻量结果和结论；
- sealed test 和 OOD 不得参与 checkpoint 或超参数反选。
