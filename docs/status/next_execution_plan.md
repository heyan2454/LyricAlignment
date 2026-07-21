
# Next Execution Plan: Dataset Cleaning Automation Contract

本计划是当前 Codex 的执行合同。目标不是只产出分析报告，而是完成所有不依赖外部授权的自动化代码、测试、运行与证据。不得在首个错误处停止，不得使用 placeholder、空实现、静默跳过或降低验收标准来宣称完成。

## 通用执行规则

每个阶段必须同时具备：

1. 核心库实现位于 `src/lyricalign/`；
2. 可复现薄入口位于 `scripts/`；
3. 配置/规则版本明确；
4. 单元测试与最小 fixture；
5. 外部输出目录不覆盖原始数据；
6. 原子写入、可恢复、显式覆盖策略；
7. 机器可读 run summary；
8. 人类可读轻量报告；
9. 验收命令和返回码；
10. Git commit、dirty 状态和阶段结论。

阶段失败时：先定位并修复根因；仍可独立推进的阶段继续完成。只有外部授权、数据资产确实不可得或硬件不可用时，才能标为 external blocker。不得把实现困难标成 blocker。

---

## Stage 0：服务器工作树与归档完整性恢复

### 实现

- 检查服务器已有 `src/lyricalign/datasets/` 和 `scripts/datasets/`；
- 合并本归档时保留服务器实现；
- 检查 Git branch、remote、commit、dirty diff；
- 修复归档收集规则，使测试引用的项目内模块必然进入包；
- 增加 archive self-check：导入测试中的 `lyricalign.*` 模块、对比 manifest 和实际 ZIP 文件。

### Gate S0

必须满足：

```bash
python -m compileall -q src scripts tests
python -m pytest -q
```

- compile 返回 0；
- pytest collection 无错误；
- 已有测试至少全部通过；
- archive self-check 通过；
- 不删除服务器独有的数据集实现。

未通过 S0 不得宣称归档修复完成，但应继续审计可独立执行的外部资产。

---

## Stage 1：M4Singer schema、音频与 mismatch 全量审计

### 实现

建立 `audit_m4singer.py` 及核心审计模块，统计：

- 必需字段存在性与类型；
- `phs/ph_dur`、`notes/notes_dur` 等长度关系；
- `sum(ph_dur)` 与音频时长误差；
- WAV 可读性、采样率、声道、编码、时长；
- 特殊 token、标点、空格、数字、英文、儿化、衬词；
- song/singer/item 序号与相邻关系；
- 当前 14,845 条 mismatch 的可解释 taxonomy。

至少区分：

```text
punctuation_or_space
special_non_lyric_token
mandarin_syllable_parse_failure
slur_or_repeated_vowel
latin_or_digit
lyrics_phoneme_count_mismatch
duration_metadata_mismatch
audio_metadata_invalid
unknown
```

每类保存统计和小型代表样本，不把完整 per-item 大文件放入 Git。

### Gate S1

- 20,896 items 全部被审计，`processed + failed == total`；
- 所有失败有 error code，不允许静默丢失；
- taxonomy 总数与 mismatch 总数守恒；
- `unknown` 比例必须被报告；若过高必须继续细分，不能只把大多数样本塞入 unknown；
- 生成 JSON summary、JSONL/Parquet 外部诊断和 Markdown 报告；
- 重跑相同输入结果确定性一致。

---

## Stage 2：`text_normalization_v1`

### 实现

保留：

```text
lyrics_raw
lyrics_normalized
raw_to_normalized_map
normalized_to_raw_map
normalization_version
normalization_flags
```

v1 可自动处理 Unicode、全半角、不可见字符、排版空格和标点分离。不得静默进行简繁转换、数字改写、英文发音改写或删除括号语义内容。

### Gate S2

- 映射可回溯到原文；
- 规范化幂等；
- 覆盖中文、标点、空格、全角字符、数字、英文、中英混排、括号、衬词 fixture；
- 无字符被无记录删除；
- 版本与规则 hash 写入 manifest。

