# Project Current

**Snapshot date:** 2026-07-25  
**Stage:** first Qwen Forced Aligner LoRA cycle archived; focused 120s quick diagnostic and standalone demo code ready for server execution

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

## 2026-07-25 implementation status

Implemented but not yet executed on the GPU server:

- dense short-sample prefix-silence probe around 120 seconds;
- fixed-target trailing-silence probe for total-input-length effects;
- request-hash-aware resume and strict validation-best checkpoint resolution for the new quick entry;
- standalone 夜苏打 R0/R1/R2 × mix/vocal × full/windowed serial demo;
- Spleeter vocal preparation;
- 12 KTV videos, four three-way comparisons and three same-model four-way comparisons.

Execution guide:

```text
docs/manual/qwen_fa_120_quick_feedback_and_yessoda_demo.md
```

No new metric result or model conclusion should be inferred until the server outputs are returned.
