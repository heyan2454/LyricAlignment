# Review: Qwen FA Follow-up Repair

**Date:** 2026-07-24

## Verdict

The first Qwen FA LoRA experiment cycle is now sufficiently complete for a
canonical project archive. Missing formal evaluations were recovered, primary
results are verified, known metric bugs are fixed with regression tests, and
corrected auxiliary metrics are versioned separately from original evidence.

## Primary result table

| Model | M4Singer test | MIR-1K OOD |
|---|---:|---:|
| R0 raw | 251.391 ms | 97.108 ms |
| R1 projector-only | 90.775 ms | 44.007 ms |
| R2 seed3407 | 79.590 ms | 42.557 ms |
| R2 seed20260724 | 80.920 ms | 40.459 ms |

The two complete R2 seeds agree closely on M4Singer test and both remain better
than R1 seed3407 on MIR-1K OOD.

## Repairs accepted

- MIR-1K derived-label schema and timestamp unit fixed;
- complete base-model snapshot preflight added;
- terminal validation included in checkpoint selection;
- execution identity distinguishes requested limits and selected counts;
- auxiliary metric semantics corrected and recomputed;
- archive hash generation made portable and self-consistent;
- long-context outlier analysis added.

## Evidence strength

Strong enough for:

- projector versus raw comparison;
- matched-budget R2 versus R1 seed3407 comparison;
- R2 reproducibility across two complete R2 seeds;
- reporting the approximately 150-second failure as a negative result.

Not strong enough for:

- claiming natural full-song robustness;
- claiming monotonic duration degradation;
- attributing the failure mechanism;
- claiming cross-seed stability of the R2-minus-R1 difference without a second
  full R1 run.

## Validation status

The repaired paths compile successfully; 26 targeted tests pass; all seven shell
entrypoints pass `bash -n`. Full local test collection is blocked only because
`pypinyin` is absent from the archive-building environment.

## Archive decision

Archive now. The next experimental action should be a small controlled long-
context diagnostic, not a larger training sweep.
