# 2026-07-28 Inline Realign 补充实验、稳定段分窗与 Demo 执行归档

## 1. 问题来源

上一轮 formal 得到三个重要结果：

- 稳定段字符的 GT 明显优于全体字符，支持“连续稳定段可作为参照”；
- 稳定前缀复现初步可行；
- 13 个 shadow 候选全部没有运行 local inference，主要原因不是附近真的没有稳定段，而是“尾部堆积”把未来歌词算入异常，并把整窗提交范围当成 target，导致 target 经常从字符 0 开始，必然没有左稳定段。

同时，上一轮没有真正完成以下实验：

- Demo 未进入清单；
- GT 错误段上的 local realign oracle；
- 稳定段实际帮助下一窗歌词起点和安全提交边界；
- 强制增加未来歌词的配对实验；
- fail-closed 未完成字幕；
- raw/official planner 真正发生分歧的定向比较。

本次补充实现针对这些缺口，而不是继续无条件放宽 anchor 门槛。

## 2. 被纠正的实现

### 2.1 局部异常定位

旧行为：只要窗口尾部统计触发，就把整窗提交范围作为 realign target。

新行为：target 只来自真实连续异常段：

- 零时长连续段；
- 同边界连续堆叠段；
- 核心区末端实际提交字符的集中堆积；
- 有人声但零推进时，从当前未提交字符开始标记。

未来歌词位于完整输入尾部不再算作 realign 异常。稳定段搜索会排除 target 自身，因此一个长稳定区可在异常左右分成两个候选段。

### 2.2 稳定前缀覆盖要求

只观察到稳定段中的一个字时，不再判定整段复现。需要至少观察固定最小字数和最小比例，否则记录 `insufficient_segment_coverage`。

### 2.3 缓存身份

基线请求升级到 `inline_realign_baseline_request_v3_localized_diagnostics`。稳定段辅助请求升级为 `stable_window_assistance_request_v3_local_subsegment`，避免复用旧版整窗异常和过长稳定段起点结果。

## 3. 新增实验

### 3.1 GT-oracle local realign

对 MIR-1K 和 M4Singer 的明显 GT 错误连续区域主动运行：

```text
寻找一到两个相邻窗口中的左右稳定段
→ exact context 局部推理
→ +2 context 局部推理
→ 检查两次一致性
→ bounded splice
→ 比较局部 GT 前后 MAE 与结构
```

GT oracle 与自动候选分别统计。它回答“local realign 是否有能力”，不回答自动检测器是否成熟。

### 3.2 稳定段辅助窗口推进

对于每个相邻窗口：

- 从下一窗左侧可听上下文寻找靠近接缝的稳定子段；
- 提议下一窗从该稳定子段开头重新输入歌词；
- 从当前窗核心区内最后稳定子段提议安全提交终点；
- 有 GT 时与理想 cursor 比较；
- 建议与基线不同时实际重跑下一窗口。

这是稳定段第一次实际参与分窗/歌词推进实验，而不只是作为 realign anchor。

### 3.3 强制候选歌词扩展

每个选中窗口主动运行 +25% 和 +50% 未来歌词，比较原有区域的边界移动、结构和 GT。重点是识别大片变化，不叠加过多硬条件。

### 3.4 Planner divergence 定向运行

B2 的同一次模型输出同时计算 raw 与 official 会如何提交和选择下一窗歌词起点。只有确实发生分歧的 official-primary 样本才追加 B3，避免在两者完全相同的样本上浪费计算。

### 3.5 Fail-closed incomplete

选择一个 Demo 和一个 GT 样本构造明确标记的未完成字幕，保留已完成前缀并拒绝尾窗强制吞完。该输出用于验证下游能否正确识别 incomplete，不参与主指标。

## 4. 数据规模与防过拟合

Formal 默认扩大到：

```text
Demo 12
MIR-1K development + spare 16
M4Singer native 24
M4Singer synthetic-long 12
```

B0–B3 只在 Demo 4、MIR-1K 8、M4 synthetic-long 4 上运行，其余只运行 B2 和补充实验。这样扩大歌曲和错误类型覆盖，同时控制四基线和局部重跑成本。

