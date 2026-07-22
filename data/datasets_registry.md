
# Datasets Registry

## 长期数据角色与当前资产状态

当前主项目只推进普通话 character-level forced alignment。主输入统一为 vocal-only。角色规划、资产可用、字符转换完成和 split 冻结必须分开记录。

| 名称 | 长期角色 | 当前资产状态 | 当前使用边界 |
|---|---|---|---|
| M4Singer | primary train + custom validation | 当前 operational canonical：20,896 items、193,666 character records；20,298 `rule_validated` candidates、598 review、0 rejected/failed | `rule_validated` 不等同于人工确认高置信；当前 manifest 身份见 `docs/status/project_current.md` |
| OpenCpop official train/test | train/validation source + final in-domain test | pending official authorization/download | 外部阻塞；不得绕过授权；不阻止完成 M4Singer/MIR-1K 自动化 |
| MIR-1K | OOD test-only | 用户已确认 zero-based channel index 1 为人声；17 首 vocal-only、2,035 字符派生 manifest 已固定 | natural-long OOD test-only；不训练、不 validation、不调参 |
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
- 当前归档已包含数据集代码与准备脚本；大型 manifest 和音频继续保留在外部数据盘。

## 进入正式训练前必须冻结

- dataset/version/acquisition identity；
- vocal source contract；
- text normalization 与 character mapping 版本；
- A/B/C 质量状态；
- song-level split 与 leakage report；
- native/synthetic/natural length source；
- manifest hash；
- metric schema 和 raw baseline。
