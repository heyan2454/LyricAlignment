# Session: Asset Preparation and Raw Smoke Scope

**Date:** 2026-07-19  
**Temperature:** hot

## 背景

原计划让 Codex 下载 Qwen 模型和数据，并立即推进字符边界转换、metric smoke 和训练可行性检查。用户进一步收缩了当前阶段，避免在数据 schema 尚未设计清楚时提前实现转换与评测。

## 用户决策

- 字符边界转换与 metric smoke 本轮不做；下一阶段数据清洗时统一设计可用数据集转换。
- 当前可以使用音频和已有歌词运行 Qwen Forced Aligner raw smoke，观察是否返回输出。
- raw smoke 不使用 GT，不计算 metric，不据此判断准确率。
- 用户已经下载 M4Singer，原计划传输到服务器。
- AST 项目已经存在 M4Singer 和 MIR-1K；优先检查是否能直接链接或只读复用，避免重复存储。
- 如果 AST 数据不能可靠复用，不勉强耦合；记录原因后再决定共享副本或传输。
- 本轮除模型/数据资产登记、相关最小代码和 smoke 外，不实现其他功能。

## 本轮执行口径

```text
verify Git and external roots
-> discover AST M4Singer / MIR-1K
-> decide direct reference / symlink / transfer
-> download/register Qwen and Opencpop
-> run official and singing raw smoke
-> validate output structure only
```

## 数据复用判断

优先级：

1. local config 直接引用 AST 外部数据绝对路径；
2. 源码仓库外建立统一共享路径或 symlink；
3. 仅在版本、权限或稳定性不满足时保存第二份。

复用的是数据资产，不复用 AST Python 源码和内部运行状态。

## raw smoke 合法结论

允许：

- 模型加载成功/失败；
- 返回空/非空；
- 输出是否可解析；
- timestamp 是否有限、单调和大致在音频范围；
- 某种音频输入发生异常。

禁止：

- 宣称对齐准确或不准确；
- 计算 F1、MAE 或容忍度指标；
- 根据无 GT 输出调阈值、筛数据或冻结模型方案。

## Deferred

- M4Singer/Opencpop 字符 schema；
- MIR-1K 字符 annotation 接入；
- 数据清洗和 split；
- metric；
- projector/head、LoRA 和 trainability audit；
- 正式 baseline 与 held-out test。

## 当前依赖

- 服务器 AST 实际路径与 external 配置；
- 用户本地 M4Singer 与 AST 副本的版本/hash 比较方式；
- Qwen 官方模型实际 revision 和依赖；
- 各数据集中可直接读取的音频—歌词映射。

## Server execution update

- `/home/hyan/Data` resolves to the external AutoDL data disk. M4Singer is complete at
  `/home/hyan/Data/ast_data/m4singer/current` and can be referenced read-only; no new M4Singer transfer is needed.
- M4Singer root `meta.json` supplies existing Chinese `txt` fields keyed by `item_name`; one WAV/text pair is queued
  for smoke without deriving any character boundary.
- MIR-1K `current` resolves to its `prepared` directory and contains readable vocal WAV, but a reliable lyric mapping
  was not audited, so no MIR-1K smoke sample was added.
- The official Qwen model page and Transformers-native call path were verified. Its download began but the large
  weight transfer stalled under Xet, while a standard HTTP retry disconnected. This is a recorded acquisition block,
  not an inference result. No second Qwen variant was downloaded.

## 2026-07-20 closure update

本 session 已由 `20260720_smoke_infrastructure_archive.md` 接替并降为 warm。Qwen 下载与一条 M4Singer short smoke 后续确实完成；旧文中“下载阻塞”只保留为历史 negative result，不再代表当前状态。恢复、证据和 runtime 基础设施已在新 session 修复。
