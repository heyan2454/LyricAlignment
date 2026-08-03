# LyricAlignment 下一阶段执行计划

## 历史实验结论修复与生产型不合法输入行为研究

**计划版本：research_v7_align_behavior**  
**日期：2026-08-03**

---

# 0. 阶段目标

本阶段分为两个严格隔离的部分。

## 阶段 A：修复历史实验结论

修复已确认的指标和报告问题，使 E0–E9 可以可信归档。原则上不重新进行昂贵模型推理，也不继续调旧方案参数。

必须完成：

1. 修复 E1 event-level 跨 item 聚合错误；
2. 重算 E5、E6 的同子集 paired baseline；
3. 给所有条件指标补充明确分母；
4. 明确 E2、E3、E5–E9 的结论状态和去留；
5. 生成修正后的 formal 报告、provenance 和验证脚本。

## 阶段 B：集中研究 Alignment 行为

重点研究实际生产中可能出现的“不合法输入”：

- 输入歌词多于当前音频实际包含的内容；
- 输入歌词少于当前音频实际包含的内容；
- 歌词与音频仅部分对应；
- 歌词完全不对应；
- 文本起点、音频起点或串行 cursor 错误；
- 同一歌词在歌曲中出现多次；
- 完整长音频配短文本；
- 严格串行少量多次是否吞字、重复或传播错误；
- sparse timestamp slots 是否比孤立短文本更符合模型行为；
- posterior、raw、official、repair trace 和串行状态在正确与错误输入下有何差异。

本阶段优先回答：

> Aligner 面对不同类型的不合法输入时会以什么方式失败；哪些信号在正确区、错误区、误判区和漏判区之间存在稳定差异。

不以训练一个新 detector 为首要目标。先建立数据、行为分类和信号统计，再决定 QualityAssessor、decoder 或 coarse localization 的实现。

---

# 1. 基本假设与禁止事项

## 1.1 默认路径

```bash
REPO=/home/hyan/LyricAlignment
DATA_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign
```

实际代码必须支持环境变量覆盖，不得在 Python 中写死机器路径。

## 1.2 模型基线

从已有 formal provenance 读取，不得自行猜测。当前预期为：

- Qwen3-ForcedAligner-0.6B；
- R2 step-000750；
- Demucs vocal 为主要推理输入；
- official decoder 为生产展示基线；
- raw、top-K、weighted isotonic 同时作为研究证据保存。

## 1.3 禁止事项

1. 不得使用 GT 时间裁出 production-like 实验的目标音频；
2. 不得根据 test/heldout 结果继续调阈值并仍称 heldout；
3. 不再调 E5 exact/−2/−4；
4. 不再搜索 E6 silence cap；
5. 不修复或扩大 E3 decoder-only local repair；
6. 不让旧 detector 自动修改正式对齐；
7. 条件指标必须给分子、分母和非空数量；
8. 无 GT 共识不能称为 accuracy 或 pseudo-GT；
9. M4Singer train 不得混入主 heldout 结论；
10. 不得为完成报告补造数据；
11. 不得在 formal 中临时删去不利 mutation 或增加有利阈值；
12. 不得把 no-match、多解重复副歌和同歌错段混成同一种错误。

---

# 2. 工作目录

```text
docs/research_v7_align_behavior/
scripts/research_v7/
tests/research_v7/
configs/research_v7/
runs/research_v7_align_behavior/
```

建议脚本：

```text
repair_e1_event_metrics.py
recompute_e5_e6_paired.py
audit_conditional_denominators.py
build_behavior_manifest.py
run_alignment_behavior.py
collect_alignment_behavior.py
analyze_alignment_behavior.py
render_alignment_behavior_cases.py
build_no_gt_review_bundle.py
verify_research_v7_outputs.py
```

旧 formal 输出不得覆盖。所有修正结果写入新的 v7 目录，并引用原始输出身份。

---

# 3. 阶段 A：历史结论修复

## A1. E1 event-level

事件必须先按至少 `item_id` 分组，推荐身份：

```text
dataset / source_song_id / item_id
```

每个 item 内合并连续 reference/prediction event，再做 one-to-one matching。输出：

- micro event precision/recall/F1；
- item macro event F1；
- source-song cluster bootstrap；
- 数据集和 event length 分层；
- reference/prediction event 数量。

测试必须覆盖跨歌曲相同字符索引不会合并、空集合、多对一 matching 等。

