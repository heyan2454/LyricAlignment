# Review: Qwen FA Follow-up, Long Diagnostics, and Seed2

**Date:** 2026-07-24  
**Reviewed inputs:** uploaded project archive and exact supplied `final_summary.json`  
**Evidence limit:** external run/checkpoint/prediction directories were not included.

## Overall verdict

The experimental chain executed successfully, but the uploaded package was not yet a complete final archive. It mixed a 2026-07-23 status snapshot with 2026-07-24 follow-up code and omitted final seed2/OOD lightweight evidence. Two auxiliary metrics also require code correction and recomputation.

## Findings by severity

### P0 — must resolve before formal result publication

1. Collect full R2 seed2 lightweight metric and identity files.
2. Collect final R2 MIR-1K OOD metrics and evaluation identity.
3. Repair and recompute `valid_only_boundary_mae_sec`.
4. redefine and recompute `song_coverage`.
5. identify the exact checkpoint step for every final evaluation.

### P1 — reproducibility and interpretation

1. Fix millisecond/second handling in the one-off OOD script.
2. strengthen evaluation/training completion identity checks.
3. require R2 adapter artifacts when declaring training complete.
4. validate reused derived MIR-1K labels against source hashes and quantization schema.
5. audit approximately 150-second R2 outliers before claiming long-duration behavior.

## Supported conclusions

Using the song-macro penalized boundary MAE, which is not directly affected by the two identified auxiliary-metric bugs:

- R1 projector-only is substantially better than raw on M4Singer test and MIR-1K OOD;
- R2 top-half LoRA improves over matched-budget R1 on validation, M4Singer test, and approximately 20–50-second diagnostic sets;
- the seed2 100-step primary-MAE direction supports another R2 seed;
- R2 has a strong negative result on the approximately 150-second diagnostic set relative to R1.

## Unsupported conclusions at archive time

- final R2 is better than R1 on MIR-1K OOD;
- full R2 stability has been demonstrated across two complete seeds;
- R2 works on true three-minute inputs;
- error increases monotonically with duration;
- existing valid-only MAE or song coverage values are correct.

## Decision

Archive the exact evidence and known defects now. Defer metric correction, missing-value collection, and regenerated consolidated reporting to the next session. Do not launch additional LoRA-layer experiments yet.
