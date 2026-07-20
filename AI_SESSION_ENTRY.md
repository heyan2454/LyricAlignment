# AI Session Entry

本文件是 GPT / Codex / 其他 AI 的固定入口，只负责导航、当前任务和强约束。

## 必读顺序

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/status/next_execution_plan.md`
4. `docs/principles.md`
5. `docs/sessions/SESSION_INDEX.md`
6. 目标目录及上级目录的 `README.md`

## 当前执行阶段

```text
merge and verify smoke-infrastructure archive
-> run local tests and capture exact server environment
-> rerun official/M4Singer schema-v2 raw smoke
-> enter unified data cleaning
```

## 已实现能力

- Qwen Forced Aligner 最小推理封装；
- revision/config/input-aware resume；
- 逐样本模型身份与输入 hash；
- 分阶段 runtime；
- overlap、gap 与真正逆序分离诊断；
- 轻量 run evidence；
- 资产检查、断点下载和环境捕获脚本。

不得继续把代码或脚本描述成“尚未实现”。但服务器上的 schema-v2 smoke 尚未重新执行，也不得把本地测试描述成模型实测。

## 强约束

- 根目录固定为 `LyricAlignment/`，只有 archive、run 和 session 名称使用后缀；
- 当前只推进中文 character-level；英文 word-level 为未来备选；
- 数据和模型只读复用优先，不因目录整齐复制大资产；
- raw smoke 不使用 GT，不计算 metric，不宣称准确率；
- 5 秒 smoke 不能证明长音频稳定；
- 长音频构造与统一音频格式纳入数据清洗，不在 smoke 基础设施中另建临时管线；
- 未来 manifest 必须区分 `native_short`、`synthetic_concat`、`natural_long`；
- 完整模型响应、音频、权重和大日志不进入 Git；
- Transformers 源码开发版必须记录实际 commit，只有 `dev0` 版本号不构成精确锁定；
- 失败、未知、旧证据缺口必须保留，不能补造 hash 或执行事实。

## 当前入口

按 `docs/status/next_execution_plan.md` 执行。先在服务器验证本包、运行测试、捕获环境并重新做 schema-v2 smoke，再进入数据清洗；不要提前开始 LoRA。
