# Long-Slot / Region Assessor 实现复审（2026-08-05）

状态：**不批准 real smoke、pilot 或 formal**。本文件是对当前实现的只读代码审查，供下一位实现 agent 按优先级整改；不是科研结论，也不替代 `13` 的冻结实验设计与 `14` 的执行合同。

## 复审更新：提交 `cdd387f` 至 `5dc5350`

复审时间：2026-08-05。`tests/research_v7` 已由 56 项增至 **63 项通过**。本轮确实改善了 P0-2--P0-5 和 C3：mapping 改为显式 canonical id、slot 支持 canonical-to-local、seam 会平移后续 unit 时间、C3 加入 silence frame audit，report 至少校验 manifest SHA。

但这些修复尚不足以关闭相应 gate；没有真实运行产物，P0-1 也完全未改变。因此结论仍为：**仅允许 draft 校准/CPU smoke，不批准 real smoke、pilot 或 formal。**

### 本轮必须优先处理的残余缺陷

1. **P0-4 seam 总时长仍被双计。** `timeline.build_timeline()` 已在每个后续 segment 前把 `artificial_silence_sec` 加到 cursor，原有 duration 计算又再加一次每 seam silence。后续 unit 起止虽然正确，`duration_sec` 却会多出一份 seam silence；修复为只使用已累计的 cursor，并在 test 中断言总时长与最后一个 canonical end/音频拼接长度一致。
2. **P0-4 replace 两方向指标仍不正确。** `wrong_output_metrics()` 用同一个 `pred_wrong_output` 同时计算 wrong-output recall 与 replaced-GT omission recall；后者必须输入、使用和评价 predicted gap/omission candidates，不能复用错误输出命中数。`gap_metrics()` 的 `pred_gap_omitted` 与 `weighted_deleted_gt` 参数目前也未使用，应删除或实现并加 partial-coverage tests。
3. **P0-5 仍可把 smoke 伪标为 formal。** report 只要给出存在且 SHA 相符的任意 manifest，就将从同一个 `smoke/LONG_SLOT_SMOKE.json` 读取的结果设为 `formal_approved=true`、`status=formal`；它没有验证 formal evidence/run manifest、all gates、预算、真实模型执行或 12h hard stop。应把 `formal_approved` 与“formal run completed and validated”分开；没有真实 formal evidence 时无条件 draft。
4. **P0-2 mapping 的输入/输出约束不完整。** 没验证 `role` 的长度/枚举、canonical id 的范围/唯一性、inserted 必为 null、retained/replacement 不可为 null。`output_row_canonical_ids` 被强制和 input 等长，不能表达真实 decoder 的缺行/多行。100% replace 仍不产生可评价 omission gap，违反 replace 同时评价 wrong-output 与 omitted-original 的合同；须建立显式 whole-region omission candidate 或等价结构。
5. **P0-3 phase/common-anchor 仍未可执行地保证公平。** common anchor 是每个 stride 的所有 phase 的并集交集；单一 phase 可不含某个 common unit，而计划仅记录 note，并未在汇总器强制按实际共同 queried units 成对评分。还需校验 canonical ids 本身严格递增、所有 id 都在 `canonical_to_local` 中，且 local index 在 request text 长度内；当前缺失键会抛裸 `KeyError`，而 local 上界只误用 canonical unit count。
6. **C3 选择阶段仍用“最低 20% 分位”寻找窗口。** 这使任何窗口天然约有 20% 被视为 candidate，未使用新加的绝对/相对/连续 silence 条件；随后即便 `build_window()` 得到 `n_sil=0` 仍可导出 control 与完全相同的 weak 文件。窗口选择必须复用 `detect_silence_frames()`，要求 `n_sil>0`、污染比例/连续段合格，否则记录 skip。source SHA 目前只是从 input item 读取可选字段，未实际计算；sample-rate mismatch 测试也没有调用 exporter `main()`，仅比较两个读出的 rate，不能证明 skip 行为。

### 已完成但仍需保持的改进

- C3 docstring、sample-rate 拒绝、最短连续 silence 和临时 WAV fixture 已较上一版明显改进；保留此方向；
- mapping 不再按 input index 推断 canonical id，head/tail sentinel 与 replacement row mapping 是正确方向；
- density plan 不再用 full base 与 stride 并集，修复了最初的“伪稀疏”问题；
- report 的 SHA 校验降低了误传参数即降级为 formal 的风险，但不能替代真实 formal gate。

下一位 agent 应先关闭上述 1--5 并添加失败回归测试，再将 C3 artifact 接进真实 request/evidence manifest。P0-1（真实 executor、identity-enforced cache、hidden audit、serial lineage、preflight/pilot artifacts）仍是最大未实现项。

