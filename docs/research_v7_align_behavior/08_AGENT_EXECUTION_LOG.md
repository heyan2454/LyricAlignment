# research_v7 执行记录

## 2026-08-03 — Stage A revalidation 与真实 workflow pilot

### Stage A revalidation

- 输入：v8 formal root
  `/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/alignment_research_v6_formal_20260731_e9_lazy_compact_v8_inputcache_e9scope_aggregatefix`
- 输出：`/root/autodl-tmp/AST_storage/Data/lyricalign/runs/research_v7_align_behavior/stageA_revalidated_20260803/`
- E1：21,527 GT item；event micro F1 `0.127919`，item macro F1 `0.079772`，source-song cluster bootstrap median `0.079593`。
- E5：807 个原 artifact 均缺失 fixed baseline；拒绝以 dynamic variant 替代。因此旧 E5 的 paired negative-result 结论在当前保存的 formal artifact 上**不可验证**。
- E6：11,988 paired variant；mean ΔMAE `+1.0545s`，improve/harm/no-change `923/3268/7797`。

### Frozen real workflow pilot

- manifest：`runs/research_v7_align_behavior/real_workflow_pilot_20260803/workflow_manifest.jsonl`
- freeze：`pilot_freeze.json`，manifest SHA256
  `b7ebe55c8f05b917afb1dbebad58befca0cebaf1c1e869523f839b0ed04f1b6a`。
- 输入：v8 formal manifest 的 MIR-1K `mir1k_fdps_1`，official vocal，前 64 GT units。
- 模型：本地完整 Qwen3-ForcedAligner-0.6B snapshot + R2 `20260724` step-000750；环境 `lyricalign-qwen`。
- 运行：P0、P1×2、P2×2、D×2、S×2 共 9 attempts，全部 `ok`；collection hash verification 无错误。
- P2 第二段：父 P1 cursor `19.84s`，以 10s left context 得到 audio start `9.84s`。
- S 第二段：64-unit text context、slot `32..63`，返回 32 个目标 units；其 evidence 位于
  `items/mir1k_fdps_1/`。

### 限制

- 这是单 item controlled pilot，不是 formal GT behaviour；不得据此比较路线优劣。
- 尚未冻结 cross-song donor manifest，也没有运行 mutation 主曲线、demo review、validation 或 heldout。

## 2026-08-03 — 派生 long-audio GT pilot（真实执行）

- v8 formal manifest 的 synthetic-long `audio_path` 已失效；没有把该缺陷掩盖为可用 validation。
- 从现存的
  `/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/inline_realign_formal_v2_20260728/materialized/m4singer/long_60s/`
  构造了 6 条 `derived_pilot` record。每条保留 vocal、逐字 GT、原
  `source_manifest.json` 以及 audio/GT/source manifest SHA256；不推断其 formal split。
- 冻结：`runs/research_v7_align_behavior/legacy_m4_60s_derived_pilot_20260803/pilot_freeze.json`，behavior manifest SHA256
  `fedc1bee5a006fc16e277ff564bf07ba93a081c058ffc1b13db10943184a5089`；donor manifest SHA256
  `7ec2989add73085c323bfc7ffea5ff5a698340f3ff5211692767926a72998f24`。
- donor 规则：跨 source song、64-unit 等长连续片段、normalized LCS <= 0.20、bigram Jaccard <= 0.25；语音相似度在逐字 GT 条件下不可获得，显式记录为 unavailable。
- 真模型完成 6 item × baseline/extra50/missing50/replace50/no-match = 30 attempts，全部 `ok`；collection identity/hash verification 无错误。
- GT 配对评价仅覆盖 baseline/extra/missing/replace 的正确文本 core；no-match 不被包装成 accuracy。18 个可配对 attempts：improve/harm/no-change = `6/9/3`，micro ΔMAE `+0.000379s`；6 source-song bootstrap 95% 区间 `[-0.002251, +0.002752]s`。
- 这是派生、6-song、单 ratio pilot，只用于验证证据链与暴露失败形态，**不是** M4 validation/test 或 heldout 结论。

