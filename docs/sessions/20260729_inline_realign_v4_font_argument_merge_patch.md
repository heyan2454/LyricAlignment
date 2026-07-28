# Inline realign v4 font and argument merge patch — 2026-07-29

## Purpose

Merge the omitted server startup hotfix into the newer full-timeline/video-page
implementation without reverting its later control-plane and visualization changes.

## Incorporated fixes

1. Low-level plotting APIs now resolve and register the exact `Noto Sans CJK SC`
   face themselves. Direct calls no longer depend on the outer visualization entry
   point and should not fall back to DejaVu Sans.
2. Negative text-dosage CSV values are forwarded as `--option=value`, preventing
   argparse from treating values such as `-8,-4,-2,0,2` as new options.

## Explicitly preserved newer behavior

- full-song static timeline output;
- paginated reusable video pages;
- no video-page generation under `RENDER_MODE=skip`;
- collapsed zero/negative-duration annotations;
- black indexed lyric labels;
- aligned inconsistency heatmap x-axis;
- experiment invalidation and `force+resume` control-plane fixes.

## Validation

The patch includes regression tests for exact SC registration, negative CSV parsing,
and preservation of the newer control/visual behavior.