MIR-1K held-out 仍未使用。M4Singer native 进行跨歌曲均匀抽样；synthetic-long 只使用同歌片段并单独报告人工接缝。

## 5. Demo 对齐与渲染纪律

强制顺序：

```text
所有 item 全部 align 完成
→ 生成 experiment_summary
→ 才批量 render Demo
```

每首 Demo 只保留：

```text
items/<item_id>/render/official.mp4
```

不创建第二套歌曲输出树，不复制同体积入口视频。默认 review 规格，raw 不渲染。

## 6. 数据收集

新增机器可读和可读总表：

```text
followup_analysis_summary.json
followup_analysis_summary.md
```

证据包额外保存：

- 自动与 GT oracle 候选的区分；
- stable-window cursor 建议与主动重跑；
- 强制文本扩展有限结果；
- planner 真正分歧窗口；
- incomplete 摘要。

仍遵守默认 8 MiB 上限，不打包音视频、权重和全量重复推理结果。

## 7. 预期结果与对应结论

### Local realign oracle

- GT oracle 多数能执行且 GT 改善：稳定段 + local inference 有能力，下一步改进自动检测并做单窗写回；
- 能执行但 exact/+2 常不一致：局部结果对文本上下文敏感，应先研究输入构造；
- 一致但 GT 不改善：结构平滑不能代表准确，需要研究 official 解码或声学输入；
- 仍大量找不到稳定段：检查错误是否覆盖整个一到两个窗口，或稳定段定义仍过严。

### 自动候选

- 由整窗误报大幅下降，零时长/局部堆叠成为主要来源：异常定位修复有效；
- 自动候选与 GT 错误段重合增加：检测器方向正确；
- 自动候选很少但 GT oracle 大量可修：检测器召回不足，需要增加 official 修补幅度等信号；
- 自动候选多但 GT 正常：触发条件仍把正常未来文本或正常高语速当异常。

### 稳定段辅助分窗

- 建议 cursor 对 GT 更接近，主动重跑稳定：可进入 shadow serial planner；
- 建议经常更早但只是增加无用旧歌词：需继续裁短局部稳定段；
- 建议更接近 GT，但重跑结果变差：cursor 位置正确不等于文本上下文最佳；
- 大多与基线相同：当前 planner 已较好，稳定段更适合作为校验而非替代。

### 文本扩展

- +25% 稳定、+50% 开始大范围移动：建立软扩展上限，并要求扩展前后检查；
- 两档均稳定：现有“多给未来歌词”风险较小；
- 高语速样本需要更多文本但不坍缩：不要使用严格字速硬限制；
- 正常样本也频繁移动：forced aligner 对文本范围高度敏感，需要粗定位或多候选策略。

### Raw / official planner

- 分歧窗口很少：raw planner 不是多数样本的主变量，应集中分析少量分歧病例；
- official 更接近 GT：生产 planner 应切换 official；
- raw 更接近 GT：不能简单删除 raw，需要研究两者差异来自何处；
- 两者 cursor 不同但最终字幕相同：窗口重叠和后续修正吸收了差异。

### Incomplete

- 下游正确展示已完成前缀和未解决区：可作为尾部失败保护；
- 渲染或汇总误把 incomplete 当完整：先修下游契约，不能启用生产 fail-closed。

## 8. 尚未实现

- realign 自动写回正式串行结果；
- 可疑尾部 pending 到下一窗口；
- 两窗口联合重新分配 cursor；
- 自然触发的尾窗回退；
- 多候选 cursor；
- official logits 全局概率最优路径。

这些仍需等待本轮 GT oracle、稳定段辅助和扩展实验结果。

## 9. 验证状态

本地无服务器模型和真实数据，因此只验证代码、合成清单、有限证据和真实 ffmpeg 流程，不声称完成 GPU inference。

已完成：

- 局部异常、稳定段拆分、prefix coverage、planner divergence、GT oracle/incomplete、稳定段辅助重跑、强制扩展等专项测试；
- Demo 多 prepared suffix 发现；
- Demo 全 align 后批量单目录渲染 smoke；
- follow-up 汇总和有限证据 smoke；
- 排除本容器缺少 `pypinyin` 的既有测试文件后，全体可执行测试通过。
