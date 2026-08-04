# Stage B 行为报告（冻结证据版）

**日期：2026-08-04**

## 证据范围

所有数值来自本地完整 Qwen3-ForcedAligner-0.6B + R2 step-000750 的真实 GPU 推理；每个 collection 已做 evidence SHA256 和 request identity 校验。production-like 运行使用完整 source WAV，GT 仅在运行后用于评分。

正式运行的输入、freeze、collection 与 evaluator/review artifact 已汇入内容寻址索引：`/root/autodl-tmp/AST_storage/Data/lyricalign/runs/research_v7_align_behavior/research_v7_provenance_index_20260804_v9.json`（SHA256 `d92da5ff47ab72939c0957cdbd9e1f00bd85ac00ee285dd5cb7bce886f9ed18a`；16 个 run、2,269 条 collected evidence）。索引会显式列出缺失文件；唯一没有独立 manifest 的是单条 `real_weighted_top16_contract_20260804` contract proof，其 request 仍由 collection/evidence identity 固定。

| 范围 | 真实 attempts | 可用结论 |
| --- | ---: | --- |
| M4Singer test，19/19 source-song C1–C6 | 1,178 | source-song 母集全覆盖的文本量/替换/strict no-match 主曲线 |
| M4Singer test，19 source-song C7–C9 | 190 | 音频范围错误 |
| MIR-1K heldout，4 source-song C1–C6 | 268 | OOD 小样本主曲线 |
| MIR heldout formal accompaniment C6 | 8 | 4 首 vocal baseline 与 real accompaniment 的 GT paired control |
| MIR stateful workflows/cursor/provisional | 36 + 100 + 76 | P0/P1/P2/D/S 与状态敏感性 |
| MIR recovery workflow | 16 | 错误 committed prefix 后恢复正确输入的传播检验 |
| 全部 test demo | 140 | 无 GT 行为、人工复核 |
| demo 重复段 C10 | 66 | 无 GT 多解/重复段复核 |
| MIR heldout C10 multi-answer | 6 | 3 首存在真实非重叠重复段的 controlled GT 多解评分 |
| M4 C6 text controls | 76 | 重排、随机置换、错语言 unit |

## 冻结观察

