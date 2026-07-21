
# Archive Validation

**Date:** 2026-07-22  
**Scope:** documentation handoff archive built from `LyricAlignment_202607211613_datasetok.zip`

## Local commands

```bash
python -m compileall -q src scripts tests
python -m pytest -q
```

## Local result before final packaging

- Python compile: passed
- Pytest: collection failed with 2 errors

Missing modules in the source ZIP:

```text
lyricalign.datasets.m4singer
lyricalign.datasets.mir1k
```

The corresponding server directories are reported to exist:

```text
src/lyricalign/datasets/
scripts/datasets/
```

Therefore this failure is classified as an archive-collection omission, not evidence that the server implementation is absent. The archive must be merged into the server worktree without deleting those directories. Stage S0 requires rerunning the complete tests on the server and repairing the archive collector.

## Documentation validation

Updated or added:

- root README and AI entry;
- current status and staged execution contract;
- project/data/audio/execution principles;
- data preparation and curation manuals;
- dataset registry and smoke report;
- current-work review;
- 2026-07-22 archive/session record;
- direct Codex execution prompt;
- session temperature index.

## Final ZIP validation

The final archive process must regenerate `ARCHIVE_MANIFEST.json`, compare all paths/sizes/SHA256 with the extracted ZIP, and ensure the stable root remains `LyricAlignment/`.
