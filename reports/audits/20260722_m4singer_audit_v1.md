# M4Singer Audit v1

**Date:** 2026-07-22  
**Command:** `python scripts/datasets/audit_m4singer.py --m4singer-root /home/hyan/Data/datasets/m4singer/raw/extracted/m4singer --out-dir /home/hyan/Data/lyricalign/derived/m4singer_audit_v1`

## Result

- processed: 20,896; failed: 0; conservation check passed;
- rule-based phoneme-group candidates: 6,050;
- mismatch/non-accepted records: 14,846;
- taxonomy: `special_non_lyric_token` 14,843, `duration_metadata_mismatch` 2, `latin_or_digit` 1; `unknown` 0;
- full JSONL diagnostics and representative samples are external at `/home/hyan/Data/lyricalign/derived/m4singer_audit_v1/`.

## Interpretation

Pause/breath tokens dominate the current mismatch category; this is an audit result, not a rejection decision.  The audit has not used raw-aligner output to remove data.  The next mapping pass must refine this broad category using the phoneme and slur sequence rather than accepting it wholesale.

## Character preparation result

`prepare_m4singer.py` was rerun to `/home/hyan/Data/lyricalign/derived/m4singer_character_v1/`: 20,896 manifests and 193,666 character records were emitted.  66 records met the strict cumulative-duration/audio-duration condition and are marked `accepted_rule_based`; all remaining records retain explicit review status.
