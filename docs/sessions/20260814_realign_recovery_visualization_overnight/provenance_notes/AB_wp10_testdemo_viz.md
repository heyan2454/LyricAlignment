# WP10 — Test Demo 可视化批量封装（E8/E9 Test Demo batch）

## 目标 / 依据

把已实现的 double-way（B4-vs-Current）与 four-way（Current/R-U/R-S[/R-CF→WP6 四路]）
可视化批量扩展到 Test Demo（中/粤/英/日 代表 cases + hard-case mp4）。复用 WP2 共享
controller（`visualization_controller.py`），**不重写 renderer、不重复 Qwen forward**，
约束：collection-before-visualization、rerender cache-only、GT 不进渲染。

- 03 V1/V2（track 冻结）、V6（smoke/formal 顺序）、V7（输出布局）
- 07 plan §9 WP10

## 交付

- `scripts/realign_recovery/visualization/run_test_demo_viz.py` — 批量封装
- `scripts/realign_recovery/visualization/README.md` — 使用说明

## 批量封装要点

- CLI：`--test-demo-root` / `--out-root` / `--languages zh,yue,en,ja`（代表 case 选择）/
  `--fourth-family R-CF`（WP6 第四路，缺 evidence 时按 `render_current_4way` 语义走 3 路）
  / `--media-root` / `--skip-render`（dry-run，只建清单不渲染）/ `--rerender-only` / `--mode` / `--duration`。
- 代表 case 选择：`REPRESENTATIVES = {zh: Chinese/此处通往天空.mp3, yue: Cantonese/浮夸.mp3,
  en: English/Past Lives.mp3, ja: Japanese/乙女解剖.mp3}`；plan 里缺代表时回退为该语言首个 item。
- U4 判定：对 3 个已知 mp4（Side by Side.mp4 / 祈愿花开.mp4 / 夜苏打.mp4）ffprobe 判定，
  有可读 audio stream → `transcode_media_to_wav` 转 wav 作音轨并补进渲染；不可开 → 记 `failed`
  跳过。dry-run 也跑 ffprobe（只判不开），从而报告 openability。
- 四路 family 解析直接扫 evidence index 的 `proposal_method`（R-U / R-S / fourth），
  对 R-S 的 `-sparse` request_id 与 plan request_id 不同的事实健壮（`render_current_4way` 的
  fourth-family 也这样扫全 index）。
- camera-only rerender 复用 `snapshot_scientific_hashes` 语义：前后快照断言不变。

## U4 判定结果（CPU dry-run）

| item | ffprobe 判定 |
|---|---|
| `Side by Side.mp4` | `openable` / stream_resolvable（有可读 audio stream）|
| `祈愿花开.mp4` | `openable` / stream_resolvable |
| `夜苏打.mp4` | `openable` / stream_resolvable（`demo_diagnostics/inline_realign_formal_v2_20260728/items/demo_夜苏打/render/official.mp4`）|

与 `transcode_media_to_wav.py` 记录一致：文件并非损坏，根因仅是 soundfile 不支持 mp4 容器；
ffprobe 判定全部可开，故 `failed_items = []`。若某个文件 ffprobe 解析不到 audio stream，
会进入 `failed` 分支。

## Dry-run 输出（`--skip-render`）

测试根：`runs/unit_realign_test_demo_formal_20260813/04_test_demo`
输出：`/home/hyan/Data/lyricalign/runs/run_test_demo_viz_dryrun_20260814/`

- `test_demo_batch_plan.json`
- 列出 4 个代表 cases（zh/此处通往天空、yue/浮夸、en/Past Lives、ja/乙女解剖）
- u4_probe：3 个 mp4 全 `openable`
- failed_items：`[]`
- planned_groups：4

## Smoke（CPU，复用 WP2 已验证流程）

输出：`/home/hyan/Data/lyricalign/runs/run_test_demo_viz_smoke_20260814/`
命令：`--languages zh --fourth-family R-CF --mode fourway --duration 3`

- `build_family_tracks`（zh item）：Current baseline / R-U / R-S（各 470 rows；R-CF 无
  evidence 不作 silent 4 路，回 3 路正确）
- `two_way_tracks`：B4 / Current（8 rows）
- 产出 V7 布局：`collection/collection.json`、`analysis_complete.json`、
  `visuals/current_realign_4way/....png`、`renders/current_realign_4way/此处通往天空.mp4`（36K 3s）、
  `render_manifest.json`、`test_demo_batch_plan/summary.json`
- collection-before-visualization 与 4-way 逐条断言通过

## GPU formal 批量模板

```bash
PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
    --test-demo-root <test_demo> --out-root <run> \
    --languages zh,yue,en,ja --fourth-family R-CF \
    --media-root /home/hyan/Data/lyricalign/test
```
每代表/lang 出 double-way + four-way MP4；3 个 mp4 hard-case 自动 U4 转码补进；不可开记
`failed`。formal 前先 `--skip-render` 核对清单；渲染需 GPU/ffmpeg，本批次未跑全量多语言
（CPU 验收只要求 dry-run + 可选 3s 双路 smoke，本报告做了 fourway 3s smoke）。

## 遗留 / TODO

- `--skip-render` 目前代表 case 选择只覆盖 zh/yue/en/ja；若需 hard-case（catastrophic /
  serial drift / repeat / window-boundary）细分到具体 item，可给 `--items-jsonl` 显式覆盖
  （当前 run_test_demo_viz.py 未加该参数，后续按 render_comparison_batch 的 items JSONL 语义补）。
- 3 个 mp4 在本 formal run 的 plan 里不在场，故 U4 通过常量 hint 路径直接探测；formal 若把
  mp4 item 纳入 plan，则走 `selected` 内联探测，结果一致。
- 若跑真实多语言全量，建议每语言抽查 1 个渲染后再放量（对齐 03 V6 smoke→formal 顺序）。
