# Datasets Registry

## 长期数据角色与当前资产状态

当前主项目只推进普通话 character-level forced alignment。角色是长期规划；“资产可用”与“已转换可训练”必须分开记录。

| 名称 | 长期角色 | 当前资产状态 | 本轮使用边界 |
|---|---|---|---|
| M4Singer | primary train + custom validation | 用户报告已本地下载，AST 也有副本；待核验路径、版本和完整性 | 优先只读复用；仅用现有 audio+lyrics 做 raw smoke，不做字符转换 |
| Opencpop official train/test | train/validation source + final in-domain test | pending official download | 本轮只下载、登记和可选 raw smoke，不划 split、不评测 |
| MIR-1K | OOD test-only | 原始集已在外部数据盘验证：110 首整曲、1,000 条短片段、歌词与 pitch 标签；另有公开 17 首人工字符级标注 | 仅 17 首人工标注歌曲进入 character-level OOD test；不用于训练或 validation |
| MIR-MLPop Mandarin | later evaluation candidate | deferred | 当前不下载 |
| DALI | English training candidate | deferred | 当前不推进 |
| JamendoLyrics | English evaluation candidate | deferred | 当前不推进 |
| Jam-ALT | excluded | not used | 仅行级标注，不符合当前主任务 |

## 当前资产复用原则

- 优先直接只读引用 AST 外部数据路径；
- 其次在源码仓库外建立统一共享根或符号链接；
- 只有版本、权限或稳定性不满足时才复制必要副本；
- 不依赖 AST Python 源码；
- 不在本轮从音素、note 或 annotation 推导字符边界；
- 无可靠歌词映射时，只登记音频，不强行做 smoke。

## 后续数据阶段

字符 schema、正式 manifest、song-level split、同曲/歌词泄漏和 metric 均在后续数据清洗阶段设计。任何候选进入正式训练或评测前，需补充版本、获取日期、样本数、磁盘占用、manifest hash 和冻结 split。
