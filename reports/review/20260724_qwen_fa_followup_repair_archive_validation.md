# Archive Validation: Qwen FA Follow-up Repaired Archive

**Date:** 2026-07-24  
**Scope:** code repair, evidence integration, deterministic metric recomputation,
identity reconciliation, and portable archive construction.

## Code and syntax

```text
python -m compileall -q src scripts tests
```

Result: passed.

```text
pytest -q \
  tests/test_character_metrics.py \
  tests/test_recompute_character_metrics.py \
  tests/test_qwen_fa_training_entrypoint.py \
  tests/test_qwen_fa_followup_entrypoint.py \
  tests/test_qwen_fa_finalize_entrypoint.py \
  tests/test_qwen_fa_labels.py \
  tests/test_qwen_fa_model.py \
  tests/test_smoke_helpers.py \
  tests/test_archive_builder.py
```

Result: **26 passed in 2.48 seconds**.

All seven shell entrypoints under `scripts/` passed `bash -n`.

## Full pytest limitation

A full `pytest -q` attempt stops during collection because this archive-building
environment does not have `pypinyin` installed. The affected modules are:

```text
tests/test_audio_contract.py
tests/test_m4singer_preparation.py
tests/test_mir1k_partial_align.py
```

This is an environment dependency limitation, not an observed failure in the
repaired metric/training/evaluation paths. The dependency remains declared by the
project and should be exercised in the canonical server environment.

## Metric recomputation checks

- 19 result sets recomputed from preserved references and predictions;
- every recomputation records source hashes and corrected schema;
- every recomputation asserts the original and corrected
  `song_macro_boundary_mae_sec` agree within tolerance;
- originals are not overwritten.

## Identity checks

- seed2 original identity remains unchanged;
- separate reconciliation records map requested limit `0` to full-split behavior;
- resolved counts are 17,748 train and 1,711 validation items;
- final checkpoint selection remains validation-only step750.

## Manifest policy

- `PATCH_MANIFEST.sha256` contains only changed/new files relative to the received
  handoff and excludes itself;
- `ARCHIVE_MANIFEST.json` contains relative paths for all archived files and
  excludes itself;
- caches, bytecode, and `.git` metadata are excluded;
- the final ZIP is independently checked against `ARCHIVE_MANIFEST.json` after
  construction; the external validation JSON records that result.
