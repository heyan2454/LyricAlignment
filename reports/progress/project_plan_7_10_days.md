# Initial Short-Cycle Plan

本文件保留短周期推进顺序，不把 7–10 天作为硬期限。

## 已完成：资产与 smoke 基础设施

- 发现并只读复用 M4Singer；
- 下载并登记 Qwen Forced Aligner 指定 revision；
- 完成一条历史 M4Singer 短片段 raw smoke；
- 修复恢复语义、模型身份、轻量证据、runtime 口径和结构诊断；
- 修复资产检查与 OpenCpop 续传脚本；
- 增加环境捕获和小型测试。

历史 smoke 仍缺原 JSON hash 与命令，因此需要 schema-v2 服务器重跑。

## 当前周期 A：服务器验证与 raw smoke

- 合并稳定根目录 `LyricAlignment/`；
- 运行 compile/pytest；
- 捕获 Transformers source commit 和完整环境；
- 官方示例 1 条；
- M4Singer 原生短片段 3–5 条；
- 检查恢复、证据、runtime 和诊断口径。

## 当前周期 B：统一数据清洗

- 音频格式规范化；
- 字符 schema 与 phoneme/syllable/note 映射；
- 异常样本和人工复核状态；
- `native_short`、`synthetic_concat`、`natural_long` 类型；
- 同曲相邻片段构造 20/30/60/180 秒 bucket；
- song-level split 与切片包含泄漏审计。

## 后续周期

- metric fixture 与单元测试；
- raw baseline 和长短长度退化分析；
- projector/head 与 audio-tower LoRA；
- 冻结后的 held-out evaluation。

## 当前结论强度

已证明最小短片段调用链可以返回结构化结果，但尚未证明准确率、长音频稳定性、正式 runtime 或训练收益。
