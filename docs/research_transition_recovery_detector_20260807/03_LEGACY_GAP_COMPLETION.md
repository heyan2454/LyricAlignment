# 基础线 B：先前实验缺陷补齐计划

本线目标是让旧结论可被新阶段正确复用，不是重新跑完整 Detector V2。

## 1. 已闭合，不重复跑

根据最新 BACKLOG25 evidence：

- request identity 已闭合为 1440/1440 matched；
- duplicate identity 审计已闭合；
- Family-LOO master conclusion 的错串数字已有修正版；
- PRECHECK/HIDDEN/REQUEST identity audit 文件已存在；
- deliverable audit 已补齐。

Agent 只更新状态引用，不再次花 GPU/大量 CPU 重做这些项。

---

## 2. Stress evaluator 模型不一致 — 必修

旧 no-GT stress 路径存在固定 Logistic，而 GT family/正式 detector 使用 frozen small-MLP 等模型，导致 accept/reject state distribution 不能严格比较。

### 修复

- 同一 frozen model；
- 同一 scaler；
- 同一 feature combo；
- 同一 threshold/operating point；
- 同一 per-request postprocessing；
- GT/no-GT 只差是否可计算 correctness metric。

### 保留结论

旧 18-family 对 53 features 的直接 rank-AUC/KS 分析不依赖该 evaluator bug，可以保留“现有单点 feature 对多数 stress 弱”的探索结论。

### 不再正式引用

旧 no-GT stress 的具体 accept-rate 不能继续当作 frozen small-MLP 的正式结果。

---

## 3. Serial propagation 缺口 — 用新 benchmark 替代旧重复

旧 serial 中 detector 太严格，1774 units 只提交约 86，真正错误几乎没有进入 carried state；旧 evaluator 对部分提交窗口的未提交 unsafe 跟踪也有缺陷，因此 `propagation=0` 不能解释为成功阻断传播。

### 修复方式

不简单重复旧 run，而是使用主线 A 的：

- natural propagation；
- model-native forced commit；
- canonical state corruption；
- SA80 高提交工作点。

正式报告必须区分：

- unsafe observed；
- unsafe rejected before commit；
- wrong committed；
- wrong state carried；
- propagated to later window。

---

## 4. Hidden extraction — 尚未真正实验

旧 evidence 中 hidden availability = 0；这不是 hidden 无用，而是 extraction/mapping 未发生。

### Gate

1. 明确 hook layer；
2. generated token → output row → canonical unit 映射；
3. hook on/off logits/posterior/raw/official decoded rows 等价；
4. 保存 schema/version；
5. sample audit 能人工追踪一个 request 的 token/slot/unit。

Gate 未通过时，所有 hidden 结果必须标 `not_executed`，不能写“无增益”。

---

## 5. Cross-view posterior — 尚未真正实验

旧 cross-view metadata 有一部分，但 full posterior vectors 未保存，`posterior_distance=0` 不能解释为一致。

### 补法

只对重点 corpus 重新 forward：

- Transition candidate 的重叠 window units；
- repeated occurrence；
- propagation-prone episodes；
- 少量 safe controls。

保存足够 posterior 或压缩后仍能精确计算的分布信息，用于：

- L1/L2；
- JS divergence；
- top-k time displacement；
- mode switching。

无需全量重跑所有旧请求。

---

## 6. Repeated-section stress — 产品语义不足

旧 repeated-section 更接近“只改文本、音频不变”的 synthetic mismatch，不充分模拟正确歌曲+正确歌词情况下的 occurrence ambiguity。

### 新替代

- natural repeated chorus；
- mechanical audio+lyrics+GT 同步复制；
- seam control；
- 前窗 state 误选另一 occurrence 后真实继续 forward。

旧 repeated stress 保留为输入鲁棒性 sanity，不作为产品核心异常。

---

## 7. CNN1D 旧协议 — 必须纠正结论

旧 CNN1D：

- sequence-level any-unsafe 标签；
- train sequences 约 22，且 train 全 positive；
- validation 仅约 6 条，5 unsafe + 1 safe；
- sequence AUC=1 只能表示那 1 条 safe 恰好排在 5 条 unsafe 后；
- 把 sequence score 广播到 window/unit 后 protocol 退化。

### 后续动作

- 旧 `AUC=1` 不得写成“会检测窗口错误”；
- 新实验只允许 per-unit supervision + per-unit output 的 CNN/TCN；
- 与 simple MLP baseline 公平比较；
- 若 per-unit sequence 无增益，记录 negative result 并停止扩模型。

---

## 8. Isotonic calibration — 已回答的问题

旧结果已经显示 isotonic 显著改善 ECE，但不能改善高保护工作点下的 safe acceptance。

### 结论

- calibration 不是当前 safe/unsafe 分不开的主要原因；
- 后续仅在需要把 `p_bad` 解释为概率时复用 isotonic；
- 不再花主预算做 temperature/isotonic 细调；
- 不把校准后的概率改善误写成 discrimination 改善。

---

## 9. 旧工作点缺失

后续文档已计划 SA60/SA80/R95，但 BACKLOG25 中并没有这些正式结果；旧 `protected_recall_95` 不是新 R95。

必须由 Detector 线重新正式完成，见 `04_DETECTOR_RESEARCH_PLAN.md`。
