# LyricAlignment：Qwen Forced Aligner LoRA 首轮实验执行计划

> 用途：交给 Codex，在服务器 `/home/hyan/LyricAlignment` 中实现并完成首轮 LoRA 可行性实验。  
> 日期：2026-07-23  
> 项目根目录必须保持为：`/home/hyan/LyricAlignment`

---

## 1. 任务目标

本轮不追求直接训练最终模型，而是完成一个可复现、可比较、可恢复的 LoRA 实验闭环，回答以下问题：

1. 当前 M4Singer 字符时间标注能否正确转换为 Qwen Forced Aligner 的训练标签；
2. 只训练多模态投影层或在音频塔加入 LoRA，是否能改善歌声字符边界；
3. 当前 32GB vGPU 环境能否稳定完成训练、验证、保存、恢复和推理；
4. 哪一种最小训练配置值得进入后续全量实验。

本轮不得因为剩余 598 条 review 尚未修完而停下。它们全部排除，只使用当前 accepted 数据。

---

## 2. 当前有效数据身份

### 2.1 M4Singer

当前 operational canonical manifest：

```text
/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_manifest.jsonl
```

身份：

```text
rows: 20,896
SHA-256: 22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a
input meta.json SHA-256:
50030a56d4529bb460f3088534655e27b75b4e538fcbe4f2ea2a4b968935d433
```

字符标注文件：

```text
rows: 193,666
SHA-256:
ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d
```

状态：

| 状态 | 数量 | 本轮用途 |
|---|---:|---|
| accepted | 20,298 | 可用于本轮训练、验证和测试划分 |
| review_required | 598 | 全部排除 |
| rejected / failed | 0 | 不适用 |
| total | 20,896 | 数量守恒 |

`accepted` 的含义是：

```text
rule-validated character-to-phoneme candidate mapping
```

不得写成人工确认高置信 GT。训练报告中应称为：

```text
rule-validated weak supervision
```

### 2.2 MIR-1K

MIR-1K 已由项目负责人于 2026-07-22 人工确认：

```text
UndividedWavfile 的第二个交错 PCM 声道
zero-based channel index = 1
为 vocal channel
```

当前 vocal-only OOD 数据：

```text
/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood
```

身份：

| 项目 | 值 |
|---|---|
| vocal-only songs | 17 |
| character annotations | 2,035 |
| use | `ood_test_only` |
| extraction manifest SHA-256 | `5ed24d2a616af5764ab036876ccba919595728a31586d3b593a39bdb4fb2a9da` |
| manifest SHA-256 | `bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f` |
| character JSONL SHA-256 | `78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9` |

MIR-1K：

- 不得进入训练；
- 不得参与超参数选择；
- 不得用于 early stopping；
- 只在模型配置和 checkpoint 冻结后运行 OOD 测试。

---

## 3. 基本原则

### 3.1 不修改当前 canonical 数据

本轮不得静默修改 canonical manifest 或字符标注。

如训练适配需要生成新文件，只能生成派生文件，例如：

```text
/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/
```

必须保留：

- 源 manifest 路径；
- 源 manifest SHA-256；
- 代码 commit；
- 配置；
- 输出 manifest SHA-256。

### 3.2 598 条 review 全部排除

不得：

- 将 review 样本混入训练；
- 用宽松 fallback 自动接收；
- 为增加数据量而改变当前 accepted/review 状态；
- 在本轮顺带重做 slur 规则。

### 3.3 先验证标签，再训练

不得在没有通过标签 round-trip 和小样本过拟合的情况下直接启动全量训练。

### 3.4 不训练 language model

本轮所有正式配置均冻结 language model。

暂不进行：

- language model LoRA；
- 全模型微调；
- 4-bit QLoRA；
- 新增自定义回归头；
- 新增复杂 decoder；
- 修改官方时间分类定义。

### 3.5 不混淆指标

必须区分：

