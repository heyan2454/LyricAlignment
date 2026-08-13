# C_note — schema / cache identity / R-B provenance 核实

> 会话：`20260814_realign_recovery_visualization_overnight`
> 文件角色：为 `07_CODEX_IMPLEMENTATION_PLAN.md` 做前置事实核实的 Codex 现状记录。
> 命令环境：`conda lyricalign-qwen`，`PYTHONPATH=src`。本 note 全部为**代码字面量级**证据，行号指当前工作树。

## 1. R-U builder 默认值（问题 1）

**结论：会话记录 00_..._RECORD.md L92-100 的默认值与代码一致，真实字面量位置如下。**

- `audio_margin_sec = 0.5`、`context_neighbors = 1`、`ra_context_units = 1`
  → `src/lyricalign/unit_realign/request_families.py` `build_family_request` 默认参数（L99-100）。
- CPI 侧 CLI 默认 `None`（不覆盖 builder 默认，交给 `Unit_REQUEST_SCHEMA` 的默认值）
  → `scripts/unit_realign/run_unit_realign.py` `--audio-margin-sec / --context-neighbors / --ra-context-units`（L313-319），
  execute 时仅当非 None 才作为 `request_config` 传入（L380-384）。
- **target span 连续 1–3 units**（不是"默认值"，而是 R-U 家族的硬约束字面量）
  → `request_families.py` L113：
  `if family in {"R-U","R-U1","R-U3"} and (len(targets) > 3 or targets != list(range(min(targets), max(targets)+1))):`
  → 返回 `_null(..., reason="invalid_unit_target_span")`。
- 1–3 unit 的**枚举**来自 region sampling：`region_sampling.py` `build_region_population` 对每个 unsafe 连续段枚举 `_all_spans(group, max_units)`，`max_units≤8`（L24-41）；实际 target span 由用户/下游按 ≤3 截取。

## 2. unit-realign artifact schema 与旧 visualizer 输入差异（问题 2）

### 2.1 request schema（v2）
`schema = "unit_realign_request_v2"`（`src/lyricalign/unit_realign/request_families.py` L15）。

`build_family_request`（L92-196）产出的关键字段：
- `request_id = f"{song_id}:{region_id}:{family}"`、`family`（∈ `{"R-U","R-U1","R-U3","R-A","R-B","R-S","R-O","R-NULL"}`）、`family_version="v1"`。
- 时间轴：`index_space="document_global"`、`canonical_ids`/`local_to_canonical`/`canonical_to_local`、`text_units`、`mapping_schema="unit_realign_local_v2"`。
- targets/context：`active_target_unit_ids`（含兼容别名 `target_unit_ids`）、`fixed_context_unit_ids`、`active_target_unit_ids`、`outside_unit_ids=[]`、`writeback_unit_ids=targets`。
- 音频：`audio_path`、`audio_start_sec/end_sec`、`baseline_audio_range_sec`/`candidate_audio_range_sec`（`[start,end]`）、`baseline_text_ids`/`candidate_text_ids`。
- R-S sparse：`timestamp_slot_indices`/`active_slot_indices`/`fixed_slot_rows`、`slot_constraint_schema="realign_sparse_fixed_v1"`、`sparse=family=="R-S"`。
- R-B anchors：`anchors = {left, right, left_candidates, right_candidates}`（family==R-B 时带 candidates；否则 `{left,right}`）。
- `evaluation_only`（oracle/R-O 时 True）。
- `result.update(dict(identity_context or {}))`（L190）；`request_identity = build_request_identity(result)`（L192-195，identity 不完整时为 None）。
- `intervention_identity = intervention_payload(result)`（L189，**诊断用，非 cache identity**）。

`intervention_payload`（L24-40）schema `unit_realign_intervention_payload_v1`，内容 = active/fixed ids、candidate_audio_range、candidate_text_ids+sha256、full_local_ids、slot indices、anchors、decoder_options。用于 **no-op 判定（`classify_intervention`）**，与 cache identity 分离，二者的分工在文件头注释（L1-7）明确说明。

### 2.2 forward evidence（baseline/candidate JSONL）
`scripts/unit_realign/run_forward_real.py`：
- 每请求产 `<request_id>.baseline.jsonl` / `<request_id>.candidate.jsonl`。
- **baseline row**（L157-158）：`{"canonical_unit_id": int, "start_sec": float, "end_sec": float}`（来自冻结 detector 的 BASELINE_UNITS）。
- **candidate row**（L178-179）：`{"canonical_unit_id": int, "start_sec": float, "end_sec": float}`（来自 real_executor 输出 `attempt.decoder_outputs["official"]["rows"]`，按 `global_character_index` 映射回 `canonical_unit_id`）。
- v2 request 经适配转成 research_v7 `attempt`（L132-138：`mutation_parameters.request_identity`、`model_id=model_identity`、`checkpoint_id=checkpoint_identity`、`slot_constraint_schema`）再走底层 executor。
- 输出登记 `schema="unit_realign_forward_execution_v1"`（L269）；其文件头注释明确：research_v7 behavior suite 的 evidence 布局不同，不被本 runner 直接消费（L7-9）。

