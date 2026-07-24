# Qwen FA Follow-up Issue Status

**Updated:** 2026-07-24  
**Rule:** original evidence files remain unchanged; repairs are versioned and traceable.

## Resolved in this archive

### Missing evaluations and evidence

Resolved with return code `0`:

- seed3407 full R2 MIR-1K OOD;
- seed20260724 terminal step1110 validation;
- seed20260724 M4Singer sealed test;
- seed20260724 MIR-1K OOD.

### MIR-1K label schema

The evaluator must receive derived Qwen FA labels containing
`timestamp_class_ids`, not the raw MIR-1K manifest. The fixed entry verifies
source hashes, deterministic label reconstruction, class count, and output hash.

### Timestamp unit

`processor.timestamp_segment_time` is normalized from milliseconds to seconds
before comparison with `0.08` seconds.

### Base-model cache completeness

The consolidated evaluation entry checks that the pinned local snapshot contains
a readable `model.safetensors`; it resolves a complete snapshot or downloads the
fixed revision before switching to offline evaluation.

### Auxiliary metrics

Fixed in `character_interval_metrics_v3_tolerant`:

- `valid_only_boundary_mae_sec` denominator;
- disjoint valid/invalid/missing states;
- prediction-based `song_coverage`;
- explicit `complete_song_coverage`;
- non-finite and negative-start handling.

Nineteen result sets were recomputed from row-level evidence. Their primary
song-macro MAE values did not change.

### Terminal checkpoint selection

Future runs explicitly evaluate a terminal step not divisible by `eval_steps`,
record its trigger, and include it in validation-only checkpoint selection.

### Execution identity counts

Future runs separate requested limits from resolved sample counts and write a
resolved dataset identity. Historical seed2 files are preserved with a separate
reconciliation record.

## Partially resolved

### Seed2 terminal-validation auxiliary metrics

The terminal step1110 primary metric is verified, but its corrected auxiliary
metrics could not be recomputed because the supplied bundle did not include the
validation reference rows. This does not affect the selected step750 checkpoint
or the primary comparison.

### Seed3407 M4Singer sealed-test auxiliary metrics

The historical v2 metric file and primary result are preserved. A dedicated
row-level recomputation input for this exact run was not supplied in the final
follow-up bundle, so the archive does not silently substitute another run's
auxiliary fields.

## Open research issue

### Approximately 150-second failure

The regression is dominated by one late-sequence collapse but is not entirely
removed with that item excluded. The next high-value test is a controlled
full-context versus overlapping-window comparison on the dominant sequence.

## Optional, not blocking this archive

- run a complete R1 seed20260724 only if the R2-minus-R1 effect size must be
  demonstrated across seeds;
- export validation references and recompute seed2 terminal auxiliary metrics;
- extend long-context testing to natural full songs rather than only synthetic
  concatenations.
