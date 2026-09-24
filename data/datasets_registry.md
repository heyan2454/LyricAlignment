
# Datasets Registry

## 长期数据角色与当前资产状态

当前主项目只推进普通话 character-level forced alignment。主输入统一为 vocal-only。角色规划、资产可用、字符转换完成和 split 冻结必须分开记录。

| 名称 | 长期角色 | 当前资产状态 | 当前使用边界 |
|---|---|---|---|
| M4Singer | primary train + custom validation | 当前 operational canonical：20,896 items、193,666 character records；20,298 `rule_validated` candidates、598 review、0 rejected/failed | `rule_validated` 不等同于人工确认高置信；当前 manifest 身份见 `docs/status/project_current.md` |
| OpenCPOP | **域外字符级报告集（test-only）** + melisma 正例来源；不作训练/验证 | **2026-09-22 已取得并解包**（15 G，物理路径 `/root/autodl-tmp/AST_storage/Data_external/opencpop/Opencpop/`）：100 首整曲 44.1 kHz mono wav、3,756 句切段、100 份七轨 TextGrid（含**汉字轨逐字人工边界**）、100 份 `.midi`；派生件在 `/home/hyan/Data/lyricalign/derived/20260924_opencpop_eval/`（`evidence_sentence.jsonl.gz`、`evidence_window.jsonl.gz`、`STATS_*.json`、`windows60/`），生成入口 `scripts/datasets/prepare_opencpop_items.py` | **只作报告，绝不参与选点/调参**（到手晚于所有 checkpoint 训练时间）。准入尺检：句级 3,724/3,731 通过、`dur_mismatch` 5、27 段因切段粒度粗于句轨丢弃；34,114 字；≥1.5 s 689 / ≥2 s 317；`_` 连音续格 1,438 处已并入前字。**单女歌手录音室 ⇒ 只能当"质"不能当"域"**，域鲁棒性不宣称；utt 后 6 位是全库累计序号，配对必须用唱词串+时长双键。**已知上游瑕疵（实测并已处置）**：`transcriptions.txt` 与 TextGrid 汉字轨存在**等长异体/别字**130 段（礡↔礴、唐↔堂、再↔在）⇒ 时间与 prompt 同源取汉字轨，只校验字数、允许文本不等；句/窗边界取字数与唱词不等的 8 段 / 21 窗（首末字归属冲突）已**显式丢弃** |
| MIR-1K | OOD test-only | 用户已确认 zero-based channel index 1 为人声；17 首 vocal-only、2,035 字符派生 manifest 已固定 | natural-long OOD test-only；不训练、不 validation、不调参 |
| MIR-MLPop Mandarin / Cantonese | natural-mixture evaluation candidate + cross-language probe | 官方 240223 标注已取得；普通话音频 20/30，粤语 Test 前 5 首中 3/5 可用 | 仅学术、非商业；缺失 ID 和来源版本见外部 `acquisition.json`，不得把 partial availability 当固定全量集 |
| GTSinger Chinese mini | phoneme-boundary + singing-technique stress test | 5 个定向 song roots 完整取得：850 files，231 WAV/TextGrid/JSON | 上游为 CC BY-NC-SA 4.0 并附加 indemnity/雇主授权等未澄清协议；目前只限内部非商业研究，不用于声音克隆 |
| AMLL TTML DB | community silver annotation pool | 固定 revision 的 sparse snapshot 已取得：3,160 TTML、无音频 | internal research-only；贡献者 CC0 声明不自动清除底层歌词/翻译第三方权利，仍需权利、平台 ID、音频版本和年代审计 |
| DALI | English training candidate | deferred | 当前不推进 |
| JamendoLyrics MultiLang English | English evaluation candidate | `en/test` raw mixture 完整取得：20 MP3、5,693 words、868 lines；operational vocal benchmark 尚未完成 | 逐曲许可不同；必须保留 URL/许可。满足 vocal-only 契约前还需分离并记录 separator identity/config/input-output hash；不混入训练 |
| PJS v1.1 | Japanese phoneme/boundary calibration | 官方归档完整取得：100 song + 100 speech；另存 100 份人工重标音素 | CC BY-SA 4.0；单男声短句，只做转换/边界单测，不作为流行混音最终评测 |
| iKala | vocal/accompaniment benchmark candidate | `blocked_pending_access`；Zenodo 主文件 Restricted | 未获数据所有者授权和原条款前不训练、不再分发、不声称已取得 |
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
- 本轮新增外部数据均位于 `/home/hyan/Data/datasets/<dataset_id>/`；每个已取得的数据集包含 `README.md`、`SOURCE.md`、`TERMS.md`、`acquisition.json` 和 `checksums.sha256`；
- iKala 目录只保存受限访问记录，没有主音频；
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

## Evaluation V1 draft split（2026-08-16，未冻结）

- 脚本：`scripts/evaluation/build_evaluation_v1_split_manifest.py`
- 输出：`/home/hyan/Data/lyricalign/runs/20260816_evaluation_v1_split_draft/`
- manifest SHA-256：`f04e0b9b959907a87965c581a615dd1d74b03dbd88dce837e2cc97927602ed8f`
- 状态：draft_not_frozen；常规 runner 不得读取 `sealed_final`，除非显式 `--allow-sealed`
- 包含：MIR-MLPop cmn/yue、JamendoLyrics en、PJS、GTSinger Chinese mini 的 grouped song-level split

## Evaluation V1 产品化输出索引

- 外部产物索引：`reports/progress/20260816_evaluation_outputs_index.json`
- 总览：`results/comparisons/20260816_productization_status.json`
- 详细报告：`reports/progress/20260816_productization_validation_report.md`
