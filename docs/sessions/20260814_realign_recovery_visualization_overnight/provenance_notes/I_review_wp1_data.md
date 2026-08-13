# I note — WP1 (E0 freeze + infrastructure) 数据一致性 / 跨模块接线 review

审查对象：commit `94fa0bf`（`request_families.build_request_identity` family-context + `build_resolved_baseline.py` E0）。
范围：identity 一致性 / cross-run 接线 / GT 防火墙 / GPU 预算 / 回归。只报 P0/P1，MINOR 进 backlog。

结论先行：**无 P0**。有 **2 条 P1**（均集中在 `build_request_identity` 的 fail-closed 与 identity_context 透传契约），其余为 MINOR。

---

## 1. identity 一致性（build_request_identity vs plan §4.2/WP1 + C_note §3.3）

### [P1] family-context 未进 `required` 集合 → 多迭代请求漏父链时静默复用旧 forward（fail-closed 缺口）
- 问题：07 plan §4.2 的意图是 `parent_request_identity/iteration/recrop_view_id/split_slot_id` 成为 request identity 的**显式扩展点**（C_note §3.3：在 `required` 键集合 + `_digest` 参与字段里追加）。实现（`request_families.py` L54-58, L71）把它们折叠进 `family_context` dict 且**只消化非 None 的键**，但**未加入 `required`**（L45-46）。因此若多迭代/多 split 调用者**漏传**任一 key，`build_request_identity` 不会 fail-fast，identity 静默回退到"无 family 上下文"版本。
- 证据：
  - `request_families.py` L43-72：`required = (audio_sha256, baseline_digest, model, checkpoint, decoder, mapping, code, text_adapter)` 不含任何 family key；`family_context` 仅 `request.get(key) is not None` 才收录。
  - 07 plan L49-50 / L134 / L237：要求"显式新增四 key"，C_note §3.3 L90 明确"在 `required` 键集合 + `_digest` 参与字段里追加"。
  - AGENTS 纪律：内容寻址下"输入变化禁止复用旧 forward / 修 identity bug 后只重跑受影响 identity"——父 candidate 变化而漏传 parent 时，identity 相同 → 直接命中旧 cache，产生被污染的复用。
- 建议：对 `identity_context` 中确实是 family 上下文的请求，把 `parent_request_identity`（及当 family 属 R-U 迭代/recrop/split 族时的 `iteration/recrop_view_id/split_slot_id`）纳入 `required` 校验；即当 `request` 携带 `identity_context` 或 `family_version>v1` 时，四个 key 缺一即 `ValueError`。至少可加一个"family-aware required"分支，避免破坏现有 single-shot（无 family 上下文）用例。

### [P1] `identity_context` 里非四 key 的其它上下文被静默丢弃 → 未来 E1/E2 扩展时 identity 碰撞
- 问题：`build_family_request`（`request_families.py` L200）`result.update(dict(identity_context or {}))` 把任意 identity_context 透传进 request，但 `build_request_identity` 只消化**显式枚举**的四个 key + 固定列表；任何其它 identity_context 键（如未来的 `mechanism`/`chain_type`/`direction`/`parent_candidate_id`）会被静默丢弃，不参与 digest。
- 证据：
  - L54-58 只枚举四 key；L59-72 digest 不包含通用 `identity_context` 整体。
  - C_note §3.3 明确依赖 "identity_context 透传"（`build_family_request` L190 已透传）作为扩展载体。
  - 07 plan L116/125-126：E1（multi_iteration）与 E2（split_variants）都要靠 identity_context 携带 parent/iteration/recrop/split 之外的轨迹上下文。
- 建议：要么把"未知 identity_context 键"视为 error（白名单 fail-closed），要么显式把整个 `identity_context`（sort_keys 序列化）并入 digest。当前"只消化白名单四 key"会让新增上下文类型静默撞 identity——正是主干上最危险的缓存污染形式。至少在实现 E1/E2 前定下规则：非白名单 identity_context 键必须显式注册，否则拒绝。

### [MINOR] 折叠成 `family_context` dict 而非法定顶层 key
- 与 plan "显式新增四 key" 的**字面**不一致：实现为嵌套 `family_context` dict（L54-58/L71），不是四个独立顶层键。功能上 identity 随这些 key 变化（测试 `test_multi_realign_family_context_changes_identity` 已覆盖），且在 `_digest` 参与字段中，故满足 plan 意图的**语义**。建议在 IMPLEMENTATION_MAP 中注明"折叠进 family_context 不改变 digest 语义"，避免后续 reader 逐 key 对照 plan 时误判为未实现。非一致性 bug。
- 备注：`iteration=0` 用 `is not None` 判断，不会因 falsy 被丢弃——正确。

---

## 2. cross-run 接线（E0 resolved JSON vs 03 V7 run 布局 / plan §5 run root）