优先从原 detector rows 重算；若轻量 evidence 缺失，读取原 formal OUT_ROOT。只有逐 item detector rows 不存在时才重新运行 detector 分析，不得重新模型 inference。

## A2. E5 同子集 paired 重算

在完全相同的 E5 applicable item 上比较：

- fixed baseline；
- dynamic exact；
- dynamic −2；
- dynamic −4。

输出每 item 的 candidate-baseline delta、macro/micro、source-song bootstrap、improve/harm/no-change、cursor、seam-near/far、runtime 和 boundary movement。

完成后停止调参数，仅保留代表失败 case。

## A3. E6 同子集 paired 重算

在同一 silence-applicable item 上比较：

- baseline；
- hard core/full context；
- cap4；
- cap1.5；
- cap0.4。

额外报告静音前后、cursor、boundary jump、压缩量及 1.5–4、4–10、10 秒以上分层，始终明确样本数。

完成后归档为当前组合式静音处理的负结果，不继续扫 cap。

## A4. 条件分母审计

每个条件指标必须输出：

```text
total_count
applicable_count
attempted_count
completed_count
non_null_count
success_count
failure_count
numerator
denominator
rate
```

重点审计 E5、E6、E7 reset、E8 selection/clean harm/continuation/oracle、E9 multi-candidate/oracle、supplemental 和所有跳过 None 的均值。

## A5. 历史状态冻结

- E0：场景依赖，可用；
- E1 unit：旧 detector 极弱，强负结论；
- E1 event：旧结果 invalid，修复后再报告；
- E2：旧 detector 结论退役，mutation 工具保留；
- E3：停止；
- E4-old：oracle/localized upper bound；
- E5/E6：修正后负结果归档；
- E7：旧 reset 不完整，保留有限负证据；
- E8：rerun/continuation 框架保留，自动选优失败；
- E9：旧实验不能否定有界 request pool，暂停。

---

# 4. 最小数据契约

## AlignmentRequest

保持简单，只描述“这次模型收到什么”：

```python
@dataclass(frozen=True)
class AlignmentRequest:
    request_id: str
    item_id: str
    parent_request_id: str | None
    audio_source: str
    audio_start_sec: float
    audio_end_sec: float
    text_source: str
    text_start_index: int
    text_end_index: int
    text_units: list[str]
    timestamp_slot_indices: list[int] | None
    workflow_mode: str
    mutation_type: str
    mutation_parameters: dict[str, object]
    model_id: str
    checkpoint_id: str
    input_variant: str
```

## AlignmentAttempt / Evidence

每次 attempt 保存：

- raw、official、top-K、weighted；
- cursor/previous_end before/after；
- committed/provisional；
- runtime/status/error；
- posterior top-16 或 top-32；
- entropy、margin、远距离第二峰；
- official repair trace；
- parent request lineage；
- GT 只作为 evaluation 字段；
- 人工评论和自动 failure taxonomy。

EvidencePack 是每次 attempt 的不可变 cache，不要求一次 pack 包含整个动态流程。多个 pack 通过 parent ID 构成 lineage。

---

# 5. 数据与切分

## GT controlled

- M4Singer validation：开发/pilot；
- M4Singer test：冻结 formal；
- MIR-1K test：OOD；
- synthetic-long heldout：长程和串行。

Production-like request 不得使用 GT 裁音频；GT 仅在运行后评价。只有 `oracle_control` 可使用 GT localization。

## 无 GT Demo

必须拆成：

- demo_dev；
- demo_validation；
- demo_heldout；
- demo_challenge。

按音频哈希、标题和人工检查避免重复。被用户反复评论并用于修改的歌曲自动归入 dev。

---

# 6. 合法 baseline

冻结当前 fixed 60s production baseline：

- 不使用 E5；
- 不使用 E6 时间压缩；
- 不自动 realign；
- official 为正式输出；
- raw/top-K/weighted 和 posterior 同时保存；
- 使用真实文本 cursor 和 commit 流程。

所有 mutation 与同 item 合法 baseline paired 比较。

---

# 7. 文本量严重度：以百分比为主

设合法 baseline 文本长度为 `N_base`。

过量比例：

```text
+10%, +25%, +50%, +100%, +200%
```

缺失比例：

```text
10%, 25%, 50%, 75%, 90%
```

替换/不对应比例：

```text
10%, 25%, 50%, 75%, 100%
```

每条记录同时保存 requested ratio、actual ratio 和绝对 unit 数。`+2/+5` 只作为 smoke/微扰，不作为 formal 主曲线。

---