---

## Stage 3：`character_mapping_v1` 与高置信 M4Singer 子集

### 实现

采用：

```text
phoneme token -> Mandarin syllable group -> normalized character -> character interval
```

每个字符保存：

```text
char_index
character
start_sec
end_sec
source_phoneme_indices
source_note_indices
mapping_method
mapping_confidence
quality_flags
```

映射状态至少包括：

```text
accepted_exact
accepted_rule_based
review_special_token
review_ambiguous_syllable
review_text_phoneme_mismatch
review_duration_mismatch
rejected_metadata_invalid
```

不得为提高覆盖率而伪造边界。允许第一版只形成高置信子集。

### Gate S3

- 所有 accepted 字符时间戳有限、非负、`start <= end`、单调且不越出音频容忍范围；
- accepted item 的字符数与 normalized target 字符数一致；
- 每个字符可追溯到原音素/音符；
- 状态数量守恒；
- 对 accepted_exact、accepted_rule_based 和各 review 类进行分层抽样报告；
- 规则单测和全量运行均通过；
- 输出高置信 train-candidate manifest，但不在此阶段划分 test。

---

## Stage 4：vocal-only 音频合同与规范化

### 实现

主输入只使用：

```text
native_vocal
official_vocal_channel
model_separated_vocal
```

先生成 inventory，再根据模型 processor 冻结目标格式。默认候选为 mono、16 kHz、WAV PCM16；正式值必须写入 `audio_contract_v1`。

模型分离人声必须保存：separator 名称、版本/权重 hash、配置、输入 hash、输出 hash、转换工具版本。

### Gate S4

- 原始文件只读；
- 转换使用临时文件 + atomic rename；
- 相同输入/hash 跳过，冲突时报错，覆盖需显式参数；
- 输出可解码、样本数/时长误差在明确容忍内；
- 不默认做响度归一化、降噪或额外后处理；
- 生成按 `vocal_source_type` 分层的 inventory 和质量摘要。

---

## Stage 5：质量分层

### 实现

将数据分为 A/B/C，而不是不可解释删除：

- A：高置信可训练；
- B：可疑、待复核或后续鲁棒训练候选；
- C：明确不可用且原因可复查。

模型 raw aligner 失败不得单独触发 C。

### Gate S5

- 每个 item 恰好一个主状态；
- 每个 B/C 有机器可读 reason code；
- 汇总数量与输入守恒；
- 自动规则精度通过分层抽样估计；
- 原始记录和所有派生版本可追溯。

---

## Stage 6：song-level split 与泄漏审计

### 实现

- M4Singer 按 song 划分 train/custom validation；
- MIR-1K 17 首固定 OOD test-only；
- OpenCpop 未获取时保留其官方角色，不伪造 split；
- 检查 title/artist、歌词 hash/n-gram、音频 hash/指纹、完整歌曲与切片包含、cover overlap。

### Gate S6

- 同一 song 不跨 split；
- 同曲 short、synthetic concat 和其他派生样本继承同一 split；
- MIR-1K 不出现在 train/validation；
- 冻结 split manifest、seed、规则和 hash；
- 泄漏报告列出所有候选冲突及处置，不静默忽略。

---

## Stage 7：synthetic-long 构造

### 实现

仅拼接同歌曲、顺序可验证的相邻片段，目标 bucket：20/30/60/120 秒。保存：

```text
source_item_ids
source_order
cumulative_offsets
join_points_sec
seam_mask
silence_inserted_sec
shifted_character_timestamps
split
output_hash
```

主版本先使用无额外静音的顺序拼接；插入静音只能作为独立配置。

### Gate S7

- 时间轴平移单元测试通过；
- 输出时长与源片段累计时长在容忍内；
- 字符顺序、数量和边界合法；
- 不跨 song、不跨 split；
- 所有接缝显式标记；
- 各长度 bucket 数量和失败原因完整报告；
- synthetic 不能标记为 natural long。

