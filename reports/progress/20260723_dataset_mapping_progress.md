# Dataset Mapping Progress Report

**Date:** 2026-07-23  
**Scope:** M4Singer rule mapping and MIR-1K vocal-only OOD preparation

## Progress summary

M4Singer processing has moved from the early cardinality gate to a pinyin/held-vowel rule pass covering the full 20,896 source records. The current operational canonical contains 20,298 `rule_validated` candidates, 598 review records and no hard rejection or processing failure. The candidate label is deliberately weaker than “manually confirmed high-confidence”.

MIR-1K channel index 1 has been manually confirmed as vocal and explicitly extracted for the 17-song, 2,035-character OOD test-only subset.

## Canonical identities

### M4Singer

- manifest: `/home/hyan/Data/lyricalign/derived/20260722_m4singer_pinyin_validated_v4/prepare/m4singer_manifest.jsonl`
- rows: 20,896
- SHA-256: `22828f809e60cfaeb44f0fec973d7ce5b026fd024d0740b9120725f012d6053a`
- character rows: 193,666
- character SHA-256: `ba28f0e0c5f5d6c850b47632808ccc60052f3be397f3316ee95bc95678ca613d`

### MIR-1K

- root: `/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood`
- songs/characters: 17 / 2,035
- manifest SHA-256: `bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f`
- character SHA-256: `78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9`

## Current review distribution

| Category | Count |
|---|---:|
| complex/multiple slur | 487 |
| single slur, one-group deficit | 74 |
| Mandarin pinyin parse failure | 36 |
| Latin/digit | 1 |
| total review | 598 |

Mapping result: 531 ambiguous and 67 no-match.

## Historical correction

The 6,051/14,845 and 18,057/2,839 figures remain historical trace only. The 66-item result is invalid. The only current operational count is 20,298/598 under the stated manifest identity.

## Conclusion strength

Strongly established: record conservation, current external artifact identities, review distribution, and MIR-1K vocal-channel derivative identity.

Not yet established: manual correctness of all 20,298 candidates, final training quality tier, or model improvement from these data.
