# 2026-07-27 Raw decoder、guarded realign、Demo 与 follow-up 实验会话记录

## 1. 会话范围与目标

本会话从 `realign_quick_v2_1` 的 overnight 交接包出发，核心目标逐步演化为：

1. 评审原有 overnight 设计，重点判断能否利用 MIR-1K 与 M4Singer 的较大规模数据优化真实 Demo；
2. 重新审视 `raw timestamp → 初步 decoder → 串行提交 → local realign` 各层职责；
3. 在不造成 CPU 密集瓶颈的前提下尝试 GPU decoder；
4. 使用真实 overnight 结果选择当前更可靠的 Demo 主干；
5. 建立可量化的 detector / repair PRF 与误改分析；
6. 将 Demo 恢复为可直接按文件、名字或文件夹运行、可选择语言、可进行人声分离与视频渲染的完整应用；
7. 实现后续 E0–E5 实验入口，同时保持数据、指标和 held-out 使用口径清楚；
8. 修复 patch 基线不一致和遗漏文件问题，提供可恢复的 safe overlay。

本记录不仅保存最终结果，也记录问题来源、方案取舍、预期、负结果与下一步依赖。

---

## 2. 初始问题与约束

### 2.1 原 overnight 设计的不足

最初方案主要延伸 Quick v2.1，在少量 MIR-1K 歌曲上扩展上下文、注入和 selector 组合。主要风险是：

- 调用次数可能很多，但不一定等于真正使用了大量数据；
- `raw → processor decoded` 被当作固定前处理，没有单独评测；
- processor decoded 会影响窗口归属、下一窗歌词 cursor 和最终提交，因此错误可能沿串行状态传播；
- local realign 可能只是在补偿初步 decoder 或 commit 的问题；
- 若直接展开 decoder × 窗口 × 音频 × 上下文，容易形成无效笛卡尔积。

### 2.2 用户明确约束

用户进一步明确：

- 新 decoder 不能成为 CPU 密集型，应以 GPU 批处理为主；
- realign 应在原 decoder 和新 decoder 上都进行大量测试；
- 数据量大时必须避免完整笛卡尔积；
- 需要核实 M4Singer 的“样本”到底按 item、歌曲还是独立异常计数；
- Demo 最终应保持之前应用的完整功能，包括视频渲染、语言参数、按名字寻找文件和文件夹处理；
- 默认人声分离应使用 Demucs，而不是 Spleeter；
- 需要清楚定义 raw、baseline、guarded、final；
- 需要能够测量错误检测 PRF、正确区域误检与实际误改，而不是只看候选平均 MAE。

---

## 3. 数据盘点与实验单位

### 3.1 M4Singer

从 overnight 输入审计和缓存结果确认：

- 可用 label item：20,298；
- 唯一歌曲：419；
- 唯一歌手：20；
- 字符标注：187,385；
- train：17,748 item；
- validation：1,711 item；
- test：839 item。

本次 decoder 缓存实际使用 train + validation：

- 19,459 item；
- 400 首歌；
- 20 位歌手；
- 358,704 个 timestamp slot；
- 77 个缓存 shard。

因此，M4Singer 远超过 1,000 个 **item**。但不能据此声称存在 1,000 个独立自然异常，因为：

- 多个 item 来自同一歌曲；
- 自然异常率需要在 baseline 扫描后统计；
- item 数、歌曲数、歌手数和异常数必须分别报告。

### 3.2 MIR-1K 字符 GT 子集

当前 inventory 有 17 个可用 item，角色包括：

- development：8；
- heldout：4；
- quick_v2_extra：4；
- spare：1。

本次 overnight 使用 development + quick_v2_extra，并固定：

- Demucs 人声；
- 30 秒 core；
- held-out 不参与调参。

该角色划分必须继续保持。development 上看到结果后可以调整参数；held-out 只能在参数冻结后单独运行一次。

---

## 4. Raw、official decoder 与串行提交的重新理解

### 4.1 Raw

`raw` 指 Qwen timestamp slot 的 argmax 时间类别，即官方 processor 单调修正之前的直接模型输出。