## 已确认的进展

- `tests/research_v7` 当前共 56 项通过；
- 已有纯 CPU 的 timeline、canonical mapping、slot planning、R/O/H feature 骨架、metrics、numpy logistic assessor、preflight-lite 和 smoke/report 脚本；
- 新增 C3 `export_silence_polluted_weak.py`：可在同一 20 秒窗口保留原 vocals，并仅向低能帧叠加按正常人声 RMS 的 2% 标定的 accompaniment residual，导出 `control.wav`/`weak_2.wav`，这是比此前只写 manifest 更实质的校准样本；
- 当前工作树还存在未提交的 `scripts/research_v7/export_weak_vocal_samples.py`；它不属于已验证实现，不能作为运行依赖。

当前仓库未发现 `PRECHECK.json`、`LONG_SLOT_SMOKE.json`、`AUTO_SUMMARY.json`、`RUNTIME_BUDGET.json`、`HIDDEN_EXTRACTION_AUDIT.json` 或 `RUN_MANIFEST.json` 等本轮实际运行产物。因此任何结果都不能被称为 real smoke/pilot/formal evidence。

## 阻塞 formal 的 P0 问题

### P0-1：真实 long-slot 流程没有接通

`AlignmentRequest.request_identity()` 是可用的散列工具，但没有被 runner、cache 或 evidence 写入逻辑调用。当前缺少 real long-timeline manifest builder、long-slot request builder、实际 feature extraction、assessor train/evaluate CLI、内容寻址 cache、hidden extraction audit 和真实 serial lineage/commit 状态。现有 `run_long_slot_smoke.py` 只跑合成数组，不能替代真实 Qwen 请求。

整改：先实现一个可验证的 request/evidence schema；由 runner 强制写入 `request_identity`、完整 hash context、parent identity、cursor/commit 状态和 failure。cache/resume 只能按该 identity 命中。随后接入 fixed-60s executor，最后才生成真实 smoke artifacts。

### P0-2：canonical mapping 不可用于 head/middle mutation

`build_mapping()` 把 retained input 的 canonical id 固定为 input index；head/middle extra 或 missing 后该假设即错误。replacement 在 `InputUnit` 中虽保留被替代 id，但 `output_row_map` 又丢为 `None`，破坏可逆追踪。head/tail omission 也不能建立边界 gap candidate。

整改：manifest 必须显式传入每一 input unit 的 canonical id（可为 null），不允许函数根据 index 猜测。增加 `<START>`/`<END>` sentinel gap，覆盖 head、tail、全删和 100% replace；对所有 mutation position 与跨视图 row mapping 添加单测。

### P0-3：density 设计未实际稀疏化，local index 也不正确

`build_density_plans()` 将完整 `base_ids` 与 stride 集取并集，所以每个“稀疏” plan 仍包含 full slots。`plan_slots()` 又直接把 canonical ids 写为 local indices，不能处理请求中的历史/未来文本上下文。

整改：输入必须同时给 `canonical_to_local` 映射和 `candidate canonical ids`。每个 stride/phase 只选择该 phase 的 subsample；从 full、stride 2/4/8 的真实 selected sets 求 common anchors，并在 summary 中强制只评这些共同单位。

### P0-4：timeline seam 与 R/O/G 指标不能保证正确

插入 0.5s seam silence 时，timeline 总时长增加但后续 canonical timestamps 未平移。feature extractor 不读取当前 real executor 的 `fixed_global_start_sec`/`fixed_global_end_sec` official rows；gap weighted recall 用 gap-id set 而不是被检出的 omitted canonical units 加权；split 汇总还读取 `fpr`，而 unit evaluator 输出为 `correct_unit_fpr`。

整改：先统一 raw/official row schema，并用真实 executor evidence fixture 回归测试。seam control 必须逐后续 unit 平移。gap metric 应根据每个 detected gap 的 `omitted_canonical_unit_ids` 计算 weighted recall；FPR 分母只能是 retained-and-correct units。实现并报告 replace wrong-output recall、replaced-GT omission recall、interval recall@75/@100、>=3-unit complete-miss 与 unsafe expansion。

### P0-5：当前 smoke/report 可造成错误 gate 表述

smoke 实际只构造一条合成 timeline、一个 slot plan 和一个 tail-missing mapping，未执行注释所称三个 60s window 或 replace。report 接受任意非空 `--formal-approved-manifest` 即将 `draft=false`，不检查文件、hash、manifest gate 或真实 formal evidence。

整改：在 report 中删除该降级路径。只有验证过签名/sha256 的 frozen manifest、已完成的真实 formal run manifest、预算记录和 all-gates-pass 才允许 `formal_approved=true`；否则无条件 `draft=true`。smoke 要断言三次 60s request、non-contiguous slot、missing 和 replace 双向 mapping、lineage、cache resume 和 English/Japanese 边界 fixture。

