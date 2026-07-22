# LyricAlignment

面向普通话歌声的歌词强制对齐研究项目。仓库根目录永久保持为 `LyricAlignment/`；日期、阶段和 session 后缀只用于压缩包、run 和报告名称。

## 当前研究主线

```text
audio + known Mandarin lyrics
-> native or explicitly extracted vocal-only audio
-> Chinese character-level timestamps
-> traceable data cleaning and long-audio construction
-> automatic raw baseline and evaluation
-> staged adaptation
-> held-out evaluation
```

## 当前状态（2026-07-23）

### M4Singer 当前 operational canonical

当前规则轮次使用：

```text
/home/hyan/Data/lyricalign/derived/
20260722_m4singer_pinyin_validated_v4/prepare/m4singer_manifest.jsonl
```

- 总记录：20,896；
- `accepted`：20,298，均为 `rule_validated` character-to-phoneme candidate mapping；
- `review_required`：598；
- rejected/failed：0；
- character annotation：193,666 rows；
- manifest SHA-256：`22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`；
- character annotation SHA-256：`ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d`。

`accepted` 表示当前规则验证候选，不等同于已经人工确认的高置信训练集。598 条 review 包括：487 条复杂/多重 slur、74 条单 slur 且缺一个音节组、36 条普通话拼音解析失败、1 条英文/数字；mapping status 为 531 ambiguous、67 no-match。

历史的 6,051/14,845、66 条、18,057/2,839 均已被当前版本替代，不得与当前 manifest 混用。

### MIR-1K 当前状态

- 用户已于 2026-07-22 人工确认 `UndividedWavfile` 的第二个交错 PCM 声道，即 zero-based channel index 1，为人声；
- 实现按交错样本步进提取该声道，不进行双声道平均；
- 已生成 17 首 vocal-only、2,035 字符的 OOD test-only 子集；
- 输出目录：`/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood`；
- manifest SHA-256：`bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f`；
- character JSONL SHA-256：`78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9`。

## 当前阶段

当前处于 M4Singer 规则映射收尾与 MIR-1K OOD 数据固定阶段。当前包负责保存代码、规则、轻量关键结果、当前状态和历史版本关系；大型 manifest、音频及逐样本结果保留在外部数据盘。

同音伪歌词不属于当前主清洗输入。它保留为后续鲁棒性或低标准标注可接受性副实验。

## 输入音频原则

主训练、验证和测试统一使用人声音频：

- 原生独立人声；
- 数据集官方或人工确认的人声声道派生；
- 固定版本分离模型生成的人声 stem。

必须记录 `vocal_source_type`、输入输出 hash 及必要处理身份。模型分离人声和原生/官方声道人声必须可分层统计。

## 顶层目录

| 路径 | 定位 |
|---|---|
| `configs/` | 可提交模板和模型/实验配置；真实绝对路径使用 gitignored local 文件 |
| `data/` | 轻量 schema、registry 和 manifest 模板，不保存数据本体 |
| `src/lyricalign/` | 核心 Python 逻辑 |
| `scripts/` | 可复现薄入口 |
| `runs/` | 轻量 run 证据和外部产物索引 |
| `results/` | 结构化 metric 结果 |
| `reports/` | 资产、smoke、研究和 review 报告 |
| `docs/` | 原则、状态、manual 和 session |
| `requirements/` | 环境复现说明和已知版本记录 |
| `tests/` | 不依赖大型真实资产的小型工程检查 |

## 入口

1. `AI_SESSION_ENTRY.md`
2. `docs/status/project_current.md`
3. `docs/sessions/20260723_m4singer_rule_review.md`
4. `docs/status/next_execution_plan.md`
5. `docs/sessions/SESSION_INDEX.md`

## 外部资产与 Git

- remote：`git@github.com:heyan2454/LyricAlignment.git`
- 数据、模型缓存、checkpoint、音频、完整逐样本输出和大型日志必须位于仓库外；
- 仓库保存复现所需规则、命令/配置、关键数量、身份 hash 和轻量结论；
- OpenCpop 不得绕过官方授权或把 HTML 授权页面当作数据文件。
