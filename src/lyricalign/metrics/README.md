# Metrics

Current character-interval evaluation uses
`character_interval_metrics_v3_tolerant`.

Key rules:

- valid, invalid, and missing prediction states are disjoint;
- the primary metric is penalized per-song macro boundary MAE;
- valid-only MAE uses the exact valid set in both numerator and denominator;
- `character_coverage` is the valid-character rate;
- `song_coverage` means at least one valid prediction in the song;
- `complete_song_coverage` means every character in the song is valid.

See `docs/manual/metric_definitions.md` for the complete contract.
