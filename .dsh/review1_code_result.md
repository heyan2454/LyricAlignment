# Review 1 — 代码正确性与实验契约审查(P0/P1)

范围:`batch_b4_dual.py`、`build_noncore_mech_regions.py`、`render_full_song.py`、
`visualization_controller.py`、`build_demo_rcf_regions.py`、`report_atlas_thresholds.py`
(全部在 commit `92ec378` HEAD 上;6 文件 `py_compile` 通过)。

对照 `03_VISUALIZATION_DESIGN_AND_ACCEPTANCE.md` 与 `04_EXECUTION_CONTRACT_AND_FREE_EXPLORATION.md`。

---

## P1 问题(MAJOR,可视化层缺陷;不影响科学数字,不 mislabel)

### P1-1 `render_full_song.py:237-238` — KTV 字幕条跟随 B4 而非 Current
`rows = tracks[0].get("rows")` 用第一条 lane 建 karaoke 带。
`batch_b4_dual.py:103` 与 `batch_final_4way.py` 的 V1 都把 `B4 历史pre-slot串行` 放在第一位,
因此 KTV 两行字幕高亮跟随 B4(冷/易漂)的时间戳,却叠在原曲 MP4 音轨上 → 字幕与真实演唱对不上。
03 §3.3 要求"字符高亮与当前播放时间一致",B4 恰恰不是 playback-truth。建议:从
`label.startswith("Current")`(或最后一条 full-song lane)取行建 KTV,而非总是 tracks[0]。

### P1-2 `render_full_song.py:189` — `--fourth-family` 对 R-CF 会误抛 SystemExit
R-CF 证据从不落主 `forward_root`(已核对 test-demo evidence 只有 R-U×118 / R-S×115,
R-CF 各活独立 `rcf_evidence_root` 且 request 无 item_id),故 `--fourth-family R-CF` 在主
evidence 里永远搜不到 → 提前 `raise SystemExit` 而到不了下面的 `rcf_evidence_root` glob 块。
当前无 in-scope 调用者同时传两者(4way 批次只用 `--rcf-evidence-root`),属潜在陷阱。建议:
要么说明两者互斥,要么仅当 `rcf_evidence_root` 也缺时才 raise。

---

## 已核对无 P0/P1(契约/科学边界 OK)

- **B4 vs Current 公平性**:`batch_b4_dual.py` 用同一 R2 step-000750(`CKPT`)与 R1 step-000100,
  同 song/audio/mix/vocals、同 lyrics txt、同 official decoder;B4 由 `align_qwen_fa_serial_demo.py`
  (真 pre-slot/occurrence-aware serial)产出,默认参数与 03 V1 冻结配置一致
  (60/10/10、silence-aware、skip-silent、compress/strict 默认 off、0.8/1.5/18/12/6/2 等)。
- **机制打标**:R-U/R-S 在主 evidence、R-CF 在独立 root,`proposal_method` 与 lane label 一致
  ("R-CF" 文件名/字段真实),非 mislabel。
- **region 构建合法输入**:`build_noncore_mech_regions.py`/`build_demo_rcf_regions.py` 只用
  Current full-song alignment 自身 zero/overlap 异常字符做 detector-unsafe 目标,
  打 `detector_state=UNSAFE`、`seed_kind=anomaly_region/unsafe_region`,不读 GT;realign 为
  shadow-only,不构成 train/eval 污染。
- **report_atlas_thresholds**:atlas 行确含 `best_{mech}_{b}ms`(bool)键与
  `best_achievable_ms`,`is not None`/`sum(r.get())` 计数正确;no-GT note 明确不宣称最终恢复类。
- **R-U/R-S/R-CF lane 全局坐标**:evidence 行带 `official_fixed_global_*`,
  `rows_from_decoder` 用 `canonical_ids`/`text_units` 反解到全局 gci,时间在全局轴。
- **依赖接线**:证据目录、`TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl`、`RCF` 路径、B4 输出
  `alignments/r2/vocal/windowed/alignment.json` 均与生产者一致;合成文件可编译。

## MINOR(进 backlog,不阻塞)
- `build_demo_rcf_regions.py:111-114` 第一段 `win_chars` 参数序反(`end,start`),被 116-119 覆盖,死代码。
- `batch_b4_dual.py:104` / `batch_final_4way.py` label 前缀 `" Current"` 带前导空格(cosmetic)。
- `report_atlas_thresholds.py:53` `dict(Counter)` 序列化 None 键为 `"None"`(诚实,但可改用 `r.get(k) or 0`)。
- `render_full_song.py:161` 提案_method 匹配依赖 `item_id`;R-CF 无 item_id 仅靠文件名 glob 关联,脆弱但当前生效。

## 客观范围与关键产物
- 验证读取:srcdir 6 脚本 + `track_view.py` + 实际 run 数据
  `/home/hyan/Data/lyricalign/runs/{unit_realign_test_demo_formal_20260813/04_test_demo/forward/evidence,
  20260814_rcf_demo/E4_demo_rcf/forward/evidence,20260814_viz_B4}` 与
  `20260814_wp9_E6_atlas_real/01_atlas/ATLAS.jsonl`。
- 结论:无 P0;2 个 P1(均为可视化投影层,不影响任何科学指标/打标)。