- training loss；
- character boundary metric；
- item-level invalid rate；
- M4Singer in-domain；
- MIR-1K OOD；
- frame/token 分类准确率；
- 最终字符时间区间指标。

训练 loss 下降不能自动解释为对齐效果改善。

---

## 4. 需要先检查的现有实现

在开始写新代码前，检查仓库中已有：

- Qwen Forced Aligner 加载入口；
- raw smoke 或 batch inference；
- M4Singer manifest schema；
- character annotation schema；
- Qwen 输出解析；
- metric 实现；
- checkpoint 和 resume 约定；
- `/home/hyan/Data/lyricalign/runs` 或现有 run 根目录约定。

优先复用现有模块，不要另起一套平行结构。

如现有训练模块不适用，应在项目已有结构中增加最小必要模块，并说明为什么不能复用。

---

## 5. 数据划分

### 5.1 划分单位

必须按歌曲划分，禁止按片段随机划分。

同一 `song_id` 的所有片段只能进入一个 split。

### 5.2 推荐比例

如当前没有基于 20,298 accepted 冻结的 canonical split，则生成：

| split | 比例 | 用途 |
|---|---:|---|
| train | 90% | 训练 |
| validation | 5% | 选 checkpoint、调参、early stopping |
| test | 5% | 配置冻结后一次性评测 |

要求：

- 固定 seed；
- 尽量保持歌手覆盖；
- 不追求严格逐项比例，但需报告实际片段数、歌曲数、歌手数和时长；
- 生成 split manifest；
- 保存 split manifest SHA-256；
- 后续实验不得重新划分。

若仓库已有符合这些约束的最新 canonical split，优先复用，不重复生成。

### 5.3 泄漏检查

至少检查：

- 同一歌曲不跨 split；
- 同一源片段不跨 split；
- 完全相同音频 hash 不跨 split；
- synthetic 派生样本如暂未使用则不要引入；
- MIR-1K 不与 M4Singer 合并。

---

## 6. Qwen Forced Aligner 标签构造

### 6.1 保持官方任务形式

必须检查当前使用模型和 processor 的真实输入输出接口，不得凭名称硬编码。

目标形式应保持为：

```text
字符 + 两个 timestamp 位置
```

每个字符对应：

```text
start timestamp label
end timestamp label
```

非 timestamp 位置的监督 label 应为：

```text
-100
```

只在真实需要预测时间类别的位置计算 loss。

### 6.2 时间离散化

先读取模型配置和官方 processor，确认：

- 每个时间类别对应多少秒；
- 最大 label 数；
- timestamp token 的插入规则；
- padding 方向；
- decoder 的时间恢复规则。

若确认当前模型为 80ms 一个时间类别，使用：

```python
time_class = round(time_sec / 0.08)
```

不得未经检查直接假定。

必须明确并统一：

- 使用 `round`、`floor` 还是其他规则；
- 超过最大时间类别时如何处理；
- 音频裁剪是否会同步平移或裁剪标签；
- padding 是否影响 timestamp token 对应位置。

### 6.3 标签 round-trip

对全量 accepted 数据执行或至少对足够覆盖的数据执行：

```text
GT 字符时间
→ 时间类别
→ 构造理想 logits 或理想类别输出
→ 使用项目最终 decode 路径
→ 还原字符时间
→ 与 GT 比较
```

最低验收：

- 每个字符恰好两个 timestamp label；
- 解码字符数与 GT 字符数一致；
- 无标签越界；
- 无 start/end 交换；
- 无 padding 偏移；
- 无字符错位；
- 量化误差符合时间分辨率；
- 输出量化后理论上限报告。

输出：

```text
label_roundtrip_summary.json
label_roundtrip_failures.jsonl
```

若存在失败，不得静默过滤后继续训练。必须先分类并修复。

---

## 7. 模型结构与参数检查

加载固定基础模型 revision，优先使用项目当前已经下载并 smoke 通过的 revision。

必须记录：

