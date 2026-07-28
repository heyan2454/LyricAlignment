# Next Execution Plan

**Date:** 2026-07-28  
**Goal:** run the V3 long-range visual/detector/stable/deferred suite first as smoke and then formal, using all currently prepared Test Demo in formal and preserving compact, reviewable evidence.

## 0. Current research contract

Qwen Forced Aligner is treated as a strong short-range operator. The long-range
system must extend it through window planning, serial decoding, stable anchors,
detector signals and bounded local realign.

Demo participates throughout E1–E7. It is not only a final presentation set.
Demo has no built-in artificial human labels; every item receives a blank
`visuals/HUMAN_REVIEW.md` entry for optional notes or later AI-assisted review.

All stable/realign outputs remain shadow experiments. They generate full
alignments, figures and comparison videos but do not overwrite canonical B2.

## 1. Before running

```bash
cd /home/hyan/LyricAlignment
source scripts/demo/inline_realign_env.sh
validate_inline_realign_inputs
```

Confirm:

- complete Qwen snapshot and intended checkpoint;
- recursive Demo root containing every current 17+6+6+6 prepared song;
- same-stem lyrics and reusable prepared vocal for each Demo;
- Japanese `nagisa` in the actual execution environment;
- M4Singer labels/audio and MIR-1K materialization source;
- FFmpeg/FFprobe, Matplotlib and a CJK font such as `Noto Sans CJK SC`.

If reusing an old output root after overwriting the source tree:

```bash
bash scripts/demo/cleanup_inline_realign_overwrite.sh <OUT_ROOT> derived
```

This preserves matching baseline branch caches and removes summaries, figures,
videos and shadow results that must be regenerated. After the new manifest is
written, `stale` mode can remove item directories no longer in that manifest.
Use `all` only for a deliberately clean rerun.

## 2. Smoke one-click run

```bash
bash scripts/demo/run_inline_realign_smoke.sh
```

Smoke dynamically chooses one prepared Demo per discovered language and bounded
GT examples. It must exercise the complete pipeline:

```text
manifest
→ baseline/raw alignment and shadow experiments
→ all-item static visualizations
→ all selected Demo multi-way K-song and behavior videos
→ total + grouped summary
→ compact bounded evidence
```

Monitor in another terminal:

```bash
python scripts/demo/watch_inline_realign_status.py \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_smoke_v3_20260728
```

Smoke acceptance:

- every discovered language is represented;
- resolved configuration and frozen manifest exist;
- B0/B1/B2/B3 complete for every long-serial smoke item;
- S1/S2/S3 and R0/R1/R2/R3 artifacts are present or have explicit isolated failures;
- all selected Demo have main/stable/realign 2×2 K-song videos and a behavior video;
- visual pages, duration analysis and signed-error figures are produced;
- current-manifest item count equals summarized item count;
- stale directories are reported but excluded;
- compact evidence remains within the configured 8 MiB cap.

Do not start formal if videos are unreadable, CJK glyphs are missing, branch
identity is inconsistent, or the status page cannot identify the current item.

## 3. Formal one-click run

```bash
bash scripts/demo/run_inline_realign_formal.sh
```

Canonical formal policy:

- all discovered and prepared Demo, with no fixed current song-count contract;
- all natural/synthetic long-serial GT items run B0–B3;
- M4Singer native short clips run the primary branch and local diagnostics;
- MIR-1K held-out remains excluded unless explicitly enabled after rules freeze;
- all Demo generate the complete comparison-video set.

Monitor:

```bash
python scripts/demo/watch_inline_realign_status.py \
  /home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v3_20260728
```

The terminal also receives live tee output, while `live_status.json` and
`experiment_live_status.json` provide machine-readable stage/item/branch state.

## 4. Required experiment reading

### E1 — Raw / baseline / current visual audit

Use all-item timelines and all-Demo RAW/B0/B1/B2 videos to identify whether a
failure first appears in raw Qwen output, official decoding, window planning or
serial propagation. Report raw and each official branch with the same GT metric
schema where GT exists.

