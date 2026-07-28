# 2026-07-28 Inline Realign formal v3 数据观察与问题讨论

## 1. 观察背景

上一轮 formal 共处理 98 个 item，执行和 compact evidence 收集完整。样本包括 Demo、MIR-1K、M4Singer native 与 synthetic-long。该轮最初用于验证 B0–B3、automatic detector、stable cursor、immediate/deferred realign 和 future-text expansion。

## 2. 主要发现

### 2.1 Window baseline

B2 30 秒 silence-aware 在 MIR-1K 和 synthetic-long 上与固定窗口大体相当，长 synthetic 序列略稳定，但差距较小。它可以作为 reference，尚不能声称显著优于 30 秒或 60 秒固定窗。

### 2.2 Demo 结构性困难

多语种 Demo 中存在大量零时长，日文、高语速、部分英文和粤语尤为严重。部分窗口方案会让同一字符移动数十秒，说明模型可能进入不同离散路径，而不是普通毫秒级波动。

### 2.3 Automatic detector 评测不可解释

Automatic candidates 主要出现在无 GT Demo；GT error cases 出现在 GT 数据，两组缺少共同可评估样本。因此 precision/recall=0 不是有效性能结论。讨论后决定将 detector 降级为 Demo 导航和候选生成工具。

### 2.4 Local realign 有恢复能力，但 gate 召回低

GT-oracle 困难区间中，局部 rerun 多次改善，说明模型在更局部、边界更明确的输入下可以回到较好路径。旧非 GT gate 只接受少量改善，主要原因：

- 旧结构 gate 要求异常分数严格下降；
- 仅整体偏移但结构合法的错误无法得到更低分；
- Exact、+2、+4 在困难区间经常发生秒级分歧；
- Deferred 多数仍无法恢复右锚点或恢复后继续分歧。

### 2.5 旧 stable cursor 是无效实验定义

旧 S1–S3 保持下一窗早期音频输入，却把歌词起点移动到 stable 附近，导致 20–27 秒之类的真实音频没有对应歌词。其明显恶化不能否定 stable 思想，只能否定音频—歌词错位输入。

### 2.6 Future-text expansion 的长尾不可接受

增加未来歌词的边界移动 P90 约为 3.95 秒，部分达到数十秒。说明更多歌词可能改变模型对齐路径，不能默认“多给上下文更安全”。需要补充少给、恰好给足和多给的完整文本剂量实验。

### 2.7 Raw 值得继续分析

B2 同一窗口中的 raw argmax 在 GT 上略优于 final official，且零时长更少；但 raw 的 start/end 独立 argmax，允许负时长、回退和重叠。还必须区分：

- B2 窗口/official cursor 下观察 raw 时间；
- B3 由 raw 自己控制串行 cursor。

## 3. 用户观察对设计的修正

用户查看视频和图后提出：

- 渲染不应阻塞实验和汇总；
- 图中应少用英文并直接展示机制；
- Timeline 必须显示字符、窗口、stable 和 realign 执行过程；
- Duration 应使用包含负值、零值和正值的完整离散 PMF；
- Inconsistency 应使用歌词序号—时间折线、最大差和热力图；
- 需要比较 30/60 秒和严格静音边界；
- Stable 的音频和歌词必须同步裁剪；
- 结构 gate 只需不恶化，不要求严格下降；
- `would_write` 应拆成 oracle、automatic、manual、deferred 和 actual writeback；
- 需要正式 resume；
- 应系统研究少给、多给歌词和 decoder 各阶段。

## 4. 讨论结论

本轮不继续直接扩大旧 formal。原因不是推理成本，而是旧可视化不能有效解释：

- Realign 是否实际运行；
- 三上下文分别输出什么；
- Stable 候选与选中边界；
- Gate 拒绝发生在哪一层；
- 零时长由 raw、processor、window selection 还是 final commit 引入。

下一版先完成完整实现和可解释渲染，然后可大量使用 Demo 和数据集做机制实验。视频渲染后置或独立 resume。
