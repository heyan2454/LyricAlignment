# Alignment Research v6 完整实验设计

## 总体执行原则

正式计算必须消费 manifest 中全部 MIR-1K、M4Singer 和 test demo。pilot 只能用于试探参数，明确排除 `split=test/heldout`、`selection_role=heldout/m4_test` 以及 test-derived synthetic-long。参数冻结后 formal 不得再根据 test/held-out 结果修改阈值或 decoder。Pilot 不完整时采用 best-effort 冻结：优先使用可用成功证据，缺失部分退回预先规定的默认值，并在 provenance 中降低效力等级；不得因此静默伪装成正常冻结，也不要求停止 formal。无 GT demo 只报告结构、稳定性、跨输入一致性和可视化，不声称准确率提升。

## E0 现有数据与 Decoder 重分析

**目的**：在同一 Qwen logits、同一窗口和歌词输入上比较生成结果，避免把串行状态混入 decoder 结论。

**方法**：raw、official、joint start/end、top-K sequence、weighted isotonic。保存完整 alignment 与 raw→candidate movement。

**指标**：MAE、joint@80/160、coverage、negative/zero/overlap、raw正确被改坏率、raw错误被修复率、歌曲级 macro 与字符级 micro。

## E1 Detector 自然错误

**目的**：判断哪些 raw/logit/official movement/audio support 特征能识别 GT 错误、安全边界和可修复区。

**特征**：负时长、重叠、回退、短时长、stacking、margin、entropy、top-K、raw→official movement、跨窗口/跨输入差异、音频活动支持。

**模型**：透明规则、Logistic Regression、boosted decision stumps。pilot 训练并冻结；formal 仅评估。

**指标**：unit/event PRF、阈值曲线、clean FPR、repairable PRF、按歌曲 bootstrap。

## E2 人工腐化

**目的**：覆盖自然样本未必出现的真实故障。

**腐化**：歌词起止 ±2/4/8，歌词总量 50%/75%/125%/150%，重复已提交歌词、错误文本替换，音频起止 ±0.5/1/2s，平滑整体偏移。

**输出**：每个腐化相对 baseline 的公共字符移动、结构变化、Detector 分数和 GT 变化。

## E3 Decoder 困难区修复

**目的**：比较替换 raw 与替换 official 两类路线。

**候选**：joint start/end、top-K sequence、confidence-weighted isotonic、oracle/Detector-local weighted repair、local top-K repair。

**公平性**：同一 logits；不改变 window/cursor；局部方案先用 GT oracle span 评估上限，再用冻结 Detector。

## E4 歌词输入量与少量多次

**E4-A**：-50%/-25%/baseline/+25%/+50%，区分仅删 future 与删到 core 内真实歌词。

**E4-B**：32/48/64 或 N-16/N/N+16，报告 oracle best、固定最短、固定最长、Detector 选择和顺序扩展。

**E4-C**：一次96 vs 三次32，比较无重叠、4字和8字同步重叠；正式评价 coverage、seam、调用数和 RTF。

## E5 动态安全边界分窗

**方法**：60s 为目标，附近有限搜索安全边界；exact/-2/-4；当前 core end 等于下一 core start；下一 input 的音频与歌词同步。

**指标**：GT cursor distance、漏/多字符、coverage、MAE、seam、窗口数、first failure 和恢复距离。

## E6 静音机制

**候选**：普通 B4、hard core + full soft context、cap4、cap1.5、历史 cap0.4。静音后歌词作为 lookahead，不由当前 core 提交。

**指标**：静音前末尾/静音后开头 MAE、cursor、coverage、下一窗恢复、按静音长度分组。

## E7 串行累计

**注入**：cursor ±2/4/8；previous end ±0.4/0.8/1.6s；窗口边界独立扰动。比较预测状态、文字 reset、时间 reset、full reset。

**因果判据**：只有预测状态持续恶化且对应 reset 明显恢复，才认定该状态造成级联。

## E8 简化 Realign

Detector 给出 request；Realign 只执行。每 case 保存原始、推荐修正和一个备选输入，同时输出 local raw/official/top-K。

局部候选不能只静态替换目标区间。候选写入 committed prefix 后，从目标所在 baseline 窗开始，沿冻结的 baseline window plan 重新执行该窗剩余部分及全部后续窗口。候选自己的 continuation trace 用于后续 Detector 诊断，不能把“与 baseline 不同”本身作为风险。

**评价**：local raw 是否因输入修正恢复；official 是否再改善或过修复；Detector 是否选中 GT 改善候选；clean harm；整首变化；目标区之后的 MAE/coverage 相对 baseline 与静态 splice 的变化；continuation failure。只有真实重跑结果才称为“后续窗口影响”。

## E9 系统级 Pilot

**A**：实现真实跨窗 cursor/window/text-budget beam。每条 hypothesis 保存 committed rows、committed cursor、input cursor、previous-window state、累计风险和路径；每个窗口分别做模型前向并将最多 3 条不同状态推进到下一窗。无前进路径直接淘汰；剪枝不使用 GT，按 fallback、当前进度缺口、风险 span、结构错误、最大/平均风险、尝试次数和复杂度依次排序。所有模型路径失败时允许显式 baseline fallback，以优先产出可分析的最终结果。

**B**：行/短句粗定位后进行局部字符级对齐，重点覆盖重复副歌、长静音和长歌后半段。

## 数据与统计口径

- formal manifest：所有 test demo、MIR-1K development/extra/spare/heldout、M4Singer 配置 splits 的全部 native 与全部可构造 long。
- pilot：每数据集按时长分层选少量，held-out 排除。
- 统计：字符级 micro、歌曲级 macro、源歌曲 cluster；synthetic-long 不将同源不同长度当独立歌曲。
- 失败：单 item failure 必须落盘；formal summary 保留失败清单，不静默丢样本。

## Formal 重复 case 口径补充

“Formal 全量”指 manifest 中每个数据 item 均进入执行和失败统计，并默认穷举全部 eligible 窗口、完整 96 字组和 Detector risk span。对应上限参数默认均为 0（不设上限）。若因资源约束显式设置正整数，只能作为 case-level subsampling 诊断运行，必须在报告中记录，不能与完整 formal 混称，也不能用于跳过 item、split 或 held-out。
