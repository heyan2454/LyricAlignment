# Session: Structure and Data Curation Revision

**Date:** 2026-07-19  
**Temperature:** cold

## 背景

本次只评审和修订项目结构，不把尚未实现代码视为问题。用户明确要求完全移除行级路线，并重新定义核心文档职责。

## 已确认决策

- 不保留任何 line-level 任务、GT、匹配或指标。
- 中文字符级为主；英文 word-level 为备选。
- `README.md` 掌控目录结构、存放边界和导航。
- `AI_SESSION_ENTRY.md` 面向 AI，提供阅读顺序、任务入口和强约束。
- `docs/status/project_current.md` 描述带日期的当时状态。
- `important_records.md` 移除，长期内容迁移为 `docs/principles.md`。
- 主要文件夹和承担多个文件职责的子文件夹使用 `README.md` 分隔范围，便于 AI 导航。

## 数据治理设计

长期保留以下设计：

```text
raw manifest
-> audio validity
-> lyrics normalization
-> duplicate / leakage audit
-> raw-aligner diagnostics
-> quality flags
-> accepted / review_required / rejected
-> manual spot check
-> curated manifest
```

关键风险：模型失败可能来自歌声域差异，而非数据错误，因此 raw aligner 信号只能作为复核线索。

## 资源状态

当时曾将 GPU 描述为“4090 Super”；后续已更正为 AutoDL 32 GB vGPU。当前事实以 `docs/status/project_current.md` 为准。

## Negative / avoided directions

- 未把数据清洗设计成独立大型平台；
- 未提前固化 LoRA rank、target modules 或 batch size；
- 未将 LRC 降级保留为隐藏的行级主指标；
- 未因 raw aligner 失败直接删除数据。

## 当前归档定位

目录职责已迁移到顶层 README、`docs/principles.md` 和 status；数据治理将在后续清洗阶段重新进入执行。因此本 session 只在追溯结构决策时读取。

## Temperature update

2026-07-19：调整为 `cold`。结构与边界决策已被稳定文档吸收，当前资产准备无需频繁读取本 session。
