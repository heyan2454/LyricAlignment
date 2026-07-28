# Project Current

**Snapshot date:** 2026-07-28
**Stage:** multilingual Test Demo and complete inline-realign shadow suite implemented; server GPU smoke/formal evidence is next

## Completed experiment chain

```text
M4Singer weak-supervision preparation
-> Qwen FA R0 raw
-> matched-budget R1 projector-only
-> R2 projector + top-half audio-attention LoRA
-> M4Singer validation-only checkpoint selection
-> sealed M4Singer test
-> MIR-1K vocal-only OOD
-> approximately 22/33/48/152-second synthetic diagnostics
-> second full R2 seed
-> missing evaluation completion
-> metric/identity repair and archive
```

All required follow-up evaluations now have return code `0`:

- seed3407 R2 MIR-1K OOD;
- seed20260724 terminal step1110 validation;
- seed20260724 M4Singer sealed test;
- seed20260724 MIR-1K OOD.

## Primary results

Primary metric: `song_macro_boundary_mae_sec`, lower is better.

| Configuration | Validation | M4Singer test | MIR-1K OOD |
|---|---:|---:|---:|
| R0 raw | — | 251.391 ms | 97.108 ms |
| R1 projector-only, seed3407 | 55.649 ms | 90.775 ms | 44.007 ms |
| R2 audio LoRA, seed3407 | 46.734 ms | 79.590 ms | 42.557 ms |
| R2 audio LoRA, seed20260724 | 47.160 ms | 80.920 ms | 40.459 ms |

The second seed selected step 750 using M4Singer validation only. Terminal step1110 was explicitly evaluated at 48.412 ms and did not replace step750.

## Metric repair status

`character_interval_metrics_v3_tolerant` is now canonical.

Fixed:

- valid-only numerator and denominator use the same valid set;
- invalid and missing prediction states are disjoint;
- non-finite and negative-start intervals are invalid;
- `character_coverage` is explicit;
- `song_coverage` means at least one valid character;
- `complete_song_coverage` measures full-song validity.

Nineteen result sets were recomputed from preserved prediction/reference rows. The primary song-macro metric remained unchanged in every recomputation. Historical metric files are preserved and corrected files are stored separately.

Seed2 terminal-validation auxiliary fields were not recomputed because the supplied recomputation bundle did not include its validation reference rows. Its primary metric and checkpoint-selection role are verified.

## Identity and execution repair

Future training runs now:

- distinguish requested item limits from resolved sample counts;
- write `resolved_dataset_identity.json`;
- accept legacy execution identities during resume;
- automatically evaluate a terminal checkpoint that is not on an evaluation interval;
- record evaluation step and trigger;
- include terminal validation in validation-only best-checkpoint selection.

Historical seed2 identity is preserved and reconciled as:

```text
requested limit 0 = full frozen split
resolved train items = 17,748
resolved validation items = 1,711
```

## Long-context negative result

R2 remains better than R1 on approximately 22–48-second diagnostics, but worse on the approximately 152.5-second set.

The outlier audit shows that most of the R2 regression is caused by one Tenor-6 `寻人启事` sequence, with a multi-second early drift around 120–140 seconds. Removing this single item reduces R2 pooled penalized MAE from 115.085 ms to 64.534 ms; R1 without the same item is 48.929 ms. A smaller residual R2 disadvantage therefore remains.

Canonical audit:

```text
reports/audits/20260724_qwen_fa_long_b180_outlier_audit.md
```

## Current conclusion strength

Supported:

- projector adaptation supplies the majority of the gain;
- top-half audio-attention LoRA provides an additional matched-budget gain;
- R2 performance is stable across two complete R2 seeds on M4Singer test;
- both R2 seeds outperform R1 seed3407 on MIR-1K OOD;
- the training, resume, evaluation, and evidence path is operational.

Not yet supported:

- monotonic degradation with duration;
- robust full-song alignment at approximately 150 seconds and above;
- cross-seed stability of the R2-minus-R1 effect size, because a second full R1 seed was not run;
- attribution of the long-context collapse to attention length, repeated lyrics, timestamp classes, or synthetic concatenation.

