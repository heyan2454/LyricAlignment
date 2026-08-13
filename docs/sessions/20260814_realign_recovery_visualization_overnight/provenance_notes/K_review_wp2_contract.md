# K-note — WP2 可视化 controller 代码正确性/契约 review

> 审查对象：commit `714d514`，`scripts/realign_recovery/visualization/`（visualization_controller.py
> + 4 个 runner：render_b4_vs_current / render_current_4way / render_comparison_batch / render_rerender_only）。
> 审查方式：只读代码 + `tests/unit_realign/test_track_view.py`（4 passed，0.05s）。
> 依据文档：J-note、03 V4/V7、07 计划 §9。只报 P0/P1；MINOR 进 backlog。

---

## 结论：存在 1 个 P1（行投影 display_text 始终为空）；其余 GT/顺序/stand-in 契约均合规。

---

## [P1] 行投影把 `global_character_index` 直接当 `canonical_unit_id` 反投，导致渲染文本/序号全部为空

**问题 → 证据：**

1. `visualization_controller.rows_from_decoder`（controller L114-129）读 decoder 行，
   `gci = row.get("global_character_index") or row.get("character_index")`，然后
   `rows.append({"canonical_unit_id": int(gci), ...})`。**decoder 行的 `global_character_index`
   是 0-based 字符下标（局部），而字段名被写进 `canonical_unit_id`。**

2. `build_track_from_evidence` 再走 `tv.rows_from_forward_evidence(request, evidence_rows)`
   （controller L158）→ `track_view._canonical_index_and_text`：
   ```python
   char_index_by_canon = {int(c): int(l) for c, l in canon_to_local.items()}
   gci = char_index_by_canon.get(int(canonical_unit_id))   # get(0) → None（key 是 canonical id 72+）
   if gci is None:
       return int(canonical_unit_id), ""    # 命中兜底，index 保持原值、text="" 返回
   ```
   真实证据里 `canonical_to_local = {'72':0,'73':1,...}`（canonical id 起点 72），传入的是
   `canonical_unit_id=0/1/2...`，查表必然 `None` → **每行都走兜底返回 `("", text="")`**。

3. **实测复现**（读冻结 evidence 一次，无渲染）：
   ```
   rows_from_decoder first 5 canonical_unit_id: [0, 1, 2, 3, 4]
   first 5 projected: [(0, "''"), ...]
   nonempty display_text count: 0 / 8
   ```

**影响：** 这是**静默**渲染缺陷——不抛错（`track_rows_ready` 只查 start/end/gci 非 None，text 为空不拦），
但 timeline 每块只画色块/空标签，KTV 字幕 alignment 也全是空/占位字（`build_karaoke_alignment` 用
`display_text or '·'` 兜底）。正式输出会显示空字歌词，属数据一致性/契约违反（P1）。

**根因：** controller 为"练习官方 adapter 全链路"走 canonical 反投，但 decoder 行本就没有
`canonical_unit_id` 字段（真实 row 只有 `global_character_index` + `display_text`，见 evidence 实测）；
`rows_from_decoder` 把「局部 char index」塞进「canonical id」槽位，两个域错位。而测试
`test_track_view.py` 只用**正确**的 `canonical_unit_id`（1/2/3）喂 `rows_from_forward_evidence`，
从不覆盖 controller 的 `rows_from_decoder` 喂给它的路径，因此 4 项全过但未抓住此 bug（测试盲区）。

**建议：**
- 最小修复：`rows_from_decoder` 输出的行直接带 decoder 行自身的
  `global_character_index` 与 `display_text`，不再塞进 `canonical_unit_id`；
  `track_view` 侧新增一条直通 path（行已含 `global_character_index`+`display_text` 时不再走
  canonical 反投），或在 controller 里用 `display_text` 覆盖反投结果。
- 补一条控制器级测试：用真实 decoder row schema（`global_character_index` 0-based + `display_text`）
  喂 `rows_from_decoder → rows_from_forward_evidence`，断言 `display_text` 非空。

---

## [P1] batch 多 item 固定 group 名，同 mode 输出互相覆盖（静默）