Raw 不是完整 Demo 输出，因为它仍需要：

- 将每个窗口输出映射回整曲；
- 决定窗口 core 内哪些字符提交；
- 维护下一窗歌词输入起点；
- 合并 overlap；
- 保证最终结构可序列化和渲染。

### 4.2 Official decoder

官方 processor decoder 的核心是对 start/end 边界序列进行单调修正，包括最长非降子序列、异常段吸附或插值。它可以修复逆序，但也可能把多个边界压到同一时刻。

### 4.3 Baseline

本项目中的 `baseline` 或 `raw baseline` 指：

> 使用 raw timestamp 作为边界来源，完成完整串行分窗、core 归属、cursor 推进、冻结前缀和 overlap 合并后的整曲对齐，但还没有执行 local realign。

因此 baseline 已是可渲染的整曲输出，不等同于单个窗口的 raw tensor。

### 4.4 Guarded

`guarded` 不是另一种全局 decoder，而是局部干预机制：

1. 宽松检测可疑区间；
2. 用 exact 和 matched +2 两种输入重新推理；
3. 检查两个结果是否一致；
4. 检查结构异常是否减少；
5. 检查最大边界改动是否受控；
6. 只有通过安全门才写回 baseline。

### 4.5 Final

`final` 或 `guarded final` 是 baseline 应用所有通过安全门的局部修复后的最终结果。若没有 repair 通过，final 与 baseline 完全相同。

---

## 5. GPU decoder 设计与目的

### 5.1 设计目的

原计划希望使用 M4Singer 大量数据学习一个比 official processor 更好的初步 decoder，并满足：

- 训练和推理以 GPU 为主；
- 共享一次 Qwen 特征缓存，避免反复调用大模型；
- 同时比较不同结构，不预设 TCN 最优；
- 与 official decoder 使用相同 MIR-1K case 和 realign funnel。

### 5.2 实现的 decoder

实现了两种 GPU decoder：

- `gpu_tcn`：残差膨胀 TCN，约 2.22M 参数；
- `gpu_transformer`：轻量双向 Transformer Encoder，约 2.57M 参数。

两者共享：

- 16 维 timestamp 特征；
- raw argmax、top-k、margin、entropy 等缓存；
- residual timestamp head；
- repair gate；
- GPU 单调投影；
- M4Singer train/validation split；
- MIR-1K paired realign case。

### 5.3 Smoke validation 缺失问题

第一次 smoke 报错：

```text
ValueError: decoder training requires validation items
```

根因不是 M4Singer 没有 validation，而是 Smoke 的 16 条 item 在 train+validation 合并排序后直接截断，前 16 条全部来自 train。

修复方式：

- 小样本缓存按 split 分层取样；
- 默认 Smoke 至少保留若干 validation item；
- 旧缓存可增量补 validation；
- Smoke 在确实没有正式 validation 时可使用按歌曲隔离的临时 holdout，并明确记录；
- Overnight 不静默使用临时 holdout，仍要求正式 validation。

---

## 6. GPU decoder overnight 设计

### 6.1 阶段结构

Overnight 被设计为：

1. 资产与输入审计；
2. 一次性缓存 M4Singer Qwen timestamp 特征；
3. 分别训练 TCN 和 Transformer；
4. 在 M4Singer validation 比较 raw、official、新 decoder；
5. 在 MIR-1K 生成 official、TCN、Transformer 三条 baseline；
6. 取三种 baseline 的自然异常并集；
7. 所有分支运行 exact；
8. 仅未解决或分歧案例升级 matched +2；
9. 剩余困难案例升级 matched +4；
10. 收集紧凑证据。

### 6.2 避免笛卡尔积

设计上不同时展开：

- decoder；
- 音频分离来源；
- core 长度；
- 上下文档位；
- anchor policy。

而是先固定 Demucs + 30 秒 core，只在异常并集上逐级升级上下文。

### 6.3 预期

理想结果：