## Canonical artifacts

```text
results/comparisons/20260724_qwen_fa_followup_final_summary.json
results/recomputed/20260724_character_metrics_v3/
reports/progress/20260724_qwen_fa_overnight_overall_summary.md
reports/audits/20260724_qwen_fa_long_b180_outlier_audit.md
docs/sessions/20260724_qwen_fa_followup_repair_archive.md
```

## 2026-07-26 demo implementation status

Completed and archived:

- strict Spleeter model-cache and two-stem quality gate;
- preservation of mix, vocals and accompaniment identities;
- full-song versus 03:05 cropped R2 windowed-vocal comparison;
- evidence that the 225-second collapse was amplified by candidate selection and cumulative monotonic repair;
- rejection of strict-core v2 after it supplied left acoustic overlap without matching overlap lyrics;
- `hard_core_forward_overlap_compression_v6` with 60-second adjacent cores and nominal left acoustic context always retained;
- immutable ownership by current-window start time, overlap lyrics as context only, and forward-only compression of new predictions against the previous committed end;
- full-overlap units may become zero-duration; original current-window times and compression diagnostics remain in alignment JSON;
- reusable same-stem batch entry defaulting to R2 + vocal + windowed;
- video rendering with a separate bottom subtitle band and audio-only black-background rendering;
- optional individual, three-model and four-input composite outputs;
- language-aware units for English words, Japanese Nagisa words, and Chinese/Cantonese CJK-character plus Latin-word mixtures;
- language/unit identity in alignment caches and language-specific default subtitle fonts.

Current reusable entry:

```text
scripts/demo/run_qwen_fa_batch.sh
```

Current detailed records:

```text
docs/manual/qwen_fa_batch_demo.md
docs/sessions/20260726_demo_exploration_archive.md
```

The new demo path has passed focused code, discovery, window-policy, separation-quality and FFmpeg rendering regressions. Actual multi-file GPU inference remains a server execution task. The qualitative improvement observed on 夜苏打 is not a formal metric result because corrected vocals, forced re-inference and the new window policy changed together.


## 2026-07-27 controlled demo-diagnostic package

Added without changing the v6 alignment policy:

- stage-separated `raw`, `processor_decoded`, `selected`, `final`, and
  `alignment.quality.json` artifacts;
- structural warning/failure status for timestamp regressions, candidate
  expansion, overlap compression and zero-duration units;
- consistent progress/failure artifacts for the historical fixed-song and tail
  entries;
- tail policy identity corrected to the implementation's current constant;
- render-only execution no longer resolves Spleeter or Demucs weights when the
  required cached audio exists;
- optional Demucs separator support in the reusable batch entry;
- deterministic MIR-1K 8-development / 4-held-out / 5-spare selection using
  data/GT descriptors only;
- MIR-1K separator preparation with cached identities and quality checks;
- independent oracle-window context/separator probes and current v6 serial
  evaluation against character GT;
- real-Processor equivalence audit for multilingual input preparation.

Canonical execution documents:

```text
docs/sessions/20260727_mir1k_demo_diagnostic_experiment.md
docs/manual/demucs_deployment.md
docs/status/next_execution_plan.md
```

Current limits:

- v6 still propagates transcript state from prior predictions and may convert
  severe overlap into zero-duration but structurally legal units;
- structural quality is not alignment accuracy;
- Demucs and multilingual behavior have not yet been executed on the server;
- MIR-1K is OOD test-only and its development subset cannot select a checkpoint.

## 2026-07-27 decoder × realign silence-aware Demo archive

Current development comparison is no longer the earlier raw-guarded baseline.
It now uses one shared raw-argmax serial planner and replays official/raw
timestamps on the same accepted windows, lyric slices, ownership, and cursor.
The four branches are O0/O1/R0/R1 = official/raw × realign off/on.

Windowing is planned once for the whole vocal stem:

- target core is 30 s;
- long leading silence is excluded from ownership but retained as a silence anchor;
- internal boundaries prefer nearby sustained silence;
- a short final core is merged if it has one predecessor, otherwise its duration
  is split equally across the two preceding windows;