### [MINOR] resolved JSON 写在 run root 而非 `scientific/`，与 03 V7 布局字面不符
- 问题：03 V7（L322-342）每个 run 内布局为 `scientific/ collection/ analysis_complete.json visuals/ renders/ render_manifest.json scientific_hash_before/after.json`。E0 把 `CURRENT_BASELINE_RESOLVED.json / B4_BASELINE_RESOLVED.json / BUDGET_PROJECTION.json` 直接写到 `--out-root` 顶层（`build_resolved_baseline.py` L135-142），未落在 `scientific/` 下。
- 证据：06_PLANNED_RUNS.yaml P0 outputs（L19-22）列出的正是这三个文件名，未指定嵌套层级；07 plan §5 L172 "每个 run 内布局遵循 03 文档 V7（scientific/...）"。
- 评估：resolved 是"冻结配置/前置",非 `scientific/` 科学产物，放在 run root 顶层在语义上可接受，且命名与 plan §5 / 06 yaml 完全匹配；脚本接 `--out-root`，run root 名称（`P0: 20260814_visualization_E0_freeze_and_preflight`）由调用方以 `--out-root` 传入，脚本无需感知。因此这**不构成 P0/P1**，仅建议在 run root 顶部放一个 README/IMPLEMENTATION_MAP 注明这三个文件是 P0 冻结产物、reused sha256 进入后续 `scientific_hash_before/after`。若后续接可视化要求严格 V7，可把 resolved 移入 `scientific/config/`。
- resolved 的 `sha256` 复用 `baseline_identity.identity_digest`（L65-67/L99-101），并可被下游当作 baseline_identity.identity_digest，cache/rerender 稳定——接线正确，无 P1。

---

## 3. GT 防火墙（family_context 是否进 no-GT 特征路径 / 会不会被拒）

### (无 P0/P1) 防火墙本身成立，但存在跨模块 deny-list/allow-list 不一致
- 问题（无实际泄漏，列为 MINOR）：unit_realign 的 no-GT 特征走**严格 allow-list**（`unit_gate_features.py` `ALLOWED_FEATURE_KEYS`，不包含任何 family_context 四 key），故 `parent_request_identity/iteration/recrop_view_id/split_slot_id` **不可能**进 no-GT 特征行（fail-closed，够安全）。而 research_v7 的 `assert_no_label_leak`（`detector_v2_evidence.py` L29-34）是 **deny-list**，FORBIDDEN_FEATURE_FIELDS **不含**这四个 key——即若某下游误把它们放进特征行，`assert_no_label_leak` 会**静默放行**而非拒绝。
- 证据：`assert_no_label_leak` L29-34 无四个 key；`unit_gate_features.assert_no_gt_feature_row` L8-15 严格 allow-list。
- 评估：这四个字段本身不携带 GT/误差值（是 identity 字符串），即使经 deny-list 放行也不构成 GT 泄漏；且 unit_realign 主路径用 allow-list 已阻断。不属 P1。建议（MINOR）：在 `assert_no_label_leak` 的 FORBIDDEN_FEATURE_FIELDS 里也显式列入四个 family key（或至少列入 `parent_request_identity`/`split_slot_id`），使 deny-list 路径与 unit allow-list 口径一致，防未来扩 family 时误入。
- `audit_evaluator_only.py`：只校验 `post_hoc_evaluator_only / runtime_gt_access False / writeback 0 / NO_GT_CHECK 全 validated / request 对齐 / outcome canonical`，不会因行内含 parent/iteration/split 而拒绝行（它也不要求这些字段不得存在）。与 E_note §4.3 契约一致——E_note §4.3 描述的是 evaluator 边界而非特征字段黑名单，未违反。无 P1。

---

## 4. 预算（BUDGET_PROJECTION vs E_note §5）

### (无 P0/P1) 预算与 E_note §5 一致，无单位错误
- 核对：`per_forward_sec=0.5`（E_note §5.3 "≈0.5s（warm ~60s window）"，0.2–0.75 区间中值）✓
- `screening_regions=40` × `branches_per_region=5` → `screening_forward_estimate=300`（E_note §5.3 说 40–60×3–5 ≈ 120–300，300 取上界，保守）✓
- `expansion_regions=200` → `expansion_forward_estimate=500`（E_note "扩 1–2 机制 × ≥200 regions ≈ 数百 forward"）✓
- `total_forward_estimate=1000`（E_note "合计 ~500–1000"）✓
- `total_forward_wall_sec_warm=500` = 1000×0.5 = 500s ≈ 8.3min —— 与 E_note "5–10 分钟 warm GPU"一致，**无单位错误**（秒已注明）。
- `target_hours=10 / hard_cap_hours=12` 与 06 yaml / E_note §5.1 合同逐字一致 ✓
- note 说"forward wall time 是分钟级，大头是模型加载/冷 cache/evidence IO"——与 E_note §5.3 结论一致 ✓
- 结论：**预算无 P0/P1**。

---

## 5. 回归

### ✅ 全绿
- 命令：`PYTHONPATH=src python -m pytest -q tests/unit_realign tests/realign_recovery`
- 结果：**237 passed in 2.91s**（exit 0）。WP1 未破坏既有 unit_realign / realign_recovery测试。
- 新增用例 `test_request_families.py::test_multi_realign_family_context_changes_identity / is_reproducible`、`test_resolved_baseline.py`（含 BUDGET within cap 10/12h）均已通过。

---

## 汇总

| 项 | 结论 |
|---|---|
| P0 | 无 |
| P1 | 2 条（family key 未进 `required` → 漏传父链静默复用旧 forward；`identity_context` 非四 key 被静默丢弃 → 未来 E1/E2 扩展 identity 碰撞） |
| MINOR | resolved 落 run root 而非 `scientific/`；family_context 折叠而非顶层 key；`assert_no_label_leak` deny-list 未列 family 四 key（跨模块口径不一致） |

P1 均在 identity 层，属于"静默兜底而非 fail-closed"类问题——不改变当前已冻结 E0 结果的正确性（resolved 不含 family_context 消费路径），但在 multi-iteration/split（E1/E2）上线前必须修复，否则会在主干上产生可污染结果的跨迭代缓存复用。
