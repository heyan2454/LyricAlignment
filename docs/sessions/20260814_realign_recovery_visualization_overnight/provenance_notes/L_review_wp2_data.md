# L-note — WP2 可视化 controller 数据一致性 / 跨模块接线 / 文档对照 review

> 审查对象：commit `714d514`，`scripts/realign_recovery/visualization/`（visualization_controller.py
> + render_comparison_batch.py / render_rerender_only.py 等 runner）。
> 审查方式：只读代码 + 实读 2 个 real evidence JSON（`.../04_test_demo/forward/evidence/sha256:009f...13cb.json`、
> `sha256:0a62...` 等）+ 单测 `tests/unit_realign/test_track_view.py`（**4 passed，0.04s**）。
> 依据：03 V7、07 计划 §9、J-note §B/§E、K-note。只报 P0/P1；MINOR 进 backlog。

---

## 结论：存在 **1 个 P0**（行投影全局序号彻底错乱，所有 track 折叠到 index 0-7，渲染输出无科学意义）；
另有 2 个 P1（rerender hash 覆盖范围不全、B4 stand-in 口径与 decoder 混叠）。单测全过但不覆盖真实 evidence 路径。

---

## [P0] `rows_from_decoder` 把**窗口局部** `global_character_index` 当作 document-global canonical id 反投，导致所有窗口折叠到全局 index 0-7 + 空文本

**问题 → 证据：**

1. `visualization_controller.rows_from_decoder`（L114-126）：`gci = row.get("global_character_index")
   or row.get("character_index")`，随后 `rows.append({"canonical_unit_id": int(gci), ...})`。
2. **真实 evidence 的 decoder 行不含 `canonical_unit_id`**（我实读
   `forward/evidence/sha256:009f...13cb.json`，request `test-demo-045-narrow`，官方行首行 key 集
   校验：含 `global_character_index/raw_global_*/official_fixed_global_*/fixed_global_*` 等，
   **无 `canonical_unit_id`**）。同时该请求行的 `global_character_index == [0,1,2,...,7]`，
   而请求 `canonical_to_local == {72:0,73:1,...,79:7}`、`canonical_ids == [72,...,79]`、`text_units` 长度为 8
   ——即行上的 `global_character_index` 是**窗口局部序号**（对应 document 全局 canonical 72-79）。
3. 因此 `rows_from_decoder` 把局部 0-7 当成 canonical_unit_id，注入
   `track_view.rows_from_forward_evidence` 后，
   `_canonical_index_and_text` 用 `canonical_to_local.get(0..7)` 反查——key 是 72..79，查不到 → 走
   `return int(canonical_unit_id), ""` 退化分支，**global index = 0-7、display_text 恒为空**。
4. 实证：我用真实 evidence 复算该 item（Chinese/此处通往天空，35 个 ok R-U payload）的 R-U 聚合，
   **8 个 distinct unit（0-7）全部重复出现在 35 个请求中**（unit 0 来自 test-demo-000/001/002/003/…-narrow，
   start 3.81/7.49/11.73/14.69…）。每个窗口本应是不同 document 区间（000 覆盖 unit 0-7、001 覆盖 8-15……
   045 覆盖 72-79），却被全部折叠到全局 index 0-7。
5. 正确恢复：`canonical_ids[ row.global_character_index ]`（或反转 `canonical_to_local`）。我用该法对
   045 请求复算得到 global 72-79 + 正确文本「可/沉/浸/于/自/我/疗/伤」+ start 35.49/36.93/.../38.21 ——
   这正是控制器应产出而未产出的结果。

**影响：** 不只是 K-note 报告的"文本为空"——**全局序号本身也是错的**。所有窗口的 R-U/R-S/Current track
全部折叠到 document index 0-7，同一页反复渲染相同的 8 个字符（不同时间）；R-U/R-S 各自的聚合也因索引崩塌而
无法区分不同 song/window 的相同 index，视觉完全错乱，B4-vs-Current 与 Current 四路对比**无任何科学意义**。
J-note smoke"跑通"只是"无 KeyError、renderer 消费了 rows"，未做全局 index/文本正确性校验，故未暴露。

**建议：** `rows_from_decoder` 需携带 `request`，用 `request.canonical_ids` 恢复全局 canonical id（或
`canonical_to_local` 反转 + `text_units` 补文本），再进 `rows_from_forward_evidence`。同时**补一条真实 evidence
级单测**（mock 一个带 `canonical_ids/canonical_to_local` + 局部 `global_character_index` 行的证据，断言投影出的
global index 与 text 正确、且不同窗口不被折叠）——现有 `test_track_view.py` 直接喂 `canonical_unit_id`，
**不覆盖真实 evidence 路径**，故 4 passed 却漏掉此 P0。

---

## [P1] rerender 的 scientific hash 断言范围不含 `<out>/scientific/`，只覆盖 2 个工件

**问题 → 证据：**

1. `snapshot_scientific_hashes(out)`（L268-281）`rglob("*.json*")`，仅收录路径段含 `scientific`/`collection`
   或 `rel.endswith("analysis_complete.json")` 的文件。controller **从不写 `<out>/scientific/`**（J-note
   §E 已注明"未复制出 scientific/"），故在 smoke/本实现下快照只含 `collection/collection.json` +
   `analysis_complete.json`（与 J-note §B 报告"2 个工件"一致）。
