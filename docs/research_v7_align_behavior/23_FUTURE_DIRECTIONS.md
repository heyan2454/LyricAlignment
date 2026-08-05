# Detector V2 之后：未来方向探索与实验设计（2026-08-06）

来源：两路并行 explore（方向 A：repair 闭环/streaming/多语言/自监督；方向 B：
序列模型/校准/数据基建/产品化）+ 本轮返工（22 文档 Phase A-D）的经验。
状态：**设计素材，未立项**。所有方向受 22 验收约束：传播未观测（serial）、
safe_accept 低（4-21%）是当前 frozen 点的属性，新实验须在修正标签 + song-grouped
split 上运行。

## 排序（共识）
1. **repair 闭环产品**：detector 三态 → repair 候选生成（demo/realign_diagnostics
   repair_context_agreement/select_single_repair_candidate 已现成）→ uncertain 额外
   验证（serial multi_view 已验证 30 次请求机制）→ shadow 提交 → 用户确认写回
   （actual_writeback=0 约束下先做模拟确认层）。serial 传播不可观测的解法之一：
   在 accept 区间内推进 cursor 而非窗级二元。
2. **p_bad 校准 + uncertain 成本模型**：性价比最高（纯 CPU）。基元已有：
   v6 weighted_isotonic（decoders.py L208）、hidden_linear_probe 的 sigmoid 校准
   （detector_v2_models.py L376）。脚本 analyze_pbad_calibration.py 已写（Brier/ECE/
   reliability diagram）。风险：val 仅 5 歌，校准曲线需 song-grouped 交叉验证。
3. **CNN1D 序列模型**（light_merge 替代）：sequence_model 已完整实现（numpy 1D CNN）
   未接入公平比较；边界一致性由卷积窗口隐式建模。需 song-grouped 序列数据集
   （canonical 序、定长 T）。
4. 自监督 cross-view 一致性（cv_posterior_distance vs label spearman）——免费信号，
   服务标签审计。
5. 多语言（数据缺口最大，需新数据立项）；streaming（回放式 harness 与 serial
   共享基建，VAD 接入点在 window_planning 静音 region）。

## 本轮返工沉淀的可复用资产
- 全局 GT 确定性映射（segment_offsets + source_segment_id/source_unit_index）+
  6 项语义测试（22 §2.4）
- query_set/output_set 三集合语义（22 §3.2）+ sparse 分母测试
- 模型阶梯（rule/logistic/GBDT/MLP）+ 常量基线 + 双约束冻结（constraint_violated
  如实报告）+ per-model trade-off 表
- serial unit 级提交仿真（simulate_route）+ stride overlap 轨迹生成器
- matched common-unit 视图评价（full/sparse/overlap agree 0.92-0.99）
- MIR 单段回退（弱标签整曲，免重新 forward）
