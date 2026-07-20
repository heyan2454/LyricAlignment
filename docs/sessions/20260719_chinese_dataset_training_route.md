# Session: Chinese Dataset and Training Route

**Date:** 2026-07-19  
**Temperature:** warm

## 用户决策

- 当前研究主线为中文字符级歌词对齐。
- 长期训练来源：M4Singer + Opencpop official train。
- 长期测试：Opencpop official test + MIR-1K character-aligned subset。
- MIR-MLPop 只记录，之后再考虑。
- 英文 DALI / JamendoLyrics 路线降为次要；Jam-ALT 不使用。
- 长期模型顺序：先完整训练 multi-modal projector 与 timestamp head，再做 audio tower LoRA；language model LoRA 延后。
- Git remote：`git@github.com:heyan2454/LyricAlignment.git`。
- 用户报告服务器 GitHub SSH 已连接。
- 服务器资源：AutoDL 32 GB vGPU、约 90 GB RAM、数据盘剩余约 60 GB且可扩容。

## 仍有效的长期判断

### Validation 不能缺失

Opencpop official test 和 MIR-1K 最终需要封存。正式训练时应从官方训练数据内部建立 song-level validation：

- Opencpop train holdout：同歌手 in-domain；
- M4Singer holdout：多歌手 development validation。

主 checkpoint 选择规则必须在测试前冻结。

### 字符边界转换是核心风险

M4Singer / Opencpop 的基础标注包含音素、音节、note、duration 和特殊 token，不能直接假定为统一字符 GT。需要在后续数据清洗阶段统一处理：

- 多音素聚合；
- melisma / slur；
- phoneme duration 与 note duration 区分；
- `<SP>` / `<AP>` / silence；
- 一字多音、英文、数字；
- 映射失败的人工复核。

### 清洗效果实验使用决策门

只有当过滤、边界修正或去重达到实质影响时，才需要 `raw-all` vs `clean-all` 正式训练；数据量变化大时再补 `raw-size-matched`。

### 测试输入条件

MIR-1K 后续应独立报告：

- vocal-only OOD；
- vocal + accompaniment mix OOD。

## 当前阶段变化

本 session 的数据角色和长期训练路线继续有效，但以下工作已后移：

- character boundary conversion；
- split 冻结；
- metric；
- projector/head 与 LoRA。

当前操作入口改为 `20260719_asset_preparation_and_raw_smoke_scope.md`。

## 待验证

- AST 中 M4Singer/MIR-1K 的实际路径与复用性；
- M4Singer 实际版本、metadata schema 和磁盘占用；
- Opencpop 下载内容；
- Qwen Forced Aligner raw singing smoke；
- 后续训练接口、timestamp label 和实际模块名；
- 三个数据集的同曲、同歌词或翻唱泄漏。

## Temperature update

2026-07-19：由 `hot` 调整为 `warm`。原因是长期决策仍有效，但当前 Codex 工作已收缩为资产准备与 raw smoke。