## C3 弱人声更新：可保留的部分与待修正项

`export_silence_polluted_weak.py` 的方向与 13 §C3 一致：相同窗口、正常 vocal 不缩放、只在被判定为低 vocal 的帧引入 residual。可用于用户试听/校准；生成文件不能在审计前混入 formal。

仍需先修正：

1. 脚本 docstring 仍写 1%/2%/5% 与 `weak_1/weak_2/weak_5`，但代码实际只导出 control/2%，必须一致；
2. `window_pick()` 是未使用且对一维数组会因 `mean(1)` 出错的死代码，应删除或完成并测试；
3. 当前 silence 判断是每窗最低 20% 分位，因此任何持续人声窗口也会机械产生约 20% “silence”。必须加入绝对 RMS 上限、相对 sung-RMS 比例、最短连续静音长度和 frame-level audit；若不满足则拒绝该窗口，而不是污染真实人声帧；
4. 需要验证 vocal/accompaniment sample-rate 相同，否则重采样 accompaniment；还应记录 source hash、实际 gain、每个被污染 frame 的 residual RMS、污染时长比例、clipping count；
5. 将 exported WAV 写入明确的 calibration manifest（audio path、window、同一歌词 unit 范围、condition、control pairing id），再由真实 runner 消费。当前 exporter 仅供试听，未与 request/evidence pipeline 集成；
6. 为 exporter 增加临时 WAV fixture 单测：只修改获准 silence frames、normal 帧逐采样不变、输出 sample rate/长度正确、无 eligible silence 时跳过、不同 sample rate 被拒绝或正确重采样。

## 建议实施顺序和验收

1. 修 P0-2/P0-3/P0-4 并新增覆盖其失败模式的单测；
2. 建立长 timeline/request manifest、identity-enforced evidence/cache、真实 fixed-60s runner 与 serial lineage；
3. 完成 C3 frame audit、试听 packet 和 manifest 接线；用户冻结档位后才将 C3 加入 smoke；
4. 生成 preflight 全部交付物与真实 smoke，验证 hidden audit、multilingual boundary、matched baseline、resume；
5. pilot 测得 actual runtime/forward/cache/分母后，先满足 <=10h 预测及所有 gate，再请求 formal 授权。

在上述 P0 全部关闭前，唯一允许的输出是标有 `draft=true` 的校准与 smoke artifact。

## 复审更新 2：提交 `69777b9` 至 `64b835d`，含当前未提交 P0-4 修改

复审时间：2026-08-05。当前 `tests/research_v7` 为 **77 项通过**。本轮对上一轮问题有明显跟进：mapping 增加角色/id 校验和 whole-region omission candidate；slot 增加 canonical/local 上界校验；C3 选窗改为复用 silence detector；工作树中的 P0-4 修改修复了 seam duration 双计，并将 replace 的两个 recall 分开计数。

这些均是有效的单元级改进；但当前存在未提交修改，且没有任何真实 run artifact，故仍不批准 real smoke、pilot 或 formal。

### 本轮新增或仍未关闭的 P0/P1 问题

1. **P0-5 formal report 仍读取 smoke 作为“formal”结果。** 即使 SHA、`formal/FORMAL_MARKER.json`、`all_gates_passed` 与 `runtime_budget_ok` 都通过，`report_long_slot_region.py` 仍只读取 `smoke/LONG_SLOT_SMOKE.json`，随后把 status 写为 `formal`。marker 也没有绑定 frozen manifest hash、run identity、evidence inventory 或实际 elapsed/forward/cache 数。必须改为读取并校验真实 formal result/run manifest；marker 只能是该验证的输入之一，不可单独授权 formal。还缺少该 gate 的正反向 CLI 测试。
2. **P0-1 仍完全未接通。** 没有实际 fixed-60s long-timeline runner、identity-enforced evidence/cache、hidden extraction audit、serial lineage、feature/train/evaluate CLI 或 preflight/pilot artifact；当前无 `PRECHECK`、`RUN_MANIFEST`、`HIDDEN_EXTRACTION_AUDIT`、`RUNTIME_BUDGET` 等产物。
3. **canonical row-map 对真实 decoder 仍不够表达。** 虽然 `output_row_canonical_ids` 可有不同长度，map 仍把 `input_index` 强设为 `row_i`；少行、重行或插入行时并非可逆。应增加显式 `output_row_input_indices`（可为 null），验证 output canonical id 范围/一致性，并要求 retained/replacement canonical 轴严格递增；当前只检查唯一性，不检查顺序。
4. **slot 的公平 helper 尚未接入 evaluator。** `common_only_pairs()` 只是返回交集，未被任何 runner/evaluator 调用；`build_density_plans()` 也未传 `request_local_count`，所以 builder 路径仍不校验真实 request 的 local 上界。把 helper 写出来不等于主统计已只评分共同 queried units。
5. **P0-4 的工作树修复未覆盖 R/O schema 接线。** seam duration 与两个 replace recall 的方向已修正，但 `features.py` 仍不能直接读取 current real executor 的 `fixed_global_start_sec`/`fixed_global_end_sec` official rows，真实 evidence 进 feature 后仍可能退回默认 geometry。必须用 real-executor-shaped fixture 测试 raw/official/repair/posterior 特征抽取；随后再提交当前 metrics/timeline 修改。
6. **C3 exporter 有阻塞性运行时错误。** 在写 manifest 的成功分支引用未定义变量 `vpath`（应为 `vp`），因此任何真正合格的 export 会在 WAV 已写后抛 `NameError`，manifest 不完整。现有“main via subprocess”测试没有覆盖成功导出分支，故 77 项通过未能发现它。修复后测试必须断言成功返回、`done=true`、两个文件存在、sha 字段存在；同时记录实际 gain、污染帧 residual RMS 与 clipping，而不仅是 source hash。
7. **report/C3 均未形成可消费 request manifest。** C3 的 WAV 仍未和歌词 unit 范围、pair id、condition、audio hash、request identity 写入固定 schema，也没有被真实 runner 消费；它只能继续作为校准工具。