### E2 — Zero and short-duration pathology

Do not begin with a universal 20/40 ms threshold. Use zero rate, fine positive-
duration histograms, ECDF, percentiles, local median ratios and burst length.
Compare clean/error regions and raw/B0/B1/B2/realign stages.

### E3 — Detector capability

Overlay every detector component in GT figures and Demo behavior videos. Report
case/unit recall only on the same GT population. Precision is `null` when there
are no automatic positives. Separate automatic, GT-oracle and clean-control
reasons.

### E4 — Multi-scale inconsistency

Measure 30/60-second, exact/+2/+4, raw/official and cross-window-overlap boundary
dispersion. Determine whether inconsistency correlates with GT error and whether
it appears before zero-duration collapse. In Demo, inspect highlighted
inconsistent intervals for audible/visible jumps and recovery.

### E5 — Corrected stable-anchor comparison

Compare B2/S1/S2/S3 on GT and every Demo video:

- S1 includes the stable segment itself;
- S2 also retains left transcript overlap;
- S3 freezes the stable overlap during the shadow splice.

The old stable-cursor negative control must not be used as evidence against
these corrected designs.

### E6 — Immediate and deferred realign

Compare R0/R1/R2/R3 on GT and every Demo:

- R1: bounded immediate inline-realign shadow;
- R2: anchor-recovered deferred realign plus bounded final residual sweep;
- R3: R1 followed by R2 logic.

Current implementation is a reproducible full-trace shadow simulation for fair
comparison. It is not yet a production decoder that writes corrections into the
online cursor. Evaluate whether final sweep handles only a small residual set;
large final modifications imply insufficient online detection/recovery.

### E7 — Candidate selection and non-GT gate

For GT-oracle, automatic and clean-control candidates, report:

- `would_pass_non_gt_gate`;
- GT improvement/worsening where available;
- counterfactual false accept;
- exact/+2/+4 agreement;
- stable preservation and splice validity.

Clean controls remain ineligible for actual writeback, but their counterfactual
gate result must be measured.

## 5. Demo output contract

Every formal Demo must have:

```text
comparison_main_2x2.mp4     RAW / B0 / B1 / B2
comparison_stable_2x2.mp4   B2 / S1 / S2 / S3
comparison_realign_2x2.mp4  R0 / R1 / R2 / R3
behavior_current.mp4        B2 karaoke + current-window model behavior
```

No unpaired ordinary raw/baseline/current video is required. Optional human or
AI review belongs in `items/<item_id>/visuals/HUMAN_REVIEW.md` or a separate
project document; the pipeline does not require manual annotation.

## 6. Result and evidence policy

Primary reports must contain total and grouped results by:

- dataset;
- profile;
- language;
- alignment unit mode;
- duration bucket;
- variant.

GT results distinguish unit-micro and item-macro. Demo contributes structural,
behavioral and listening evidence, not invented accuracy.

The default evidence collector excludes media, complete alignments, weights and
full logs. It keeps resolved config, manifest identity, summaries, bounded cases,
status, visual/video indexes and experimental alignment summaries. If a later
review needs full data, collect only the named items separately instead of
inflating the canonical evidence archive.

## 7. Decision order after formal

1. Verify result identity, complete Demo coverage and visual readability.
2. Decide whether raw decoder, detector or realign is the dominant bottleneck.
3. Select the stable design only after GT and full-Demo paired comparison.
4. Decide whether multi-scale inconsistency belongs in detector.
5. Decide whether R1, R2 or R3 deserves an actual online writeback implementation.
6. Freeze detector/gate/range rules before any held-out MIR-1K run.

## 8. Still prohibited as a claimed production result

- automatic modification of canonical B2;
- claiming R1/R2/R3 are already integrated into the live serial cursor;
- whole-song Qwen realignment after the serial pass;
- treating Demo listening as GT metric;
- tuning on MIR-1K held-out;
- assuming a universal short-duration threshold before E2/E3 evidence.