### 2.3 评价产物
- `run_unit_realign.py evaluate` 产出：
  - `03_unit_outcomes/UNIT_OUTCOMES.jsonl`（schema `unit_realign_outcome_v2`，见 `unit_realign/unit_outcome.py` L12：`onset_error_ms/offset_error_ms/max_boundary_error_ms` 与 `*_le_100/200/500/1000ms` bucket 布尔，`BUCKETS_MS=(100,200,500,1000)`）。
  - `03_unit_outcomes/REGION_OUTCOMES.jsonl`、`CANDIDATE_OUTCOMES.jsonl`、`NOT_EVALUATED.jsonl`。
  - `05_analysis/CANDIDATE_OUTCOMES.json`（聚合）、`MISSING_EVIDENCE_REPORT.json`。
- `02_forwards/FORWARDS.jsonl` 是已派发集合（authoritative dispatch），evaluate 只评价派发请求（L447-459）。
- RUN_STATE `07_runtime/RUN_STATE.json`：`completed/queued/planned/failed/null/not_constructible_identities` + `completed_region_ids`，resume 依据（L91-103 `_record_identity`）。

### 2.4 旧 inline-realign visualizer 输入结构（差异对照）
- **repo 中不存在名为 `ComparisonTrack` 的类型，也没有 task 里假设的
  `canonical_units / detector_spans / target_spans / fixed_spans / proposal_spans / metadata` 命名字段组合。** 全 demo 目录 grep 无此集合（仅有 `window_trace`、`metadata` 两处零散命中）。
- 实际契约：
  - `src/lyricalign/demo/visual_diagnostics.py` `_unpack_track`（L222-229）：track 是 **2 元组 `(label, rows)` 或 3 元组 `(label, rows, windows)`**，rows 为含 `start_sec/end_sec/text` 的 unit dict，windows 为 window dict。可视化真正消费的是"已解包 rows + windows"，不是命名字段对象。
  - `src/lyricalign/demo/alignment_artifacts.py` L351 读 `payload.get("window_trace")`。
  - `src/lyricalign/demo/realign_diagnostics.py` L264-266 把 `window_trace` 作为后续分析输入。
  - `src/lyricalign/demo/timeline_video.py`：消费 **`pages`（dict 列表）+ `alignment` + `audio_track`**（L111-142），把已渲染页面转视频；PDF 页面由 visual_diagnostics 的 `draw_track*` 产出。
- **差异结论**：unit-realign 现产 evidence = `{canonical_unit_id,start_sec,end_sec}` 扁平行 + v2 request（含 `family/active_target_unit_ids/fixed_context_unit_ids/anchors/request_identity`），
  而旧 visualizer 吃 `(label, rows, windows)` 元组 / `window_trace` / `pages`。
  二者之间**没有直接兼容的 adapter**；`target/fixed/proposal/detector span` 的语义需从 v2 request 的 `active_target_unit_ids/fixed_context_unit_ids/anchors` 重新映射，不能按旧 `canonical_units/detector_spans/...` 字段名直读。
  → 新可视化脚本必须写 v2→`(label,rows,windows)` 转换层。

## 3. shared cache identity（问题 3）

### 3.1 realign_recovery forward cache（已实现）
文件 `src/lyricalign/realign_recovery/forward_cache.py`：
- `FORWARD_SCHEMA_VERSION = "realign_recovery_forward_v1"`（L20）。
- `REQUIRED_FORWARD_FIELDS`（L22-41，共 26 个）：`model_id, model_revision, checkpoint_id, checkpoint_path, processor_id, audio_source, audio_sha256, audio_start_sec, audio_end_sec, text_unit_ids, text_content_hash, request_mode, core_sec, left_context_sec, right_context_sec, silence_aware_window_plan, code_version, schema_version`（+ 其余 `silence_*`）。
- 含 **model/checkpoint/audio SHA/text hash/code/schema**；不含 GT/detector 阈值/ranking/writeback（头注释 L1-6 明确排除）。
- `build_forward_key` 从 request 抽 canonical key；`_FROZEN_DEFAULT_FIELDS`（L44-54）可由 Phase-0 冻结 baseline 补默认（model/checkpoint/processor/request_mode/core/context/silence plan）。
- `ContentAddressedCache.topublish/resolve`，`forward.json` 记录 `{digest,key,raw_output_path,raw_output_sha256,published_at,schema_version}`（L236-243）；flock 串行发布。