- 新 decoder 在 M4Singer validation 上优于 raw 和 official；
- 非正时长减少；
- MIR-1K 异常率下降；
- realign 触发数量减少；
- TCN 与 Transformer 至少表现出不同归纳偏置。

次优结果：

- 新 decoder 不提升，但揭示 raw 或 official 的真实上限；
- realign 的有效上下文范围得到明确结论。

---

## 7. Overnight 实际结果与负结果

### 7.1 执行完整性

实质阶段 01–20 均 complete。collector 自身的 `99_collect.json` 在打包时仍显示 running，是收集顺序问题，不代表前面阶段失败。

整次运行约 41 分钟，其中：

- M4Singer 特征缓存约 33.5 分钟；
- TCN 训练约 54.6 秒；
- Transformer 训练约 79.5 秒；
- 其余 baseline、realign 与收集约 5 分钟。

这说明本次更接近 full-scale quick run，而不是充分占用整夜的长期训练。但由于模型方向已经显示无收益，不应仅靠增加步数继续消耗预算。

### 7.2 M4Singer validation 主结果

Validation：1,711 item、30,408 个边界。

| 输出 | Boundary MAE | ≤80 ms | ≤160 ms | 非正时长 |
|---|---:|---:|---:|---:|
| Raw argmax | **26.443 ms** | **97.494%** | **98.967%** | **18** |
| Official decoder | 27.664 ms | 97.208% | 98.721% | 119 |
| GPU TCN | 27.614 ms | 97.251% | 98.740% | 118 |
| GPU Transformer | 27.614 ms | 97.251% | 98.740% | 118 |

观察：

- raw 明显优于 official 和两个新 decoder；
- official 相比 raw，MAE 恶化约 1.22 ms；
- 新 decoder 仅比 official 改善约 0.05 ms；
- 新 decoder 的非正时长约为 raw 的 6.6 倍。

当前强结论：

> 对当前模型和数据，raw timestamp argmax 是最佳初步边界来源；全局单调 decoder 反而容易制造边界堆叠。

### 7.3 TCN 与 Transformer 输出坍缩

两种 checkpoint 不同，模型身份和 SHA-256 也不同，但最终离散指标和 MIR-1K selected case 输出完全一致。

可能机制：

- raw 本身约 97.5% 边界已在 80 ms 内，repair gate 正样本极少；
- gate 初始偏向不修改；
- 没有足够 hard-error sampling 或正样本加权；
- 最终 `cummax + round` 把不同连续输出压成相同离散序列；
- best checkpoint 使用离散 projected MAE，step 100 之后长期打平。

因此不能据此断言 TCN 或 Transformer 哪个更好，只能判定当前全局 decoder 训练目标和投影方式不合适。

### 7.4 Realign funnel

异常并集：

- exact：52 case，11 首歌；
- +2：46 case；
- +4：45 case。

升级比例过高：

- 46/52 进入 +2；
- 45/52 进入 +4。

虽然名义上不是完整笛卡尔积，但 funnel 几乎没有筛掉 case。

候选平均变化显示：

- exact 整体存在一定改善机会；
- +2 对 GPU decoder 已开始倾向有害；
- +4 风险更高。

这促使后续正式 Demo 移除 +4，并把 +2 改为 exact 的独立 verifier，而不是更激进的 fallback。

---

## 8. `exact`、`+2`、`+4` 的定义与修正理解

它们表示 local realign 时，两侧在目标区间之外额外加入的歌词单位数量。中文通常为字符数。

- `exact`：只输入两侧 anchor 与目标区间；
- `+2`：左右各额外增加 2 个歌词单位；
- `+4`：左右各额外增加 4 个歌词单位。

代码中的 matched context 会同时扩展：

- 文本输入范围；
- 音频裁剪范围。

因此不是只增加文本而保持原 exact 音频。但音频范围来自 baseline 对邻近字符的预测，如果邻域本身也错，扩展后的音频—文本仍可能错配。

后续结论：

- `+4` 不进入正式 Demo；
- `exact` 作为主要 repair candidate；
- `+2` 作为独立上下文验证；
- 后续实验应记录音频与文本扩展范围和邻域 baseline 误差。

