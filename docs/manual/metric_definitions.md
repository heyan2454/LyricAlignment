# Metric Definitions

## 1. Character alignment input

Each reference and prediction row uses:

```text
item_id
song_id
character_index
normalized_character
start_sec
end_sec
```

Reference rows must have unique keys and finite intervals satisfying
`0 <= start_sec < end_sec`. Reference identity errors are hard failures.

## 2. Prediction states

The tolerant evaluator assigns every reference character to exactly one state:

- **valid**: exactly one prediction row exists and its interval is finite with
  `0 <= start_sec < end_sec`;
- **invalid**: a prediction row exists, but the key is duplicated or its
  interval is malformed, zero-duration, negative-duration, non-finite, or
  starts before zero;
- **missing**: no prediction row exists for the reference key.

These sets are disjoint. Therefore:

```text
valid_prediction_count
+ invalid_prediction_count
+ missing_prediction_count
= character_count
```

`unusable_prediction_count` is the union of invalid and missing output.

## 3. Boundary errors

For valid output:

```text
onset_abs_error = abs(pred_start - gt_start)
offset_abs_error = abs(pred_end - gt_end)
boundary_error = (onset_abs_error + offset_abs_error) / 2
```

For invalid or missing output, both onset and offset receive a transparent
penalty:

```text
max(1.0 second, reference interval duration)
```

The fixed penalty is part of the metric schema and must not be changed between
models in the same comparison.

## 4. Primary metric

```text
song_macro_boundary_mae_sec
```

First average penalized character boundary error within each song, then average
songs equally. Lower is better. This is the checkpoint-selection and primary
comparison metric for the current Qwen FA experiments.

## 5. Auxiliary metrics

- `all_item_penalized_boundary_mae_sec`: pooled average over all reference
  characters, including invalid/missing penalties;
- `valid_only_boundary_mae_sec`: average over the exact valid-prediction set;
  predictions with errors above one second remain included if their intervals
  are structurally valid;
- onset/offset mean, median, and p90;
- interval IoU;
- joint boundary accuracy at 80/160/240 ms;
- invalid, missing, unusable, zero-duration, negative-duration, and non-finite
  rates.

## 6. Coverage

```text
character_coverage = valid_prediction_count / character_count
```

`item_coverage` is retained only as a backward-compatible alias of
`character_coverage`.

```text
song_coverage
```

is the fraction of reference songs containing at least one valid prediction.
It can legitimately be 1.0 even when some characters are unusable.

```text
complete_song_coverage
```

is the fraction of songs for which every reference character has a valid
prediction. This is the stricter song-level completeness measure.

## 7. Aggregation discipline

Always report:

- metric schema version;
- character and song counts;
- primary song-macro metric;
- pooled penalized metric;
- valid-only metric;
- character coverage and complete-song coverage;
- invalid and missing rates separately.

Long songs must not silently dominate a song-macro comparison. Synthetic
concatenations are diagnostics, not independent natural-song benchmarks.

## 8. Recalculation

Historical `character_interval_metrics_v2_tolerant` files are preserved as
original evidence. Corrected auxiliary metrics are generated from preserved
reference and prediction rows with:

```bash
python scripts/evaluation/recompute_character_metrics.py \
  --references references.filtered.jsonl \
  --predictions predictions.jsonl \
  --original-metrics metrics.original.json \
  --out metrics.corrected.json
```

The tool verifies that correction of prediction-state semantics does not change
`song_macro_boundary_mae_sec`.
