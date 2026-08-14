# Visualization — REALIGN_RECOVERY

共享可视化工具与 WP10 Test Demo 批量封装。全部只读 frozen forward evidence，
**不运行 Qwen forward**、**不触碰 GT**，按 03 V4 顺序 `collection -> analysis_complete
-> static visualization -> MP4 encode` 输出。renderer 复用 `lyricalign.demo.*`，不重写。

## 模块

- `visualization_controller.py` — WP2 共享 controller：evidence 加载 / TrackView 投影 /
  render static + MP4 / collection / analysis_complete / render_manifest / scientific hash。
- `render_b4_vs_current.py` — V1 双路（B4 vs Current）。
- `render_current_4way.py` — V2 四路（Current / R-U / R-S [/ --fourth-family]）。
- `render_comparison_batch.py` — 逐 item 批量（items JSONL → twoway/fourway）。
- `render_rerender_only.py` — camera-only rerender（无 forward，scientific hash 断言）。
- `transcode_media_to_wav.py` — U4：把 soundfile 打不开的 mp4 转成 mono 16k f32 wav。
- `run_test_demo_viz.py` — **WP10** Test Demo 批量封装（中/粤/英/日代表 + hard-case + U4 判定）。

## 输出布局（03 V7）

```
<out>/
  collection/collection.json
  analysis_complete.json
  visuals/{group}/{item_slug}/full_timeline.png + pages/...
  renders/{group}/{item_slug}.mp4
  render_manifest.json
  test_demo_batch_plan.json / test_demo_batch_summary.json   (WP10)
  scientific_hash_before.json / scientific_hash_after.json    (rerender-only)
```

## WP10 批量用法

```bash
# dry-run（CPU 验收）：列代表 cases + U4 判定 + 写 render 计划，不渲染
PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
    --test-demo-root <test_demo> --out-root <run> \
    --languages zh,yue,en,ja --fourth-family R-CF \
    --media-root /home/hyan/Data/lyricalign/test --skip-render

# 真实批量（GPU formal 模板）
PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
    --test-demo-root <test_demo> --out-root <run> \
    --languages zh,yue,en,ja --fourth-family R-CF \
    --media-root /home/hyan/Data/lyricalign/test [--duration 3] [--page-seconds 30]

# camera-only rerender（无 forward，scientific hash 断言）
PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
    --test-demo-root <test_demo> --out-root <run> --rerender-only [--mode fourway]
```

参数：`--test-demo-root`（Test Demo collection 根，含
`TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl` + `forward/`）、`--out-root`、
`--languages zh,yue,en,ja`（代表 case）、`--fourth-family R-CF`（WP6 第四路）、
`--media-root`（源媒体，U4 ffprobe + 音轨）、`--skip-render`（只建计划）、`--rerender-only`。

## U4 判定

3 个已知 mp4（Side by Side / 祈愿花开 / 夜苏打）ffprobe 判定：有可读 audio stream →
`transcode_media_to_wav` 转 wav 作音轨并渲染；不可开 → 记 `failed` 并跳过。文件本身不损
坏（根因仅 soundfile 不支持 mp4），故一般判定为 `openable`。