### 状态判定

| 项目 | 状态 |
|---|---|
| P0-2 mapping 基础契约 | 部分关闭；真实 decoder row map 与运行接线未完成 |
| P0-3 slot 基础校验 | 部分关闭；公平评分强制执行未完成 |
| P0-4 seam/replace metric | 工作树中部分修复；R/O feature schema 与真实 evidence 未完成 |
| P0-5 report gate | 部分修复；不得把 smoke 读成 formal |
| C3 音频校准 | 方向正确，但成功 export 分支当前不可用 |
| P0-1 实际实验管线 | 未开始 |

下一个实现步骤应先修复 C3 `vpath`、report 的 formal-result source 与 formal gate tests；然后完成真实 evidence schema/runner，才有条件将前述模块级改动接入 smoke。

## 复审更新 3：提交 `8474880` 至 `d727827`

复审时间：2026-08-05。`tests/research_v7` 已增至 **87 项通过**。上次发现的 C3 `vpath` 运行时错误已修复；seam/replace metric 修改已提交；formal report 改为读取 `formal/RUN_MANIFEST.json`；mapping row-to-input、density local bound/common score、real-executor-shaped official geometry 都新增了针对性测试。这些改动可保留。

结论仍为：**不批准 real smoke、pilot 或 formal。** 当前没有任何本轮运行 artifact，且真实 runner/evidence/cache/hidden/serial 管线依然不存在。

### 仍需整改的具体问题

1. **C3 `REQUESTS.jsonl` 不是可直接执行的 request contract。** 每条记录缺 `AlignmentRequest` 所需的 `audio_source`（生成的 control/weak WAV）、text units/range、slot、window/workflow/model 和 canonical mapping 信息；现有 `run_behavior_suite.py` 不消费 `files` 或 `audio_path_vocals`。control 和 weak request 都把 `target_ratio` 写为 2%，且 control 也标为 `mutation=silence_residual`。应先定义/实现 adapter 或统一的 long-slot request schema，并让 runner 真实消费 generated WAV。
2. **C3 identity 与写入不可复现。** `_reqid()` 未包含 accompaniment SHA、导出 WAV content hash、alpha、silence mask/selection 或代码/transform version；伴奏或构造规则变化可能复用同一 identity。`REQUESTS.jsonl` 使用 append，重跑同一 out-root 会追加重复请求，而 `AUDIO_EXPORT_MANIFEST.json` 会覆盖，二者不一致。应先写临时文件后原子替换、按 identity 去重，并对每个输出 WAV 算 content SHA。
3. **formal report 的信任边界（用户接受）。** marker/run manifest 可由具备工作目录写权限的操作者手写；用户明确接受这一点，因此不作为整改阻塞项。仍应修正一个数据一致性问题：即使 formal approved，report 仍写出 `draft=true` 的 `RUNTIME_BUDGET.json`，应改为保留/引用实际 formal budget，避免同一 run 内自相矛盾。
4. **feature 接线仍停在单行 fixture。** `row_official_features()` 现在能读 `fixed_global_*`，但真实 evidence 的 raw/official rows 是不同 decoder-output collections，尚无按 output-row/canonical map join 成输入 row 的 extractor。hidden 也仍是全零占位、没有 extraction audit。不能将当前单元特征用于真实 assessor。
5. **density common scoring尚未成为管线门槛。** `evaluate_on_common()` 是独立 helper，只对单个 score mapping 求均值；未按 condition/phase/source-song 建立成对分母，也不会在 common unit 缺失时失败。必须在实际 evaluator 中按 `comparison_group_id` 加载 paired evidence，拒绝不完整 pair，并输出共同 unit 的实际分母。
6. **mapping 输出仍缺 output row field validation。** `output_row_input_indices` 已是正确接口，但未验证 input index 范围、输出 canonical id 范围、以及 input/canonical 的对应一致性。真实 decoder 的 duplicate/missing rows 进入前应在此处被显式标识与审计。

