# Session: Qwen FA Follow-up Repair and Archive

**Date:** 2026-07-24  
**Scope:** repair known code/metric/identity defects, integrate completed follow-up evidence, and create a new canonical archive

## Inputs

- prior handoff archive `LyricAlignment_20260724_qwen_fa_followup_review_handoff.zip`;
- lightweight follow-up evidence package collected after successful completion;
- row-level metric recomputation package;
- completed missing-evaluation controller and logs;
- preserved overnight summary.

## Confirmed completed evaluations

All returned code `0`:

1. seed3407 R2 MIR-1K OOD;
2. seed20260724 terminal step1110 validation;
3. seed20260724 M4Singer sealed test;
4. seed20260724 MIR-1K OOD.

The seed20260724 checkpoint remained step750 after adding terminal step1110 to
the validation candidate set.

## Code changes

### Character metrics

`evaluate_tolerant` now uses metric schema
`character_interval_metrics_v3_tolerant`.

Changes:

- valid, invalid, and missing states are disjoint;
- zero-duration rows are invalid rather than simultaneously missing;
- valid-only MAE uses the exact valid count;
- structurally valid predictions with errors above one second remain in
  valid-only MAE;
- non-finite and negative-start intervals are invalid;
- character and song coverage semantics are explicit;
- complete-song coverage is reported.

### Training finalization

`run_qwen_fa_lora.py` now:

- records requested item limits separately from selected sample counts;
- writes `resolved_dataset_identity.json`;
- supports resume from historical execution-identity schema;
- evaluates terminal checkpoints when the final step is not a periodic
  evaluation step;
- writes `evaluation_step` and `evaluation_trigger`;
- includes terminal validation in validation-only best-checkpoint selection.

### Evaluation and orchestration

- fixed MIR-1K timestamp milliseconds/seconds conversion;
- added the consolidated missing-evaluation entry;
- added complete local model snapshot validation;
- added checkpoint step and metric schema to evaluation identity;
- added a deterministic metric recomputation utility.

## Recomputed results

Nineteen test/OOD/long-diagnostic result sets were recomputed from preserved
references and predictions. Every recomputation asserted that
`song_macro_boundary_mae_sec` stayed unchanged.

The correction materially changes interpretation of auxiliary fields:

- zero-duration rows are invalid but not missing;
- historical missing rates that duplicated invalid rates become zero where a
  malformed row was actually emitted;
- valid-only MAE increases where the previous denominator was too large;
- complete-song coverage exposes partial failures even when any-valid
  `song_coverage` is 1.0.

Original metrics remain available as historical evidence.

## Identity reconciliation

Historical seed2 `execution_identity.json` recorded `train_items=0` and
`validation_items=0`. Those values were requested limits meaning “use the full
split,” not actual counts.

A separate reconciliation record establishes:

- selected train items: 17,748;
- selected validation items: 1,711;
- completed optimizer steps: 1,110;
- seed: 20260724.

The original file was not rewritten.

## Long-context audit

The approximately 152.5-second R2 regression is dominated by one Tenor-6
`寻人启事` sequence. R2 becomes several seconds early over a contiguous region
around 120–140 seconds and later partially recovers.

Removing that item reduces R2 pooled penalized MAE from 115.085 ms to 64.534 ms;
R1 without the same item is 48.929 ms. The negative result therefore contains a
severe local collapse plus a smaller residual R2 disadvantage.

## Tests and validation

Added regression tests for:

- corrected valid-only denominator;
- disjoint invalid/missing states;
- duplicate-key behavior;
- non-finite and negative-start intervals;
- recomputation provenance;
- legacy execution-identity resume compatibility;
- terminal-validation code path and resolved data identity.

Final local validation:

- `python -m compileall -q src scripts tests`: passed;
- targeted tests: 26 passed;
- shell syntax: 7 scripts passed `bash -n`;
- full pytest collection is blocked by missing local `pypinyin` in three
  dataset/audio modules, not by a failing repaired-path assertion.

## Negative results and limitations

- the approximately 150-second failure remains unresolved at mechanism level;
- seed2 terminal-validation auxiliary metrics could not be recomputed without
  validation references;
- the exact seed3407 R2 M4Singer row-level recomputation input was not available;
- a second full R1 seed was not run, so cross-seed R2-minus-R1 variance remains
  unknown.

## Current decision

Do not expand LoRA scope yet. First run a controlled full-context versus
windowed evaluation on the dominant long-context outlier.
