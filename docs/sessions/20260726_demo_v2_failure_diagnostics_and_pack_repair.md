# Demo v2 failure diagnostics, Japanese unit, and archive repair

## Scope

This repair addresses four demo-blocking issues observed on Cantonese and
Japanese songs: duplicate generated manifests, excessive root clutter, repeated
`first uncommitted character aligned before the trusted core` failures without
inspectable JSON, and Japanese unit disagreement caused by a second tokenizer
pass.

## Decisions

1. `ARCHIVE_MANIFEST.generated.json` is output-only. The archive builder excludes
   a stale tracked copy defensively, rejects every duplicate ZIP member name,
   and verifies that the generated manifest neither lists itself nor leaves
   unmanifested members.
2. Historical root patch/archive records were reviewed and absorbed into canonical
   session, manual, review, implementation and test files. Redundant `APPLY*`,
   `PATCH*`, old manifest/metadata/report and checksum copies were removed; the
   mapping is recorded in `docs/archive/20260726_legacy_root_cleanup.md`.
3. Window policy is now `hard_core_adaptive_overlap_v5`. Absence of matching lyric
   context is not treated as a proven cause: nominal left overlap is tried first.
   Only an observed `first_uncommitted_before_trusted_core` rejection triggers a
   local retry from the core start.
4. Each alignment writes `alignment.progress.json` during execution and
   `alignment.failure.json` on failure. A failed rerun cannot leave a stale
   `alignment.json`. Render records a skip instead of producing a secondary
   missing-file failure.
5. Parsed lyric units are authoritative. Forced-aligner chat content is built
   directly from those units, one text item per unit, so Japanese text is not
   passed through Nagisa a second time.

## Validation

The available suite passed `81` tests after excluding three collection modules
whose unrelated dataset tests require the absent `pypinyin` dependency. The
focused demo/archive subset passed `28` tests and covers adaptive unmatched-overlap
probe/fallback behavior, Japanese compound-unit preservation, failure/progress artifacts,
render skip behavior, stale generated-manifest exclusion, and duplicate
ZIP-member rejection. The subsequent cleaned archive removes redundant root-era artifacts and still
contains exactly one generated manifest. Real Qwen GPU inference is not available in the
packaging environment and must be rerun on the server.