---

## Stage 8：MIR-1K vocal-only OOD 冻结

### 实现

- 使用官方 vocal channel 作为主 OOD 音频；
- 17 首/2,035 字符标注转换为正式 manifest；
- 校验歌词字符、时间戳、音频时长、hash 和数据角色；
- 可选 mixture 只作为单独辅助条件，不进入主指标。

### Gate S8

- 17/17 音频和标注通过；
- split 固定为 test，usage 固定为 ood_test_only；
- 无 train/validation 引用；
- 主输入均为 `official_vocal_channel`；
- manifest hash 冻结并写入状态文档。

---

## Stage 9：自动 metric fixture 与评测执行器

### 实现

一次命令完成：预测读取/执行、schema 校验、逐样本 metric、micro、per-song macro、时长与来源分层、失败统计、JSON/CSV/Markdown 输出。

fixture 至少覆盖：perfect、global shift、missing、extra、duplicate、zero-duration、overlap、reverse order、large gap、late drift、seam error。

严格区分 overlap 与逆序。

### Gate S9

- perfect fixture 达到预期满分；
- 各扰动 fixture 与手算预期一致；
- micro 和 macro 口径有独立测试；
- 输出包含模型身份、manifest/config hash 和 metric schema version；
- 样本缺失、重复 ID、hash 不一致、非法时间戳必须 hard fail；
- 全流程可恢复，失败样本不会被当作成功跳过。

---

## Stage 10：自动 Qwen raw baseline

### 实现

在冻结 manifest 后，对：

- M4Singer native short validation；
- M4Singer synthetic-long 各 bucket；
- MIR-1K natural-long vocal-only OOD；

自动运行并评测。保存完整逐样本结果到外部，仓库内只保存轻量摘要和 hash。

增加 zero/near-zero duration、前后段漂移、大片 gap 和时长 bucket 诊断。

### Gate S10

- 所有目标样本都有 success 或显式 failure record；
- 模型、revision、代码/config/manifest/input identity 完整；
- 相同身份成功结果可恢复跳过，任何身份变化会重跑；
- 分别报告 native_short、synthetic_concat、natural_long；
- 不将 synthetic 结果冒充真实长音频结论；
- 不基于 OOD test 调阈值或修改规则。

---

## Stage 11：阶段关闭、文档与 Git

### 实现

- 更新 README、entry、status、manual、dataset registry 和 session；
- 记录 negative results、unknowns、人工依赖、外部 blocker；
- 保存各 stage gate 结果与命令；
- 生成 archive manifest 并从解压后的 ZIP 二次验证；
- commit 并 push 到 private GitHub；
- 输出下一阶段训练建议，但不自动启动 LoRA。

### Gate S11

- compile/tests 全通过；
- 所有已执行阶段 gate 状态可机器读取；
- Git commit 已记录，工作树 clean 或 dirty 内容被解释；
- 大文件/per-item 产物未进入仓库；
- archive manifest 与 ZIP 实际内容完全一致；
- 下一入口无需依赖聊天上下文即可执行。

---

## Deferred：同音伪歌词鲁棒性副实验

当前只需预留 schema，不作为主清洗 gate。后续自动生成：

- 原始歌词；
- 同音同调随机常用字；
- 同音节异调；
- 错音控制；
- 局部顺序打乱。

使用固定 seed 和逐字符替换映射。用途是评估字符/语义依赖，以及需求数据是否可接受较低标准文字标注；不能单独证明模型没有记忆训练数据。

## 当前禁止

- 自动化闭环完成前启动 LoRA；
- 使用 MIR-1K 训练或调参；
- 为提高 accepted 比例伪造字符边界；
- 以 Qwen 失败为删除 GT 的理由；
- 把模型分离人声与原生人声静默混合；
- 把 synthetic concat 当 natural long；
- 用 placeholder、TODO、空 CSV 或仅报告替代实现；
- 因一个阶段困难而终止所有后续独立工作。
