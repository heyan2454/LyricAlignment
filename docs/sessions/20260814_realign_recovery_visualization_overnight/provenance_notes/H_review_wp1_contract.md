# H Review — WP1 (04fa0bf) 契约/正确性 review（P0/P1 only）

> 审查对象：commit `94fa0bf` 的
> `src/lyricalign/unit_realign/request_families.py`（build_request_identity + family_context）、
> `scripts/unit_realign/build_resolved_baseline.py`（E0 resolved baseline）、
> `tests/unit_realign/test_request_families.py`（新增 2 个 family-context 测试）、
> `tests/unit_realign/test_resolved_baseline.py`（新增 E0 测试）。
>
> 实测：`PYTHONPATH=src python -m pytest -q tests/unit_realign/test_request_families.py tests/unit_realign/test_resolved_baseline.py` → 16 passed；
> `tests/unit_realign/` 全量 → 73 passed。语法/diff 干净。
> 本轮 review 结论与代码证据。

---

## 结论汇总

- **P0：无。**
- **P1：1 条**（B4 冻结 cascade 的 `skip_silent_windows` 与 B4 serial runner 默认不一致）。
- MINOR → backlog（5 条，见后），不阻塞 WP1 后续。

---

## [P1] B4_BASELINE_RESOLVED cascade 的 `skip_silent_windows=True` 与 B4 serial runner 默认 `False` 冲突（数据一致性 / B4 冻结契约精度）

**问题 → 证据 → 建议**

- **问题**：`build_resolved_baseline.py` 的 `_b4_baseline()` 与 `_current_baseline()` 共用同一常量
  `WINDOW_SILENCE_RESOLVED`，其中硬编码 `"skip_silent_windows": True`。但脚本文档（L4`"从代码字面量冻结值"`，
  L9`B4 = align_qwen_fa_serial_demo --decoder official`）声称 B4 取自该 serial runner；而该 runner 的
  `--skip-silent-windows` **默认是 `False`**（`scripts/demo/align_qwen_fa_serial_demo.py` L1646
  `action=argparse.BooleanOptionalAction, default=False`；消费处 `getattr(args,"skip_silent_windows",False)` L960/L871）。
  于是 B4 resolved 的 cascade 与服务端默认行为不一致：在未显式传 flag 时 serial runner 实际 `skip_silent_windows=False`，
  resolved 却记 `True`。
- **证据**：
  - resolved：`scripts/unit_realign/build_resolved_baseline.py` L31-46 `WINDOW_SILENCE_RESOLVED` 含 `skip_silent_windows: True`，
    且 `_b4_baseline()`（L71-102）直接 `cascade = dict(WINDOW_SILENCE_RESOLVED, ...)`。
  - B4 runner 默认：`scripts/demo/align_qwen_fa_serial_demo.py` L1646（default=False）、L960/L871（getattr 兜底 False）。
  - 前置核实文档 `provenance_notes/B_note_baseline_current_b4.md` L96 早已把 B4 的 `skip_silent_windows` 标记为
    “**需核实**（serial runner 层）”；本轮实现**未先解决该核实项**就在 B4 freeze 里硬编码 `True`。
  - Current 侧无此问题：Current runner `scripts/demo/run_inline_realign_experiment.py` L290 硬编码
    `skip_silent_windows=True`，故 Current cascade 的 `True` 是权威的。
- **影响**：B4 是 E0 冻结的、会被下游 cache/rerender 与 `B4_BASELINE_RESOLVED.sha256` 引用的 resolved profile。
  若历史 B4 按 runner 默认（`false`）跑，则此 resolved 不“如实表达 B4”，并可能污染基于它的 rerender/cache baseline。
  若历史 B4 确实传了 `--skip-silent-windows`，则 `True` 正确，本项降级为“待在 P1-1 对照 run 打勾”。
