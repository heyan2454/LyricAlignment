# Demo Alignment Stability Exploration Record

Date:
2026-07-26

Stage:
Qwen Forced Aligner Demo Stabilization

Status:
Exploration / Investigation

Related:
- windowed forced alignment
- vocal separation
- context sensitivity
- streaming commit policy

---

# 1. 背景

当前 demo pipeline 已经能够稳定输出：

- alignment.json
- rendered subtitle/video

此前主要问题：

1. archive manifest 重复；
2. demo 目录冗余；
3. window alignment failure 导致无法输出；
4. Japanese unit mismatch。

这些问题已经解决。

当前问题转移为：

> 输出成功，但是部分歌曲（高语速、有伴唱、复杂声学环境）出现明显错误。

典型现象：

- 字符跳变；
- 时间突然提前/延后；
- 多字符压缩到同一时间；
- 前一个窗口错误影响后续窗口；
- 高语速段明显下降。

---

# 2. 窗口机制探索

## 2.1 初始问题

原 window pipeline:

- 使用重叠窗口；
- 每窗输入左右上下文；
- 当前核心区负责提交；
- overlap 用于保持连续。

发现：

某些窗口中：

previous window:
    lyric A predicted at 61s

next window:
    same lyric A predicted at 58s

导致：

first uncommitted character before trusted core

---

# 3. 关于 carry-forward 的探索

## 初始假设

认为：

下一窗首字符过早可能来自窗口边界不稳定。

尝试：

使用上一窗 lookahead 修复下一窗。

即：

previous window:
    lookahead prediction

next window:
    replace conflicting prediction

---

## 发现的问题

该方案假设：

previous lookahead > current prediction

但实际上：

lookahead 本身也不是可信区域。

它可能包含：

- 不完整音素；
- 边界错误；
- 未来歌词竞争。

因此：

不能简单认为 previous lookahead 正确。

---

# 4. 当前采用的窗口合并规则

采用：

hard core + forward overlap compression

核心思想：

> 当前窗口核心区域完全可信，下一窗口只能处理未提交部分。


规则：

假设：

previous committed end:

60.16s


next window raw:

char A:
59.8-60.0

char B:
60.0-60.2


处理：

A:

start=max(59.8,60.16)
end=max(60.0,60.16)

=> 60.16-60.16


B:

start=max(60.0,60.16)

=> 60.16-60.20


特点：

- 不使用 previous lookahead；
- 不整体平移；
- 只删除重叠部分；
- 保证 monotonic。

---

# 5. 当前新的问题

## 5.1 单窗口内部错误

即使窗口之间没有冲突：

raw alignment 仍可能出现：

- start inverse；
- overlap；
- jump；
- skipped character。

monotonic repair 可以保证输出合法：

但是：

合法 ≠ 正确。


因此需要区分：

raw alignment

↓

monotonic repaired alignment

↓

final committed alignment


---

# 6. 需要补充的三个 alignment artifact

未来应保存：

## raw_alignment.json

模型原始输出：

包含：

- unit index
- start
- end
- confidence
- raw score


目的：

判断模型本身是否错误。


---

## repaired_alignment.json

应用：

- monotonic constraint
- overlap compression

之后结果。


目的：

判断规则修复影响。


---

## final_alignment.json

窗口提交结果。


目的：

判断：

- commit cursor
- propagation
- merge

是否导致错误。

---

# 7. 当前主要假设

## Hypothesis A:
人声分离质量影响较大

原因：

高语速：
- 辅音弱；
- 音素密集。

伴唱：
- 多条 vocal path；
- 模型可能选择错误人声。

需要实验：

Spleeter vs Demucs vs MDX。


---

## Hypothesis B:
未来歌词上下文过长导致搜索困难

观察：

给模型更多未来文本后：

困难区域可能更容易错误。

可能原因：

alignment search space 增大。


需要实验：

固定 audio:

比较：

future text:

- +5s
- +10s
- +30s
- full


---

## Hypothesis C:
窗口状态传播导致级联错误

当前传播：

- committed_cursor
- last_committed_end


问题：

如果一个窗口错误：

后续窗口可能继承错误。


---

# 8. 未来可能的 propagation 方案

## Option 1:
soft commit

例如：

60s window:

0-50 hard commit

50-60 soft commit


下一窗允许修正。


---

## Option 2:
overlap reconciliation

两个窗口共同区域：

比较：

window A prediction

window B prediction


根据：

- confidence
- monotonic
- duration

选择。


---

## Option 3:
confidence anchor

不传播所有 committed end。

只传播：

高 confidence anchor。


---

# 9. 新实验计划

## Experiment 1:
Vocal separation

Input:

same song

Compare:

- original mix
- Spleeter vocal
- Demucs vocal
- MDX vocal


Metrics:

- raw jump count
- monotonic violation
- compression amount
- human demo


---

## Experiment 2:
Context sensitivity

固定：

audio window


改变：

future lyric context:

- short
- medium
- long
- full


观察：

是否未来文本导致困难。


---

## Experiment 3:
Text robustness

测试：

correct lyric

extra characters

missing characters

homophone characters

wrong characters


目的：

判断模型依赖：

- acoustic
- text matching


---

# 10. 当前阶段结论

已经解决：

- pipeline fail；
- window crash；
- Japanese unit mismatch；
- output generation。

尚未解决：

- alignment accuracy stability。

当前重点不是继续增加规则修补，而是建立：

raw → repair → commit

三个阶段证据链。

下一阶段优先：

1. 保存三个 alignment artifact；
2. 做 context ablation；
3. 做 vocal separation ablation；
4. 分析 propagation。