**问题 → 证据：** `render_comparison_batch.py` L163/L179 对所有 item 用固定
`group="b4_vs_current"` / `group="current_realign_4way"`。多 item 同 mode 时：
- `render_static_group` 写 `visuals/{group}/page_*.png`、`full_timeline.png`（同名），
- `render_video` 写 `renders/{group}.mp4`（同名），
- 后一个 item **静默覆盖**前一个，磁盘上只剩最后 item 的产物；
- 但 `write_render_manifest` 把**每个** item 的 `meta`/`video`（指向同一被覆盖路径）全写入 manifest，
  manifest 与实际磁盘内容不一致（"撒谎"），`summary` 的 `n_videos` 也虚高。

**影响：** 多 item batch 数据完整性被破坏——正式按 `03 V7` 逐 item 出视频时只能拿到最后一项，
且 manifest 不可信。属会污染结果的数据问题（P1）。

**建议：** group 名按 item 熔进子目录/文件名（如 `visuals/{group}/{item-slug}/`、
`renders/{group}__{item-slug}.mp4`）；或对同 group 多 item 明确拒绝并报错，禁止静默覆盖；manifest 以实际落盘文件为准。

---

## 核查通过项（无 P0/P1，供回归）

- **顺序（03 V4）**：4 个 runner 均按 `write_collection → write_analysis_complete →
  render_static_group → render_video → write_render_manifest`；无"先可视化后 collection"倒挂。✓
- **GT 防火墙**：目录内 grep 无 `gt/ground/truth/eval` 业务 import（仅 docstring/`forward_root` 变量名）；
  `track_view` 不读 evaluator/GT；collection/analysis_complete 均为只读 frozen-evidence 清单。✓
- **无 model/forward/torch/transformers import**：目录 import 仅 stdlib + `lyricalign.demo.{track_view,
  timeline_video, visual_diagnostics}`；`render_rerender_only` 显式 `forward_triggered=0`。✓
- **B4 stand-in 如实标注**：`render_b4_vs_current` 用 `decoder_kind="raw"` + `metadata=raw_argmax_standin`，
  docstring/标题明确"B4=raw argmax stand-in，B4 alignment.json 尚不存在"，未冒充 genuine B4。✓
- **双路同全局时间轴、window_trace 不串**：`render_static_group` 共享同一 `start/end`；
  每 track 自带 `window_trace`（`as_renderer_track` 3-tuple 第 3 元素），`draw_track_windows` 只画本 track 窗。✓
- **四路第四路退三路（03 V2）**：`render_current_4way --fourth-family` 默认 None → 3 tracks，
  有真实证据才追加第 4 路；绝不重复 forward/旧家族冒名。✓（batch 的 `--fourth-family` 同理。）
- **rerender 科学 hash 断言**：`snapshot_scientific_hashes` 覆盖 `scientific/`、`collection/`、
  `analysis_complete.json`（按 `path.parts` 命中 scientific/collection，或 endswith
  `analysis_complete.json`），before/after 比对；dry-run 仅快照不重渲。✓
- **batch 逐 item audio 接线**：`audio = audio_map.get(item) or args.audio`（已修，透传逐 item 解析的 audio）；
  缺 audio 的 item 跳过并 warn。✓（接线正确，仅上面的 group 覆盖是问题。）

---

## MINOR（进 backlog，不阻塞）

- **Current baseline 窗 trace 只覆盖首家族**：`render_current_4way`/rerender 的
  `base_payloads = ru or rs` 且 `_trace_for(base)` 只含 ru（若有 rs 则 rs 窗不入 current window_trace），
  docstring "union of realigned windows" 与实际不符（仅首家族）。
- **`copy` 只缺未列**：`snapshot_scientific_hashes` 只比对 before 中存在的 key，
  before 缺失、after 新出现的 scientific 工件不会被 `changed` 抓到。
- **四路 KTV 只用 current 行**：`build_karaoke_alignment(rows, ...)` 里 rows 取 current_track，
  未聚合 R-U/R-S 行，KTV 只是当前基线。
- **`write_analysis_complete` 打 `n_requests=len(plan)`**（batch L145）是全量 plan 请求数，非本 item 数，
  语义与 b4/4way 单 item 口径不一致。

---

## pytest

`PYTHONPATH=src python -m pytest -q tests/unit_realign/test_track_view.py` → **4 passed (0.05s)**。
（注意：通过仅覆盖 `rows_from_forward_evidence` 正确输入，未覆盖 controller `rows_from_decoder` 错位路径，
见 P1 测试盲区。）