```text
model_id
model_revision
processor_revision
transformers source/revision
torch version
CUDA version
GPU name
```

运行时检查并保存：

- 模型总参数量；
- `audio_tower` 实际模块路径；
- audio tower 层数；
- `multi_modal_projector` 实际模块路径；
- timestamp classifier/head 实际路径；
- language model 实际路径；
- 所有候选 LoRA target module；
- 最终命中的 LoRA module；
- trainable parameters；
- frozen parameters；
- trainable / total ratio。

不得仅根据模型文档或记忆硬编码完整模块前缀。

输出：

```text
model_structure.txt
trainable_parameter_summary.json
lora_target_modules.json
```

---

## 8. 实验配置

本轮至少完成以下配置。

### R0：Raw baseline

```text
所有参数冻结
不训练
```

对固定 validation 和后续 test 运行 raw 模型，作为比较基线。

### R1：Projector-only

```text
multi_modal_projector: full train
audio_tower: frozen
language_model: frozen
timestamp classifier: frozen
```

用途：判断仅调整音频表示到语言模型接口是否有效。

### R2：推荐主配置

```text
multi_modal_projector: full train
audio_tower top half attention: LoRA
language_model: frozen
timestamp classifier: frozen
```

初始 LoRA 建议：

```yaml
r: 8
lora_alpha: 16
lora_dropout: 0.05
bias: none
target_modules:
  - q_proj
  - k_proj
  - v_proj
  - out_proj
```

“top half”必须根据实际 audio tower 层数计算，指靠近 audio tower 输出的一半层。

不得使用模糊的 `all-linear`，避免误注入 language model。

### R3：扩展配置

只有在 R2 pilot 明显优于 R0/R1 后才运行：

```text
multi_modal_projector: full train
audio_tower all attention layers: LoRA
language_model: frozen
timestamp classifier: frozen
```

---

## 9. 为什么正式配置先冻结 classifier

当前训练数据主要为短 M4Singer 片段，而 timestamp classifier 预测绝对时间类别。

直接训练完整 classifier 可能让监督过度集中在时间轴前部，破坏较长音频上的时间类别。

因此：

- 正式 R1/R2/R3 先冻结 classifier；
- 小样本过拟合验证中可临时解冻 classifier，用于证明标签和 loss 可学习；
- 小样本过拟合 checkpoint 不得用于正式比较；
- 若正式配置完全无法学习，再单独设计低学习率 classifier 实验，不得在本轮默认开启。

---

## 10. Stage A：最小数据与标签检查

先完成：

- 数据读取；
- processor 输入；
- audio feature；
- timestamp label 插入；
- batch collator；
- padding；
- mask；
- loss；
- decode；
- metric。

生成一个固定 debug batch，保存：

```text
item_id
audio duration
normalized lyrics
character count
timestamp token positions
GT start/end seconds
GT class ids
input tensor shapes
label tensor shapes
attention masks
decoded ideal output
```

不得保存大量二进制 tensor；只保存必要摘要。

---

## 11. Stage B：32 条过拟合测试

### 11.1 数据

固定选择：

```text
32 train
16 validation
```

覆盖：

- 不同歌手；
- 不同歌曲；
- 不同音频时长；
- 不同字符数；
- 不同 slur 数量；
- 不同音素结构。

保存选样 item ID 和 seed。

### 11.2 配置

此阶段允许：

```text
projector + classifier train
其他冻结
```

目的仅是验证：

- 标签正确；
- loss 可下降；
- gradient 正常；
- decode 正确；
- 保存和恢复正确。

### 11.3 通过条件

- 训练 loss 明显下降；
- 训练集字符边界接近时间量化上限；
- 字符数量完全匹配；
- 不产生大规模 zero-duration；
- checkpoint reload 后结果一致；
- 中断后 resume 能继续；
- global step、optimizer、scheduler 和随机状态合理恢复。

若失败：

1. 优先检查标签和 mask；
2. 再检查 classifier 和 projector 是否真的 trainable；
3. 再检查梯度；
4. 最后才调整学习率。

