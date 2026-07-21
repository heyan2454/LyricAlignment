
# LyricAlignment

面向普通话歌声的歌词强制对齐研究项目。仓库根目录永久保持为 `LyricAlignment/`；日期、阶段和 session 后缀只用于压缩包、run 和报告名称。

## 当前研究主线

```text
audio + known Mandarin lyrics
-> separated/native vocal-only audio
-> Chinese character-level timestamps
-> traceable data cleaning and long-audio construction
-> automatic raw baseline and evaluation
-> staged adaptation
-> held-out evaluation
```

## 当前状态

已完成并有轻量证据：

- Qwen3 Forced Aligner Transformers-native 最小封装；
- 5 条 M4Singer schema-v2 raw smoke，全部成功返回字符时间戳；
- 精确记录模型 revision、Transformers source commit、输入 hash、配置 hash 和分阶段 runtime；
- M4Singer 原始元数据准备：20,896 items、193,666 character records；
- MIR-1K 原始归档校验、110 首整曲音频审计；
- 17 首人工字符级对齐 MIR-1K 歌曲接入为严格 OOD test-only；
- 数据处理测试已经存在于服务器工作树。

当前主要缺口：

- 本归档源 ZIP 漏收 `src/lyricalign/datasets/` 与 `scripts/datasets/`，因此只能合并到服务器现有工作树，不能覆盖式替换；
- M4Singer 仍有 14,845 条 group-count mismatch，需要分类和映射规则审计；
- 尚未冻结 text normalization、character mapping、vocal audio contract、song-level split 和 synthetic-long manifest；
- 自动 metric、raw baseline 和完整数据清洗闭环尚未实现；
- OpenCpop 仍受官方授权/获取流程阻塞。

## 当前阶段

本包进入统一数据处理与清洗自动化阶段。Codex 应按 `docs/status/next_execution_plan.md` 和 `docs/sessions/20260722_codex_dataset_cleaning_prompt.md` 推进，完成所有可自动化内容并逐阶段通过硬验收门槛，不提前启动 LoRA。

同音伪歌词不属于当前主清洗输入。它保留为后续鲁棒性/低标准标注可接受性副实验，用于检验在保持读音、破坏字形与语义时的对齐稳定性。

## 输入音频原则

主训练、验证和测试统一使用人声音频：

- 原生独立人声；
- 数据集官方人声声道；
- 或固定版本分离模型生成的人声 stem。

必须记录 `vocal_source_type`、分离模型/版本、配置、输入输出 hash。模型分离人声和原生干声必须可分层统计，不能静默混为同一质量来源。

## 顶层目录

| 路径 | 定位 |
|---|---|
| `configs/` | 可提交模板和模型/实验配置；真实绝对路径使用 gitignored local 文件 |
| `data/` | 轻量 schema、registry 和 manifest 模板，不保存数据本体 |
| `src/lyricalign/` | 核心 Python 逻辑 |
| `scripts/` | 可复现薄入口 |
| `runs/` | 轻量 run 证据和外部产物索引 |
| `results/` | 后续结构化 metric 结果 |
| `reports/` | 资产、smoke、研究和 review 报告 |
| `docs/` | 原则、状态、manual 和 session |
| `requirements/` | 环境复现说明和已知版本证据 |
| `tests/` | 不依赖真实大资产的小型测试 |

## 入口

1. `AI_SESSION_ENTRY.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/sessions/20260722_codex_dataset_cleaning_prompt.md`
5. `docs/sessions/SESSION_INDEX.md`

## 外部资产与 Git

- remote：`git@github.com:heyan2454/LyricAlignment.git`
- 数据、模型缓存、checkpoint、音频、完整逐样本输出和大型日志必须位于仓库外；
- 阶段完成后应提交并推送代码、配置、文档和轻量证据到私有 GitHub 仓库；
- OpenCpop 不得绕过官方授权或把 HTML 授权页面当作数据文件。
