# Review 8 — 产品化验证综合审查

审查范围：截至 Round 25 的所有 Evaluation V1 产物、脚本、canonical 结果和报告。

## 结论
无 P0/P1。所有关键数字均来自实际运行 JSON，不是手抄。

## 关键验证
- GTSinger 75 段 official R2：both_100ms=90.05%
- GTSinger 75 段 raw decoder R2：both_100ms=91.84%，20 improved / 2 regressed
- hard18 raw decoder：78.32% -> 84.47%
- PJS official vs rawdecoder：结构 warning 对比已记录，待 phoneme GT
- MIR raw mixture：全部 warning，确认必须先 vocal 派生
- sealed gate：默认拒绝 sealed，测试通过
- 所有外部批次有 cleanup report

## 遗留风险
- raw decoder 2 个回退段需要 hybrid/局部精修研究
- PJS 无 phoneme GT，日语结论仍是结构级
- MIR/Jamendo vocal 派生未执行
- sealed milestone 未端到端运行

## 建议
- 下一步优先 raw decoder regression_selection 验证
- 将 PJS phoneme GT 作为日语正式化前置
- 在 vocal 派生完成后接入自然混音评测