不得通过增加训练规模掩盖小样本无法过拟合的问题。

---

## 12. Stage C：Pilot 实验

### 12.1 数据

使用约：

```text
2,000 train
完整固定 validation
```

抽样仍按歌曲边界处理，不得从 test 抽取。

### 12.2 运行配置

至少运行：

```text
R0 raw
R1 projector-only
R2 projector + audio top-half LoRA
```

### 12.3 初始训练参数

作为起点，可在显存探测后调整：

```yaml
dtype: bfloat16
optimizer: AdamW
effective_batch_size: 32
micro_batch_size_candidates: [1, 2, 4, 8]
gradient_accumulation: auto
projector_lr: 5.0e-5
lora_lr: 1.0e-4
weight_decay: 0.01
warmup_ratio: 0.05
scheduler: cosine
max_grad_norm: 1.0
max_optimizer_steps: 500
eval_steps: 100
save_steps: 100
seed: 3407
```

若 500 steps 尚不能判断趋势，可扩展到 1,000 steps，但必须复用同一 run 并 resume，不另起无关联 run。

### 12.4 初始关闭项

第一轮先关闭：

```text
torch.compile
4-bit / 8-bit quantization
自定义 CUDA kernel
复杂 gradient checkpointing 组合
额外 decoder
```

FlashAttention 是否使用，遵循当前环境已有稳定配置。不得为了理论加速破坏可运行性。

### 12.5 梯度注意事项

即使 language model 参数被冻结，也不能把整个 language model forward 包在 `torch.no_grad()` 中，不能 detach projector 输出，因为梯度仍需穿过冻结模块回传到 projector/audio LoRA。

---

## 13. Stage D：全量训练

只有 R2 在 pilot 中满足以下条件才进入：

- 相对 R0 主指标明显改善；
- 相对 R1 有额外改善或更稳定；
- invalid/zero-duration rate 未恶化；
- 训练稳定；
- checkpoint 和 resume 正常。

全量训练建议：

```yaml
epochs: 2
max_epochs_if_improving: 3
eval_steps: 250
save_steps: 250
save_total_limit: 3
early_stopping_evals: 3
seed: 3407
```

不要仅按 epoch 比较训练成本。必须同时记录：

- optimizer steps；
- 样本数；
- 音频秒数；
- wall time；
- validation 次数；
- 每次 validation 成本。

先完成一个 seed。只有提升明确时，再增加第二 seed。

---

## 14. 指标

### 14.1 主指标

本轮主指标：

```text
song-macro character boundary MAE
```

单字符：

```text
(|pred_onset - gt_onset| + |pred_offset - gt_offset|) / 2
```

聚合：

```text
先在每首歌曲内平均
再对歌曲平均
```

不得只计算所有字符直接 micro average。

### 14.2 辅助指标

至少输出：

- onset MAE；
- onset median；
- onset p90；
- offset MAE；
- offset median；
- offset p90；
- joint within 80ms；
- joint within 160ms；
- joint within 240ms；
- interval IoU；
- zero-duration rate；
- negative-duration rate；
- reversed interval rate；
- character-count mismatch rate；
- item coverage；
- song coverage。

### 14.3 分层

至少按以下条件分层：

- 音频时长；
- 歌词字符数；
- 歌手；
- slur 数量；
- mapping status；
- M4Singer in-domain；
- MIR-1K OOD。

### 14.4 非法预测

非法预测不得让整批 metric 直接终止，也不得静默删除。

必须同时报告：

```text
all-item penalized metric
valid-only auxiliary metric
invalid prediction rate
```

身份不一致、GT 字符错位等数据错误可以 hard fail；模型输出 zero-duration 等应作为模型错误计入。

---

## 15. Test 使用规则

### M4Singer test

配置和 checkpoint 冻结后运行一次。

不得：

- 根据 test 结果改 LoRA rank；
- 根据 test 结果改学习率；
- 根据 test 结果重新选 checkpoint。