## 2026-08-03 — MIR-1K heldout mutation 运行（真实执行）

- 目标来自既有 v8 active manifest 中 `selection_role=heldout` 的 4 条 MIR-1K：`mir1k_jmzen_1`、`mir1k_stool_1`、`mir1k_annar_1`、`mir1k_tammy_1`；没有使用 M4Singer train 或派生 long pilot。
- 冻结目录：`runs/research_v7_align_behavior/mir1k_heldout_mutation_formal_20260803/`；behavior manifest SHA256
  `636fd96b2de4639760320efd2802cc855584f85ea013489109b63d04e668f7b9`，strict donor manifest SHA256
  `ab51ef5788728d6661498b938e87776620123810053b7464e7b727b1ec7a23bb`。
- 执行：4 item × baseline/extra50/missing50/replace50/no-match = 20 次 R2 真模型 attempts，全部 `ok`，collection hash verification 无错误。新的 evidence 含 raw/official、posterior top-K/entropy/margin 和 official repair trace；weighted isotonic 明示为未运行。
- 仅就 frozen ratio=50% 的 GT core 配对：12 个 applicable，improve/harm/no-change `2/8/2`，micro ΔMAE `+0.018333s`；4 source-song bootstrap 95% 区间 `[-0.000864, +0.037530]s`。extra/missing/replace 的均值分别为 `+0.000312`、`+0.000398`、`+0.054288s`。
- 这是一组小型 frozen heldout slice，比例曲线、更多 OOD item、完整 P0/P1/P2/D/S 对照和 no-GT review 尚未完成；不把它扩大为总体结论。

### 2026-08-04 更正

- 上述 early GT mutation compiler 使用了第 N 个 GT unit 的结束时间作为 audio end。这违反 production-like 实验不得按 GT 裁音频的约束。因此 legacy long pilot 与 4-item MIR heldout mutation slice 仅保留为 **oracle-localized controlled evidence**，不再称作 production formal；不会将其数值用于生产型主结论。
- `build_gt_mutation_manifest.py` 已改为默认读取完整 source WAV duration；仅在显式 `--oracle-gt-audio-end` 时才允许该 oracle control。后续 formal mutation 需以新 manifest 重新冻结、重跑。

## 2026-08-04 — 全量 test demo 无 GT 行为集（真实执行）

- 使用既有 active manifest 全部 35 条 `dataset=demo`，没有只保留两首 smoke。两首中文歌的早期 8 attempt 是链路检查；本节为独立的全量冻结运行。
- 构造并冻结：`runs/research_v7_align_behavior/demo_all_partitioned_20260804/manifest.jsonl`，SHA256
  `f61e91a883e03b99ee8b96e45b1f106a6e05d11321170d42c74aac095d897ade`。按 source identity hash 固定且无标题泄漏地划为 demo_dev/validation/heldout/challenge，item 数为 `19/9/3/4`（attempt 数 `76/36/12/16`）。
- 语言覆盖：Cantonese 6 song（24 attempts）、Chinese 17（68）、English 6（24）、Japanese 6（24）。真实 R2 运行 baseline、tail extra50、tail missing50、跨歌 no-match，共 `35 × 4 = 140` attempts；全为 `ok`。
- 输出：`collection.json`（140 record）、`analysis.json`、`review_bundle.json`（140 blind-review cases）；identity/hash verification `errors=[]`。
- demo 无 GT：review bundle 每例均带音频、原歌词、请求文本、证据 SHA256 和空白人工标签栏；明确禁止生成/汇报 MAE、accuracy 或伪 GT。此数据用于多路线观察和人工复核，不混入 controlled GT 结论。

## 2026-08-04 — production-like MIR-1K heldout C1–C6 与 workflow

