# Next Execution Plan

**Date:** 2026-07-28  
**Goal:** validate and execute Inline Realign v4 full mechanism suite with strict resume, large inference coverage and postposed rendering.

## 1. Source deployment

The archive root is `LyricAlignment/` and can be extracted directly over:

```text
/home/hyan/LyricAlignment
```

No source file must be deleted before overlay. Old v3 result directories are not compatible with v4 run identity. Use the new v4 default roots, or delete an old result root completely:

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh OLD_OUT_ROOT all
```

Do not clean an interrupted v4 run that should be resumed.

## 2. Preflight

```bash
cd /home/hyan/LyricAlignment
bash scripts/demo/verify_inline_realign_v4.sh
```

Required result:

```text
VERIFY_OK: Inline Realign v4 implementation and exact SC font face are ready.
```

The font report must show `Noto Sans CJK SC` for both fontconfig and Matplotlib. JP substitution is a failure.

## 3. Smoke: analysis first

```bash
cd /home/hyan/LyricAlignment
RENDER_MODE=skip bash scripts/demo/run_inline_realign_smoke.sh
```

Default root:

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728
```

Monitor:

```bash
/root/autodl-tmp/AST_storage/conda/envs/lyricalign-qwen/bin/python \
  scripts/demo/watch_inline_realign_status.py \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728
```

Smoke analysis acceptance:

- `analysis_complete.json` status is `complete`;
- experiment, visualization and evidence failure counts are zero;
- every configured variant is recognized;
- all expected S0–S3, R1–R4, D0–D6 and text-dosage artifacts exist for eligible items;
- canonical metric schema is `character_interval_metrics_v3_tolerant`;
- `actual_writeback` remains zero;
- representative static figures contain Chinese characters, negative/zero durations and realign execution pages;
- no item is silently marked complete while an expected artifact is missing.

## 4. Smoke render

```bash
bash scripts/demo/run_inline_realign_render_only.sh \
  smoke \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728
```

Each Demo must have five videos. Check at least:

- one high-speed Chinese case;
- one Japanese high-zero-duration case;
- one English collapse case;
- one Cantonese case;
- one clean control;
- one exact/+2/+4 disagreement case;
- one deferred case.

Do not start formal if the fixed-scale pointer, window boundaries, stable candidates or realign execution cannot be understood visually.

## 5. Resume

Interrupted analysis:

```bash
OUT_ROOT=/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728 \
RESUME=1 RENDER_MODE=skip \
  bash scripts/demo/run_inline_realign_smoke.sh
```

Interrupted rendering:

```bash
bash scripts/demo/run_inline_realign_render_only.sh \
  smoke \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v4_full_20260728
```

Retry failed items only:

```bash
OUT_ROOT=... RESUME=1 RETRY_FAILED_ONLY=1 RENDER_MODE=skip \
  bash scripts/demo/run_inline_realign_smoke.sh
```

Restart explicit items:

```bash
OUT_ROOT=... RESUME=1 RESTART_ITEM='ITEM_A,ITEM_B' RENDER_MODE=skip \
  bash scripts/demo/run_inline_realign_smoke.sh
```

If run identity differs, resume must fail. Use a new root rather than bypassing the identity gate.

## 6. Formal analysis

After smoke acceptance:

```bash
cd /home/hyan/LyricAlignment
RENDER_MODE=skip nohup bash scripts/demo/run_inline_realign_formal.sh \
  > /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728.launcher.log \
  2>&1 &
```

Default root:

```text
/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728
```

Formal uses all discovered prepared Demo, MIR-1K roles under cap 17, M4Singer native under cap 32 and synthetic-long under cap 18 across 60/120/180 seconds. Current counts are metadata, not fixed contracts.

## 7. Formal render

After `analysis_complete.json` exists:

```bash
nohup bash scripts/demo/run_inline_realign_render_only.sh \
  formal \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728 \
  > /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v4_full_20260728.render.log \
  2>&1 &
```

Rendering is post-analysis. A render failure must set render status to failed but must not invalidate completed model and metric evidence.

## 8. Reading order

1. Input audit and resolved config;
2. branch/canonical metric summary;
3. decoder stage D0–D6;
4. duration PMF and inconsistency figures;
5. window/core/silence comparison;
6. text dosage under/exact/over;
7. synchronized stable S0–S3;
8. immediate/deferred realign gates and clean controls;
9. Demo behavior and execution videos.

Automatic detector metrics are secondary. Main realign evidence comes from GT-oracle, manual Demo cases, explicit zero-duration candidates and clean controls.

## 9. Evidence handoff

Default compact evidence is bounded and excludes audio, video, model weights, full logs and full alignments. If deeper analysis needs large logits, full window traces or all alignments, create a separate targeted collector rather than enlarging the routine handoff archive.
