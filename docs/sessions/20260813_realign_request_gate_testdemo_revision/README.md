# 2026-08-13 — Realign Request / Gate / Test Demo Revision

本 session 是对 `20260812_detector_production_realign_gate` 当前真实运行结果的 review 后修订。

目的不是继续放大当前错误或不充分的 P1/P3 统计，而是把下一轮实验重新聚焦为：

1. 保留已经基本可信的 P0 production detector baseline；窗口级 `any reject -> unsafe` 的 97.5% 不再作为主要研究指标。
2. 将 realign request 从整窗/粗 region 推向真实局部 interval / unit 级，比较多种**实际改变 forward 输入**的请求方式。
3. 重新实现并真实运行 R-A / R-B；R-B 必须存在真实左右 safe anchors，禁止 null/no-op R-B 被当作 intervention。
4. 将 `n_big` 降级为 change-magnitude diagnostic，继续主动寻找能区分 improve / neutral / harm 的 no-GT realign gate 信号。
5. Test Demo 必须使用真实模型与真实 detector/realign pipeline；mock 结果不进入实验结论。
6. “样本不足”不是默认停止理由。agent 必须主动改变采样层级、扩大 eligible population、补构造或利用 cache，直到达到预先定义的最小有效样本，或穷尽数据并给出可审计的不可满足证明。

文件：

- `00_SESSION_DISCUSSION_RECORD.md`：本轮 review 与用户反馈的完整记录。
- `01_REVIEW_FINDINGS_AND_CORRECTIONS.md`：当前实验结果的审计结论与需要纠正的口径。
- `02_NEXT_ROUND_EXPERIMENT_DESIGN.md`：下一轮实验原因、目的、设计、预期结果与可支持结论。
- `03_CODEX_HANDOFF.md`：交给 Codex 的合并与实现方案要求。
