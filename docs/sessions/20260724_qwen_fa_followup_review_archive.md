# Qwen FA Follow-up Review and Handoff Archive

**Date:** 2026-07-24  
**Archive role:** preserve confirmed execution results and review findings; defer metric correction and missing-value collection to the next session.

## 1. What completed

The detached pipeline completed with return code `0`. The supplied evidence supports completion of:

- R0 raw evaluation on frozen M4Singer test and MIR-1K OOD;
- full R1 projector-only matched-budget training at seed 3407;
- full R1 M4Singer test and MIR-1K OOD;
- synthetic-long diagnostics for nominal 20/30/60/180-second buckets;
- paired 100-step seed2 R1/R2 validation pilots;
- a validation-only decision recommending full R2 seed2;
- full R2 seed `20260724`, according to the user-provided pipeline completion event.

The full seed2 metric files are not inside this uploaded archive, so only execution completion—not the final metric values—is archived as user-provided evidence.

## 2. Preserved result evidence

The exact supplied summary is preserved without modification at:

```text
results/comparisons/20260724_qwen_fa_followup_final_summary.provisional.json
```

SHA-256:

```text
a6d27c73115fd9b9e0c0799e4f11d2be82697063735a0735548862489ac42171
```

It is marked `provisional` because two auxiliary metric implementations are confirmed incorrect and because final R2 OOD/full seed2 values are missing from it.

### Main result direction supported by unaffected primary metrics

M4Singer frozen test song-macro penalized boundary MAE:

| Configuration | Value |
|---|---:|
| R0 raw | 251.391 ms |
| full R1 projector-only | 90.775 ms |
| full R2 top-half audio LoRA | 79.590 ms |

This supports:

- projector-only supplies the largest adaptation gain;
- top-half audio LoRA supplies an additional improvement over matched-budget R1 for seed 3407.

MIR-1K OOD in the supplied summary:

| Configuration | Value |
|---|---:|
| R0 raw | 97.108 ms |
| full R1 projector-only | 44.007 ms |
| full R2 | missing from supplied summary |

### Second-seed gate

The paired 100-step validation-only pilot used seed `20260724` and recommended full R2:

- R1: 124.628 ms;
- R2: 68.898 ms;
- absolute improvement: 55.729 ms;
- relative improvement: 44.716%;
- invalid-rate and coverage gates passed according to the then-current metric implementation.

The primary MAE gate is useful evidence. Auxiliary invalid/coverage criteria must be revisited after metric repair.

## 3. Synthetic-long result and negative result

For the approximately 20–50-second diagnostic sets, R2 is better than R1 on song-macro penalized boundary MAE. For the approximately 150-second set, R2 is worse:

| Actual mean duration | R1 | R2 |
|---:|---:|---:|
| 22.350 s | 74.180 ms | 59.255 ms |
| 33.052 s | 75.258 ms | 54.019 ms |
| 48.120 s | 92.549 ms | 72.068 ms |
| 152.500 s | **51.831 ms** | **102.825 ms** |

After excluding characters within 0.5 seconds of joins on the longest set:

- R1: 46.215 ms;
- R2: 90.923 ms.

Interpretation strength:

- valid as a same-set R1/R2 warning signal;
- not sufficient to claim monotonic length degradation;
- the longest set has only six songs and is not an exact 180-second test;
- likely heavy-tail/outlier behavior because medians and p90 remain much smaller than the means.

## 4. Confirmed defects and missing evidence

The canonical issue list is:

```text
docs/status/known_issues_20260724.md
```

Highest-priority items:

- incorrect denominator for `valid_only_boundary_mae_sec`;
- non-informative `song_coverage` implementation;
- absent full seed2 lightweight metrics/identity in the archive;
- absent final R2 MIR-1K OOD metrics/identity in the supplied summary;
- ambiguity between step-1000 periodic evaluation and step-1110 training completion;
- stale millisecond/second assumption in the one-off OOD recovery script;
- completion checks that do not fully validate adapter and evaluation identity.

## 5. Reproducibility and dependencies

Known external dependencies remain outside the archive:

- model cache under `/home/hyan/Data/lyricalign/models/hf_cache`;
- M4Singer/MIR-1K audio and derived labels under `/home/hyan/Data/lyricalign` and dataset roots;
- checkpoints, predictions, and large logs under external run directories;
- Conda environment `lyricalign-qwen`.

The archive preserves code, configuration, lightweight summaries, paths, hashes when available, and explicit evidence boundaries. It does not claim independent verification of external checkpoint bodies.

## 6. AI collaboration and negative-results record

Confirmed workflow mistakes from this stage:

1. the first OOD finalizer passed a raw MIR-1K manifest to a collator expecting derived `timestamp_class_ids`;
2. the first follow-up smoke compared an 80-millisecond processor field directly with `0.08` seconds;
3. archive/report synchronization lagged behind successful server execution;
4. unit tests did not cover the valid-only denominator, prediction-based song coverage, or final evaluation-step identity.

These are retained as engineering negative results. The next session should add tests before recalculation rather than patching only the observed outputs.

## 7. Next-session handoff

Read in this order:

1. `docs/status/project_current.md`;
2. `docs/status/known_issues_20260724.md`;
3. this session record;
4. the provisional exact summary JSON;
5. `docs/status/next_execution_plan.md`.

Do not start new LoRA layer-location experiments until the current evidence is repaired and consolidated.
