# 用户意见、质疑、取舍与最终决定

本文专门记录本轮讨论中用户提出的判断。为避免将用户意见与 assistant 推断混淆，每项均按“用户意见—背景理由—当前决定—仍待验证”记录。

## 1. 阶段性 Demo 与协作分享

### 用户意见

需要向合作者分享阶段性成果，希望最终整理出：

- 当前最优或最稳妥的 Demo；
- 对应说明文档；
- 可直接使用的环境；
- 讨论结束后再彻底整理，当前先准备。

### 当前决定

暂以 R2、Demucs vocal、fixed 60s、official decoder、无自动 realign 作为保守展示基线；official/top-K/weighted 可做匿名对比。最终分享包必须包含环境锁、模型/checkpoint 身份、验证脚本和单 case 命令。

### 保留意见

用户认为 decoder 仍需结合 test demo 观察，并担心 formal pilot 的过拟合。因此展示选择和正式 accuracy 结论必须分开。

---

## 2. 历史实验修复

### 用户意见

- E1 event 聚合错误确实要修；
- E5/E6 口径不一致可以简单重算；
- 条件指标缺非空分母可以补；
- 如果实验已经不再服务新设计，不需要为了形式把所有旧实验“修到成立”。

### 当前决定

只修结论可信度：E1 event、E5/E6 paired subset、条件分母。E3 不修主结论；E5/E6 不继续调参数。

---

## 3. E3 decoder-only local repair

### 用户意见

如果不重新推理，局部 decoder repair 不值得期待。关键更可能是：

- 给模型的输入是否正确、匹配；
- 模型对不稳定或不对应输入的 alignment 能力。

如果 decoder-only repair 真有效，不同 decoder 应已显示更明显的整体差异。

### 当前决定

停止 E3，不再补 paired baseline 作为正式主实验。保留历史代码和结果，但标注为“与当前主要问题不匹配”。

---

## 4. Decoder

### 用户意见

- 当前没有统一最好 decoder；
- 应多看 test demo；
- formal pilot 可能过拟合；
- official decoder 很简单、规则式，仍有提升空间。

### 当前决定

official 作为稳健展示基线，不宣称统一最优。继续研究 posterior-aware constrained decoder，但不再做 E3 式局部事后修复。

---

## 5. Detector

### 用户意见

当前 detector 看起来基本无效。更需要先统计异常区的各种性质，寻找正确区与错误区之间的信号，必要时采用学习方法。

在 detector 与 realign 形成两个循环时，detector 可负责：

- 评价对齐质量；
- 给出安全、危险区间；
- realign 后再判断是否最终接受。

不一定需要提前判断“是否可修”或哪个候选最优，只要最终能接受或拒绝。

### 当前决定

QualityAssessor 内部至少区分：correspondence、commit safety、danger/mismatch、candidate acceptance。Repairability predictor 降为可选效率模块。输出支持 safe/danger/unknown，不强制二分。

### 用户额外担忧

D7 如果用大量人工规则会复杂、工期长且 OOD 性能差，可能不如学习方法。

### 当前决定

先收集 posterior、repair trace、多 request 和辅助信号；使用 logistic/GBDT 做可解释基线，再考虑小型学习模型。只保留少数硬合法性规则。

---

## 6. E2 扰动

### 用户意见

由于 detector 本身性能低，旧 E2 作为 detector 评价效力不高。

### 当前决定

旧 E2 detector 结论退役；其扰动生成基础设施改造成 input robustness / alignment behaviour 研究。

---

## 7. E4 与“少量多次”

### 用户意见

旧 3×32 同时使用了局部短音频，不能回答真实生产问题。真正想看的比较是：

- 同一长音频一次输入全部正确文本；
- 同一长音频配短文本，严格按生产 workflow 串行推进；
- 前一次是否吞字、重复、错误消费 cursor，并影响后续。

非串行短文本可以作为模型行为诊断，但生产意义次要。

### 当前决定

新 E4 以严格串行 P1 为核心，同时保留一次全量 P0、递进 crop P2、独立诊断 D、sparse-slot S 和 oracle O。