- M4 C1–C6：19-song macro ΔMAE `+1.02163s`，cluster bootstrap 95% `[+0.88634,+1.14976]s`。`source_song_coverage.json` 已证明 839 个 test segments 的全部 19 个 source song 均有一个最长可用代表；这是 source-song 母集全覆盖，但不是 839 segment 全量推理。extra、missing、replace 分开保存在 `gt_paired.json`；100% replace 的 72 条无正确锚点保留为 unscorable，而非从分母删除。
- 定量诊断（冻结 evidence 逐边界、仅匹配的真实文本单元）：M4 baseline 的 `≤0.25s` 边界命中率为 `98.68%`、近零时长率 `0.38%`、repair boundary ratio `2.42%`；extra 为 `77.60%/41.84%/26.57%`，missing 为 `76.16%/10.27%/7.61%`。MIR 也出现相同方向：baseline `≤0.25s=99.61%`，extra/missing 为 `81.50%/79.65%`。完整 0.25/0.5/1/2/5 秒阈值、gap/overlap、posterior/repair 字段汇总保存在各正式主曲线 run 的 `gt_evidence_diagnostics.json`。
- 内部信号可分离：以 request 平均 posterior start entropy 区分 mutation 与合法 baseline，M4 的 AUROC 为 extra `0.962`、missing `0.773`、replace `0.954`、strict no-match `1.000`；MIR 分别为 `0.928/0.859/1.000/1.000`。start-margin 得到同向结果。`internal_signal_separation.json` 使用 request（不是字符行）为统计单位；这是 QualityAssessor 的可行信号证据，不等于已训练/校准的质量模型。
- M4 C7–C9：音频后半段单独输入最严重（ΔMAE `+2.72253s`）；起点延后为 `+1.19046s`。
- MIR workflows：stateful P1（committed prefix + full prefix slots）与 P0 基本持平；独立短文本 D 明显差；P2 部分恢复；S（仅当前 segment slots）同样与 P0 基本持平。
- Recovery workflow：4 首 × 80 units 的三段链中，先送正确 prefix、再送反序错误 committed prefix、最后重送已纠正 full prefix；最后段相对同一 P0 尾段的 ΔMAE 均为 `0.0s`。这证明当前调用式实现不会把前一请求的错误文本保留为跨调用隐状态；不是“错误请求本身无害”的泛化结论。
- 新 evidence contract 保存 raw/official/top-16 posterior/weighted-isotonic/repair trace；历史 top-8 evidence 不会被事后称为 top-16。自动 taxonomy 只覆盖可验证几何：`ZERO_DURATION_CLUSTER`、额外字的 head/tail collapse、`DECODER_REPAIR_DOMINATED`。其它语义标签保留给人工复核。
- C6 controls：重排真实文本和随机置换在有正确 anchor 的 subset 上均恶化；错语言 unit 的 19/19 无正确 anchor，明确只报告行为/几何而非 MAE。
- C6 formal pure-instrumental：本地 MIR heldout 4/4 均有与 `official_vocal.wav` 同目录的真实 `accompaniment.wav`。8 次真实运行（4 vocal baseline + 4 accompaniment-only）均可评分；伴奏相对 vocal baseline 的 macro ΔMAE 为 `+23.46764s`，source-song bootstrap 95% `[+15.13557,+37.18049]s`，4/4 harm。这是有 GT 的 pure-accompaniment 结论，不再以 demo 盲审替代。
- C10 controlled GT：MIR heldout 的 4 首中，3 首具有长度 6–16 的真实非重叠重复段；在完整 source WAV 上运行 single-ambiguous 与 ordered-double 共 6 次。single 的多答案最小 MAE 均值为 `16.49057s`（范围 `0.03332–32.54855s`），ordered double 的均值为 `22.84921s`（范围 `1.02238–36.33513s`）。该小样本显示稳定错段/多段分裂确实存在，但不外推为所有歌曲的发生率。
- 伴奏+真实歌词：全部 35 demo 的本地 `accompaniment.wav` 已真实运行并进入盲审；它是 verified accompaniment-only 音频，但仍无 GT，不能写入 formal MAE/accuracy。
- 人工盲审交付已拆分为不含 mutation type 的 140 个全 demo packet 与 66 个 C10 packet；实验者 decode key 独立保存。packet 提供固定 taxonomy、`severe_error_minutes`、`longest_error_sec` 与 `unresolved` 字段，但当前仍未填写，不将空模板当作人工结果。
- 同歌 wrong-section：从同 source song 的其它原生 GT segments 派生（19 song / 38 attempts）；仅 5 条存在正确 anchor 可 MAE 配对，余下显式 unscorable。该 control 不是连续远处副歌的等价替代。

## 不能声称的内容

- demo 没有 GT，不报告其 accuracy/MAE，也不把 review queue 当 pseudo-GT。
- 每个 source song 只取一个最长可用代表，故 M4 的 source-song 母集（19/19）和 MIR heldout 的 source-song 母集（4/4）均已覆盖；这仍不等于对 M4 全部 839 个相邻 segment 的独立推断。报告以 source-song bootstrap 而非切片数作不确定性单位。
- early GT-timestamp-cropped mutation runs 仅为 oracle-localized control，不属于 production 主结论。
- C10 已补有 3-song controlled multi-answer 小样本，且 recovery-after-correction 已在所有 MIR heldout source song 完成；demo C10 的 66 个案例仍为 no-GT review，不能写为其 accuracy。

## 可复现入口

各 run root 下均含 manifest（部分 workflow 使用 `workflow_manifest.jsonl`）、freeze、donor manifest（如适用）、`collection.json`、`verification` 命令输出、analysis/GT evaluator 输出。新增 `build_research_v7_provenance_index.py` 可从这些根目录重建/校验索引；完整命令与 SHA256 见 [08_AGENT_EXECUTION_LOG.md](08_AGENT_EXECUTION_LOG.md)。