### 推荐下一步

停止继续增加仅 standalone helper 的 formal 外观代码，优先实现一个 real fixed-60s request/evidence runner：它读取冻结 manifest、生成 identity、运行 executor、持久化 raw/official/posterior/lineage/cache、并生成可验证 `RUN_MANIFEST`。随后把 C3 generated WAV 通过该 schema 接入一条真实 smoke request，再完成 hidden audit、feature join、assessor train/evaluate 与 pilot budget。

## 复审更新 4：提交 `85f2511` 至 `f4c5fb3`

复审时间：2026-08-05。`tests/research_v7` 为 **89 项通过**。本轮已正确修复：formal approved 时预算报告不再自称 draft、C3 请求文件采用原子替换并含导出 WAV hash、canonical output row 的 index/range 校验、以及 mapping/slot 的若干契约。可保留。

不过 `1d924d2` 所称“real-runner scaffold”当前不能消费它自己导出的 C3 请求，因此 P0-1 **仍未关闭**，且不批准 real smoke。

### Runner/C3 接线的阻塞性问题

1. **C3 request 会在 `AlignmentRequest.validate()` 失败。** exporter 生成的 `REQUESTS.jsonl` 没有 `text_units`、`text_start_index` 或 `text_end_index`；runner 因而构造空 units 和 end=0，违反 `text_end_index > text_start_index`。C3 calibration 必须显式提供同窗口的歌词 units/range；若本意是无歌词声学 probe，则需要单独的、明确不进入 aligner 的 request type，不能伪装成 alignment request。
2. **生成 WAV 的时长与 runner 请求范围不一致。** C3 导出文件长度由 `--window-sec` 决定（默认 20 秒），但 C3 row 只有 `window_sec`，没有 runner 所读取的 `duration_sec`/`audio_start_sec`/`audio_end_sec`。runner 走 `files` 分支后默认 end=60 秒；real executor 会因 audio range 超出 20 秒文件而失败。C3 row 必须携带 `audio_path=<generated wav>`、`audio_start_sec=0`、`audio_end_sec=<generated length>` 和可验证 duration；long-timeline 60s contract 不应由这个短 calibration asset 旁路或误称满足。
3. **runner 没有真正使用 C3 的内容 identity。** 它把输入的 `request_identity` 仅放进 metadata，而 `AlignmentRequest.request_identity()` 会排除 metadata，且调用时未提供包含 audio content hash、code/env、mapping schema 的 context。resume 仍以输出路径与 request dict 比较，若同一路径 WAV 内容替换则可能错误 cache hit。应由 runner 验证 manifest identity，或以统一 canonical payload 重新计算；evidence/run manifest 必须持久化该同一 identity。
4. **RUN_MANIFEST 仍只是 behavior-suite 的摘要。** 它写在 out root 而 formal report 要求 `formal/RUN_MANIFEST.json`，没有 experiment manifest SHA、environment/model/audio hashes、attempt evidence inventory、failure records、actual cache keys 或 stage-level resume。`dirty_tree_hash` 只写 `clean/dirty`，不是 hash。当前没有对应 runner integration test，89 个单测也未覆盖 C3 request 进 runner 成功、真实/假 executor resume、或 manifest identity drift。
5. **C3 identity 声明略高于实际。** output WAV SHA 已间接涵盖 silence mask/alpha，但 `sil_desc` 本身只是 audit 汇总，不是 mask；若要把它作为独立构造证明，应保存 frame mask hash、actual gain、residual RMS 和 transform spec。control request 仍带 `mutation=silence_residual` 与 `target_ratio=0.02`，应明确 control 为 ratio 0/baseline condition，避免后续 evaluator 把它算成污染样本。

### 本轮状态

| 项目 | 状态 |
|---|---|
| C3 导出与可重复写入 | 模块级基本可用；尚未成为可运行的对齐请求 |
| behavior-suite RUN_MANIFEST | 初始 scaffold；不满足 long-slot formal evidence contract |
| C3 → runner → evidence | 未通过，需先修复 text/duration/identity |
| formal report 预算一致性 | 已关闭（沿用用户接受的 marker 信任边界） |
| P0-1 实验管线 | 未关闭 |

