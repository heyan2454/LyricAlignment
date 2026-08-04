# 阶段 B 进展 — 真实行为证据

**更新：2026-08-04 · 计划：research_v7_align_behavior**

## 已完成的真实运行

- 完整 R2 executor、raw/official/posterior/repair trace、immutable evidence、hash collection/verify、GT paired bootstrap、无 GT review bundle 均已实现并测试。
- demo：35 首 / 140 attempts（baseline、extra50、missing50、cross-song no-match）；所有真实运行 `ok`。冻结 partition：dev 19、validation 9、heldout 3、challenge 4。无 GT，不报告 accuracy。
- demo C10：从 33 首真实歌词的重复片段构造 66 个短重复/双重复 request；真实运行、hash verification 与 blind-review bundle 均完成。
- MIR-1K heldout：4 source song、C1–C6 主曲线 268 attempts；stateful P0/P1/P2/D/S 36 attempts；另有 80-unit cursor ±2/4/8 三段矩阵 100 attempts。全部使用完整 source audio；早期 GT-cropped outputs 已降级为 oracle control。P1 现将 committed prefix/all prefix slots 真实送入 processor；S 仅保留当前新段 slots。
- M4Singer test：19 source-song strata（每歌最长可用 native item），C1–C6 共 1,178 attempts；C7–C9 共 190 attempts；全部真实执行、collection verification 无错误。
- Provisional：MIR heldout 80-unit/三段 full/last-8/last-16/last-predicted-10sec slot-policy matrix 76 attempts，真实执行并校验。

## 当前冻结观察（不是超出样本范围的结论）

- MIR heldout workflow：S 与 P0 基本持平；P1/D 显著变差，P2 部分恢复。优先继续 sparse-slot 路线。
- M4 C1–C6：19-song macro ΔMAE `+1.0216s`，source-song bootstrap 95% `+0.8863..+1.1498s`。
- M4 C7–C9：音频后半段单独输入最不利（平均 ΔMAE `+2.7225s`），起点延后 `+1.1905s`。
- 100% replacement 的无正确文本锚点被保留为 unscorable/catastrophic 分母，未计入 MAE 分子。

## 仍需完成

- C10 已补 MIR heldout 3-song / 6-attempt multiple-legal-answer GT control；C6 已含同歌错段、纯器乐、错语言等独立对照。demo C10 仍是无 GT review，不混同为 accuracy。
- 更长序列的 commit/provisional 恢复传播矩阵（80-unit 三段已完成，但不能代替长程结论）。
- GT strata 的 localization thresholds、coverage/overlap、posterior/repair 信号分层和综合报告。
- demo 人工盲审填写与无 GT 错误时长统计；没有人工标签前不可作 quality/accuracy claim。