- 重新冻结的 production mutation 以及完整 C1–C6 曲线均使用 **完整 source WAV**，不以 GT time 裁音频；GT 只在执行后用于评价。
- C1–C6 主曲线：`mir1k_heldout_c1_c6_production_20260804/`，4 song、268 个真实 attempts（baseline 4、extra 100、missing 80、replace 80、strict no-match 4），全部 `ok`，collection verification 无错误。frozen manifest SHA256 `3f790d024093dfab59450c318a0a490d8ccd1569f1ab3018d0a7b92796e28b78`。
- Core MAE 配对：eligible non-no-match 260，applicable 252，unscorable（100% replacement 无正确文本锚点）8；improve/harm/no-change `21/174/57`，micro ΔMAE `+4.3902s`，4 source-song bootstrap 95% `[+3.8271,+4.8840]s`。extra/missing/replace 分开保存；不得把 8 条 unscorable 从分母中静默删除。
- workflow：`mir1k_heldout_workflow_production_v2_20260804/`，P0/P1/P2/D/S 共 36 个真实 attempts，全部校验通过。mean MAE（相对 P0）：P0 `0.03281s`；P1 `+3.89759s`；D `+3.89759s`；P2 `+1.61194s`；实际 sparse-slot S `-0.00023s`。这是 4-song frozen heldout slice，而非总体估计；当前决策证据指向 sparse slots 优先于孤立短文本 controller。
- **后续实现审计更正**：P1 当前只存储 parent/cursor/commit lineage；same-audio short-text 模型输入未包含 cursor 或 committed prefix，所以 P1 在模型层与 D 等价。P1/D 的相同数值只能证明这一实现等价，不能证明 strict serial controller 失败。S 的 prefix text + actual sparse timestamp slots 才是当前真正 stateful 的输入变体。

## 2026-08-04 — M4Singer test C1–C9 与 demo C10（真实执行）

- M4Singer test native 共 839 item、19 source song。为防止相邻短片段伪重复，按 source song 选择最长可用 item，冻结 19-song strata；strict donor 候选补入已有 legacy long materialization，但 donor source 与 target source 仍严格不同。
- C1–C6：`m4singer_test_c1_c6_production_20260804/`，1,178 real attempts（全部 `ok`、hash verification 无错误）。GT paired 的 eligible/applicable/unscorable 为 `1140/1068/72`；19-song macro ΔMAE `+1.02163s`，bootstrap 95% `[+0.88634,+1.14976]s`。
- C7–C9：`m4singer_test_c7_c9_production_20260804/`，190 real attempts（全部 `ok`、verification 无错误）。171 paired，macro ΔMAE `+0.99424s`。按范围：start-late `+1.19046s`、end-early `+0.33724s`、prefix/middle/suffix half 为 `+0.80654/+0.83602/+2.72253s`。
- C10：从 active demo manifest 的原歌词检测到 33 首非重叠 exact repeated n-gram；生成 short-repeat/double-repeat 66 real attempts，写入 `demo_c10_repeated_sections_20260804/`，且 66 条均已进入无 GT blind-review bundle。没有将其称为 strict no-match 或 GT accuracy。
- `analyze_alignment_behavior.py` 现另外输出保守自动 taxonomy：仅零时长簇、额外头/尾部塌缩和 repair 主导；其余情形保持未标注，交人工 review，避免以启发式伪造语义结论。

## 2026-08-04 — stateful P1 与 cursor 注入

- 审计修正后，P1 改为 `strict_serial_committed_prefix_all_slots`：每段将已 committed 的 text prefix 与全部 prefix timestamp slots 真实送入 processor，只过滤/提交当前新段。它与 S 不同：S 仅给当前新段 slots。
- `mir1k_heldout_workflow_stateful_p1_20260804/`：4 song、64 units、36 real attempts。P1 的 mean ΔP0 MAE `0.00000s`；D `+3.89759s`；P2 `+1.61194s`；S `-0.00023s`。这替代了 metadata-only P1 的无效比较。
- `mir1k_heldout_workflow_cursor_matrix_20260804/`：因其中一条 MIR 仅 85 units而用 80 units/三段，100 real attempts，全部 hash-verified。P1 cursor offset `-8/-4/-2/+2/+4/+8` 的 ΔP0 分别为 `+0.000579/-0.000209/-0.000443/-0.000366/-0.000433/-0.000734s`（每个 8 chunk）。这是 4-song small slice；其稳定性不能外推为 controller robustness。