---

## 9. Context agreement

Context agreement 指：

> 同一目标区间用 exact 和 matched +2 两种合理但不同的上下文重新推理，结果应在指定容忍度内一致。

它的目的不是提高 detector recall，而是提高实际修改 precision。

原 overnight 使用过：

```text
--no-q2-require-context-agreement
```

因此即使第二个合理输入不支持某个 repair，selector 仍可能采用它。这与“高置信局部修改”的设计目标不一致。

后续修正：

- exact 与 +2 在同一 case 内共同运行；
- +2 作为 verifier；
- 未达到 agreement 的 candidate 不进入 final；
- agreement tolerance 进入 E2 单维敏感性实验。

---

## 10. Raw + guarded Demo 的形成

基于 overnight 结果，正式 Demo 改为：

```text
R2 raw timestamp
→ 完整串行 baseline
→ 宽松异常检测
→ exact candidate
→ matched +2 verifier
→ context agreement
→ 结构安全门
→ 最大边界改动限制
→ final
```

不再默认使用：

- official processor decoded 作为主输出；
- TCN 或 Transformer；
- +4；
- 单个输入直接修改；
- GT anchor。

默认模型路径：

```text
/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064
```

默认 revision：

```text
c07281df297b9905d24a508279258cccf987a064
```

默认 R2 checkpoint：

```text
/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
```

路径仍允许环境变量或命令行覆盖。

---

## 11. PRF 实验的实现、报错与修复

### 11.1 参数报错

首次运行：

```bash
bash scripts/demo/run_raw_realign_prf_experiment.sh
```

报错：

```text
ValueError: --max-automatic-anchor-policies must be positive
```

原因：runtime anchor 模式不使用自动 shortlist，但主程序仍无条件要求该参数大于 0。

修复：

- runtime anchor 或 GT anchor 诊断时允许 0；
- 完全依赖 automatic anchor 时仍要求大于 0。

### 11.2 PRF 指标定义

对每个字符定义真实错误：

```text
max(|pred onset - GT onset|, |pred offset - GT offset|) > tolerance
```

分别报告 80、160、240 ms。

Detector PRF：

- TP：错误字符被 detector 覆盖；
- FP：正确字符被 detector 覆盖；
- FN：错误字符未被覆盖。

Intervention correction PRF：

- TP：错误字符被修改且修正到阈值内；
- FP：发生修改但没有形成有效修正；
- FN：错误字符最终仍未修正。

后者是项目内部干预指标，不应与普通 detector PRF 混称。

---

## 12. PRF 实际结果与分析

输入结果：

```text
raw_detector_repair_metrics.json
```

总体：

- 评测字符：1,375；
- detector 覆盖字符：568；
- 自然 case：116；
- 最终 selected case：3。

### 12.1 160 ms 主口径

- 真实错误：170；
- 正确字符：1,205；
- 错误率：12.36%；
- detector TP：117；
- FP：451；
- FN：53；
- precision：20.60%；
- recall：68.82%；
- F1：31.71%；
- case-level precision：61.21%。

实际干预：

- 451 个正确字符被 detector 覆盖但未修改；
- 正确字符被实际修改：0；
- selected case：3 个，全部改善；
- meaningfully modified observation：14；
- 其中原本正确：0；
- 原本错误且改善：14；
- 修正到 160 ms 内：10；
- intervention precision：71.43%；
- intervention recall：5.88%。

解释：

> Detector 偏宽松，最终安全门非常保守。当前主要问题不是误改，而是修复召回过低。

### 12.2 tolerance 敏感性

| 阈值 | 错误率 | Detector Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| 80 ms | 26.69% | 35.21% | 54.50% | 42.78% |
| 160 ms | 12.36% | 20.60% | 68.82% | 31.71% |
| 240 ms | 8.36% | 15.32% | 75.65% | 25.48% |

阈值越宽，严重错误更少，但 detector 覆盖仍很宽，因此 precision 降低、recall 升高。

### 12.3 Trigger 观察（160 ms）

较有价值的结构类 trigger：

