# LyricAlignment

面向普通话歌声的歌词强制对齐研究项目。仓库根目录永久保持为 `LyricAlignment/`；日期、阶段和 session 后缀只用于压缩包、run 和报告名称。

## 当前研究主线

```text
audio + known Mandarin lyrics
-> Chinese character-level timestamps
-> raw Qwen baseline
-> traceable data cleaning and long-audio construction
-> staged adaptation
-> held-out evaluation
```

## 当前状态

已完成：

- Qwen3 Forced Aligner 官方 Transformers-native 最小封装；
- 一条 5.005 s M4Singer 样本的历史 raw smoke 报告；
- M4Singer 共享数据只读复用判断；
- revision-aware resume、模型/输入身份记录、轻量证据索引；
- runtime 分阶段定义和时间戳结构诊断拆分；
- 资产校验、OpenCpop 断点下载与环境捕获脚本修复。

尚未完成：

- 使用新 schema 在服务器重新运行 smoke；
- Transformers 源码 commit 的实际捕获；
- OpenCpop 获取；
- character schema、数据清洗、长音频构造、metric、LoRA 和正式实验。

## 当前阶段边界

当前包只提供可靠的 smoke 基础设施和下一阶段入口，不把 5 秒 raw smoke 解释为准确率结论。

长音频不在本轮临时拼接。下一阶段数据清洗将统一处理：

- 音频格式规范化；
- 音频、歌词和标注映射；
- 中文字符边界转换；
- `native_short`、`synthetic_concat`、`natural_long` 三类样本；
- 同曲相邻片段拼接、时间轴平移、接缝记录和长度 bucket；
- train/validation/test 与泄漏审计。

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
| `tests/` | 不依赖真实数据/模型的小型测试 |

## 入口

1. `AI_SESSION_ENTRY.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/sessions/SESSION_INDEX.md`
5. 目标目录的 `README.md`

## 外部资产与 Git

- remote：`git@github.com:heyan2454/LyricAlignment.git`
- 数据、模型缓存、checkpoint、音频、完整逐样本输出和大型日志必须位于仓库外；
- 标准 smoke 在仓库内只保存 command、环境摘要、run summary、外部路径和 SHA256；
- OpenCpop 当前受官方授权流程阻塞，不得绕过许可或把 HTML 授权页面当作数据文件。