### 3.2 使用点
- `realign_recovery/runners.py`（L33-36 import cache；L179 `key=build_forward_key(resolved)`，L193 `forward_identity=forward_digest(key)`；L410-412 no-GT 路径直接实例化 cache）。
- `realign_recovery/candidate_bank.py`（L21 注释：其 content-hash 是 request-content hash，**≠** forward_cache.forward_digest；L340 也强调二者区别）。
- `research_transition_recovery_detector/identity.py` L12 有**另一套** `forward_cache_key`（独立实现），`runner.py` L198 用它做 resume——与本 forward_cache 模块不同，属历史/过渡 runner。
- **`unit_realign` 当前不用 forward_cache。** 其 resume 依赖 `build_request_identity`（见 §2.1/§5）＋ RUN_STATE 的 `completed_identities`。二者尚未连通。

### 3.3 缺 parent_candidate_iteration / recrop / split 的字段扩展点
- `unit_realign` 的 `build_request_identity`（request_families.py L50-62）把它想要"冻结"的键都显式列出：schema、family+family_version、`intervention_payload`、`canonical_ids/local_to_canonical`、`baseline_digest`、`audio_sha256`、model/checkpoint/decoder/mapping/code/text_adapter identity、`decoder_options`、`audio_preprocess_identity`、`determinism_identity`。
  - `recrop`：会改变 `candidate_audio_range_sec` / `canonical_ids` 或 `audio_preprocess_identity` → 已被 `intervention_payload`/`canonical_ids` 覆盖，**无需新增**（但若要"同一音频不同 crop 算同一 iter 内多 view"则需额外的 view/recrop 显式维度）。
  - `split`：改变 `canonical_ids`/`active_target_unit_ids`/`fixed_context_unit_ids` → 也已在 identity 与 payload 内隐式变化。
  - **`parent_candidate_iteration`：当前无显式维度**。若要支持"同一目标被多次迭代、且结果依赖上一轮候选"（真实 multi-realign dynamics），必须新增一个父迭代/父候选 identity 维度（例如 `parent_request_identity` 或 `iteration`），否则缓存会跨迭代复用旧 forward。这是规划 07 时应补的**显式扩展点**。
  - 扩展方式：可在 `build_request_identity` 的 `required` 键集合 + `_digest` 参与字段里追加一个新 key（如 `parent_request_identity` / `recrop_view_id` / `split_slot_id`），并通过 `identity_context` 传入（`build_family_request` L190 已透传 `identity_context`）。

## 4. k1/k3 manifests 与当前 schema 的兼容性（问题 4）

**结论：k1/k3 的 REQUESTS 是旧 `research_v7` request schema，与当前 `unit_realign_request_v2` builder 构造**不兼容**。对比脚本是按其旧结构适配读取的。**

证据：
- `runs/unit_realign_explore_context_k3_20260813/02_behavior/REQUESTS.jsonl` 首行顶层 key：
  `schema_version, input_variant, item_id, pairing_key, parent_request_id, mutation_type, mutation_parameters, provenance, source_song_id, ... workflow_mode, request_id, canonical_ids, text_units, timestamp_slot_indices, canonical_to_local, ...`
  - 含 `workflow_mode` / `parent_request_id` / `pairing_key` / `mutation_type` —— 这些字段定义在 `src/lyricalign/research_v7/requests.py`（L36 `workflow_mode`、L41 `input_variant`）与 `scripts/research_v7/build_behavior_workflow_manifest.py`（L28-85 构造）。
  - **没有** `family`、`active_target_unit_ids`、`fixed_context_unit_ids`、`request_identity`、`baseline_digest`、`audio_sha256`、`mapping_schema`、`index_space`；version 字段叫 `schema_version` 而非 `schema`。
  - 即它是 research_v7 behavior-suite 时代产物（`input_variant`，如 `"strict_serial_*"`/`"full"`），**不是** v2 builder 生成的。
