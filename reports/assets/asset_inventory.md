# Asset Inventory

**Status:** partial server execution  
**Updated:** 2026-07-19

| Asset | Expected action | Actual path | Revision/version | Size | Verification | Notes |
|---|---|---|---|---:|---|---|
| Qwen Forced Aligner | downloaded preferred official variant | `/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064` | `c07281df297b9905d24a508279258cccf987a064` | 8 files / ~1.8G cache | passed | Initial transport failure resumed successfully; one M4Singer raw smoke completed. |
| Opencpop | download official source | `/home/hyan/Data/lyricalign/datasets/opencpop` | to verify | 0 | blocked on official access grant | Official site requires a Google Form and emailed download instructions; no public direct archive URL is provided. |
| M4Singer | direct read-only shared-data reuse | `/home/hyan/Data/datasets/m4singer` | `google_drive_archive_20260714` | prior AST audit: 20G / 65,198 files | passed | Migrated raw WAV and `meta.json` lyrics were rechecked at the new path; no second transfer needed. |
| MIR-1K | legacy path pending migration-path confirmation | `/home/hyan/Data/ast_data/mir1k/current` -> `prepared` | to verify | 404 files | partial | No `/home/hyan/Data/datasets/mir1k` directory was found; vocal WAV readable but lyrics mapping has not been audited. |

## Required completion fields

- source and acquisition date;
- resolved model revision or dataset version;
- external absolute path;
- file count and total disk usage;
- sampled audio readability;
- whether direct read-only reuse is possible;
- whether a transfer, symlink or second copy was created;
- verification command and outcome.

Machine-readable audit artifacts are external: `/home/hyan/Data/lyricalign/outputs/audits/ast_discovery.json` and
`/home/hyan/Data/lyricalign/outputs/audits/asset_inventory.json`.
