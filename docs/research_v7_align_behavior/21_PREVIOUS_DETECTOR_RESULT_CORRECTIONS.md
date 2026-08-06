# 上一轮 Detector/指标结果修正

日期：2026-08-05

## 1. 删除的结论

- `full replace wrong_output_recall=1` 不是检出；它只是所有 replaced units 都有 slot；
- s2/s4 的 0.5/0.25 是 query coverage；
- M4 0.5844 与 MIR 0.5469 接近不代表跨域 detector 稳定；
- tail missing `gap_recall=1` 不是通用 missing detection；
- baseline/extra 无正例时的 recall=1 是空指标；
- `formal_approved` 不等于 detector 实验完成。

这些字段不得进入 Detector V2 报告。历史 artifact 保留，但必须标 `deprecated_non_detector_metric=true`。

## 2. 旧 Unit LogisticAssessor 的可声明边界

同构造 tail-25%-replace、item split：

- 95% recall：correct-unit FPR 约 12.7%；
- 99% recall：FPR 约 17.4%。

但：

- missing/mixed FPR 约 92–99%；
- mixed song-LOO 仍约 92–99% FPR；
- 不看 replace 训练再测 replace，recall 约 1.7–5.8%，且 FPR 约 81–86%；
- 没有 hidden、真实音频文字相容、真实错位或完整跨域 family 结果。

正确表述：旧 Logistic 只识别相同 tail-replace 构造中的局部坍缩形态，是原型信号，不是产品 detector。

## 3. 上一轮明确设计但未闭环的内容

- 随机 1/2/4/8 unit 错误；
- replace/extra 10/25/50 曲线；
- 最新 long-slot 的头/中/分散错误；
- 同音/近音；
- 真实连续 90/180s 串行传播；
- end-early 0.5/1/2/4/8；
- raw-target/official-target 分开；
- hidden 抽取与 H/R/O 消融；
- gap assessor；
- interval@75/@100 与连续全漏；
- source-song heldout replace；
- M4→MIR missing/replace/extra family 分项；
- MIR mutation 补齐后的 assessor 重跑；
- demo 人工标签导入；
- serial closed-loop。

Detector V2 coverage matrix 将这些缺失变成硬 gate。

## 4. 继续保留的行为结论

- 未查询的尾部额外上下文对已有 slot 基本无影响；
- tail replace 会造成被替换区明显偏移、坍缩和提前结束，前缀较稳定；
- slot mask 会改变少量共同 unit，错误文本会放大差异；
- 两轮 seam 对照均无明确影响，seam 不再是主实验因素。
