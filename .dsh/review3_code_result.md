# Review 3/2 — 代码正确性二次审查报告（render_full_song.py 修复验证 + visualization/ 补充扫描）

审查对象：`scripts/realign_recovery/visualization/`。基线：commit 2fc5e7a。
方法：静态读码 + `py_compile`（conda lyricalign-qwen 下通过）。未跑真实实验。

---

## 一、修复1（KTV lane 跟随 Current）—— 判定：**正确**

`render_full_song.py:247-253` 现为：

```python
ktv_track = next(
    (t for t in tracks
     if ("Current" in (t.get("label") or ""))
     and (t.get("metadata") or {}).get("family") == "full_song"),
    tracks[0],
)
rows = ktv_track.get("rows") or tracks[0].get("rows") or []
```

### 逐调用核对

| 调用 | lanes 顺序 | Current label | family | KTV 选择结果 |
|---|---|---|---|---|
| `batch_b4_dual.py:102-106`（V1） | [B4 历史pre-slot串行, Current] | `Current`，含 "Current" | `full_song`（`build_fullsong_track` 固定写入） | Current（tracks[1]），**正确** ✓ |
| `batch_final_4way.py:61-65`（V1） | [B4 历史pre-slot串行, Current] | `Current`，含 "Current" | `full_song` | Current ✓ |
| `batch_final_4way.py:74-80`（V2） | [Current] | `Current`，含 "Current" | `full_song` | Current（=tracks[0]）✓ |
| `batch_v2_overlay.py:42-47` | [Current 全曲] | `Current 全曲`，含 "Current" | `full_song` | Current（=tracks[0]）✓ |
| `--fullsong-align`（`render_full_song.py:130`） | [Current (全曲)] | `Current (全曲)`，含 "Current" | `full_song` | Current ✓ |

- `Current` 关键词命中：所有 in-scope 调用者的 current lane label 都含子串 `"Current"`。
- `metadata.family=='full_song'` 第二条件把机制 overlay lane 排除：mechanism lane（R-U/R-S/R-CF/`--fourth-family`）的 family 分别为 `"R-U"`/`"R-S"`/`"R-CF"`/`args.fourth_family`，永非 `"full_song"`，不会误选。
- `--fourth-family` 的 label 即使含 "Current"（如 `--fourth-family "Current X"`），其 family 是 `"Current X"` 而非 `"full_song"`，也避开误匹配。安全。
- **回退风险**：只有当不存在含 "Current" 且 family=='full_song' 的 lane 时才回退 `tracks[0]`。在 batch_final_V2 / batch_v2_overlay 中 Current 就是 tracks[0]，回退结果仍为 Current。仅 batch_b4_dual（Current=tracks[1]）会受回退影响，但其 current lane 含 "Current" 且为 full_song，必然命中，不走回退。**未破坏任何 in-scope 调用者**。

### 结论
修复1 **正确**。KTV 高亮现在严格跟随 Current 全曲 lane，满足 03 §3.3「字符高亮与当前播放时间一致」，且 B4 在前的 batch_b4_dual 不再被误用为 KTV 源。

---

## 二、修复2（R-CF `--fourth-family` 不再误 SystemExit）—— 判定：**正确**

`render_full_song.py:174`（`f4_handled=False`）、`189`（主 root `f4` 命中→置 True）、`209-210`（rcf glob 命中且 `fourth_family=="R-CF"`→置 True）、`214-217`（统一判断 raise）。

f4_handled 置 True 的时机：
1. 主 `forward_root` 中存在 `proposal_method==fourth_family` 的 ok payload（f4 非空）；
2. rcf root 命中 R-CF 证据，且 `fourth_family=="R-CF"`。

raise 条件（`fourth_family 且 not f4_handled`）：明确请求 `--fourth-family` 但主 root 与 rcf root 双源均无证据 → 仍报错。契约保留（显式请求无证据视为配置错误，非静默降级），未丢失原语义。

