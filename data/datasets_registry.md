
# Datasets Registry

## 长期数据角色与当前资产状态

当前主项目只推进普通话 character-level forced alignment。主输入统一为 vocal-only。角色规划、资产可用、字符转换完成和 split 冻结必须分开记录。

| 名称 | 长期角色 | 当前资产状态 | 当前使用边界 |
|---|---|---|---|
| M4Singer | primary train + custom validation | 外部原始资产可用；已审计 20,896 items、193,666 character records；6,051 自动音素分组候选，14,845 group-count mismatch；尚无 accepted 子集 | 当前完成 mismatch taxonomy、text normalization、character mapping、vocal contract、song split 和 synthetic-long；不提前训练 |
| OpenCpop official train/test | train/validation source + final in-domain test | pending official authorization/download | 外部阻塞；不得绕过授权；不阻止完成 M4Singer/MIR-1K 自动化 |
| MIR-1K | OOD test-only | 原始集校验完成：110 首整曲、1,000 条短片段；17 首人工字符级标注、2,035 字符已准备 | 17 首官方 vocal channel 固定为 natural-long OOD test-only；不训练、不 validation、不调参 |
| MIR-MLPop Mandarin | later evaluation candidate | deferred | 当前不下载 |
| DALI | English training candidate | deferred | 当前不推进 |
| JamendoLyrics | English evaluation candidate | deferred | 当前不推进 |
| Jam-ALT | excluded | not used | 仅行级标注，不符合当前主任务 |

## vocal 来源规则

```text
native_vocal
official_vocal_channel
model_separated_vocal
```

模型分离人声必须记录 separator identity、配置和输入输出 hash。不同来源分层报告。

## 当前外部路径事实

- M4Singer raw 和已生成的 preparation 结果位于服务器外部数据盘；
- MIR-1K 原始归档、解压数据、公开字符标注和派生 manifest 位于服务器外部数据盘；
- 仓库只保留轻量 run summary、规则、schema 和报告；
- 本归档源 ZIP 漏收数据集代码，服务器工作树已有实现，下一次完整归档必须纳入。

## 进入正式训练前必须冻结

- dataset/version/acquisition identity；
- vocal source contract；
- text normalization 与 character mapping 版本；
- A/B/C 质量状态；
- song-level split 与 leakage report；
- native/synthetic/natural length source；
- manifest hash；
- metric schema 和 raw baseline。