### MIR-1K OOD

只在最终候选配置冻结后运行。

不得：

- 用 MIR-1K 调参；
- 用 MIR-1K early stop；
- 用 MIR-1K 选择 R1/R2/R3；
- 混入训练。

---

## 16. 判定标准

### 值得继续

R2 至少应满足：

- validation 主指标相对 raw 明显改善；
- invalid/zero-duration rate不恶化；
- 优于或稳定优于 projector-only；
- M4Singer test 保持改善；
- MIR-1K 无严重退化；
- 训练、保存、恢复稳定。

可将 validation 主指标相对下降约 5% 作为“明显改善”的参考，但不要将它当成绝对硬阈值。

### 不值得扩大

若出现以下情况，不继续增加层数或 rank：

- loss 下降但边界指标不改善；
- R2 与 R1 基本相同；
- validation 改善但 MIR-1K 严重退化；
- 结果主要来自修复少数非法输出；
- 小样本不能过拟合；
- resume 不可靠；
- 显存或速度无法支撑。

此时应形成负面结果报告，而不是通过更多训练掩盖问题。

---

## 17. 保存与恢复

run 根目录建议：

```text
/home/hyan/Data/lyricalign/runs/
```

命名示例：

```text
20260723_qwen_fa_r0_raw_seed3407
20260723_qwen_fa_r1_projector_seed3407
20260723_qwen_fa_r2_audio_tophalf_lora_seed3407
```

每个 run 至少保存：

```text
config.yaml
command.sh
source_manifest_identity.json
split_manifest_identity.json
model_identity.json
lora_target_modules.json
trainable_parameter_summary.json
trainer_state.json
metrics.jsonl
best_checkpoint.json
runtime_summary.json
checkpoints/
```

checkpoint 必须支持：

- 模型参数；
- LoRA adapter；
- 完整训练的 projector；
- optimizer；
- scheduler；
- scaler，如使用；
- RNG state；
- global step；
- epoch / sampler state，若实现可行。

目录写入规则：

```text
相同配置与身份 → 允许 resume
不同配置或数据 hash → 拒绝写入原 run
```

不得静默覆盖已有结果。

---

## 18. PEFT 保存要求

基础模型不重复保存。

保存：

- LoRA adapter；
- 完整训练的 projector；
- 必要 config；
- 基础模型 ID 和 revision；
- processor ID 和 revision。

若使用 `modules_to_save` 保存 projector，必须验证重新加载后：

- projector 参数一致；
- LoRA 参数一致；
- 输出一致；
- 不依赖训练进程中的临时 monkey patch。

---

## 19. 运行入口

最终应提供清晰入口，至少包括：

```text
prepare training labels
validate label round-trip
run overfit smoke
run pilot
resume pilot
evaluate validation
evaluate sealed M4Singer test
evaluate MIR-1K OOD
```

优先提供一条主入口，例如：

```bash
bash scripts/training/run_qwen_fa_lora_pipeline.sh <config>
```

或：

```bash
python -m lyricalign.training.qwen_fa_lora ...
```

入口必须支持：

- `--config`；
- `--run-dir`；
- `--resume`；
- `--overwrite`，默认 false；
- `--stage`；
- `--seed`；
- `--max-steps`；
- `--device`。

不要创建多个含义重叠、无法判断先后顺序的 shell 脚本。

---

## 20. 测试要求

不要求为测试通过本身建立沉重证据。

但至少需要针对以下内容有回归测试：

- timestamp label 位置；
- 时间类别量化；
- padding；
- round-trip；
- LoRA target 命中；
- 冻结和可训练参数；
- projector 保存和加载；
- checkpoint resume；
- 非法预测 metric；
- song-macro 聚合。

测试通过不等于实验正确。仍需真实 overfit、pilot 和 validation 结果。

---

## 21. 失败处理

不得因为单个配置失败而停止整个任务。

处理方式：