- severe duration compression：precision 50.82%，recall 36.47%；
- structural candidate：47.52%，39.41%；
- boundary stacking：41.67%，41.18%；
- zero duration：41.24%，42.94%；
- local / one-step short：40.39%，48.24%。

Cross-window disagreement：

- precision 18.82%；
- recall 58.24%。

因此它适合作为高 recall 的第二级候选，不适合单独触发写回。

### 12.4 重复计数问题

原结果中：

- `selected_modified_unit_count = 11`；
- `meaningfully_modified = 14`。

差异来自多个 selected case 对同一字符的重复观察。正式全局结论不能直接把独立 case 的修改数相加。

后续分析器新增：

- independent-case observation；
- unique modified unit；
- duplicate observation；
- severity-first global non-overlap replay。

正式 Demo 的实际改动应以全局 non-overlap replay 为准。

---

## 13. 完整 Demo 功能恢复

用户要求新版不能只是算法脚本，而要仿照之前 Demo 的应用方式。当前实现目标包括：

- 直接输入媒体文件；
- 输入 TXT，并寻找同名媒体；
- 输入无扩展名名字；
- 文件夹扫描；
- 可选递归；
- `--name` 精确选择；
- 媒体和歌词不同名时使用 `--lyrics`；
- 多语言参数；
- 人声分离；
- ASS 卡拉 OK 字幕；
- 原视频 + 原混音主视频；
- 分离人声诊断视频；
- raw baseline 与 guarded final 对比视频；
- stage-specific resume；
- 输入/模型/参数 identity；
- force prepare/separation/align/render。

### 13.1 语言参数

支持：

- Chinese / zh / 中文；
- Cantonese / yue / 粤语；
- English / en / 英文；
- Japanese / ja / 日语。

中文采用字符级，英文采用词级。R2 权重主要由中文歌唱数据训练，其他语言属于可运行但尚未系统验证。

### 13.2 默认分离器改为 Demucs

用户指出当前应使用 Demucs。最终设计：

- 默认 separator：Demucs；
- 默认模型：`htdemucs_ft`；
- 默认 device：CUDA；
- shifts：0；
- overlap：0.25；
- 优先查找显式 `--demucs-command`、PATH、当前 Python module、指定 conda 环境；
- Demucs 不可用时不静默退回 Spleeter；
- Spleeter 仅保留显式 legacy compatibility。

### 13.3 视频输出

完整流程：

```text
原始媒体
→ 提取 mix
→ Demucs vocals / accompaniment
→ raw baseline
→ guarded final
→ ASS 字幕
→ individual mix/vocal 视频
→ raw/final comparison
→ 主 Demo 视频
```

主视频使用原视频画面、原混音和 final 字幕。

---

## 14. E0–E5 后续实验设计与实现状态

以下实验入口已实现，但在本会话中尚未收到正式服务器运行结果。不能把设计目标当成结果。

统一入口：

```bash
bash scripts/demo/run_raw_guarded_experiment_suite.sh
```

### E0 — Raw baseline census

目的：完整描述错误分布，而不仅是 overall MAE。

输出：

- 80/160/240 ms 错误率；
- 每首歌错误数；
- first failure；
- recovery distance；
- zero duration；
- severe compression；
- cursor 跳过或重复；
- seam 与非 seam 错误。

预期：确认错误是否集中在少量局部区间，以及全局自行恢复能力。

### E1 — Detector trigger ablation

目的：找出高 precision 的结构 trigger 与高 recall 的辅助 trigger。

比较：

- structural；
- boundary stacking；
- zero duration；
- severe compression；
- local short unit；
- cross-window disagreement；
- frozen-prefix conflict；
- margin、top-1 probability、entropy 分位数。

输出：每种 trigger 的 PRF、独立 TP、重叠和增量贡献。

### E2 — Repair / verifier ablation

目的：分离 candidate、context agreement 与 change cap 的贡献。

配置：

- A：baseline 不修改；
- B：exact + 结构安全门；
- C：exact + matched +2 agreement；
- D：C + 最大边界改动限制。

另做单维敏感性：

