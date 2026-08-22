# 数据获取结果快照

本文件保存本 session 结束时的数据资产快照。后续若源数据变化，以各数据集 `acquisition.json` 和 `checksums.sha256` 为准。

| Dataset | External root | Payload | Status / role |
|---|---|---|---|
| MIR-MLPop | `/home/hyan/Data/datasets/mir_mlpop` | 240223 全部标注；20 cmn WAV；3 yue WAV | partial upstream availability；自然混音评测候选；学术非商业 |
| AMLL TTML DB | `/home/hyan/Data/datasets/amll_ttml_db` | 3,160 TTML，无音频 | internal research-only silver pool；底层歌词/翻译权利未解决 |
| PJS v1.1 | `/home/hyan/Data/datasets/pjs` | 100 song + 100 speech；原始/人工重标音素 | complete；日语边界校准；CC BY-SA 4.0 |
| JamendoLyrics English | `/home/hyan/Data/datasets/jamendolyrics_en` | 20 raw-mixture MP3；5,693 words；868 lines | raw complete，operational vocal pending；逐曲许可 |
| GTSinger Chinese mini | `/home/hyan/Data/datasets/gtsinger_chinese` | 5 song roots；850 files；231 WAV/TextGrid/JSON | complete selected subset；附加协议未澄清，内部非商业研究 |
| iKala | `/home/hyan/Data/datasets/ikala` | 无主音频 | blocked_pending_access；custom license unresolved |

## 已执行验证

- MIR-MLPop：23 个现有 WAV 全部通过 ffprobe，缺失 ID 与 `acquisition.json` 一致；
- AMLL：3,160/3,160 TTML 通过 XML parse；
- PJS：官方 zip 通过 `unzip -t`，200 个主 WAV 通过 ffprobe；
- Jamendo：20/20 MP3 通过 ffprobe，5,693 word 和 868 line interval 顺序合法；
- GTSinger：850/850 与固定 Git tree 精确匹配，231 JSON、157 MusicXML、231 WAV 全部通过检查；
- 五个 payload 数据集的 4,186 条 checksum 全部验证通过。

## 重要边界

- 大型数据只保存在 `/home/hyan/Data/datasets/`，不提交 Git；
- raw 不得被人声分离、规范化或重采样结果覆盖；派生结果应写到 `/home/hyan/Data/lyricalign/derived/`；
- Jamendo/MIR 的 raw mixture 不能直接冒充项目要求的 vocal-only operational input；
- AMLL 的上游 CC0 声明不解决完整商业歌词/翻译的第三方权利；
- GTSinger 的附加协议未澄清；
- iKala 没有获权，不得训练、再分发或声称已经取得。

## 稳定登记入口

- `data/datasets_registry.md`
- `reports/assets/asset_inventory.md`
- 各 external root 的 `README.md`、`SOURCE.md`、`TERMS.md`、`acquisition.json`、`checksums.sha256`