```text
R1 失败
→ 保存失败原因
→ 修复通用问题
→ 重跑 R1
→ 再进入 R2

R2 OOM
→ 依次降低 micro batch
→ 增加 gradient accumulation
→ 再考虑 gradient checkpointing
→ 不立即改变模型方案

validation 失败
→ 保留训练 checkpoint
→ 修复评测入口
→ 从 checkpoint 继续

进程中断
→ 从最近 checkpoint 恢复
```

不得用以下方式规避问题：

- 跳过 validation；
- 删除失败样本后不记录；
- 把错误输出当作空结果；
- 重建新 run 掩盖旧 run；
- 只报告训练 loss；
- 因时间不足直接标记“不可行”。

---

## 22. 本轮最终交付

完成后应交付：

### 代码

- 数据适配；
- collator；
- 训练入口；
- LoRA 注入；
- metric；
- checkpoint/resume；
- 评测入口；
- 配置。

### 结果

至少包括：

| 配置 | 必需结果 |
|---|---|
| R0 | validation raw baseline |
| overfit | 32 条训练与 16 条验证结果 |
| R1 | pilot validation |
| R2 | pilot validation |
| R3 | 仅在 R2 有效时 |
| full run | 仅在 pilot 通过时 |
| M4Singer test | 最终冻结配置 |
| MIR-1K OOD | 最终冻结配置 |

### 报告

报告必须区分：

1. 假设；
2. 数据；
3. 实验配置；
4. 观察结果；
5. 可能解释；
6. 替代解释；
7. 负面结果；
8. 当前结论强度；
9. 尚未验证内容。

### Session 记录

记录：

- 实际完成内容；
- 未完成内容及原因；
- 使用命令；
- run 目录；
- commit；
- 是否 push；
- 下一会话恢复入口。

---

## 23. 推荐首个正式候选

```yaml
data:
  train_source: M4Singer accepted only
  excluded: 598 review_required
  split_unit: song

model:
  base: Qwen Forced Aligner current pinned revision
  language_model: frozen
  timestamp_classifier: frozen
  multi_modal_projector: full_train
  audio_tower:
    scope: top_half_attention
    adaptation: LoRA

lora:
  r: 8
  alpha: 16
  dropout: 0.05
  targets:
    - q_proj
    - k_proj
    - v_proj
    - out_proj

training:
  dtype: bf16
  optimizer: AdamW
  effective_batch_size: 32
  projector_lr: 5.0e-5
  lora_lr: 1.0e-4
  warmup_ratio: 0.05
  weight_decay: 0.01
  scheduler: cosine
  seed: 3407

selection:
  metric: song_macro_boundary_mae
  split: M4Singer validation

final_evaluation:
  - M4Singer sealed test
  - MIR-1K 17-song vocal-only OOD
```

---

## 24. 执行优先级

严格按照以下顺序推进：

```text
检查现有实现
→ 固定 split
→ 构造标签
→ round-trip
→ 模块与参数检查
→ 32 条过拟合
→ R0 raw
→ R1 pilot
→ R2 pilot
→ 判断是否继续
→ 必要时 R3
→ 全量训练
→ 冻结配置
→ M4Singer test
→ MIR-1K OOD
→ 报告与 session 记录
```

不得跳过前置验收直接进入长训练。

---

## 25. 当前任务完成定义

满足以下条件，才算本轮完成：

- 数据身份和 split 固定；
- 标签 round-trip 通过；
- 32 条可过拟合；
- raw baseline 完成；
- projector-only pilot 完成；
- audio LoRA pilot 完成；
- LoRA 的效果有明确结论；
- checkpoint 可保存、重载和恢复；
- 指标不因模型非法预测整体崩溃；
- 最佳配置按规则决定；
- 若 pilot 有价值，则完成全量训练及两套测试；
- 若 pilot 无价值，则形成充分的负面结果和诊断；
- 代码、配置、结果和 session 记录均可供下一会话继续。