- **建议**：① 派一个对照 run（serial runner + `--decoder official` + 60/10/10 + window 参数）
  与历史 B4 artifact 对账，落地 `B_note` 遗留的 `skip_silent_windows` / `compress_silence_audio` 核实项；
  ② 按对账结果把 B4 cascade 的 `skip_silent_windows` 改为实际值，并**与 Current 拆分**或新增
  `b4_cascade`（不要 Current/B4 共用一份常量掩盖差异）；
  ③ 在 `test_resolved_baseline.py` 增加断言：B4 cascade 的 `skip_silent_windows` 与 serial runner 默认（False）
  一致（或显式声明来源），否则本 bug 测试不会拦。

---

## 审查点逐项核对

### 1. `build_request_identity` + family_context

#### (a) 能否避免“同一请求在不同迭代/recrop/split 复用旧 forward”——✅ 机制有效
- 实现：`request_families.py` L54-58 把 `parent_request_identity/iteration/recrop_view_id/split_slot_id`
  中非 `None` 者收进 `family_context`，L71 并入 digest。只要 E1（multi_iteration）、E2（split_variants）
  的 caller 经 `identity_context` 正确填入这些键，对应 identity 必变 → 不会跨迭代/recrop/split 命中旧 forward。
- 测试 `test_multi_realign_family_context_changes_identity`（L145-169）逐键断言
  parent/iteration/recrop/split 任一变化 → identity 变化，且 `test_multi_realign_family_context_is_reproducible`
  （L172-182）断言相同上下文 → 相同 identity（正确 cache 命中）。机制正确。
- **注意（不断言为 bug）**：当前 E0 阶段**没有任何 caller 设置这 4 个字段**（grep 全 src + scripts，
  仅 request_families.py 自身引用）。即扩展点是“休眠”的，等 E1/E2 接线才真正生效。
  故本条验证的是机制正确性，尚不能证明端到端不复用——E1/E2 落地时需复跑本测试。
- 契约对照：07 计划 L50 要求“显式新增四个 key”。实现采用**嵌套 `family_context`（非空才入）** 而非
  四个平铺 key。功能意图（输入变化→identity 变）达成，但这是一个**可选设计偏差**，见 MINOR-4。

#### (b) 单次请求 identity 稳定性（family_context 为空）——❌ 与改动前不一致（MINOR-1）
- 实测（本机 Python 复算）：对同一单次请求，
  改动前 digest（无 family_context 键）`sha256:4d0f3a69…`，改动后（含空 `"family_context":{}`）
  `sha256:189db319…`，二者**不同**。原因：`_digest` 用 `json.dumps(sort_keys=True)`，
  新引入的 `"family_context"` 键即使为空也会进入序列化串。
- 现实影响评估：`unit_realign` 是本 WP1 才冻结的新模块，改动前后**均无已持久化/已提交的旧 identity**，
  无门禁 G0 固定期望 digest，故此变化不会让旧结果失效或错配（所有行统一用新方案重算）。
  这属于“同一 commit 内定义冻结 scheme”，非追溯性失效。

#### (c) GT 泄漏——✅ 当前无 GT 泄漏
- 4 个 family 字段是结构元数据：`parent_request_identity`=sha256 digest 串、`iteration`=int、
  `recrop_view_id`/`split_slot_id`=view/slot 名；不携带 GT 对齐值（时间戳/标签）。
- identity 所包 `intervention_payload` 里的文本/音频字段取自 **baseline**（已知歌词 + baseline audio range），
  非 GT；`evaluation_only` 仅置标志，不把 oracle 结果写进 identity。
- **前瞻风险（记录，不判 P0）**：E1 oracle/recovery recovery 流若往 `identity_context`
  注入候选结果/GT，才会引入泄漏。建议在 E1 code map 里显式写“identity_context 只允许结构 meta，禁 GT”。

### 2. `build_resolved_baseline.py`（E0）

#### (a) CURRENT 反映 full_slot / decoder_view=raw——✅
- `_current_baseline()` 直接 `identity = dict(FROZEN_BASELINE_IDENTITY)`
  （`frozen_baseline.py`：`request_mode="full_slot"`、`decoder_view="raw"`、60/10/10、阈值、GT source），
  是权威字面量。✅
- 注意：resolved `sha256` 用 `{**identity, "cascade":…, "schema_version":"resolved_baseline_v1"}`
  计算，覆盖掉 identity 里原 `"realign_recovery_baseline_identity_v1"`。属确定性自描述小瑕疵（MINOR-2）。