# 8. 核心行为实验

## C1. 尾部过量文本

比例：+10/+25/+50/+100/+200%。来源必须分开：

1. 额外文字已存在于当前 lookahead；
2. 同歌正确未来歌词，但不在当前音频；
3. 部分存在、部分不存在；
4. 正确顺序但远期才出现；
5. 追加跨歌错误文本。

观察合法 core 的 raw/official/posterior 是否变化，多余字是否尾帧吸附、零时长、均匀铺开，以及 strict serial cursor 是否过度消费并跳过后续真实歌词。

## C2. 头部过量

比例：10/25/50/100%，来源包括重复 committed prefix、前一段真实歌词、同歌其他段、跨歌错误歌词。头部会影响后续因果 slots，重点观察整体后移和持续 cursor 污染。

## C3. 中间插入

在文本 25/50/75% 位置插入 10/25/50/100%。来源包括重复前文、future text、同歌错段、跨歌真实歌词。观察插入点前后的分界、是否局部恢复和 posterior 模式切换。

## C4. 文本不足

尾部、头部、中间连续和分散缺失分别测试 10/25/50/75/90%。观察拉伸、边界吸附、后半段重定位、cursor under-consumption 和恢复。

## C5. 部分替换

保持总长度不变，将头/中/尾/分散的 10/25/50/75/100% 替换为 donor text，形成从合法到 no-match 的连续响应曲线。

## C6. 完全不对应文本

主实现不是随机字符串，而是同语言、同 unit mode、同长度、跨歌曲连续真实歌词。另分开：

- 同一歌曲错误段；
- 重复副歌多解；
- 行/句顺序打乱；
- 纯器乐区配真实歌词；
- 随机/置换文本机制对照；
- 错语言/错 unit mode 极端 OOD。

### Cross-song strict no-match donor 规则

- donor song != target song；
- language/unit mode 相同；
- 连续片段长度等于 N_base；
- normalized LCS、最长连续匹配、n-gram overlap 和可用的 phonetic similarity 低于冻结阈值；
- 固定 seed；
- 保存 donor song/index/相似度；
- pilot 后冻结 donor manifest 和 SHA256。

No-match 不计算 donor MAE。评价输出几何、decoder 干预、posterior、request sensitivity、外部兼容度和 strict serial 后果。

## C7–C9. 音频范围不合法

- audio start 提前/延后，并加入按文本缺失比例定义的裁切；
- audio end 延长/提前；
- 音频只覆盖文本前半、后半或中间。

绝对秒数与比例同时保存，避免不同语速不可比。

## C10. 重复副歌与多解

音频包含一次/两次副歌，输入整段或短片段，改变串行历史和 slot mask。区分正确、多峰、多解、稳定错段和多段分裂。

---

# 9. 新 E4：生产型结构比较

所有 production 路线使用同一个 planner 生成的长音频 A，不根据 GT 为每个 chunk 裁音频。

## P0 一次全量

```text
Align(A, L[0:96])
```

## P1 同一长音频、严格串行短文本

每次给约 32 units，按真实 commit/cursor/provisional workflow 推进；三次始终使用同一个 A，不使用 GT 修正 cursor。必须记录吞字、重复、过度/不足消费和最终覆盖。

## P2 递进裁音频严格串行

下一次从 predicted_end-left_context 开始，单独衡量 audio crop 传播。

## D 非串行独立诊断

三段短文本独立使用同一个 A，不传 cursor。只用于区分模型定位能力和状态传播问题。

## S 严格串行 sparse slots

扩展 processor，不改模型主体：

- 第一次 L[0:31]，0–31 有 slots；
- 第二次 L[0:63]，仅 32–63 有 slots；
- 第三次 L[0:95]，仅 64–95 有 slots。

保存实际 token、slot mapping，并测试数量一致性和 causal 左上下文影响。

## O oracle localized upper bound

保留旧 E4，只表示 localization 已解决时的上限。

---

# 10. 串行状态

研究：

- cursor ±2/4/8；
- 重复 committed prefix 按 10/25/50% 或代表绝对数；
- 全提交 vs 最后 8/16 字、10 秒或句段 provisional；
- 正确输入恢复后的传播与恢复次数。

旧 E7 的 reset 没有回滚 committed prefix、window plan 和 crop，不能沿用其“full reset”定义。

---

# 11. 内部与辅助证据

## Posterior

保存 top-16/32、entropy、margin、mean/variance、局部 mass、远距离第二峰和 start/end 冲突。

## Official repair trace