原行为保留性：
- `--fourth-family R-CF` + rcf root 有证据：旧实现会误 SystemExit（rcf 分支 `pass` 不置位），新实现正确跳过。✓
- `--fourth-family <其他>` 主 root 有证据：置 True，不 raise。✓
- `--fourth-family <其他>` 双源无证据：raise，与原行为一致。✓
- **不传 `--fourth-family` 时**（batch_final_4way V2 即此用法，仅 `--rcf-evidence-root RCF`）：`if args.fourth_family` 为假，f4_handled 虽 False 但不触发 raise；rcf lane 正常追加。原行为保留，batch_final_4way V2 运行正常。✓

仅一处 MINOR（非 P0/P1）：若主 root 恰又含 `proposal_method=="R-CF"` 的 payload，会同时追加主 root 的 "R-CF"（label=fourth_family）+ rcf 的 "R-CF" 两个 lane（重复）。现实主 root 不含 R-CF，冲突概率低，且语义无害（均为 R-CF 证据）。建议在主 root sibling 命中时跳过 rcf 追加，或对 `(family, evidence_source)` 去重。

### 结论
修复2 **正确**。逻辑自洽，raise 条件合理，原行为被保留（含 batch_final_4way V2 无 `--fourth-family` 的正常运行路径）。

---

## 三、补充扫描结果

### P1 — 重复 KTV 跟随错误 lane 的 bug 仍存在于 3 个旧 runner

这些脚本都用 `rows = next((t.get("rows") for t in tracks if t.get("rows")), [])` 选 KTV 源，**取 tracks 中第一个非空 rows 的 track**。在 twoway（B4 vs Current）分支里 tracks=[B4, Current]，B4（raw 几何）几乎总有 rows，因此 KTV 高亮跟随 **B4 而非 Current**，违反 03 §3.3——与 render_full_song 修复前同一类 bug 的残留实现：

- `scripts/realign_recovery/visualization/run_test_demo_viz.py:310`（twoway 分支，`two_way_tracks` 返回 [B4, Current]）—— 当前 session 报告（08）点名的 Test Demo 批量可视化入口。
- `scripts/realign_recovery/visualization/render_comparison_batch.py:107`（twoway 分支 `two_way_tracks`=[B4, Current]）。
- `scripts/realign_recovery/visualization/render_rerender_only.py:108`（`mode="twoway"` 分支 tracks=[B4, Current]）。

> 注：同一模式的 **fourway** 分支无此 bug（tracks 以 Current baseline 为第 0 个，rows 即 Current）。`render_b4_vs_current.py:106`、`render_current_4way.py:124` 显式 `current_track.get("rows") or ...`，也正确。

建议：把这三处 `next((t.get("rows") for t in tracks if t.get("rows")))` 改为按 label/family 选 current lane（如 `next((t["rows"] for t in tracks if "Current" in t["label"] and t.get("rows")), tracks[0].get("rows") or [])`），或直接取 `current_track`/`base` 变量的 rows，与 render_full_song 修复对齐。

定级说明：这三个 runner 均非当前 batch（batch_b4_dual / batch_final_4way / batch_v2_overlay）直接调用的正式实验链路，故定 P1 而非 P0；若后续仍用它们产出 B4-vs-Current 视频被当作正式验收，应优先修复。

### 无其他 P0/P1
`visualization_controller.build_karaoke_alignment`（:408）为纯函数，收容传入 rows，**不依赖 tracks[0]**，无隐藏依赖；`track_view`（src/lyricalign/demo/track_view.py）仅投影 rows，无 karaoke 依赖。render_full_song 的 ktv 修复改用了该纯函数的上层选 lane 逻辑，改动边界正确。

---

## 四、结论
- **修复1 正确**（KTV 跟随 Current，未破坏 batch_b4_dual / batch_final_4way / batch_v2_overlay 任一调用）。
- **修复2 正确**（f4_handled 判定与 raise 条件合理，原行为保留）。
- 新增 **P1×1**（同源类 bug 残留于 run_test_demo_viz.py / render_comparison_batch.py / render_rerender_only.py 的 twoway KTV rows 选取），+ MINOR×1（修复2 主 root 与 rcf root 双命中 R-CF 时 lane 重复）。
