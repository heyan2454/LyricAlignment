# Dataset Cleaning Execution v2

## Completed execution evidence

- S1: 20,896 M4Singer records audited; processed + failed equals total; full JSONL is external.
- S2/S3: reversible normalization and phoneme-duration candidate mapping are implemented.  Only 66 records satisfy the current strict time-boundary acceptance rule.
- S4/S5: vocal contract and one-of A/B/C quality tier are assigned; 66 A, 20,830 B, 0 C.
- S6: a deterministic song split and leakage audit pass for the 66 A-tier records.
- S7: construction code passes invariant tests, but all 20/30/60/120-second buckets are data-limited under the same-song/same-singer/A-tier constraint.
- S8: MIR-1K 17-song/2,035-character official-vocal OOD manifest is frozen externally.
- S9: strict character metric fixtures and MIR-1K oracle are validated; reference has six legitimate adjacent overlaps.
- S10: Qwen raw baseline: M4Singer validation is metric-evaluable; MIR-1K 17/17 raw inference completes but strict metric hard-fails on 410 zero-duration and 47 near-zero-duration predictions.
- S11: portable archive self-check passes for `/home/hyan/LyricAlignment_20260722_dataset_cleaning_execution_v2.zip` (161 tracked files, stable root and SHA-256 manifest).

## Gate status

| Gate | Status | Reason |
| --- | --- | --- |
| S0 | incomplete | Full pytest has one known OpenCpop local-server download failure (HTTP 502); user explicitly deferred repair. |
| S1 | passed | Full M4Singer audit completed. |
| S2–S5 | passed for current rules/assets | Outputs and conservation evidence recorded. |
| S6 | passed for A-tier subset | Frozen song split is leakage-clean. |
| S7 | data_limited | No valid source sequence reaches first bucket. |
| S8 | passed | MIR-1K OOD manifest frozen. |
| S9 | passed | Fixtures and oracle validated. |
| S10 | mixed | Native-short metric recorded; MIR-1K raw output has hard-failing zero-duration diagnostics. |
| S11 | incomplete | Archive passes; project-wide test gate remains held by deferred S0 repair. |

## Next entry

When OpenCpop handling is no longer deferred, repair the isolated download test/proxy behavior, rerun full pytest, then regenerate the archive so S0/S11 can be closed.  Independently, improve M4Singer boundary recovery before attempting synthetic-long again; do not relax same-song/singer or timestamp invariants.