### Sparse slots

用户质疑是否需要深入模型结构。当前判断：只需扩展 processor 和 slot mapping，不修改模型主体，但必须验证因果上下文和 token/slot 数量。

---

## 8. 过量与不足文本严重度

### 用户意见

原 `+2/+5/+16` 对 60 秒窗口过于保守，必须加入相对文本长度的百分比；文本不足同样如此。

### 当前决定

正式主曲线：

- 过量 +10/+25/+50/+100/+200%；
- 缺失 10/25/50/75/90%；
- 替换/不对应 10/25/50/75/100%。

绝对 unit 仍记录，`+2/+5` 只用于 smoke/微扰。

---

## 9. 完全不对应文本

### 用户意见

完全不对应是很好的实验，但必须明确如何实现，不能含糊。

### 当前决定

主 no-match 使用同语言、同 unit mode、同长度、跨歌曲连续真实歌词，并冻结 donor manifest。另将同歌错段、重复副歌多解、纯器乐配歌词、行序错误和随机文本机制对照分开。

---

## 10. GT 与无 GT 数据

### 用户意见

现有分析过多集中于有 GT 的 MAE，容易过拟合。无 GT 完整 Demo 也应形成可分析数据，且可能更接近真实 test。

### 当前决定

无 GT Demo 建立 Request/Evidence、多路线一致性、音频支持、人工 span 评论和 heldout 切分。没有 GT 不等于天然未见；被反复观看后必须归入 dev。

---

## 11. Realign

### 用户意见

realign 可能是必须的，但现有设计无法安全。旧 D1 由于 detector 性能不足而失败，但未来 detector 改善后，完整 align 后 realign 仍可作为基线。

### 当前决定

保留 rerun 和 downstream continuation 基础设施；新 realign 采用 proposer + acceptance gate + rollback。D1 保留为 post-hoc 和 per-window precommit 两种基线。

---

## 12. 串行是否必需

### 用户意见

项目定位“speech aligner 适配到 long-form singing、伴奏、歌词不完全匹配和生产对齐”准确，但如果后续结构更好，也可以不使用串行。

### 当前决定

公平比较整首一次、全音频 sparse slots、独立局部 + 全局拼接和滚动串行。串行是候选，不是项目定义。

---

## 13. Qwen LLM、上下文和 ASR

### 用户意见

要求说明 ForcedAligner 中 LLM 的依据、是否能保留上下文只对齐中间部分、ASR 是否可共享主要模型，以及 hidden/posterior 和端侧部署。

### 当前决定

- 技术报告表明音频 embedding 与 transcript/slot 进入 Qwen3 Transformer；
- sparse slots 可保留左侧因果文本上下文，只预测目标段；
- 发布的 ASR 与 aligner 是独立 checkpoint，同时常驻接近双模型需求，不能只加小 head；
- 优先收集 posterior，hidden states 先 pilot；
- 端侧先研究量化、音频 embedding cache、小型辅助模型，最终结构冻结后再蒸馏。

---

## 14. ASR 提交策略

### 用户意见

ASR 的 unfixed tail 值得借鉴，但本项目窗口是 60 秒，一首歌通常只有三四窗。

### 当前决定

不保留多个完整窗口，只比较最后若干字、若干秒或最后句段 provisional 的最小策略。

---

## 15. D1–D8 用户评价

- D1：未来可作为基线，但旧版偏完整 align 后再修；
- D2：request 可重放很有利，但应保持简单，不能要求 detector 输出复杂原因；
- D3：适合作为每次 align/realign 的 cache 和分析工具；
- D4：状态机有价值，但暂不做复杂结构；
- D5：不适合长期主架构，且旧结构耦合太乱；
- D6：request pool 思想好，旧 E9 结果不可靠，要控制性能；
- D7：合理但容易复杂，应重视学习方法和 OOD；
- D8：本质是 D2/D3/D4 的总结性实施原则。

### 当前收敛

最小新架构为：简单 Request → Attempt/Evidence → 学习式 QualityAssessor → 有界 Request Proposal → Acceptance → Commit/Rollback/Unresolved。