#### (b) B4 表达 pre-slot serial + decoder official——⚠️ 内核正确，cascade 一处失准（→ 上文 P1）
- B4 identity 含 `decoder_kind:"official"`、`request_mode:"pre_slot_serial_non_slot"`、
  `runner:"scripts/demo/align_qwen_fa_serial_demo.py"`、60/10/10 —— 与 03 V1 + B_note 一致 ✅。
- 但与 serial runner 默认冲突的 `skip_silent_windows=True` 见 P1。

#### (c) sha256 用稳定 canonical — ✅
- `identity_digest`（`baseline_identity.py` L43-50）用 `canonical_identity_json` =
  `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True)`。稳定、可复现；
  `test_resolved_baseline_hashes_are_deterministic` 双重跑一致 ✅。
- MINOR：Current 与 B4 的 digest 覆盖 field 集不对称（B4 identity 缺 `detector_artifact_sha256`/
  `silence_aware_window_plan`/`decoder_view`/阈值/`real_gt_source`），B4 是历史 profile 可接受，但两处
  digest 字段集不同，建议在文件里记明字段集差异（MINOR-3）。
- 注：`detector_artifact_sha256` 本机文件存在 → 为真实 hash 非 `"MISSING"`，当前两台/本机一致。

#### (d) actual_writeback=0 全分支成立——✅
- `_current_baseline` L62、`_b4_baseline` L96 均 `"actual_writeback": 0`；
  `BUDGET_PROJECTION` 是纯投影无 writeback 字段（语义合理）；测试断言 ==0 ✅。

### 3. 测试质量
- `test_request_families.py` 新增 family-context 两用例：正确覆盖 parent/iteration/recrop/split 各维，
  且含“相同→复用”反向用例，无假阳性。
- `test_resolved_baseline.py`：字段/writeback/确定性/预算 cap 合理；**缺陷**：B4 cascade 的
  `skip_silent_windows` 未与 serial runner 默认对账，导致 P1 未被测试拦下（见 P1 建议③）。

---

## MINOR（backlog，不阻塞）

- **MINOR-1（回答审查 #1b）**：`family_context` 为空 dict 时 identity 与改动前不一致（实测 4d0f3a69→189db319）。
  当前无旧持久化 identity，实际影响为零；建议在 commit message 或模块 docstring 里注明“WP1 E0 冻结即统一新 digest 方案”。
- **MINOR-2**：`_current_baseline` 的 digest 把 `schema_version` 覆盖为 `resolved_baseline_v1`，
  而存储的 `identity.schema_version` 仍是 `realign_recovery_baseline_identity_v1`；
  从文件内容 alone 无法重算 sha256（需知道 override）。建议 digest 不含 override 或字段集一致化。
- **MINOR-3**：Current 与 B4 的 `sha256` 覆盖不同字段集；建议在 JSON 里显式写 digest 字段集，便于审计。
- **MINOR-4**：07 计划 L50 写“四个平铺 key”，实现用嵌套 `family_context`（非空才入）。功能等价，
  但 dev from 文字契约；建议在 code map 注释说明，避免后续 reviewer 误判。
- **MINOR-5**：`build_request_identity` 对 `iteration` 做 `json.dumps`，int `2` 与 str `"2"` 会序列化为不同 digest。
  E1/E2 caller 若类型不一致会导致本应相同的 cache 分开。建议 identity_context 里统一类型/加类型契约（E1 code map 写入）。

---

## 验证记录
- `pytest -q tests/unit_realign/test_request_families.py tests/unit_realign/test_resolved_baseline.py` → 16 passed
- `pytest -q tests/unit_realign/` → 73 passed
- 单次请求 digest 前后对比脚本：OLD(无 family_context)=`sha256:4d0f3a69…`, NEW(空 family_context)=`sha256:189db319…`, `DIFFER:True`
- detector artifact 存在于 `/home/hyan/Data/lyricalign/runs/…/FROZEN_OPERATING_POINTS.json`（非 MISSING）