- `runs/unit_realign_explore_context_k1_vs_k3_20260813/` 下只有 `CONTEXT_PADDING_COMPARISON.json`。
  - 其 `schema="unit_realign_context_padding_comparison_v1"`，引用 `short_run=<...k1_20260813_v2>`、`long_run=<...k3_20260813_v2>`。
  - 生成脚本 `scripts/unit_realign/compare_context_padding.py` `sparse_rows()` 读 `*.json` evidence 的 `attempt["request"]["input_variant"]=="R-S_sparse_fixed"`、`attempt.get("decoder_outputs",{}).get("_sparse_constraint",{})`、`request.get("canonical_ids")`/`active_slot_indices`/`fixed_slot_rows` —— 全部是 research_v7 attempt/request 结构，不是 v2 evidence。
- 三个 runs 目录（k1_vs_k3、k3、k3_v2）的 `02_behavior/` 是 run_behavior_suite 的输出根；`02_behavior/forward/evidence/*.json` 的 `attempt["request"]` 也是 research_v7 request。

**规划含义**：若 07 计划要"复用/重跑 k1/k3 对比"，不能把 `REQUESTS.jsonl` 直接当 v2 request 交给新可视化；`compare_context_padding.py` 也不读 v2 产出。要么保留旧适配（旧 run 只支撑 no-GT structural 结论，见 CONTEXT_PADDING_COMPARISON `scope="no_gt_structural_screen_only"`、`interpretation` 不声明 accuracy），要么对新 v2 run 重写对比脚本。

## 5. R-B / bilateral anchor provenance（问题 5）

**结论：在当前 unit_realign 中，R-B 是 genuine bilateral-anchor（锚点来自 detector ACCEPT provenance），不是旧 compat adapter。**
另存在旧机制，标注其不构成当前 genuine R-B。

genuine 路径（unit_realign）:
- `region_sampling.py build_region_population`（L24-69）：对每个 ROW 从 detector shadow 的 `units` 取 `state=="ACCEPT"` 集合 `accept_ids`，为每个（unsafe 或 ACCEPT 对照）region 填
  `left_anchor_candidates = [c in accept_ids if c < ids[0]]`、`right_anchor_candidates = [c in accept_ids if c > ids[-1]]`（L53-54, 67-68）。
- `request_families.build_family_request` R-B（L115-129）校验：
  - 必须 `left_anchor_id/right_anchor_id` 都存在（`missing_bilateral_anchor` → not_constructible）；
  - 锚必须在 local context（`anchor_not_in_local_context`）；
  - 必须 `left_anchor_id < targets < right_anchor_id`（`invalid_bilateral_anchor_order`）；
  - 必须有 `left_accept_anchor_candidates`/`right_accept_anchor_candidates`（`missing_anchor_candidate_provenance`）；
  - **锚必须是 eligible 中最近邻**：`left_anchor_id == max(eligible_left)` 且 `right_anchor_id == min(eligible_right)`（`non_nearest_bilateral_anchor`）。
  → 因此 R-B 有明确的 ACCEPT anchor provenance 且强制最近邻，是 genuine。
- `intervention_check.validate_request`（L55-58）对 R-B 强制 `anchors.left/right` 非空。
- 消费端：`scripts/unit_realign/analyze_multi_request_consensus.py`（L20 `FAMILIES=("R-U","R-S","R-A","R-B")`）把 R-B 当第 4 个 genuine evidence family；`build_fixedpoint_requests.py`（L135-138）从 region 的 `left/right_anchor_candidates` 造 fixedpoint R-B。

旧/过渡机制（不视为当前 genuine bilateral-anchor，需核实是否进入可视化输入）：
- `src/lyricalign/realign_recovery/e5_proposals.py`、`e5_eval.py`、`run_objects.py`、`runners.py`，以及 `research_v7/detector_v2_coverage.py`、`realign_gate/{gate_features,detector_audit,case_selection}.py` 中存在 `anchor/bilateral` 相关符号 —— 这些是 E5 提案 / detector_v2 coverage / realign_gate 等老模块，字段名与语义需单独核实，**与 unit_realign 的 R-B 是不同轨道**。

## 6. 待核实 / 未知
- `realign_recovery/e5_proposals.py / e5_eval.py / run_objects.py / runners.py` 中的 anchor/bilateral 是否属于"旧 adapter/compat"，目前只确认它们与 unit_realign R-B 不同轨，具体语义未知/需核实。
- k1/k3 runs 的 `audit`/`run_manifest` 完整清单（是否含 RUN_MANIFEST.json/环境记录）未逐条读取；已确认 request 结构为 research_v7 式。
- visual_diagnostics 的 `draw_track*` 具体 row dict 必需字段全清单（除 start/end/text 外的可选键）未穷举。
- 会话 05_CODEX_HANDOFF.md 对上述 schema/cache 的既定合同（应以此为准）未在此 note 复核。

---
*本 note 仅汇总代码字面量证据；正式实现合同以会话 00-06 文档为准。*