- agreement tolerance：80/160/240 ms；
- max boundary change：240/480/800 ms。

不展开完整笛卡尔积。

### E3 — Candidate upper bound

目的：判断问题在 candidate 生成还是 selector。

比较：

- exact oracle；
- matched +2 oracle；
- exact/+2 二选一 oracle；
- 自动 selector；
- baseline。

解释：

- oracle 低：local inference 本身无效；
- oracle 高、自动低：selector/verifier 有问题；
- detector 未覆盖：检测问题。

### E4 — Clean-control harm

目的：直接测安全门是否保护正确区域。

三条路径：

1. 正常 detector；
2. 强制正确区进入 realign，但保留安全门；
3. 强制写回，仅用于伤害上限诊断。

输出：误检未修改、被安全门拦截、实际误改。

### E5 — Long-sequence propagation

目的：M4Singer 短 item 很多，需要评估长序列 cursor 传播。

构造：

- 60 秒；
- 120 秒；
- 240 秒。

报告：

- first failure；
- recovery distance；
- cursor 非前进；
- zero duration；
- severe compression；
- seam 附近错误；
- seam mask 后内部错误；
- realign 改善/恶化。

同曲连续片段、人工 seam 和内部自然区域必须分别报告。

---

## 15. 数据集扩展判断

当前不应仅因“错误样本少”立即引入大量其他数据集。先判断缺少的是：

- 错误数量；
- 错误类型；
- 真实 Demo 域错误；
- detector 可利用特征；
- selector/verifier 能力。

建议顺序：

1. 先完成 MIR-1K development E0–E4；
2. 冻结 detector/guard 参数；
3. 运行 MIR-1K held-out；
4. 若错误类型覆盖不足，优先增加人工校验的真实歌曲字符 GT；
5. 可引入 OpenCPOP 作为中文外部干净域；
6. M4Singer 做机制匹配的错误注入与长序列；
7. 暂不把英文 DALI 等混入中文 detector 主实验。

过拟合风险主要来自：

- M4Singer item 高度相关；
- 自然错误占比低；
- 反复依据 development 调 selector；
- 把同一字符在重叠 case 中重复计数；
- 阈值直接根据 GT 调整后仍称 held-out。

---

## 16. Patch 与实现问题记录

### 16.1 Git patch 基线不一致

一次应用失败：

```text
README.md: patch does not apply
run_demo_realign_quick.py mode mismatch
run_raw_guarded_karaoke_batch.py: No such file
run_raw_guarded_karaoke_demo.sh: patch does not apply
```

原因：服务器当前目录已包含额外本地改动，和打包时的精确 Git 上下文不一致。

应对：改为 safe overlay：

- 应用前备份所有将覆盖的文件；
- 新文件按路径安装；
- README 使用标记增量合并；
- 修正可执行权限；
- 生成 restore.sh；
- 不依赖 `git apply` 上下文。

### 16.2 Safe overlay 遗漏 batch shell

随后发现：

```text
bash: scripts/demo/run_raw_guarded_karaoke_batch.sh: No such file or directory
```

根因：

- `run_raw_guarded_karaoke_batch.py` 已进入 overlay；
- `run_raw_guarded_karaoke_demo.sh` 会调用 shell wrapper；
- 但 `run_raw_guarded_karaoke_batch.sh` 未进入 overlay、changed_files 和 verify required list。

这是打包清单和验证覆盖不足，不是运行环境问题。

本次修正版同时：

- 补入 shell wrapper；
- 加入 changed_files；
- 加入 required file 验证；
- 加入 shell syntax 检查；
- 加入 chmod；
- 保证备份和 restore 也覆盖该文件。

---

## 17. 当前可复现路径与命令

### 17.1 完整 Demo

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /path/to/Song.mp4
```

按名字：

```bash
cd /data/songs
bash /home/hyan/LyricAlignment/scripts/demo/run_raw_guarded_karaoke_demo.sh Song
```

媒体与歌词不同名：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/Song.mp4 \
  --lyrics /data/lyrics.txt
```

文件夹：