下一步应先为 C3 增加一个成功的 runner smoke integration test（生成 WAV → materialized alignment request → fake executor evidence → identity-safe resume）。通过后再考虑真实 executor；不要先启动真实模型来发现上述确定性的 schema/range 错误。

## 复审更新 5：提交 `3f95b7b` 与 `2d8fad7`

复审时间：2026-08-05。`tests/research_v7` 已达 **90 项通过**。C3 在明确传入 `--text-units` 时，已经能导出生成 WAV、通过 fake executor、写入 cache/RUN_MANIFEST 并在第二次运行命中 cache。这是 P0-1 的有效 smoke-scaffold 进展。

仍不批准 real smoke、pilot 或 formal：无真实运行产物，且以下问题会使真实实验的 identity、标签和失败审计**不可追溯**。

### 新 runner 的未关闭问题

1. **manifest identity 与实际运行输入未闭环。** 对含 `request_identity` 的 C3 row，runner 直接将该值作为 cache key，不比较 `files_sha256` 与实际读取到的 audio SHA，也不将 model/checkpoint/processor/decoder/runner code 合入 key。因此无法从 cache entry 追溯它究竟对应哪一版音频和模型，且同一路径音频变化或更换 checkpoint 后可能复用旧 evidence。应验证 manifest audio hash 后，构造 `attempt_identity = hash(source_request_identity + canonical AlignmentRequest + model/checkpoint/processor/decoder/code/env/mapping schema)`，并将它与输入/输出 evidence 一并记录。
2. **C3 文本来源不能用于真实多项目实验。** exporter 的 `--text-units` 是进程全局的一组 units，会原样赋给所有 item；它没有根据 source song、选择 window、歌词时间线确定正确同窗单位，也没有保存 canonical mapping。默认空 units 仍不能送入 alignment runner。应从每个 input item 的已审计歌词/GT manifest materialize units 和 canonical range；无 GT 的 demo 必须显式标为 demo challenge，而非充当训练/正式评价样本。
3. **C3 condition 没有进入 runner 的语义字段。** exporter 写 `mutation`，runner 读取 `mutation_type`，所以 control 与 weak 均变成 `baseline`；`condition` 也未放进 request metadata/mutation parameters。虽然音频 path/外部 id 不同，后续收集器和 evaluator 无法按 control/weak pairing 正确分层。应显式保存 `condition`、`pair_id`、`target_ratio`、source/derived audio hashes，并使用定义清楚的 condition taxonomy。
4. **RUN_MANIFEST 的 failure/provenance 仍不完整。** `failures` 恒为空，即使 executor 返回 `status=error`；evidence inventory 只报 cache 文件数，没有每个 evidence path/hash/status。`dirty_tree_hash` 使用 `git write-tree`，它表示 index tree，不能覆盖未暂存工作树改动。应从实际 evidence 汇总 failures/inventory，并以 HEAD、staged diff、unstaged diff 的内容 hash 记录 source-tree identity。
5. **integration 仍只验证 fake executor。** 当前测试没有真实 executor 的短 WAV range、生成 WAV sample rate、raw/official evidence schema、C3 pairing summary 或 cache drift rejection。可先加一个不加载模型的 executor adapter fixture，覆盖 actual `fixed_global_*` rows 和强制 audio-hash mismatch failure；之后才安排单个真实模型 smoke。

### 当前 gate 结论

| 项目 | 状态 |
|---|---|
| C3 → fake runner → cache/resume | 已通过（仅在显式人工 text units） |
| C3 → real executor | 未验证 |
| 内容寻址 cache（跨模型/音频输入可追溯） | 未通过 |
| long-slot real runner、serial lineage、hidden audit | 未实现 |
| actual preflight/pilot/formal artifacts | 无 |

下一步应先关闭上述 identity、per-item text mapping、condition taxonomy 与 failure inventory；这比立即运行模型更重要。

## 复审更新 6：提交 `906b3f1`

复审时间：2026-08-05。`tests/research_v7` 已达 **91 项通过**。本轮的 attempt identity 已把 source request、canonical request、实际 audio SHA、model/checkpoint/revision、decoder、code/source-tree 与 mapping schema 合并；runner 也能拒绝 manifest audio SHA 与实际生成 WAV 不一致的请求，并输出 evidence inventory/failures/source-tree 摘要。这些均改善了可追溯性。

仍不批准 real smoke、pilot 或 formal；没有实际产物，且下列问题仍会造成输入—evidence—结果链路断裂。

### 仍待修复的可追溯性/运行问题