- all detected silence intervals are saved in `window_plan.json` and can promote
  adjacent non-collapsed characters as realign anchors.

Focused tests pass, but real Qwen/R2 GPU inference for this archived state has
not yet been run.  No claim of qualitative improvement is made before the new
window plan and realign funnel are reviewed.

Canonical record:

```text
docs/sessions/20260727_realign_demo_silence_aware_window_archive.md
docs/manual/decoder_realign_comparison_demo.md
```

## 2026-07-27 inline-realign shadow / official baseline archive

The earlier shared-raw four-way Demo is retained as historical decoder evidence,
but it is no longer assumed to represent the best official production path.
The current executable follow-up adds:

- B0/B1/B2 official self-controlled 60 s fixed, 30 s fixed and 30 s
  silence-aware baselines;
- B3 shared raw control + official output as the controlled comparison;
- precommit collapse, tail-pileup and active-zero-progress shadow diagnostics;
- compact candidate-text expansion probes;
- stable *segments* without a hard two-window, character-count, line-count or
  time-span requirement;
- future-lookahead observations excluded from true repeated-context evidence;
- previous-window stable-suffix reproduction diagnostics;
- exact/+2 inline local inference in shadow mode within one or two adjacent
  windows;
- Demo, M4Singer validation and MIR-1K development manifest preparation;
- bounded evidence collection and one-click smoke/formal runners;
- official O0/O1 one-pass rendering, with raw 2x2 opt-in.

No automatic inline writeback, pending seam state, tail rollback or incomplete
output policy is enabled yet.  These remain gated on GT-backed smoke/formal
evidence.  Actual Qwen/R2 GPU smoke is still a server task; local code and
regression tests do not establish model-quality improvement.

Canonical records:

```text
docs/sessions/20260727_inline_realign_discussion_and_experiment_plan.md
docs/sessions/20260727_inline_realign_smoke_formal_archive.md
docs/manual/inline_realign_smoke_formal.md
```

## 2026-07-28 inline-realign follow-up implementation

The first inline formal run supported stable segments but did not exercise local
realign: old tail-pileup logic counted future lookahead near the full input end
and then marked the whole committed window as the anomaly. This often made the
target start at character zero and mechanically produced `no_left_stable_segment`.

The current follow-up implementation replaces that behavior with:

- localized spans for zero-duration runs, equal-boundary stacks, committed
  characters piled near the core end, and active-core zero progress;
- future lookahead excluded from realign tail-pileup triggers;
- GT-oracle error spans on M4Singer/MIR-1K so local-realign capability is tested
  even before the automatic detector is mature;
- stable segments actively proposing next-window transcript starts and safe
  commit cursors, followed by bounded active reruns when suggestions differ;
- forced +25%/+50% future-text experiments;
- raw/official planner divergence scans, with B3 run on official-primary items
  only when split decisions actually differ;
- clearly labelled constructed incomplete outputs that preserve only the
  resolved prefix instead of forcing the tail;
- the historical follow-up package used bounded Demo/M4 caps; this is superseded by
  the multilingual completion archive, where formal uses all discovered+prepared
  Test Demo songs and records current counts only as runtime metadata; held-out
  remains excluded;
- Demo required by the wrappers, all alignment completed before rendering, and
  a single `items/<id>/render/official.mp4` output per Demo;
- compact JSON/Markdown result summaries before bounded evidence collection.

Automatic local writeback and cross-window pending confirmation are still not
enabled. GT oracle, automatic candidates, stable-window assistance, synthetic
long audio, Demo listening, and constructed incomplete artifacts must remain
separate in interpretation.

Canonical records:

```text
docs/sessions/20260728_inline_realign_followup_experiments.md
docs/manual/inline_realign_smoke_formal.md
```

## 2026-07-28 multilingual Test Demo and complete shadow-suite archive

The follow-up evidence changed the main interpretation:

- fixed 30-second B1 can match fixed 60-second B0 on the observed Demo;
- silence-aware B2 can collapse when candidate text is expanded and immediately committed;
- B3 raw-controlled planning remains diagnostic-only;
- stable segments are reliable references but direct stable-cursor replacement is a negative result;
- GT-oracle local realign has demonstrated repair capability, while the automatic detector still needs formal recall/precision measurement;
- exact/+2 alone may reject useful repairs, so exact/+2/+4 2-of-3 consensus is now evaluated;
- no automatic writeback is enabled.

