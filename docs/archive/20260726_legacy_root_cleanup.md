# Legacy root cleanup — 2026-07-26

The repository root previously contained temporary patch application notes,
archive manifests, checksum lists, and one generated archive manifest copied
back into the source tree. They were reviewed before removal rather than simply
discarded.

## Canonical destinations

- Immediate diagnostic commands: `docs/sessions/20260725_qwen_fa_immediate_all_plan.md`
  and the executable scripts under `scripts/training/` and `scripts/maintenance/`.
- Spleeter validation and recovery: `docs/manual/qwen_fa_batch_demo.md`,
  `scripts/demo/validate_spleeter_model.py`, and `scripts/demo/download_spleeter_model_resumable.sh`.
- Strict serial/window overlap policy: `scripts/demo/README.md`,
  `docs/manual/qwen_fa_batch_demo.md`, the implementation, and regression tests.
- 2026-07-24 experiment/archive conclusions: 
  `docs/sessions/20260724_qwen_fa_followup_repair_archive.md` and
  `reports/review/20260724_qwen_fa_followup_repair_archive_validation.md`.
- Archive integrity: `scripts/environment/build_archive.py` and
  `tests/test_archive_builder.py`.

## Removed redundant source files

The removed copies comprised temporary `APPLY*`, `PATCH*`, old
`ARCHIVE_MANIFEST*`, `ARCHIVE_METADATA.json`, `ARCHIVE_REPORT.md`, and checksum
lists. `ARCHIVE_MANIFEST.generated.json` is output-only and is generated exactly
once inside each built ZIP; it is not a repository source file.
