# F_note — 07_CODEX_IMPLEMENTATION_PLAN.md 代码正确性与契约 review（P0/P1）

> 会话：`20260814_realign_recovery_visualization_overnight`
> 审查对象：`07_CODEX_IMPLEMENTATION_PLAN.md`（Codex 实现方案）
> 范围：只报 P0/P1（CRITICAL/MAJOR）。逐项对照本 session 合同 02/03/04/05 + provenance B/C/D/E。
> 结论：**无 P0**；P1 共 3 项；MINOR 若干（记 backlog 不阻塞）。

---

## 审查清单结论速览

| 清单项 | 结论 |
|---|---|
| 1. 契约一致性（frozen 项逐条） | **通过**，无违反（见 §A） |
| 2. identity/cache（parent/recrop/split 并入 + 独立 cache 漏网） | **P1 ×2**（split_slot_id 未落在 code map；独立 cache 未纳入） |
| 3. R-B/GT 防火墙 | **通过**（07 明确不为旧 R-B/E5/compat 背书；no-GT 不读 GT） |
| 4. 信号口径（raw/official 单 logits 双解码；hidden 非默认导出） | **通过**（07 未混淆） |
| 5. 可视化 adapter 可行性 | **P1 ×1**（R-U/R-S 缺 canonical_unit_id→global_character_index/text 显式反映射） |
| 6. 可执行性/断句 | MINOR（run root P8 扩量缺失；pipeline 双方案二义） |

---

## A. 契约一致性（清单 1）：通过

逐条对照 03/04 frozen 项，未发现违反：

- **collection 先于 visualization**：07 L52（原则8）、L110（pipeline 阶段顺序调整）、L159/L211/L232-233/L246（各 WP）。07 L110 及 D_note §B.1 明确指出现有 pipeline 顺序 visualization→collection 与 03 V4 相悖并给出修正。
- **rerender 不重复 forward**：07 L52/L121/L194，`render_rerender_only.py`（§4.3）+ scientific hash 断言。
- **actual_writeback=0**：07 L13/L45/L173（`test_coarse_fine` writeback=0）。
- **GT 只进 evaluator**：07 L46/L193 (`evaluate_*` join)、L175（test_gt_firewall_ext 覆盖新 family）。
- **cache-only rerender + scientific hash 稳定**：07 L52/L174/L194/L259。
- **不做全笛卡尔积**：07 L50/L191/L266，与 04 §4 一致。
- **第四路不冒名**：07 L164 明确"R-U->sparse 未过 smoke 前四路只能用三路（03 V2）"，未把 R-B/R-A/重复 R-U 当第四路。

## B. identity/cache（清单 2）

### P1-1 split_slot_id 未落到 code change map（口径不一致，前因 C_note §3.3 已提示）
**问题**：冻结原则 5（07 L49）把 `parent_candidate_iteration` / `recrop_view_id` / `split_slot_id` 三者"必须并入 request identity"，且清单明确点名 `split_slot_id`；但 code map 只加后两个：
- 07 L107（§4.2 `build_request_identity`）：只加 `parent_request_identity`/`iteration`/`recrop_view_id`。
- 07 L204（WP1）：同样只有这三个 key。
- 07 L99（§4.1 `split_variants.py` E2）不携带 split identity key。
**证据**：`src/lyricalign/unit_realign/request_families.py` `build_request_identity`（L50-62）当前 8+key 集合不含 split 维度；C_note §3.3 明确"split 需新增显式维度（如 split_slot_id）才能避免跨分片复用旧 forward"。07 L259 虽写"含 …recrop/split"，但这是总述，未落到 build_request_identity 的具体键名。
**建议**：把 §4.2/WP1 的 key 列表补上 `split_slot_id`（或明确声明由 canonical_ids 变化隐式覆盖并写进 WP1 回归测试，二选一，不能既冻结又落空）。G0/G3 前必须敲定。

### P1-2 B4 serial demo 的独立 forward cache（research_infer_cache_key）未被 identity 扩展纳入（遗留漏网）
**问题**：B4 走 `align_qwen_fa_serial_demo.py --decoder official`（07 L79）→ `infer_slice` 的 `research_infer_cache_root`，其 cache identity `serial_infer_actual_input_cache_v1`（`scripts/demo/align_qwen_fa_serial_demo.py` L250-285 实测）只含 `audio_sha256/audio_sample_count/global_audio_offset_sec/character_range/alignment_units/timestamp_slot_indices/…/decoder_kind`，**不含** parent/iteration/recrop_view/split 维度。07 §4.3 `render_rerender_only.py`（L121）与原则 8（L52）承诺"cache-only rerender 不触发 forward"，但 B4 跟踪若以相同 audio+character_range 走该 serial cache，跨迭代/recrop 会错误命中旧 forward。
**证据**：`align_qwen_fa_serial_demo.py` infer_slice cache_identity（L250-285，无 parent/iteration 键）；C_note §3.2 另列举 `research_transition_recovery_detector/identity.py` L12 `forward_cache_key`（独立实现）与 `realign_recovery/candidate_bank.py`（request-content hash ≠ forward_digest）两套独立 cache，07 均未涉及。unit_realign 自身不用 forward_cache（C_note §3.2 L83），依赖 build_request_identity + RUN_STATE——此路无问题。
**建议**：a) 把新 parent/iteration/recrop/split 键也并入 serial demo 的 research_infer cache identity（或冻结 B4 仅单程基线、明确 rerender 时 B4 不承诺 cache-only）；b) 在 §4.2 明确 candidate_bank / research_transition 缓存不进本轮范围或一并冻结，避免 smoke"不触发 forward"断言失真。

