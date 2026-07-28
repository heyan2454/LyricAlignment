# Patch Notes — 2026-07-29 timeline layout + render fps fix

This patch fixes two issues relative to the latest full package:
`LyricAlignment_20260728_v4_visual_fulltimeline_video_pages.zip`

## Fixed issues

### 1) Render failure: missing `fps` in `VideoGeometry`
Fixed `src/lyricalign/demo/timeline_video.py` so karaoke-enabled page-video rendering
constructs `VideoGeometry(..., fps=...)` correctly.

This resolves errors like:

```text
TypeError: VideoGeometry.__init__() missing 1 required positional argument: 'fps'
```

### 2) Static timeline layout revised
Updated `scripts/demo/analyze_inline_realign_visuals.py` so static timeline images:

- render as a single whole-song figure per group,
- use a much wider horizontal canvas,
- write directly to flat files such as:
  - `visuals/timeline_decoder.png`
  - `visuals/timeline_window_core.png`
  - `visuals/timeline_stable.png`
- no longer create dedicated static timeline subfolders with `full_timeline.png`.

Video reuse pages under `visuals/video_pages/...` remain paginated and unchanged.

## Included test updates

- updated `tests/test_inline_realign_full_timeline_patch_20260728.py`
- added `tests/test_inline_realign_render_fps_patch_20260729.py`

## Validation performed

- `python -m compileall -q src scripts tests`
- shell syntax check for `scripts/**/*.sh`
- targeted regression:

```bash
PYTHONPATH=src pytest -q \
  tests/test_inline_realign_v4_full_mechanism.py \
  tests/test_inline_realign_control_plane_visual_patch_20260728.py \
  tests/test_inline_realign_patch_20260728.py \
  tests/test_inline_realign_pipeline.py \
  tests/test_inline_realign_full_timeline_patch_20260728.py \
  tests/test_inline_realign_render_fps_patch_20260729.py
```

Result: `70 passed`

## After applying

Because static visualization output paths change, rerun visualization and render for an existing run root.
Recommended:

```bash
OUT_ROOT="$SMOKE_ROOT" \
RESUME=1 \
FROM_STAGE=visualization \
INVALIDATE_STAGE=visualization,collection,render \
RENDER_MODE=after \
bash scripts/demo/run_inline_realign_smoke.sh
```