1. **C3 per-item text 仍未与所选 audio window 对齐。** `--text-manifest` 实际只读取 `{item_id, text_units, has_gt, source}`，忽略 text/canonical start/end；请求始终写 `text_start_index=0`。而 exporter 在整首音频中自动选择任意 20 秒窗口，因此 text units 未必对应该 window。应要求文本 manifest 提供 canonical unit ids、对应 audio span/GT path，并仅选取有可证明 lyrics overlap 的窗口；无此映射的 item 只能为 `acoustic_probe`，不得进 alignment/evaluator。
2. **C3 demo/probe 角色没有由 runner 强制隔离。** exporter 对无 GT 设置 `evaluation_role=acoustic_probe|demo_challenge`，但 runner 仍照常生成 alignment evidence；后续 train/evaluate 尚无 filter。应在 manifest builder/feature/train/evaluate 的入口明确拒绝非 `lyrics_aligned` records 进入训练、阈值冻结和正式准确率分母，并在 RUN_MANIFEST 按 role 计数。
3. **不同 identity 会覆盖旧 evidence 文件。** cache filename 已按 attempt identity 区分，但人类可读 evidence 路径仍是 `items/<item>/behavior-...-<i>.json`。同一 out-root 用 `--resume` 且输入内容变化时，会产生新的 cache entry，却直接改写这份旧 evidence，破坏历史可追溯性。evidence 文件名/目录必须包含 attempt identity，或对已有路径拒绝覆盖并写入新 identity 目录。
4. **drift/validation 等失败会中止整个批次且不留下 run manifest。** audio drift 直接 `raise RuntimeError`，此时其他独立 item 不会继续，且末尾 `RUN_MANIFEST`/`FAILURES.jsonl` 不会写入。应以 per-item `try/except` 记录 structured failure（request identity、source path、expected/actual SHA、error），继续其它独立 item，最后原子写 run manifest；只有全局初始化失败才终止进程。
5. **failure 汇总漏掉 cache-hit error。** cached evidence 若其 attempt status 已为 error，resume 分支只计 cache hit、不加入 `failures`，导致本次 `item_count.failed` 与 evidence inventory status 不一致。应从每个 cache hit/miss 的 status 统一派生 failures 与实际分母。
6. **source-tree hash 未覆盖 untracked 输入。** 当前 hash 由 HEAD、staged diff、unstaged tracked diff 组成；真正由 runner/import path 使用的 untracked 文件与外部 text manifest/audio 已不在此 hash。外部输入已可分别 SHA，但 code identity 至少应在 RUN_MANIFEST 列出实际 import file SHA，或明确记录 untracked-file inventory，避免“source_tree”被误解为完整运行源码快照。

### 本轮状态

| 项目 | 状态 |
|---|---|
| attempt identity（含模型、音频、代码） | 模块级已实现，并有 drift test |
| C3 text → audio window canonical 对齐 | 未实现 |
| cache 与 evidence 历史共存 | 未实现（当前会覆盖可读 evidence） |
| item 失败隔离与最终失败清单 | 未实现 |
| non-GT role 在训练/评价的硬隔离 | 未实现 |
| real executor / hidden / long-slot serial / pilot artifacts | 未实现 |

下一步应先修复 evidence 不覆盖和 failure isolation，并为「同 item 内容漂移」「cache-hit error」「text span 不匹配」「non-GT 入 train」分别增加回归测试；再进行单个真实 executor smoke。

## 复审更新 7：提交 `11637f5` 至 `e9cd410`

复审时间：2026-08-05。`PYTHONPATH=src python -m pytest -q tests/research_v7` 为 **98 项通过**，`git diff --check` 无格式错误。本轮以下改进已可确认，应该保留：

- evidence 与人读副本均改用 `content_identity` 文件名，因此同一 item 的新输入不再覆盖旧 evidence；
- 已进入 `try` 块的 audio-drift、cache、executor 失败会写入 `failures`，批次继续并在末尾写 `RUN_MANIFEST.json` 与 `FAILURES.jsonl`；cache-hit 的非 `ok` attempt 也会进入 failures；
- C3 已保守地将自动选窗的请求标记为 `text_window_aligned=false`，避免把没有已证明歌词窗口对应关系的样本当作可评分歌词样本；
- `imports_sha256` 对 `src/lyricalign/research_v7/*.py` 与 runner 本身取内容摘要，较单纯 git 状态更利于重放未跟踪代码版本。

结论仍为：**不批准 real smoke、pilot 或 formal。** 这不是再次讨论 marker 的信任边界（该边界按用户决定接受）；以下均为当前代码本身的可追溯性、失败可观测性或运行正确性缺口。

### 本轮仍未关闭的问题