保存 raw、LIS membership、repair 类型、移动距离、最长 repair span、尾部无右锚、修复后零时长和重复时间。

## Hidden states pilot

仅 pilot 保存中间层、倒数第四层和最后一层 timestamp-slot hidden state。若没有明显分离，不全量保存。

## 辅助音频

先使用 vocal activity、RMS、onset、silence、phrase/repeat structure。ASR/音素作为 pilot；不得默认同时常驻两个 0.6B 模型。

---

# 12. Failure taxonomy

至少包括：

```text
VALID_STABLE
VALID_BUT_UNCERTAIN
TAIL_COLLAPSE
HEAD_COLLAPSE
UNIFORM_STRETCH
START_ATTRACTION
END_ATTRACTION
PARTIAL_MATCH_REMAINDER_COLLAPSE
WRONG_REPEATED_SECTION
MULTI_SECTION_SPLIT
GLOBAL_SHIFT
LOCAL_SHIFT
ZERO_DURATION_CLUSTER
DECODER_REPAIR_DOMINATED
REQUEST_SENSITIVE_SWITCH
STABLE_WRONG_ALIGNMENT
CURSOR_UNDER_CONSUMPTION
CURSOR_OVER_CONSUMPTION
DUPLICATE_COMMIT
MISSING_COMMIT
RECOVERED_NEXT_ATTEMPT
PERSISTENT_PROPAGATION
UNRESOLVED
```

允许多标签，保存自动标签和人工复核标签。

---

# 13. 指标与分析

除了 GT MAE，还必须报告：

- localization error thresholds 0.25/0.5/1/2/5 秒；
- chunk 顺序、gap/overlap、重复段选择；
- cursor over/under consumption、duplicate/missing、最终覆盖；
- 首尾吸附、零时长、uniform spread、repair ratio/run；
- posterior entropy/multimodality；
- request、slot-mask、cross-view stability；
- catastrophic failure；
- 无 GT 人工 errors/min、严重错误时长、最长错误、盲评和 unresolved。

所有 mutation 与合法 baseline paired，按 dataset/source song/language/duration/text length/severity/decoder/workflow 分层。输出 macro、micro、source-song bootstrap、分母和 improve/harm/no-change。

---

# 14. 执行阶段

1. Stage 0：代码、环境、provenance 和原 formal 输出审计；
2. Stage 1：历史修复；
3. Stage 2：每个 mutation 单 case smoke；
4. Stage 3：controlled pilot，冻结比例、donor、commit policy、slot 实现；
5. Stage 4：formal GT behaviour；
6. Stage 5：demo_dev 多路线和 review bundle；
7. Stage 6：冻结后 demo_validation/heldout；
8. Stage 7：综合报告，区分观察、解释、替代解释和结论强度。

Pilot 结束必须生成 `pilot_freeze.json` 和 donor manifest SHA256。

---

# 15. 运行、resume 与缓存

每个 attempt identity 至少包含：

- audio hash/range；
- text hash/indices；
- slot mask；
- model/checkpoint；
- decoder；
- workflow；
- mutation；
- code version。

发现 mismatch 必须停止，不能只依赖 OUT_ROOT。Collection 必须在 visualization 前；render 失败不能破坏分析结果。

---

# 16. 结果决策树

- P1 > P0：继续少量多次和 provisional；
- D 有效但 P1 失败：主要是 controller/cursor；
- S > P1：优先 sparse slots；
- P1/D/S 都失败但 O 成功：需要 coarse localization；
- 尾部过量只伤额外字：采用 provisional 和低可信尾字不消费；
- official 改坏 core：开发 posterior-aware decoder或可信 prefix 解码；
- 内部信号可分：进入学习式 QualityAssessor；
- 内部信号不可分：必须引入独立 correspondence 信号。

---

# 17. 成功标准

本阶段成功不是只看 MAE，而是：

1. 旧结论得到可信修复和冻结；
2. 建立 production-like mutation framework；
3. 完成严格串行与 sparse-slot 新 E4；
4. 明确不同位置和比例的过量/不足文本行为；
5. 明确 no-match、多解和音频范围错误的失败形态；
6. 建立 posterior 和 repair trace；
7. 建立无 GT 结构化数据；
8. 找到可区分信号，或可靠证明内部信号不足；
9. 能决定下一步应改 controller、decoder、localization 还是 QualityAssessor。

最终产出应是一套可解释 Aligner 在合法、不完整、错误和多解输入下行为的可复现证据体系。