## C. R-B / GT 防火墙（清单 3）：通过

- 07 L48（原则4）"不把旧 R-B/E5/compat adapter 当 genuine bilateral-anchor（C_note §5）"；L267（anti-scope）同样表述。未把 R-B 列入四路可视化。
- no-GT 路径不读 GT：07 L46/L193 + WP7（L236-238）只接实际可得 no-GT 信号，heldout 一次评价、分 operating point；L175 `assert_no_label_leak` 覆盖新 family。与 E_note §4.3 / 04 §5 一致。

## D. 信号口径（清单 4）：通过

- 07 L31（fact 8）明确 raw=argmax / official=decode / per-step softmax/topk/entropy/margin，且"hidden 仅 collect_evidence_v3，当前 unit_realign 生产路径未接线"。未把 raw/official 当两个独立 decoder head（E_note §2.2 强调二者是同一 logits 两视图，L32）。
- 07 L237（WP7）只列 raw/official posterior/entropy/margin/p_bad/disagreement/stability，**不含 hidden**，未错误宣称 hidden 默认导出。
- 07 L24 Current baseline `decoder_view=raw`、L79 B4 `--decoder official`：与 B_note、03 V1 公平性一致（B4 冻结 official，Current 冻结 raw，如实反映 config 差异）。

## E. 可视化 adapter 可行性（清单 5）

### P1-3 R-U/R-S forward evidence 缺 global_character_index / text，adapter 需显式反向映射（缺必需转换）
**问题**：07 L68 TrackView.rows = `canonical_visual_row(global_character_index, start_sec, end_sec, text)`；但 R-U/R-S 的实际 forward evidence（`scripts/unit_realign/run_forward_real.py` 产出的 .baseline/.candidate JSONL）只有 `{"canonical_unit_id", "start_sec", "end_sec"}`（C_note §2.2、L157-158/L178-179 实测），**无 global_character_index、无 text**。且 `canonical_unit_id ≠ global_character_index`（candidate 由 `local_to_canonical[gci]` 映射而来，需反向 `canonical_to_local` 才能还原 gci；基准行由 `canonical_ids` 给出需经 `canonical_to_local` 解析）。
**证据**：`visual_diagnostics.canonical_visual_row`（L33-57）缺 `start/end_sec` 完整对即抛 KeyError；`row_index`（L18）取 `global_character_index`、`row_text`（L21）取 `display_text/alignment_unit/character`，均为 None 会错序/空字。`_unpack_track`（L222-229）只解 (label, rows[, windows])，detector/target/fixed/proposal overlay 经 `render_timeline_page` span 机制（D_note A.3，需新增 kind，07 L102/L108 已覆盖）。`timeline_video` 吃 pages（C_note §2.4，07 复用现成 renderer）。
**建议**：在 07 §3.1 adapter 一条显式写死：R-U/R-S 投影时用 v2 request 的 `canonical_to_local`/`text_units` 把 `canonical_unit_id → global_character_index` 并注入 display text（含零时长/负时长语义，供 `_group_collapsed_rows`/`_adaptive_row_label` 消费）。G1（PV smoke）前补 `test_track_view` 断言每行均含完整 pair + global_character_index + text。

## F. 可执行性（清单 6）：MINOR（backlog）

- run root P8（"adaptive_expansion 扩 top1/2"，见 06 E_note §5.1 顺序）在 07 §5 run roots 列表缺失（P0..P9 跳到 P9），expansion 只在 §8 预算里提到（"1–2 机制 × ≥200 regions"），未绑定 run root/gate（04 §4.3 扩量是正式实验）。
- 07 L110 "调整阶段顺序…；**或者**在 unit_realign 侧更建独立 visualization runner，不篡改旧 pipeline" 二选一未定死，WP2 L211 写"调整/新建"——实现前需敲定一个，避免双实现冲突。
- adapter 对 `canonical_visual_row` 的可选键（`display_text/alignment_unit/character/visual_timing_source`）来源未在计划说明，影响零时长聚合与文字降级输入。
- B4 "exact serial cursor/commit 版本" 对账属 U1 既有 unknown，计划已列，不新增。

## G. 总体判定
- 核心契约（collection-first、rerender cache-only、writeback=0、GT firewall、scientific hash 稳定、不做笛卡尔积、第四路不冒名、信号口径）**全部正确冻结**，无 P0。
- P1 集中在**"冻结原则落不到 code/数据流"**三类：split_slot_id 显式键落空、两个独立 cache 与 rerender cache-only 断言冲突、R-U/R-S adapter 缺 global_character_index/text 反向映射。
- 均不污染已冻结结论，属实现前必须补明的契约缝隙；修复集中在 §4.1/§4.2/§4.3/§3.1 与 WP1/WP2，G0/G1 前处理即可。

*最终以本 session 00–06 冻结合同为准。*