```bash
bash scripts/demo/run_raw_guarded_karaoke_demo.sh /data/songs --recursive
```

### 17.2 PRF

```bash
bash scripts/demo/run_raw_realign_prf_experiment.sh
```

### 17.3 E0–E5

```bash
bash scripts/demo/run_raw_guarded_experiment_suite.sh
```

只跑 MIR-1K：

```bash
RUN_LONG=0 bash scripts/demo/run_raw_guarded_experiment_suite.sh
```

只跑长序列：

```bash
RUN_MIR1K=0 RUN_LONG=1 bash scripts/demo/run_raw_guarded_experiment_suite.sh
```

Held-out：

```bash
ROLES=heldout \
RUN_LONG=0 \
OUT_ROOT=/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/raw_guarded_experiment_suite_v1_heldout \
  bash scripts/demo/run_raw_guarded_experiment_suite.sh
```

---

## 18. 当前结论强度

### 已有较强证据

- M4Singer item 足够多，但 item 数不等于独立异常数；
- raw 在 M4Singer validation 上优于 official、TCN 和 Transformer；
- 当前全局 GPU decoder + `cummax` 路线无收益并增加非正时长；
- exact candidate 比持续扩大上下文更有希望；
- detector recall 尚可，但 precision 较低；
- 最终 guard 在当前 development 结果中没有误改正确字符；
- 当前主要瓶颈是 repair recall，而非安全性。

### 中等证据

- cross-window disagreement 适合作为宽松检测而不适合作为直接修改依据；
- structural/compression/stacking trigger 更适合作为高优先级 case；
- +2 作为 verifier 比作为 fallback 更合理。

### 尚未验证

- 新完整 Demo 在多歌曲、不同语言下的稳定性；
- Demucs 默认命令在服务器具体环境中的所有解析分支；
- E0–E5 的正式结果；
- held-out 上 guard 是否仍保持零误改；
- 长序列 realign 是否缩短恢复距离；
- OpenCPOP 或新增真实 GT 是否必要。

---

## 19. 下一会话建议动作

1. 应用本次修正后的 safe overlay v2，并运行 verify；
2. 先运行 Demo `--dry-run`，确认文件发现、语言与 Demucs 命令；
3. 选一首已有 Demo 歌曲完整运行，检查：
   - `baseline_raw/alignment.json`；
   - `alignment.json`；
   - `raw_guarded_realign.json`；
   - 主视频与比较视频；
4. 运行 E0–E4 development；
5. 优先查看全局 non-overlap replay，而非独立 case 重复计数；
6. 根据 E1/E2 冻结 trigger 和 guard 参数；
7. 再运行 held-out；
8. E5 可单独 overnight 运行；
9. 只有在真实错误类型覆盖不足时，再决定新增数据集或标注。

---

## 20. AI 协作与依赖状态

### 有效协作部分

- 将初步 decoder、串行 commit 与 local realign 分层；
- 根据真实 overnight 负结果及时放弃“全局 decoder 必须更好”的预设；
- 将误检与误改分开评测；
- 建立开发集 / held-out 冻结规则；
- 将 Demo 算法更换与原有媒体功能重新整合；
- 对 patch 应用失败改用可恢复 safe overlay。

### 需要改进的部分

- 首版 GPU decoder patch 只实现 TCN，未一次覆盖替代结构；
- Smoke 首版未保证 validation split；
- 初版 compact collector 的自身状态易造成误解；
- 初版 PRF 脚本参数验证与 runtime anchor 逻辑不一致；
- 初版完整 patch 依赖过强的 Git 上下文；
- 首版 safe overlay 漏打包 batch shell，且 verify 未捕获。

### 当前依赖

服务器需要：

- Qwen forced aligner snapshot；
- R2 step-000750 checkpoint；
- `lyricalign-qwen` 环境；
- Demucs 4.x 环境或可执行命令；
- ffmpeg / ffprobe；
- MIR-1K 字符 GT subset；
- M4Singer labels 和 clean vocal；
- 足够的数据盘空间存储 Demo、实验和长序列结果。

