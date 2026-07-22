# AI Session Entry

本文件是 GPT / Codex / 其他 AI 的固定入口，只负责导航、当前事实和强约束。

## 必读顺序

1. `README.md`
2. `docs/status/project_current.md`
3. `docs/sessions/20260723_m4singer_rule_review.md`
4. `docs/status/next_execution_plan.md`
5. `docs/principles.md`
6. `docs/sessions/SESSION_INDEX.md`
7. 目标目录及上级目录的 `README.md`

## 当前执行阶段

```text
M4Singer rule-validated mapping review
-> resolve or retain the remaining 598 review records
-> keep canonical manifests immutable and versioned
-> use the extracted MIR-1K vocal-only OOD subset
-> refresh downstream split/long-audio/baseline only from an explicitly approved manifest
```

## 已确认事实

### M4Singer

- 原始总数：20,896 items；
- character annotation：193,666 rows；
- 当前 operational canonical：20,298 accepted + 598 review + 0 rejected/failed；
- accepted 仅表示 `rule_validated` 候选，不应表述为人工确认的高置信训练集；
- 598 review：487 complex/multiple slur、74 single-slur one-group deficit、36 pinyin parse failure、1 latin/digit；
- mapping-status：531 ambiguous、67 no-match；
- canonical manifest SHA-256：`22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`；
- 历史 6,051/14,845、66、18,057/2,839 均已 superseded。

### MIR-1K

- 用户已人工确认 zero-based channel index 1 为人声；
- 已按交错 PCM 样本直接提取为单声道，而非平均双声道；
- 已准备 17 首、2,035 字符的 vocal-only OOD test-only 子集；
- manifest SHA-256：`bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f`；
- character JSONL SHA-256：`78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9`。

## 当前数据身份

完整路径、hash 和历史版本关系见：

```text
docs/sessions/20260723_m4singer_rule_review.md
```

仓库不保存大型 manifest 本体。外部资产结果以路径、条数和 SHA-256 确认身份。

## 强约束

- 根目录固定为 `LyricAlignment/`；
- 当前只推进中文 character-level known-lyrics forced alignment；
- `rule_validated` 不等同于人工确认的高置信；
- 原始数据只读，派生数据使用版本化目录和 manifest；
- current canonical 不得静默覆盖；规则变化后生成新版本并显式记录替代关系；
- split 最小单位为 song；MIR-1K 17 首只用于 OOD test；
- synthetic concat 与 natural long 必须分开，目标长度口径为 20/30/60/180 秒；
- 自动检查不得以模型失败作为单独删除依据；
- 同音伪歌词属于后续副实验，不进入当前主训练数据默认流程；
- 测试属于工程检查，不替代数据统计、规则审查和人工抽查；
- 轻量证据以复现所需数据身份、规则/配置、关键数量和结果 hash 为主，不强制保存沉重的全量日志副本。

## 当前入口

先读取 `docs/sessions/20260723_m4singer_rule_review.md`，再依据 `docs/status/project_current.md` 判断当前包与外部 canonical 的关系。
