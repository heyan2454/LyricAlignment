# Archive Validation

**Date:** 2026-07-20  
**Scope:** local archive-build validation only

## Commands

```bash
python -m compileall -q src scripts tests
python -m pytest -q
```

## Result

- Python compile: passed
- Tests: `5 passed in 4.96s`

Covered behaviors:

- revision/config/input-aware resume helper;
- failed result is not skipped;
- overlap is separated from reverse ordering;
- asset inventory creates a missing output parent;
- OpenCpop downloader safely rewrites a stale partial when the server ignores Range.

## Not validated here

- Qwen model loading or inference;
- CUDA timings on the target server;
- external dataset paths;
- Hugging Face cache and exact Transformers source commit;
- OpenCpop official authorization/download;
- character conversion, long-audio construction, metrics or training.
