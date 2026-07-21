
# AI Session Entry

本文件是 GPT / Codex / 其他 AI 的固定入口，只负责导航、当前任务和强约束。

## 必读顺序

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/principles.md`
5. `docs/sessions/20260722_codex_dataset_cleaning_prompt.md`
6. `docs/sessions/SESSION_INDEX.md`
7. 目标目录及上级目录的 `README.md`

## 当前执行阶段

```text
verify server worktree and recover archive omissions
-> audit M4Singer schema and mismatch taxonomy
-> freeze text/character/vocal contracts
-> build high-confidence character subset
-> freeze song split and leakage audit
-> construct synthetic long audio
-> freeze MIR-1K vocal-only OOD manifest
-> implement automatic metric and raw baseline
-> close evidence, tests, docs and Git state
```

## 已确认事实

- 5 条 M4Singer schema-v2 Qwen raw smoke 均成功；
- Transformers source commit 已捕获为 `7ea2320c76117e6742364808a666ef6f2fb40a67`；
- M4Singer preparation 已输出 20,896 items、193,666 character records；
- 6,051 条为自动音素分组候选，14,845 条为 group-count mismatch；
- MIR-1K 原始集已校验，17 首/2,035 字符人工标注已接入为 OOD test-only；
- 数据集模块和准备脚本存在于服务器工作树，但本归档源 ZIP 漏收了它们。

## 合并警告

本包不能对服务器仓库做删除式覆盖。必须先检查并保留服务器上的：

```text
src/lyricalign/datasets/
scripts/datasets/
```

合并后重新生成完整归档和 manifest。本包中的测试收集失败是归档漏收导致，不得错误解释为服务器实现不存在。

## 强约束

- 根目录固定为 `LyricAlignment/`；
- 当前只推进中文 character-level known-lyrics forced alignment；
- 主输入统一为 vocal-only，来源可以是原生、官方声道或固定分离器；
- 原始数据只读，所有转换生成版本化目录和 manifest；
- split 最小单位为 song；MIR-1K 17 首只用于最终 OOD test；
- synthetic concat 与 natural long 必须分开；
- 自动检查不得以模型失败作为单独删除依据；
- 同音伪歌词属于后续副实验，不进入当前主训练数据默认流程；
- 所有阶段必须有可执行入口、单元测试、机器可读摘要、失败恢复和硬验收标准；
- 不允许 placeholder、静默跳过、伪造成功、只写计划不实现；
- 遇到局部失败，应修复根因并继续可独立推进的阶段；只有外部授权或资产确实不可得时才能标记外部阻塞；
- 阶段完成后提交并推送私有 GitHub，记录 commit 与 dirty 状态。

## 当前入口

按 `docs/sessions/20260722_codex_dataset_cleaning_prompt.md` 执行。完成数据自动化闭环前不要启动 LoRA。