2. 03 V7 输出目录（`<run>/scientific/...`）要求正式 run 携带 frozen scientific 证据并在
   collection 前纳入 `<out>`。现实现缺席意味着 03 V7 输出的 `scientific/` 缺失（非本 controller 复制/不复制
   的等价性问题，而是 `<out>` 根本不含该子树），rerender 守护无法保护真正需要冻结的科学证据集。
3. 自洽性**没问题**：`scientific_hash_{before,after}.json` 与 `render_manifest.json` 本身不在快照模式内，
   不会因 rerender 写文件而自变；before 先于渲染捕获、after 后捕获，比较逻辑正确（`forward_triggered=0`、
   `ok=true` 均成立）。

**与 #1（03 V7 布局）的关系：** controller 输出 `collection/analysis_complete/visuals/renders/render_manifest/
scientific_hash_*` 与 V7 基本对应；**仅 `scientific/` 未落入 `<out>`**。J-note 已定为"formal runner 需在
collection 前把 frozen scientific 工件纳入 `<out>` 并参与 hash 快照"，本项正是该待办在数据/断言层面的缺口，
故列为 P1（须在 formal 补齐，否则 rerender 的"科学产物不变"承诺覆盖不全）。

**建议：** formal 输出的 `<out>/scientific/` 在 collection 前从上游落盘，`snapshot_scientific_hashes` 随之
自动纳入（模式已匹配 `scientific`）；并在 rerender-only 上补充"存在 scientific/ 且其 hash 亦不变"的断言。

---

## [P1] B4-vs-Current 用 raw-argmax 作 B4，与 Current 的 `official` 相比是**不同 decoder**，对比失真

**问题 → 证据：**

1. `render_comparison_batch.two_way_tracks`（L91-96）与 `render_rerender_only`（L101-106）：
   B4 = `build_track_from_evidence([payload], decoder_kind="raw", metadata={"family":"raw_argmax_standin"})`，
   Current = `decoder_kind="official"`。两路来自**同一个 evidence 的同一批 R-U 行**，仅 decoder_kind 不同。
2. J-note §E 明示"B4 仍为 raw-argmax stand-in；正式 B4 alignment 产出后再接入"。故已知、非隐藏。
3. 但**口径风险仍在**：raw vs official_fixed 的差异是"单步 argmax 几何 vs 官方 fixed 几何"，这与
   "B4 基线 vs Current 提案"是**两个正交变量**。若该项目标是 B4-vs-Current 的 proposal 对比，raw 作为 B4
   会混入 decoder 差异，结论失真；且叠加 P0 索引崩塌后两路渲染当前全部无效。
4. 结论证据：二者同源同行，仅换 `raw_global_*`/`official_fixed_global_*` 起始字段（controller L114-115），
   并不能代表冻结的 serial-cursor/commit B4 alignment。

**建议：** 正式 B4 JSON 落地后走同构接入（J §E 既定）。在此之前，产出运行须显式标注"B4 为 raw 试听占位，
**不作为** B4-vs-Current 科学结论"。考虑对对比图加角标/元数据 `family=raw_argmax_standin`（已有）并在
`analysis_complete.json` 的记录中声明该限位，避免下游误当正式 B4 基线。

---

## 无问题项（核验通过）

- **#2 数据源字段名（除 P0 的 index 字段外）**：`attempt.request.request_id`、`attempt.status=="ok"`、
  `attempt.decoder_outputs.{raw|official}.rows` 均在真实 evidence 中存在且结构一致——实读 2 个 evidence JSON
  确认。`load_evidence_index` 按 `request_id` 索引、`status=="ok"` 过滤均正确；`item` 匹配走 plan 层
  `r["item"]`（plan 中 `item` 字段存在），请求经 plan `request_id`→`evidence_index` 对接正确。
- **#5 rerender 自一致性与"不因自身写文件而变化"**：`snapshot_scientific_hashes` 不含自身产物
  （before/after/manifest 均不在快照模式内），before/after 捕获时序正确——该项自洽通过（范围不足见上面 P1）。
- **单测**：`PYTHONPATH=src python -m pytest -q tests/unit_realign/test_track_view.py` → **4 passed**。
  但如 P0 所述，该测试用合成 `canonical_unit_id` 直接喂投影，**不覆盖真实 evidence 的局部 index 路径**，
  故通过不构成对 P0 的免疫。

## 附：关于 #3（R-U/R-S 同全局 index / 跨窗口混页）

设计上下文：聚合按 family 合并同一 item 的多窗口 R-U/R-S 行，各 track 自带 `window_trace`（`as_renderer_track`
3-tuple 第 3 元），renderer 只画本 track 的窗——`window_trace` 不串、同全局时间轴这层接线正确。真正让
"同一 index 混页、R-U/R-S 视觉错乱"的是 **P0 的索引崩塌**（所有窗口折叠到 0-7），而非聚合逻辑本身；
修复 P0 后需复核同窗口/跨窗口重叠的 canonical 是否导致单 track 重复行（示例：001-narrow 的 core 与
000 不重叠时无重复；但同一 canonical 出现在相邻窗口的证据文件里时，聚合会并出重复 global index，建议
`rows_from_forward_evidence` 或聚合层按 `(global index)` 去重/告警，归 MINOR backlog）。