1. **“所有 item 失败隔离”的实现并不成立。** `run_behavior_suite.py` 的 strict-serial parent-cursor 检查（约 113--116 行）、`AlignmentRequest(...)` 构造及 `req.validate()`（约 126--158 行）都在 `try` 块之前。任何缺 parent cursor、非法 range/slot/text 的行都会直接结束进程，既不会继续后续独立 item，也不会产出 `RUN_MANIFEST`/`FAILURES.jsonl`。现有回归测试只覆盖 audio drift（它在 `try` 内）。应把每条 row 从 serial 前置校验、request 构造、validate 到执行的完整过程纳入同一 item-level `try`；对依赖失败的子请求记录明确的 `blocked_by_parent` failure。
2. **role 与 text-window 标记没有被写入 runner 的可消费清单，role 计数当前必然错误。** `identities.append(...)` 只保存 item/request/id/cache/status（约 193--194、216--217 行），却没有 `evaluation_role` 或 `text_window_aligned`；随后 role count 从这些 identities 读取该字段（约 237--239 行），因而实际全是 `unknown`。这也违背了 `evaluation_guard.py` 文件头所称的 “RUN_MANIFEST.requests_identity 每项带 evaluation_role”。应把 role、text-window 对齐证据及其来源/range 写进 request identity inventory 和 evidence request metadata，并测试 manifest 的准确 role count。
3. **guard 尚未接入任何实际 train/threshold/evaluate 入口。** 全仓搜索仅有其单元测试引用 `require_trainable()` / `partition_by_role()`；不存在 research_v7 的调用者。故它目前只是可用 helper，不能构成“硬隔离”。另外 `partition_by_role()` 对缺少 `text_window_aligned` 的记录默认视作对齐（`r.get(..., True)`）；与“没有对齐证明即拒绝”的规则相反。应默认拒绝缺失标记，并在实际 feature/train/threshold/formal evaluator 的载入边界调用它、持久化拒绝清单与分母。
4. **C3 仍没有歌词—音频窗口映射，而非仅少一个布尔字段。** `--text-manifest` 只读 `{item_id,text_units,has_gt,source}`，不读取 canonical ids、文字时间范围或所选 window 的 overlap；exporter 对每条请求固定写 `text_start_index=0` 与 `text_window_aligned=false`。这是保守且正确的暂时隔离，但表示所有 C3 请求都不能进入歌词对齐训练/正式评价。要关闭此项，text manifest 必须提供可审计的 canonical unit range/时间 span，并由 exporter 以选中的 `[window_s, window_e]` 计算、记录 overlap 和选择后的 units。
5. **代码快照摘要范围需如实限定。** `_imports_hash()` 只枚举 research_v7 顶层 `*.py` 与 runner；不会列出 executor 的外部依赖、子目录模块、模型 processor 配置，且 RUN_MANIFEST 只保存摘要、不保存文件清单。因此它是有益的运行代码指纹，但尚不能独立定位完整可执行源码集合。应在 manifest 中写出 `{path, sha256}` inventory，并将 real executor/processor 配置、实际 checkpoint 路径及其 hash 纳入同一重放记录。
6. **成功 evidence 的三份写入不是原子的。** `evidence/`、`items/`、`cached/` 依次直接 `write_text()`；中断可留下三者不一致，而 inventory 只扫 cached。建议先将 payload 写入临时文件并 fsync，再以同一 content identity 原子替换每个目标；至少在 run manifest 显式记录每个副本路径/hash/status。`_mkstemp()` 返回的 fd 也未关闭便再次 `open(tmp)`，应改用 `os.fdopen` 或先 `os.close(fd)`。

### 状态表

| 项目 | 状态 |
|---|---|
| content-identity evidence 不覆盖 | 已关闭（保留） |
| drift / cache / executor 失败的 batch continuation | 部分关闭；pre-validation 与 serial 失败仍会中止全批 |
| non-GT / 未对齐样本的隔离 helper | 模块级可用，尚未接入任何消费管线 |
| RUN_MANIFEST role / text-window 可追溯 | 未通过；当前 identity inventory 漏字段、role count 错误 |
| C3 同窗歌词对齐 | 未实现；当前保守隔离正确但不能用于 lyrics-aligned 统计 |
| 完整真实运行源码与环境快照 | 部分；有摘要、无逐文件 inventory，真实 executor 仍未验证 |
| real executor / hidden audit / long-slot serial / pilot artifacts | 未实现；仓库仍未发现实际运行产物 |

建议下一位 agent 先以失败回归测试关闭第 1--3 项（尤其是 malformed row 与 parent failure 后仍有最终 manifest），再实现 C3 的 canonical text-span adapter。完成后才值得启动一次单个真实 executor smoke；在此之前，98 项测试仅证明模块与 fake-executor scaffold，不是 real evidence。
