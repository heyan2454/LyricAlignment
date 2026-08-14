# AC Review — WP10 Test Demo 可视化批量（E8/E9）

- **Commit**：`416621b`（`feat(realign_recovery): WP10 Test Demo visualization batch`）
- **变更范围**：仅 `run_test_demo_viz.py` + `README.md` + `AB_wp10_testdemo_viz.md`；复用 WP2 `visualization_controller.py` + `transcode_media_to_wav.py`。
- **Review 类型**：代码正确性/契约 + 数据一致性（只报 P0/P1，MINOR 进 backlog）。
- **方法**：静态读码 + 最小 CPU dry-run（--skip-render）+ 只读证据脚本推算 row/payload 计数推导 `build_family_tracks` 行为；**未跑 GPU、未跑全量多语言渲染**。（可选 3s fourway smoke 因下述 pytest 环境问题未作为验收依赖。）

---

## 结论：存在 2 个 P1，无 P0

发现 **2 个 P1（数据一致性 + 契约违反，均为静默错误）**：

---

## [P1] #1 `build_family_tracks` 不做 item 级 scope → 四路渲染跨歌污染

- **问题**：`run_test_demo_viz.py` 的 `build_family_tracks()`（L228–270）解析 R-U/R-S/fourth-family 全部直接 `for p in evidence_index.values() if proposal_method == X`，**扫的是整份 forward/evidence 全集，未按当前 item 收敛**。frozen evidence 的 `request.item_id`（字段确凿存在，如 `Chinese/此处通往天空.mp3` / `Chinese/人造卫星.mp3` / `English/Past Lives.mp3` / `Cantonese/浮夸.mp3` / `Japanese/乙女解剖.mp3`）在该函数中从未被读取。
- **证据**（对 `04_test_demo` 只读推算）：`load_evidence_index` 索引 118 个 ok evidence，proposal_method 分布 = R-U×59 / R-S×59，跨 5 个 item（此处通往天空 35+35、人造卫星 18+18、另 3 个 2+2）。调用 `build_family_tracks` 对 **任意** item（含 English/Past Lives）都返回：Current/R-U/R-S 各 `n_payloads=59`、`rows=470`，即 **每个 item 的四路 track 与别的 item 完全一样**，混入了其它 4 首歌的 row。
- **影响**：在 `04_test_demo` 这类 multi-item collection 上跑 WP10 批量子渲染时，`current_realign_4way/*` 的 MP4 会静默混叠多首歌的 global 时间线，输出为“假数据”且不报错。AB note 里 smoke 记录的“各 470 rows”正是该污染的体现。这违反 03 V4 每 item 一轨的语义，也是数据一致性违反。
- **正确写法参照**：同目录 WP2 `render_rerender_only.py` / `evidence_payloads_for_family()` 会按 plan request_ids 收 scope；否则至少按 evidence `request.item_id == 当前 item` 过滤。对 `-sparse` 掉链的场景，正确做法是用 `item_id`（或 `parent_request_id`→plan 归属）映射而非全局 proposal_method 扫描。
- **建议**：`build_family_tracks`（及 `build_family_tracks` 的 `ru` fallback 之前）先按 item scope；或复用一个带 item 过滤的 `evidence_payloads_for_family(..., item=...)`。修后以 `English/Past Lives`（2+2）与 `此处通往天空`（35+35）的 n_payloads 差异回归校验。

---

## [P1] #2 `--rerender-only` 是空操作，未复现 `render_rerender_only` 的“真重渲染 + hash 断言”

- **问题**：`run_test_demo_viz.py` L362–381 的 `--rerender-only` 分支只是 `snapshot_scientific_hashes(before)` → 写入 before/after JSON → 再 snapshot(after) ⇒ `changed` 判 `unchanged`。**中间没有任何 evidence 重投影、无 `render_static_group`/`render_video`**。因此断言恒真（空转），并不验证“对已存在 out-root 做 camera-only rerender 后 scientific 哈希不变”。
- **证据**：对空 out-root 跑 `--rerender-only --mode fourway` 输出 `scientific_hashes_unchanged:true`、`n_scientific_artifacts:0`，out-root 里只有 `scientific_hash_before/after.json`（均为 `{}`），无任何 visuals/renders。对照 `render_rerender_only.py`（L72–134）在非 dry-run 下会真实 build_track + render_static_group + render_video + write_render_manifest 后再定哈希。
- **影响**：AB note 声称“复用 `snapshot_scientific_hashes` 语义：前后快照断言不变”，但 run_test_demo_viz 的该 flag 并不重渲染，科学断言为空谈；用户预期获得“重渲染不污染科学产物”的保证，实得 no-op。
- **建议**：要么在 `--rerender-only` 下真正调用 `render_rerender_only` 式流程（或直接复用 `render_rerender_only.py` 入口，仅把 `--forward-root/--plan/--item/--audio` 从 batch plan 推导），再做 before/after hash 断言；要么移除该 flag 并明确文档“batch 侧当前无 cache-only 重渲染”，避免误导。

