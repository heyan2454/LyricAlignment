# 2026-08-05 Detector V2 实验设计归档

## 背景

用户复核最新 long-slot 结果后确认：full replace 的“完全检出”只是 slot coverage；tail missing gap recall 是结构性必然；旧/new Logistic 只完成了狭窄 tail-replace 原型；随机少量换字、hidden、raw/official 双目标、完整跨域和大量设计内容未实现。

产品假设改为用户歌词正确，下一阶段主攻正确文字的实际错位检测。输入为检测区间，输出接受、不接受、存疑的连续子区间。

## 用户关键决定

- 继续研究 detector；
- 从 hidden、raw、official、进阶信号和组合信号中寻找无 GT 证据；
- 重点是错位，不以 missing/replace/extra 作为产品分类；
- 允许三态而不是强制二分类；
- 仍需要模拟多种实际异常；
- 必须补齐上一轮未实现的设计并建立硬验收。

## 本次冻结

详见：

- `docs/research_v7_align_behavior/18_DETECTOR_V2_EXPERIMENT_PLAN.md`
- `docs/research_v7_align_behavior/19_DETECTOR_V2_AGENT_CONTRACT.md`
- `docs/research_v7_align_behavior/20_DETECTOR_V2_IMPLEMENTATION_BLUEPRINT.md`
- `docs/research_v7_align_behavior/21_PREVIOUS_DETECTOR_RESULT_CORRECTIONS.md`