Current code now:

- discovers all prepared Test Demo songs for formal runs without hard-coding the current number per language;
- samples one item per discovered language for smoke;
- parses language per item and groups metrics by language and alignment-unit mode;
- fixes local-rerun `start_sec/end_sec` schema;
- isolates stable-window and expansion failures;
- evaluates detector-to-GT overlap, clean-control harm, three-context consensus,
  pending-confirmation shadow, severe-tail two-window rollback shadow,
  automatic incomplete shadow, historical R2 behavior, and M4Singer seam-near/far metrics;
- builds M4Singer synthetic-long buckets at 60/120/180 seconds under one total cap;
- supports central canonical outputs and optional adjacent/directory symlink views;
- still completes all alignments before rendering any Demo.

Canonical record:

```text
docs/sessions/20260728_multilingual_inline_realign_completion_archive.md
```

Production state remains unchanged: B2 official is the current experimental
primary branch; pending, rollback, incomplete replacement, and local writeback
are shadow-only until server GPU evidence supports them.

## 2026-07-28 long-range visual / detector / stable / deferred archive

Current implementation now treats Qwen Forced Aligner as a strong short-range
operator and studies how to extend it to full songs through global planning and
bounded local execution.

Implemented for the next server smoke/formal run:

- dynamic all-discovered multilingual Demo manifest with path-derived short IDs;
- B0/B1/B2 plus raw full-song comparison for every long-serial item;
- corrected stable-inclusive S1/S2/S3 full-song shadow alignments;
- R0/R1/R2/R3 no/immediate/deferred/combined realign shadow alignments;
- per-item timeline, signed-error, duration-distribution and inconsistency plots;
- every Demo receives main, stable and realign four-way K-song videos plus one
  behavior explanation video;
- YAML-backed one-click smoke/formal, resolved configuration and layered cache
  identity;
- manifest-bounded summary/evidence collection, grouped plus total metrics,
  clean-control counterfactual gate reporting and stale-item diagnostics;
- live terminal status and bounded compact evidence.

Canonical record:

```text
docs/sessions/20260728_long_range_visual_detector_stable_deferred_experiment_implementation.md
docs/manual/inline_realign_smoke_formal.md
```

The new suite has passed local static/focused tests and synthetic FFmpeg render
checks. Real Qwen GPU smoke/formal results are not included in this archive.
R1/R2/R3 remain shadow simulations over the complete serial trace; online
writeback into the production serial cursor is intentionally not claimed.

## 2026-07-28 Inline Realign v4 full mechanism implementation

The current executable suite supersedes the earlier v3 visual/stable/deferred implementation for new runs.

Key corrections and additions:

- strict run/stage/item/visual/render resume identity;
- analysis completion separated from slow video rendering;
- 30/60-second fixed, silence-snap and strict-silence windows;
- reversible all-silence-compression diagnostic branches;
- synchronized stable audio/text crops instead of the invalid asynchronous cursor experiment;
- under/exact/over text dosage trials;
- anomaly-nonincrease and zero-duration-relaxed shadow gates;
- exact/+2/+4 execution pages and median fusion;
- split oracle/automatic/manual/deferred acceptance fields;
- raw negative/nonnegative/minimal-monotonic decoder stages;
- canonical tolerant metrics over all GT reference characters;
- Chinese character-level PMF/timeline/inconsistency/behavior render suite;
- exact `Noto Sans CJK SC` TTC face handling without JP substitution.

All realign variants remain shadow-only. No production automatic writeback is enabled.

Canonical current records:

```text
docs/sessions/20260728_inline_realign_v4_full_implementation_archive.md
docs/experiments/20260728_inline_realign_full_mechanism_design.md
docs/manual/inline_realign_smoke_formal.md
docs/status/next_execution_plan.md
```

The source has focused local validation, but real Qwen GPU smoke/formal and full server rendering remain pending.