---

## 各 Focus 判定

- **P1 #1 之外的点4**：见上 [P1]#2。
- **点1（U4 判定）— OK（含一处未覆盖观察）**：ffprobe 判定→仅当 `ok and not --skip-render` 才 `transcode_to_wav`，不可开记 `failed` 且不在渲染段跳过（skip in render loop，记入 failed_items）。dry-run 实测 3 个 mp4 全 `openable/stream_resolvable`，`failed_items=[]`。**观察**：3 个 mp4 均不在本 collection 的 plan 内 ⇒ `select_items` 不会把它们选进渲染 ⇒ “转码 WAV 作为 mp4 音轨” 分支在 `04_test_demo` 上**实际不执行**（只落在 `u4_results` 计划里）。逻辑上若未来 mp4 入 plan 会走通，但当前未被实际覆盖验证，建议后续在含 mp4 的 plan 上补一个 smoke。
- **点2（复用 WP2、无重 forward）— OK**：仅 import `visualization_controller` 的 builders/renderers；无模型 forward 路径。证据来自 `load_evidence_index` + `rows_from_decoder`（projector 层面）。
- **点3（collection-before-visualization）— OK（非 rerender 路径）**：`write_collection` + `write_analysis_complete`（L482–486）先于渲染循环（L491+）执行。仅 `--rerender-only` 提前 return（其本身是 P1#2）。
- **点5（family 扫描健壮性 / R-S -sparse）— 判定错误（见 [P1]#1）**：对 `-sparse` 掉链“健壮”是靠**全 index 全局扫 proposal_method** 换来的，代价是跨 item 污染；健壮≠正确。
- **点6（GT firewall）— OK**：渲染仅消费 frozen evidence；`write_collection` 只写 request/evidence 引用，无 GT 行。代码路径未读 evaluation/GT。
- **点7（dry-run 落盘）— OK**：`--skip-render` 实测只在 out-root 写 `test_demo_batch_plan.json`，**不**写 collection/analysis/renders，不转码。无污染。注意应向独立 out-root 输出（AB note 亦如此），避免与正式 run 同 root 混放。

---

## 测试状态（环境问题，非 WP10 代码问题）

- `tests/unit_realign` **无法在本会话跑绿**：`python -m pytest --version` 本身 segfault（exit 139，`faulthandler` trace 终止于 `_pytest/config` 插件加载 `pluggy` hook 阶段；`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 仍崩溃）。测试模块直连 import（`lyricalign.demo.track_view`、`tests.unit_realign.test_track_view`）均 OK。
- 结论：**segfault 属会话运行环境问题，与 WP10 commit（仅新增 runner 脚本）无关**；但本会话无法独立给出 `unit_realign` 全绿的验收。请在非沙箱/正常终端重新跑 `PYTHONPATH=src python -m pytest -q tests/unit_realign` 复核。
- 已将 `32` 个 test file 目录存在确认；未计通过数（pytest 无法启动）。

---

## MINOR（进 backlog，不阻塞）

1. `build_family_tracks` 中 `ru` 的 `... and request_ids and p`（p 恒真、request_ids 取外层 list）是无意义的残留条件，删除。
2. `--rerender-only` 分支 L366–369 的 `changed_after` 计算后未使用、不进输出，死代码。
3. U4 常量 hint（`_U4_MEDIA_CANDIDATES`）硬编码 `/home/hyan/...` 绝对路径（L90–98）——可作为配置/参数注入，避免跨机失效。
4. `--skip-render` 往 `--out-root` 写 plan JSON，若正式 run 同 root 会留下该文件；建议 dry-run 固定用独立 out-root 并在 README/AB 更显式声明。
5. README/AB note 建议把 U4 “3 mp4 不在 plan 故转码路径未实际执行”这一事实写清，避免误读为已覆盖。

---

## 结论

- **P0**：无。
- **P1**：#1 四路 family 跨 item 污染（数据一致性/渲染输出静默错误）；#2 `--rerender-only` 空操作（契约违反、断言空谈）。二者修后须回归：`build_family_tracks` 按 item 收敛后的 row/payload 计数，以及 `--rerender-only` 真实重渲染后 `scientific_hashes_unchanged` 为非空集合上的真断言。
- **MINOR**：5 项进 backlog。
- **环境**：pytest 启动 segfault，本会话无法跑绿 `unit_realign`；请在普通终端复核（与 WP10 代码无关）。