## 2026-08-04 — provisional commit matrix

- `mir1k_heldout_workflow_provisional_matrix_v2_20260804/`：80-unit/三段、76 real attempts、collection verification 无错误。provisional 是实际 timestamp-slot mask：last 8 units、last 16 units，以及按 parent predicted cursor 回开 last 10 seconds；不是事后删行。
- 8 chunks/policy：last-8/last-16/last-predicted-10sec 的 ΔP0 分别 `+0.000333/+0.000255/-0.000068s`。该小样本没有支持默认启用任一 provisional policy；保留为状态敏感性证据。

## 2026-08-04 — C6 独立文本机制控制

- `m4singer_test_c6_text_controls_20260804/`：19-song M4 strata × exact/reordered real lyrics/random permutation/wrong-language-unit = 76 real attempts，全部 hash-verified。
- reordered 的 applicable 14/19，macro ΔMAE `+0.31341s`；random permutation 13/19，`+0.71017s`；wrong-language/unit 的 19/19 无正确 GT anchor，明确输出 unscorable 而不造 MAE。
- 同歌错段与纯器乐区需要同一 formal target 的可验证独立 materialization；当时尚未构造，未用跨歌或随机文本冒充它们。

## 2026-08-04 — C6 same-song wrong-section 衍生 manifest

- 后续从同一 `source_song_id` 的其它原生 M4 test GT segments 拼接真实错误段，并逐 donor segment 保存 provenance；目标音频仍是完整 target WAV。
- `m4singer_test_same_song_wrong_section_20260804/`：19 song、38 real attempts、hash verification 无错误。same-song wrong-section eligible/applicable/unscorable=`19/5/14`；5 song 的 macro ΔMAE `+0.29824s`。14 条无正确 anchor 明确保留为 unscorable。
- 这实现的是同歌真实歌词但多 segment 拼接的 wrong-section control；它不是声称连续的单一远处副歌。纯器乐正式 GT control 仍未完成。

## 2026-08-04 — low-vocal-energy + real lyrics review control

- 从全部 35 demo vocal WAV 以固定 8s sliding RMS 选择最弱窗口，输入真实歌词；`demo_low_vocal_energy_controls_20260804/` 完成 35 real attempts、hash verification 和 review bundle。
- 每条记录保存 RMS、起止时间与 `low_vocal_energy_candidate`；这是可盲审的候选纯器乐/静音控制，**不是**人工确认或 GT formal pure-instrumental claim。

## 2026-08-04 — verified accompaniment-only + lyrics control

- 随后发现每个 demo prepared root 均包含 `work/audio/accompaniment.wav`。`demo_accompaniment_controls_20260804/` 使用该真实 accompaniment（非低 energy proxy）和原歌词，35 real attempts、collection verification、review bundle 均完成。
- 该控制是 verified accompaniment-only 音频，但 demo 无 GT，仍只报告结构化行为/盲审，不报告 MAE/accuracy。

## 2026-08-04 — evidence contract closure

- 新 real executor 将 posterior 从 top-8 升至 top-16，并实际保存 posthoc `weighted_isotonic` rows（raw/official/top-K/weighted/repair trace）。
- `real_weighted_top16_contract_20260804/` 真实 contract case：posterior top_k=16、16 saved candidates/boundary、11 weighted rows，collection verification 无错误。历史 evidence 保留其 top-8/weighted unavailable 状态，未重写成新格式。
- `run_behavior_suite.py --resume` 现仅会在 request identity 完全一致时复用 evidence；默认遇到已存在 evidence 拒绝覆盖。smoke 已验证首次写入、identity-equal resume（0 新写入）和不带 resume 的拒绝覆盖。
