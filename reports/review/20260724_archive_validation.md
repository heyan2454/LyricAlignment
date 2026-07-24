# Archive Validation: Qwen FA Follow-up Review Handoff

**Date:** 2026-07-24  
**Scope:** documentation/evidence archive generated from `LyricAlignment_202607240806_loraseed2fulldone.zip` and the user-supplied `final_summary.json`.

## Preservation checks

- supplied summary copied byte-for-byte to `results/comparisons/20260724_qwen_fa_followup_final_summary.provisional.json`;
- SHA-256: `a6d27c73115fd9b9e0c0799e4f11d2be82697063735a0735548862489ac42171`;
- no aggregate metric value was edited;
- no missing seed2/OOD value was filled;
- no external checkpoint, audio, prediction file, or large log was copied.

## Local syntax and tests

```text
python -m compileall -q src scripts tests
```

Result: passed.

Targeted follow-up/training/metric tests:

```text
21 passed in 3.91s
```

Relevant shell syntax checks:

```text
bash_syntax_passed
```

Full local pytest did not complete because the archive-construction environment lacks `pypinyin`. Three test modules failed at collection:

```text
tests/test_audio_contract.py
tests/test_m4singer_preparation.py
tests/test_mir1k_partial_align.py
```

This is recorded as an environment dependency limit, not a server experiment failure.

## Known-code policy

Confirmed metric and identity defects were intentionally **not** corrected in this archive. They are documented in `docs/status/known_issues_20260724.md` so the next session can add tests, patch code, and recompute from predictions without losing the original evidence state.

## Manifest policy

The archive contains one canonical `ARCHIVE_MANIFEST.json` and a separate descriptive `ARCHIVE_METADATA.json`; the previous dual-manifest naming conflict is removed. `PATCH_MANIFEST.sha256` is refreshed against the exact archived files.
