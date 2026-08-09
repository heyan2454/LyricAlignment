# Negative Results v2

- **H（hidden）**：blocked_api——output_hidden_states 未接入，无伪造特征。
- **PR（propagation-risk）**：not_executed——需 Gate P corpus 后构造（本 session 未执行）。
- **Closed loop v3**：L-SA60 与 W-R95 均 Gate C 失败（9/9）——retry 无改善、无 retry-derived 写回，不虚报 recovery；v2 detector（R, heldout AUC 0.638）在 corrected serial 上 p_bad 偏高，L/W 无产出。
- **Joint SA60+R95**：不可行（分布重叠，见旧 pareto 分析；v2 单阈值工作点未做 joint）。
- **V 特征**（20260807 探索）：无 heldout 增益（0.595→0.588），停止分支。
- **旧 20260807 结论**：serial formal/propagation/detector/closed-loop/320ms 标签均 invalidated；本 v2 报告 supersede 旧 corrected 报告（320ms primary）。