# Inline Realign v4 changes — 2026-07-28

## Execution

- Added strict run/stage/item identity and output validation.
- Added item-level resume for model experiment, static visualization and Demo rendering.
- Split `analysis_complete.json` from `render_complete.json`.
- Added render-only, retry-failed, restart-item, from-stage and invalidate-stage entries.
- Fixed cleanup to remove per-item render directories and visual/render item states.

## Experiments

- Added 30/60-second fixed, silence-snap and strict-silence windows.
- Added reversible all-silence compression diagnostic branches.
- Replaced invalid asynchronous stable inputs with synchronized exact/−2/−4 crops and anchor-only control.
- Added under/exact/over text dosage trials.
- Changed production-shadow gate from strict anomaly decrease to anomaly nonincrease; retained strict decrease as control.
- Added zero-duration relaxed selection and exact/+2/+4 median fusion.
- Split oracle/automatic/manual/deferred shadow acceptance and actual writeback fields.
- Added raw nonnegative and minimal-monotonic decoder ablations.

## Metrics and visualization

- Made `character_interval_metrics_v3_tolerant` the canonical metric and aggregated over every GT reference unit.
- Added full discrete duration PMF including negative and zero durations.
- Added per-character rainbow timelines, reverse arrows, zero-duration markers, lane packing and branch-specific window plans.
- Added index-time lines, maximum-spread and heatmap inconsistency panels.
- Added Chinese mechanism pages for behavior, window comparison, realign summary, realign execution and decoder stages.

## Font

- Exact `Noto Sans CJK SC` resolution preserves the TTC face index and extracts that SC face for Matplotlib.
- JP fallback/substitution is rejected.
