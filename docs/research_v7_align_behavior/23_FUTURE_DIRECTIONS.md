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
   （detector_v2_models.py L376）。**已探索（2026-08-06）**：`analyze_pbad_calibration_sgcv.py`
   实现 song-grouped 5 折 CV（折内 train 拟合 isotonic/temperature）→ 20 歌 CV：
   raw ECE 0.257±0.012 → isotonic **0.0197±0.0040**（official 0.0205±0.0043），
   temperature 差（0.14 量级）——isotonic 跨歌稳健，单次 5 歌 val（0.013）有轻度
   乐观偏置但量级不变。cost model（C1=10/C2=5/C3=1）：uncertain 带无存在价值，
   最优审查阈值 = T_reject（总代价 raw 23285→9375）；只有 C3 相对 C1 上升时才值得
   保留审查层。产物：`runs/research_v7_detector_v2/exploration/sgcv_calibration.json`。
3. **CNN1D 序列模型**（light_merge 替代）：sequence_model 已完整实现（numpy 1D CNN）
   **已接入公平比较（2026-08-06）**：`evaluate_sequence_cnn1d.py` 构造 song-grouped
   序列数据集（歌内 canonical 序 = official.start_sec 升序，T=90% 分位截断 4465、
   尾填 0 + mask，序列标签 = 序列内 any-unsafe，frozen 契约 y=(n,)）；真实 run2 上
   CNN1D 收敛（loss 1.60→0.10）但窗口级 broadcast 评价 **degenerate（protocol=0，
   small_mlp 0.798 / GBDT 0.0）**——序列级 any-unsafe 监督广播到窗口级无区分度，
   需序列级评价（整体窗口段预测）或逐窗口监督（改 sequence_model 契约）才有意义；
   且边界一致性未被此设计捕获。产物：
   `runs/research_v7_detector_v2/exploration/sequence_cnn1d_compare.json`（review
   后行序对齐：window_indices/y_window 保证与基线同序评价）。
4. 自监督 cross-view 一致性（cv_posterior_distance vs label spearman）——免费信号，
   服务标签审计。**已审计（2026-08-06）：结构性缺失**——`audit_cross_view_signal.py`
   全量核对 run2（134538 行）：cross_view 仅成员元数据（非空 14441 行，无
   posterior_distance/posterior_vectors 字段），evidence 不存完整 posterior（仅
   raw.topk 截断），每 request 单 view（full/overlap 无法同单位共地）→ F3 的 None
   根因确认，**离线不可重算**；复活需请求管线在 MULTIVIEW 组内显式计算
   mean pairwise posterior L2 距离并落盘。产物：
   `runs/research_v7_detector_v2/exploration/cross_view_audit.json`（label 口径
   = official target，join 键 (request_identity, view_id, canonical_unit_id)）。
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
